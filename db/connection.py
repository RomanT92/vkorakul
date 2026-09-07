# -*- coding: utf-8 -*-
import os
import sys
import subprocess

# ====================================================================
# АВТОУСТАНОВКА БИБЛИОТЕК
# ====================================================================
try:
    import psycopg2
except ImportError:
    print("Библиотека psycopg2 не найдена. Устанавливаю...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary"])
    print("Установка завершена! Перезапускаю скрипт...")
    os.execv(sys.executable, [sys.executable] + sys.argv)

from config import DB_URL

def get_db_connection():
    """Устанавливает соединение с базой данных Supabase (PostgreSQL)."""
    return psycopg2.connect(DB_URL)

def get_or_create_user(vk_id):
    """
    Находит пользователя по vk_id.
    Если пользователь пишет впервые — создает запись и возвращает сгенерированный id.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE vk_id = %s", (vk_id,))
        user = cur.fetchone()
        if not user:
            cur.execute("INSERT INTO users (vk_id) VALUES (%s) RETURNING id", (vk_id,))
            user_id = cur.fetchone()[0]
            conn.commit()
        else:
            user_id = user[0]
        return user_id
    finally:
        cur.close()
        conn.close()
