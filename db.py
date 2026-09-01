# -*- coding: utf-8 -*-
import os
import sys
import subprocess

# Автоустановка библиотеки для работы с PostgreSQL
try:
    import psycopg2
except ImportError:
    print("Библиотека psycopg2 не найдена. Устанавливаю...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary"])
    print("Установка завершена! Перезапускаю...")
    os.execv(sys.executable, [sys.executable] + sys.argv)

from config import DB_URL

def get_db_connection():
    """Устанавливает соединение с базой данных Supabase"""
    return psycopg2.connect(DB_URL)

def get_or_create_user(vk_id):
    """Находит пользователя по vk_id или создает нового"""
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

def smart_search_item(user_id, item_name, op_type):
    """
    Умный поиск с опечатками (замена Левенштейна).
    Ищет сначала в личной базе, потом в глобальной.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Используем pg_trgm для поиска ближайшего слова по расстоянию (<->)
        query = """
        SELECT type, category, subcategory, article, synonym, 
               1 - (synonym <-> %s) as similarity_score
        FROM (
            SELECT type, category, subcategory, article, synonym 
            FROM user_dictionary 
            WHERE user_id = %s AND type = %s AND is_deleted = FALSE
            UNION ALL
            SELECT type, category, subcategory, article, synonym 
            FROM global_dictionary 
            WHERE type = %s
        ) AS combined
        ORDER BY synonym <-> %s
        LIMIT 1;
        """
        # Передаем параметры: слово, user_id, тип, тип, слово
        cur.execute(query, (item_name, user_id, op_type, op_type, item_name))
        result = cur.fetchone()
        
        if result:
            score = result[5]
            # Если совпадение больше 70% (0.7)
            if score >= 0.7:
                return {
                    "status": "FOUND",
                    "type": result[0],
                    "category": result[1],
                    "subcategory": result[2],
                    "article": result[3]
                }
        return {"status": "NOT_FOUND"}
    finally:
        cur.close()
        conn.close()

def save_transaction(user_id, op_type, category, subcategory, article, amount, comment, original_text, status='verified'):
    """Сохраняет транзакцию в PostgreSQL"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        query = """
        INSERT INTO transactions 
        (user_id, operation_date, type, category, subcategory, article, amount, comment, original_text, status)
        VALUES (%s, CURRENT_TIMESTAMP, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cur.execute(query, (user_id, op_type, category, subcategory, article, amount, comment, original_text, status))
        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка сохранения транзакции: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def get_full_menu(user_id):
    """Собирает меню категорий для конкретного пользователя"""
    conn = get_db_connection()
    cur = conn.cursor()
    menu = {"Расход": {}, "Доход": {}}
    try:
        # Берем скелет из глобальной базы и кастомные папки юзера
        cur.execute("""
            SELECT type, category, subcategory 
            FROM global_dictionary 
            UNION 
            SELECT type, category, subcategory 
            FROM user_dictionary WHERE user_id = %s AND is_deleted = FALSE
        """, (user_id,))
        
        for row in cur.fetchall():
            t, c, s = row[0], row[1], row[2]
            if t not in menu: menu[t] = {}
            if c not in menu[t]: menu[t][c] = []
            if s not in menu[t][c]: menu[t][c].append(s)
        return menu
    finally:
        cur.close()
        conn.close()
