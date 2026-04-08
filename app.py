import json
import os
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from authlib.integrations.flask_client import OAuth
from database import Database
from ai_service import AIService
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "super_secret_custom_anki_key"

# Загружаем настройки
with open("config.json", "r") as f:
    config = json.load(f)

db = Database()
ai = AIService()

# Настройка OAuth для Google
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=config.get('google_client_id'),
    client_secret=config.get('google_client_secret'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

def get_session_key():
    key = session.get('api_key')
    if not key and 'user' in session:
        key = config.get('api_key')
    
    # Проверка на пустые значения или плейсхолдеры
    if not key or "YOUR_" in str(key):
        return None
    return key

def get_active_deck():
    """Возвращает ID текущей выбранной колоды, проверяя её существование."""
    deck_id = session.get('active_deck_id')
    decks = db.get_decks() # Список кортежей (id, name, ...)
    
    if not decks:
        return None # База пуста (хотя у нас есть авто-создание)

    # Проверяем, существует ли сохраненный в сессии ID
    deck_exists = any(d[0] == deck_id for d in decks)
    
    if not deck_id or not deck_exists:
        # Если ID нет или колода удалена, берем ID первой доступной колоды
        first_deck_id = decks[0][0]
        session['active_deck_id'] = first_deck_id
        return first_deck_id
        
    return deck_id

@app.context_processor
def inject_globals():
    """Добавляет переменные во все шаблоны."""
    return {
        'active_deck_id': get_active_deck(),
        'user': session.get('user')
    }

@app.route('/')
def index():
    if not get_session_key() and 'user' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        api_key = request.form.get('api_key')
        if api_key:
            session['api_key'] = api_key
            return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/login/google')
def login_google():
    redirect_uri = url_for('auth', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth')
def auth():
    token = google.authorize_access_token()
    user = token.get('userinfo')
    if user:
        session['user'] = user
        session.permanent = True
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.pop('api_key', None)
    session.pop('user', None)
    session.pop('active_deck_id', None)
    return redirect(url_for('login'))

# DECK MANAGEMENT
@app.route('/api/decks', methods=['GET'])
def list_decks():
    if not get_session_key(): return jsonify({"status": "error"}), 401
    decks = db.get_decks()
    # decks is a list of tuples: (id, name, description, card_count)
    return jsonify({
        "status": "success",
        "decks": [{"id": d[0], "name": d[1], "description": d[2], "cards": d[3]} for d in decks],
        "active_id": get_active_deck()
    })

@app.route('/api/decks/select', methods=['POST'])
def select_deck():
    deck_id = request.json.get('id')
    session['active_deck_id'] = int(deck_id)
    return jsonify({"status": "success"})

@app.route('/api/decks/add', methods=['POST'])
def add_deck():
    data = request.json
    deck_id = db.add_deck(data.get('name'), data.get('description', ''))
    return jsonify({"status": "success", "id": deck_id})

@app.route('/api/decks/delete', methods=['POST'])
def delete_deck():
    deck_id = int(request.json.get('id'))
    
    # Защита от удаления последней колоды
    decks = db.get_decks()
    if len(decks) <= 1:
        return jsonify({"status": "error", "message": "Cannot delete the last deck."})

    if deck_id == get_active_deck():
        # Если удаляем активную, переключаемся на любую другую оставшуюся
        other_decks = [d for d in decks if d[0] != deck_id]
        session['active_deck_id'] = other_decks[0][0]
        
    db.delete_deck(deck_id)
    return jsonify({"status": "success"})

# CARDS
@app.route('/api/get_card', methods=['GET'])
def get_card():
    if not get_session_key(): return jsonify({"status": "error"}), 401
    deck_id = get_active_deck()
    cards = db.get_due_cards(deck_id)
    if not cards: return jsonify({"status": "empty"})
    card = cards[0]
    return jsonify({"status": "success", "id": card[0], "front": card[2]})

@app.route('/api/check', methods=['POST'])
def check_answer():
    api_key = get_session_key()
    data = request.json
    cursor = db.conn.cursor()
    cursor.execute("SELECT * FROM cards WHERE id = ?", (data.get('id'),))
    card = cursor.fetchone()
    result = ai.check_answer(api_key, card[2], card[3], data.get('answer'))
    new_due = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE cards SET due_date = ? WHERE id = ?", (new_due, data.get('id')))
    db.conn.commit()
    return jsonify({"status": "success", "result": result, "correct": "YES" in result.upper()})

@app.route('/api/generate', methods=['POST'])
def generate():
    api_key = get_session_key()
    topic = request.json.get('topic')
    deck_id = get_active_deck()
    try:
        new_cards = ai.generate_cards(api_key, topic, count=5)
        for f, b in new_cards: db.add_card(deck_id, f, b)
        return jsonify({"status": "success", "count": len(new_cards)})
    except Exception as e: return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(host=config.get("web_host"), port=config.get("web_port"), debug=True)
