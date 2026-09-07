# -*- coding: utf-8 -*-
from .connection import get_db_connection

def smart_search_item(user_id, item_name, op_type=None):
    """
    Нечеткий поиск синонима с регистронезависимостью (LOWER).
    Если op_type не указан (None) — ищет по всей базе (и Расход, и Доход).
    1. Сначала проверяет точное совпадение без триграмм (100% совпадение).
    2. Если нет точного — запускает поиск по триграммам (pg_trgm) с порогом 0.7.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    clean_item = item_name.lower().strip()
    try:
        if op_type:
            combined_source = """
                SELECT type, category, subcategory, article, LOWER(synonym) AS synonym
                FROM user_dictionary
                WHERE user_id = %s AND type = %s AND is_deleted = FALSE
                UNION ALL
                SELECT g.type, g.category, g.subcategory, g.article, LOWER(g.synonym) AS synonym
                FROM global_dictionary g
                LEFT JOIN user_dictionary u ON (
                    u.user_id = %s AND u.type = g.type AND u.category = g.category
                    AND u.subcategory = g.subcategory AND u.article = g.article AND u.is_deleted = TRUE
                )
                WHERE g.type = %s AND g.is_default = TRUE AND u.id IS NULL
            """
            exact_params = (user_id, op_type, user_id, op_type, clean_item)
            fuzzy_params = (clean_item, user_id, op_type, user_id, op_type, clean_item)
        else:
            combined_source = """
                SELECT type, category, subcategory, article, LOWER(synonym) AS synonym
                FROM user_dictionary
                WHERE user_id = %s AND is_deleted = FALSE
                UNION ALL
                SELECT g.type, g.category, g.subcategory, g.article, LOWER(g.synonym) AS synonym
                FROM global_dictionary g
                LEFT JOIN user_dictionary u ON (
                    u.user_id = %s AND u.type = g.type AND u.category = g.category
                    AND u.subcategory = g.subcategory AND u.article = g.article AND u.is_deleted = TRUE
                )
                WHERE g.is_default = TRUE AND u.id IS NULL
            """
            exact_params = (user_id, user_id, clean_item)
            fuzzy_params = (clean_item, user_id, user_id, clean_item)

        # Шаг 1: Точное совпадение
        exact_query = f"""
            SELECT type, category, subcategory, article
            FROM ({combined_source}) AS combined
            WHERE synonym = %s
            LIMIT 1;
        """
        cur.execute(exact_query, exact_params)
        exact_match = cur.fetchone()
        if exact_match:
            return {
                "status": "FOUND",
                "type": exact_match[0],
                "category": exact_match[1],
                "subcategory": exact_match[2],
                "article": exact_match[3]
            }

        # Шаг 2: Триграммный поиск с опечатками
        fuzzy_query = f"""
            SELECT type, category, subcategory, article, synonym, 
                   1 - (synonym <-> %s) AS similarity_score
            FROM ({combined_source}) AS combined
            ORDER BY synonym <-> %s
            LIMIT 1;
        """
        cur.execute(fuzzy_query, fuzzy_params)
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
    """Записывает операцию дохода или расхода в таблицу transactions."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        query = """
            INSERT INTO transactions (user_id, operation_date, type, category, subcategory, article, amount, comment, original_text, status)
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
    """Сохраняет новое слово в персональный словарь пользователя (user_dictionary)."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        clean_syn = synonym.lower().strip()
        query = """
            INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
            VALUES (%s, %s, %s, %s, %s, %s, FALSE)
            ON CONFLICT (user_id, type, category, subcategory, article, synonym)
            DO UPDATE SET is_deleted = FALSE;
        """
        cur.execute(query, (user_id, op_type, category, subcategory, article, clean_syn))
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
    Строит актуальное трехуровневое дерево структуры для пользователя:
    menu[Тип][Категория][Подкатегория] = [Статья1, Статья2, ...]
    """
    conn = get_db_connection()
    cur = conn.cursor()
    menu = {"Расход": {}, "Доход": {}}
    try:
        query = """
            SELECT g.type, g.category, g.subcategory, g.article
            FROM global_dictionary g
            LEFT JOIN user_dictionary u ON (
                u.user_id = %s AND u.type = g.type AND u.category = g.category
                AND u.subcategory = g.subcategory AND u.article = g.article AND u.is_deleted = TRUE
            )
            WHERE g.is_default = TRUE AND u.id IS NULL
            UNION
            SELECT type, category, subcategory, article
            FROM user_dictionary
            WHERE user_id = %s AND is_deleted = FALSE
        """
        cur.execute(query, (user_id, user_id))
        for row in cur.fetchall():
            t, c, s, a = row[0], row[1], row[2], row[3]
            if t not in menu:
                menu[t] = {}
            if c not in menu[t]:
                menu[t][c] = {}
            if s not in menu[t][c]:
                menu[t][c][s] = []
            if a and a not in menu[t][c][s]:
                menu[t][c][s].append(a)
        return menu
    finally:
        cur.close()
        conn.close()

def get_unverified_transactions(user_id):
    """
    Возвращает список всех нераспознанных операций пользователя:
    со статусом 'needs_review' ИЛИ находящихся в 'Требует проверки' / 'Разное'.
    Ищет как по внутреннему id, так и по vk_id.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT t.id, t.type, t.original_text, t.amount, t.comment
            FROM transactions t
            JOIN users u ON u.id = t.user_id
            WHERE (u.id = %s OR u.vk_id = %s)
              AND (
                  t.status = 'needs_review' 
                  OR LOWER(t.subcategory) = 'требует проверки' 
                  OR LOWER(t.category) = 'разное'
              )
            ORDER BY t.id DESC;
        """, (user_id, user_id))
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

def get_unreviewed_count(user_id):
    """
    Возвращает точное количество нераспознанных операций для динамического бейджа на кнопке.
    Работает мгновенно (1-2 мс) благодаря индексам в PostgreSQL.
    Ищет как по внутреннему id, так и по vk_id.
    """
    if not user_id:
        return 0
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT COUNT(*) 
            FROM transactions t
            JOIN users u ON u.id = t.user_id
            WHERE (u.id = %s OR u.vk_id = %s)
              AND (
                  t.status = 'needs_review' 
                  OR LOWER(t.subcategory) = 'требует проверки' 
                  OR LOWER(t.category) = 'разное'
              );
        """, (user_id, user_id))
        res = cur.fetchone()
        return res[0] if res else 0
    except Exception as e:
        print(f"Ошибка подсчета нераспознанных операций: {e}")
        return 0
    finally:
        cur.close()
        conn.close()

def resolve_unverified_item(user_id, original_item, op_type, category, subcategory):
    """
    Массово подтверждает операции из завалов, устанавливая категорию,
    и одновременно вносит термин в личный словарь.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE transactions
            SET category = %s, subcategory = %s, article = %s, status = 'verified'
            WHERE user_id IN (SELECT id FROM users WHERE id = %s OR vk_id = %s)
              AND original_text = %s 
              AND (
                  status = 'needs_review' 
                  OR LOWER(subcategory) = 'требует проверки' 
                  OR LOWER(category) = 'разное'
              );
        """, (category, subcategory, original_item, user_id, user_id, original_item))
        updated_count = cur.rowcount
        conn.commit()

        cur.execute("SELECT id FROM users WHERE id = %s OR vk_id = %s LIMIT 1;", (user_id, user_id))
        u_row = cur.fetchone()
        real_uid = u_row[0] if u_row else user_id

        learn_user_word(real_uid, op_type, category, subcategory, original_item, original_item)
        return updated_count
    except Exception as e:
        print(f"Ошибка разрешения завалов: {e}")
        return 0
    finally:
        cur.close()
        conn.close()
