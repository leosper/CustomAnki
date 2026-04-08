import json
import os
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from authlib.integrations.flask_client import OAuth
from database import Database
from ai_service import AIService
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "super_secret_custom_anki_key"

with open("config.json", "r") as f:
    config = json.load(f)

db = Database()
ai = AIService()

# OAuth setup
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
    if not key or "YOUR_" in str(key):
        return None
    return key

def get_active_deck():
    deck_id = session.get('active_deck_id')
    decks = db.get_decks()
    if not decks: return None
    deck_exists = any(d[0] == deck_id for d in decks)
    if not deck_id or not deck_exists:
        first_deck_id = decks[0][0]
        session['active_deck_id'] = first_deck_id
        return first_deck_id
    return deck_id

@app.context_processor
def inject_globals():
    return {'active_deck_id': get_active_deck(), 'user': session.get('user')}

@app.route('/')
def index():
    if not get_session_key() and 'user' not in session: return redirect(url_for('login'))
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
    return google.authorize_redirect(url_for('auth', _external=True))

@app.route('/auth')
def auth():
    token = google.authorize_access_token()
    session['user'] = token.get('userinfo')
    session.permanent = True
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.pop('api_key', None)
    session.pop('user', None)
    return redirect(url_for('login'))

# SRS LOGIC (SM-2 Simplified)
@app.route('/api/rate', methods=['POST'])
def rate_card():
    data = request.json
    card_id = data.get('id')
    rating = int(data.get('rating')) # 0: Again, 1: Hard, 2: Good, 3: Easy
    
    cursor = db.conn.cursor()
    cursor.execute("SELECT * FROM cards WHERE id = ?", (card_id,))
    card = cursor.fetchone()
    if not card: return jsonify({"status": "error"}), 404

    # Поля в БД: id[0], deck_id[1], front[2], back[3], reps[4], interval[5], ease_factor[6], due_date[7]
    reps = card[4]
    interval = card[5]
    ease_factor = card[6]

    if rating >= 1: # Вспомнил (Hard, Good, Easy)
        if reps == 0:
            interval = 1
        elif reps == 1:
            interval = 6
        else:
            interval = round(interval * ease_factor)
        
        reps += 1
        # Изменяем коэффициент сложности (Ease Factor)
        # Формула упрощена: Easy повышает EF, Hard понижает.
        if rating == 3: ease_factor += 0.15 # Easy
        if rating == 1: ease_factor -= 0.20 # Hard
    else: # Забыл (Again)
        reps = 0
        interval = 0 # Показать сегодня
        ease_factor -= 0.20

    # Ограничения
    if ease_factor < 1.3: ease_factor = 1.3
    
    new_due = (datetime.now() + timedelta(days=interval)).strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("""
        UPDATE cards 
        SET reps = ?, interval = ?, ease_factor = ?, due_date = ? 
        WHERE id = ?
    """, (reps, interval, ease_factor, new_due, card_id))
    db.conn.commit()
    
    return jsonify({"status": "success", "next_interval": interval})

@app.route('/api/get_card', methods=['GET'])
def get_card():
    deck_id = get_active_deck()
    cards = db.get_due_cards(deck_id)
    if not cards: return jsonify({"status": "empty"})
    return jsonify({"status": "success", "id": cards[0][0], "front": cards[0][2]})

@app.route('/api/check', methods=['POST'])
def check_answer():
    api_key = get_session_key()
    data = request.json
    card_id = data.get('id')
    user_ans_raw = data.get('answer', '')
    user_ans = user_ans_raw.strip().lower()
    
    cursor = db.conn.cursor()
    cursor.execute("SELECT * FROM cards WHERE id = ?", (card_id,))
    card = cursor.fetchone()
    if not card: return jsonify({"status": "error"})
    
    correct_ans = card[3].strip().lower()
    
    # 1. Мгновенная проверка (если включено в конфиге)
    if config.get("fast_check", False) and user_ans == correct_ans:
        return jsonify({
            "status": "success", 
            "result": f"✅ Correct! (Fast check match: {card[3]})", 
            "correct": True
        })

    # 2. AI проверка (всегда срабатывает если fast_check=false или если ответы не совпали)
    result = ai.check_answer(api_key, card[2], card[3], user_ans_raw)
    return jsonify({
        "status": "success", 
        "result": result, 
        "correct": "YES" in result.upper()
    })

@app.route('/api/decks', methods=['GET'])
def list_decks():
    decks = db.get_decks()
    return jsonify({"status": "success", "decks": [{"id": d[0], "name": d[1], "cards": d[3]} for d in decks], "active_id": get_active_deck()})

@app.route('/api/decks/select', methods=['POST'])
def select_deck():
    session['active_deck_id'] = int(request.json.get('id'))
    return jsonify({"status": "success"})

@app.route('/api/generate', methods=['POST'])
def generate():
    api_key = get_session_key()
    topic = request.json.get('topic')
    try:
        new_cards = ai.generate_cards(api_key, topic, count=5)
        for f, b in new_cards: db.add_card(get_active_deck(), f, b)
        return jsonify({"status": "success", "count": len(new_cards)})
    except Exception as e: return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(host=config.get("web_host"), port=config.get("web_port"), debug=True)
