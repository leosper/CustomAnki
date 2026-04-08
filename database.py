import sqlite3
import json
from datetime import datetime, timedelta

class Database:
    def __init__(self, config_path="config.json"):
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
            db_path = config.get("db_path", "custom_anki.db")
        except:
            db_path = "custom_anki.db"
            
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        # Включаем поддержку внешних ключей для каскадного удаления
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        
        # Таблица колод
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS decks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT
            )
        ''')
        
        # Таблица карточек
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deck_id INTEGER,
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                reps INTEGER DEFAULT 0,
                interval INTEGER DEFAULT 0,
                ease_factor REAL DEFAULT 2.5,
                due_date TEXT,
                FOREIGN KEY (deck_id) REFERENCES decks (id) ON DELETE CASCADE
            )
        ''')
        
        # Создаем дефолтную колоду, если таблица пуста
        cursor.execute("SELECT count(*) FROM decks")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO decks (name, description) VALUES (?, ?)", ("Default", "My first deck"))
            
        self.conn.commit()

    def add_deck(self, name, description=""):
        cursor = self.conn.cursor()
        cursor.execute("INSERT INTO decks (name, description) VALUES (?, ?)", (name, description))
        self.conn.commit()
        return cursor.lastrowid

    def delete_deck(self, deck_id):
        cursor = self.conn.cursor()
        # Сначала удаляем все карточки этой колоды вручную
        cursor.execute("DELETE FROM cards WHERE deck_id = ?", (deck_id,))
        # Затем удаляем саму колоду
        cursor.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
        self.conn.commit()

    def get_decks(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT d.id, d.name, d.description, COUNT(c.id) as card_count 
            FROM decks d LEFT JOIN cards c ON d.id = c.deck_id 
            GROUP BY d.id
        """)
        return cursor.fetchall()

    def add_card(self, deck_id, front, back):
        cursor = self.conn.cursor()
        due_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO cards (deck_id, front, back, due_date) VALUES (?, ?, ?, ?)",
            (deck_id, front, back, due_date)
        )
        self.conn.commit()

    def get_due_cards(self, deck_id=None):
        cursor = self.conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if deck_id:
            cursor.execute("SELECT * FROM cards WHERE due_date <= ? AND deck_id = ? ORDER BY RANDOM()", (now, deck_id))
        else:
            cursor.execute("SELECT * FROM cards WHERE due_date <= ? ORDER BY RANDOM()", (now,))
        return cursor.fetchall()
