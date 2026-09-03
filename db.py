# -*- coding: utf-8 -*-
import os
import sys
import subprocess

# ====================================================================
# АВТОУСТАНОВКА БИБЛИОТЕК
# ====================================================================
try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    print("Библиотека psycopg2 не найдена. Устанавливаю...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary"])
    print("Установка завершена! Перезапускаю скрипт...")
    os.execv(sys.executable, [sys.executable] + sys.argv)

from config import DB_URL

# ====================================================================
# ФУНКЦИИ ПОДКЛЮЧЕНИЯ И РАБОТЫ С ПОЛЬЗОВАТЕЛЯМИ
# ====================================================================

def get_db_connection():
    """Устанавливает соединение с базой данных Supabase."""
    return psycopg2.connect(DB_URL)

def get_or_create_user(vk_id):
    """Находит пользователя по vk_id или создает нового."""
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

# ====================================================================
# ОСНОВНАЯ ЛОГИКА БОТА (ПОИСК, СОХРАНЕНИЕ, ОБУЧЕНИЕ)
# ====================================================================

def smart_search_item(user_id, item_name, op_type):
    """
    Умный поиск с опечатками.
    Берет ЛИЧНЫЕ слова юзера + ГЛОБАЛЬНЫЕ слова (только те, где стоит ГАЛОЧКА / is_default = TRUE).
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        query = """
        SELECT type, category, subcategory, article, synonym, 
               1 - (synonym <-> %s) as similarity_score
        FROM (
            -- 1. Личные слова пользователя
            SELECT type, category, subcategory, article, synonym 
            FROM user_dictionary 
            WHERE user_id = %s AND type = %s AND is_deleted = FALSE
            
            UNION ALL
            
            -- 2. Глобальные слова (ТОЛЬКО С ГАЛОЧКОЙ)
            SELECT type, category, subcategory, article, synonym 
            FROM global_dictionary 
            WHERE type = %s AND is_default = TRUE
        ) AS combined
        ORDER BY synonym <-> %s
        LIMIT 1;
        """
        cur.execute(query, (item_name, user_id, op_type, op_type, item_name))
        result = cur.fetchone()
        
        if result:
            score = result[5]
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
    """Сохраняет транзакцию (трату или доход) в Журнал операций PostgreSQL."""
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

def learn_user_word(user_id, op_type, category, subcategory, article, synonym):
    """
    Запоминает новое слово в личный словарь конкретного пользователя.
    Теперь юзер сможет писать это слово, и бот сразу его поймет.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        query = """
        INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, type, category, subcategory, article, synonym) 
        DO UPDATE SET is_deleted = FALSE;
        """
        cur.execute(query, (user_id, op_type, category, subcategory, article, synonym.lower().strip()))
        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка запоминания слова: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def get_full_menu(user_id):
    """
    Собирает актуальное меню категорий для ИИ.
    Скелет из глобальной базы (ТОЛЬКО С ГАЛОЧКОЙ) + личные папки пользователя.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    menu = {"Расход": {}, "Доход": {}}
    try:
        cur.execute("""
            SELECT type, category, subcategory 
            FROM global_dictionary 
            WHERE is_default = TRUE
            
            UNION 
            
            SELECT type, category, subcategory 
            FROM user_dictionary 
            WHERE user_id = %s AND is_deleted = FALSE
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

def get_unverified_transactions(user_id):
    """Получает список нераспознанных операций ('Завалы') из базы данных."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, type, original_text, amount, comment 
            FROM transactions 
            WHERE user_id = %s AND status = 'needs_review'
            ORDER BY id DESC;
        """, (user_id,))
        rows = cur.fetchall()
        result = []
        for r in rows:
            result.append({
                "id": r[0],
                "type": r[1],
                "original_item": r[2],
                "amount": float(r[3]),
                "comment": r[4] or ""
            })
        return result
    finally:
        cur.close()
        conn.close()

def resolve_unverified_item(user_id, original_item, op_type, category, subcategory):
    """
    Массово обновляет статус операций из завалов на 'verified'
    и одновременно добавляет слово в словарь пользователя.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # 1. Обновляем транзакции
        cur.execute("""
            UPDATE transactions 
            SET category = %s, subcategory = %s, article = %s, status = 'verified'
            WHERE user_id = %s AND original_text = %s AND status = 'needs_review';
        """, (category, subcategory, original_item, user_id, original_item))
        updated_count = cur.rowcount
        conn.commit()

        # 2. Обучаем личный словарь пользователя
        learn_user_word(user_id, op_type, category, subcategory, original_item, original_item)
        return updated_count
    except Exception as e:
        print(f"Ошибка разрешения завалов: {e}")
        return 0
    finally:
        cur.close()
        conn.close()

# ====================================================================
# МИГРАЦИЯ ДАННЫХ ИЗ GOOGLE SHEETS
# ====================================================================

def migrate_dictionary_from_gs(raw_data):
    """Переносит Глобальную базу из Google Sheets в PostgreSQL с учетом галочки."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("TRUNCATE TABLE global_dictionary RESTART IDENTITY CASCADE;")
        
        data_to_insert = []
        for i, row in enumerate(raw_data):
            if i == 0: continue
            if not row or len(row) < 5: continue
            
            is_default = str(row[0]).strip().lower() == 'true'
            op_type = str(row[1]).strip()
            cat = str(row[2]).strip()
            sub = str(row[3]).strip()
            article = str(row[4]).strip()
            
            if not op_type or not cat or not sub or not article:
                continue
            if op_type not in ["Расход", "Доход"]:
                op_type = "Расход"
                
            synonyms = [article.lower()]
            for col_idx in range(5, len(row)):
                syn = str(row[col_idx]).strip().lower()
                if syn and syn not in synonyms:
                    synonyms.append(syn)
                    
            for syn in synonyms:
                data_to_insert.append((op_type, cat, sub, article, syn, is_default))
                
        if data_to_insert:
            query = """
                INSERT INTO global_dictionary (type, category, subcategory, article, synonym, is_default)
                VALUES %s
                ON CONFLICT DO NOTHING
            """
            execute_values(cur, query, data_to_insert)
            
        conn.commit()
        return len(data_to_insert)
    except Exception as e:
        print(f"Ошибка миграции: {e}")
        return 0
    finally:
        cur.close()
        conn.close()
