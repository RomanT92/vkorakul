# -*- coding: utf-8 -*-
import os
import sys
import subprocess

# ====================================================================
# АВТОУСТАНОВКА БИБЛИОТЕК
# ====================================================================
# Проверяем, установлена ли библиотека для работы с PostgreSQL.
# Если нет — скрипт сам её скачает и установит (удобно для Bothost).
try:
    import psycopg2
    from psycopg2.extras import execute_values # <-- Тот самый инструмент для сверхбыстрой массовой загрузки
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
    """
    Устанавливает соединение с базой данных Supabase.
    Использует ссылку DB_URL из файла config.py.
    """
    return psycopg2.connect(DB_URL)

def get_or_create_user(vk_id):
    """
    Проверяет, есть ли пользователь в нашей базе PostgreSQL.
    Если есть — возвращает его внутренний ID.
    Если нет — создает новую запись и возвращает новый ID.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE vk_id = %s", (vk_id,))
        user = cur.fetchone()
        if not user:
            # RETURNING id позволяет сразу получить ID только что созданной строки
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
# ОСНОВНАЯ ЛОГИКА БОТА (ПОИСК И СОХРАНЕНИЕ)
# ====================================================================

def smart_search_item(user_id, item_name, op_type):
    """
    Умный поиск с опечатками (использует расширение pg_trgm в PostgreSQL).
    Ищет слово сначала в личной базе пользователя, потом в глобальной.
    Работает в 100 раз быстрее, чем старый поиск в Google Таблицах.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Запрос объединяет личную базу юзера и глобальную базу.
        # Знак <-> вычисляет "расстояние" между словами (насколько они похожи).
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
    """
    Сохраняет транзакцию (трату или доход) в таблицу transactions.
    """
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
    """
    Собирает актуальное меню категорий для ИИ (чтобы он мог угадывать категории).
    Берет эталонный скелет из глобальной базы + личные папки пользователя.
    """
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

# ====================================================================
# МИГРАЦИЯ ДАННЫХ ИЗ GOOGLE SHEETS
# ====================================================================

def migrate_dictionary_from_gs(raw_data):
    """
    Служебная функция. Переносит Глобальную базу из Google Sheets в PostgreSQL.
    Использует массовую вставку (execute_values), чтобы загрузить тысячи слов за 1 секунду.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Очищаем глобальную таблицу перед новой заливкой
        cur.execute("TRUNCATE TABLE global_dictionary RESTART IDENTITY CASCADE;")
        
        data_to_insert = []
        for i, row in enumerate(raw_data):
            if i == 0: continue # Пропускаем строку с заголовками
            if not row or len(row) < 5: continue
            
            op_type = str(row[1]).strip()
            cat = str(row[2]).strip()
            sub = str(row[3]).strip()
            article = str(row[4]).strip()
            
            if not op_type or not cat or not sub or not article:
                continue
            if op_type not in ["Расход", "Доход"]:
                op_type = "Расход"
                
            # Собираем синонимы: само название статьи + все колонки правее (синонимы)
            synonyms = [article.lower()]
            for col_idx in range(5, len(row)):
                syn = str(row[col_idx]).strip().lower()
                if syn and syn not in synonyms:
                    synonyms.append(syn)
                    
            # Распаковываем синонимы (одно слово = одна строка для быстрого поиска)
            for syn in synonyms:
                data_to_insert.append((op_type, cat, sub, article, syn))
                
        # МАССОВАЯ ВСТАВКА (отправляем всё за 1 запрос)
        if data_to_insert:
            query = """
                INSERT INTO global_dictionary (type, category, subcategory, article, synonym)
                VALUES %s
                ON CONFLICT DO NOTHING
            """
            # execute_values автоматически разбивает массив data_to_insert и вставляет его
            execute_values(cur, query, data_to_insert)
            
        conn.commit()
        return len(data_to_insert)
    except Exception as e:
        print(f"Ошибка миграции: {e}")
        return 0
    finally:
        cur.close()
        conn.close()
