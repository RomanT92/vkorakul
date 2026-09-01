# -*- coding: utf-8 -*-
import os
import sys
import subprocess

# Автоустановка библиотеки для работы с PostgreSQL (нужно для Bothost)
try:
    import psycopg2
except ImportError:
    print("Библиотека psycopg2 не найдена. Устанавливаю...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary"])
    print("Установка завершена! Перезапускаю скрипт...")
    os.execv(sys.executable, [sys.executable] + sys.argv)

from config import DB_URL

def get_db_connection():
    """Устанавливает соединение с базой данных Supabase"""
    return psycopg2.connect(DB_URL)

def get_or_create_user(vk_id):
    """Находит пользователя по vk_id. Если его нет — создает новую запись."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE vk_id = %s", (vk_id,))
        user = cur.fetchone()
        if not user:
            # Если юзера нет, создаем и возвращаем его внутренний ID
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
    Умный поиск с опечатками (использует расширение pg_trgm).
    Ищет слово сначала в личной базе пользователя, потом в глобальной.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
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
        # Ищем по слову, ID юзера и типу (Доход/Расход)
        cur.execute(query, (item_name, user_id, op_type, op_type, item_name))
        result = cur.fetchone()
        
        if result:
            score = result[5]
            # Порог совпадения: 0.7 (70%). Если совпадает больше чем на 70% - берем!
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
    """Сохраняет транзакцию (трату или доход) в Журнал операций PostgreSQL"""
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
    """Собирает меню категорий (Скелет) для конкретного пользователя, чтобы отдать его ИИ"""
    conn = get_db_connection()
    cur = conn.cursor()
    menu = {"Расход": {}, "Доход": {}}
    try:
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

def migrate_dictionary_from_gs(raw_data):
    """
    Служебная функция. Переносит Глобальную базу из Google Sheets в PostgreSQL.
    Распаковывает синонимы (одно слово = одна строка) для быстрого поиска.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Очищаем глобальную таблицу перед заливкой
        cur.execute("TRUNCATE TABLE global_dictionary RESTART IDENTITY CASCADE;")
        
        inserted_count = 0
        for i, row in enumerate(raw_data):
            if i == 0: continue # Пропускаем заголовки
            if not row or len(row) < 5: continue
            
            op_type = str(row[1]).strip()
            cat = str(row[2]).strip()
            sub = str(row[3]).strip()
            article = str(row[4]).strip()
            
            if not op_type or not cat or not sub or not article:
                continue
            if op_type not in ["Расход", "Доход"]:
                op_type = "Расход"
                
            # Собираем синонимы: само название статьи + все колонки правее
            synonyms = [article.lower()]
            for col_idx in range(5, len(row)):
                syn = str(row[col_idx]).strip().lower()
                if syn and syn not in synonyms:
                    synonyms.append(syn)
                    
            for syn in synonyms:
                try:
                    # ON CONFLICT DO NOTHING защищает от дубликатов слов
                    cur.execute("""
                        INSERT INTO global_dictionary (type, category, subcategory, article, synonym)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                    """, (op_type, cat, sub, article, syn))
                    inserted_count += 1
                except Exception as e:
                    pass
                    
        conn.commit()
        return inserted_count
    finally:
        cur.close()
        conn.close()
