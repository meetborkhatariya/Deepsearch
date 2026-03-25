# db.py
import sqlite3
import os

DB_PATH = "user_memory.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS user_memory (
        user_id TEXT PRIMARY KEY,
        summary TEXT
    )
    """)
    conn.commit()
    conn.close()

def save_summary(user_id: str, summary: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    INSERT OR REPLACE INTO user_memory (user_id, summary)
    VALUES (?, ?)
    """, (user_id, summary))
    conn.commit()
    conn.close()

def get_summary(user_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT summary FROM user_memory WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None