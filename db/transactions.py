# -*- coding: utf-8 -*-
from .connection import get_db_connection

def _resolve_internal_user_id(cur, user_id):
    """
    Гарантирует получение первичного ключа id (BIGINT) из таблицы users,
    даже если передан vk_id.
    """
    cur.execute("SELECT id FROM users WHERE id = %s OR vk_id = %s LIMIT 1;", (user_id, user_id))
    row = cur.fetchone()
    return row[0] if row else user_id

def smart_search_item(user_id, item_name, op_type=None):
    """
    Поиск синонима с регистронезависимостью (LOWER).
    Объединяет глобальную базу и личные слова пользователя с учетом меток удаления.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    clean_item = item_name.lower().strip()
    try:
        uid = _resolve_internal_user_id(cur, user_id)

        if op_type:
            combined_source = """
                SELECT type, category, subcategory, article, LOWER(synonym) AS synonym
                FROM user_dictionary
                WHERE user_id = %s AND type = %s AND is_deleted = FALSE

                UNION ALL

                SELECT g.type, g.category, g.subcategory, g.article, LOWER(g.synonym) AS synonym
                FROM global_dictionary g
                WHERE g.type = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM user_dictionary u
                      WHERE u.user_id = %s
                        AND u.type = g.type
                        AND (
                            (u.category = g.category AND (u.subcategory = '' OR u.subcategory IS NULL) AND u.is_deleted = TRUE)
                            OR (u.category = g.category AND u.subcategory = g.subcategory AND (u.article = '' OR u.article IS NULL) AND u.is_deleted = TRUE)
                            OR (u.category = g.category AND u.subcategory = g.subcategory AND u.article = g.article AND u.is_deleted = TRUE)
                            OR (LOWER(u.synonym) = LOWER(g.synonym) AND u.is_deleted = TRUE)
                        )
                  )
            """
            exact_params = (uid, op_type, op_type, uid, clean_item)
            fuzzy_params = (clean_item, uid, op_type, op_type, uid, clean_item)
        else:
            combined_source = """
                SELECT type, category, subcategory, article, LOWER(synonym) AS synonym
                FROM user_dictionary
                WHERE user_id = %s AND is_deleted = FALSE

                UNION ALL

                SELECT g.type, g.category, g.subcategory, g.article, LOWER(g.synonym) AS synonym
                FROM global_dictionary g
                WHERE NOT EXISTS (
                    SELECT 1 FROM user_dictionary u
                    WHERE u.user_id = %s
                      AND u.type = g.type
                      AND (
                          (u.category = g.category AND (u.subcategory = '' OR u.subcategory IS NULL) AND u.is_deleted = TRUE)
                          OR (u.category = g.category AND u.subcategory = g.subcategory AND (u.article = '' OR u.article IS NULL) AND u.is_deleted = TRUE)
                          OR (u.category = g.category AND u.subcategory = g.subcategory AND u.article = g.article AND u.is_deleted = TRUE)
                          OR (LOWER(u.synonym) = LOWER(g.synonym) AND u.is_deleted = TRUE)
                      )
                )
            """
            exact_params = (uid, uid, clean_item)
            fuzzy_params = (clean_item, uid, uid, clean_item)

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

        fuzzy_query = f"""
            SELECT type, category, subcategory, article, synonym, 
                   1 - (synonym <-> %s) AS similarity_score
            FROM ({combined_source}) AS combined
            ORDER BY synonym <-> %s
            LIMIT 1;
        """
        cur.execute(fuzzy_query, fuzzy_params)
        result = cur.fetchone()
        if result and result[5] >= 0.7:
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
    """Записывает операцию в таблицу transactions."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        query = """
            INSERT INTO transactions (user_id, operation_date, type, category, subcategory, article, amount, comment, original_text, status)
            VALUES (%s, CURRENT_TIMESTAMP, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cur.execute(query, (uid, op_type, category, subcategory, article, amount, comment, original_text, status))
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
        uid = _resolve_internal_user_id(cur, user_id)
        clean_syn = synonym.lower().strip()
        query = """
            INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
            VALUES (%s, %s, %s, %s, %s, %s, FALSE)
            ON CONFLICT (user_id, type, category, subcategory, article, synonym)
            DO UPDATE SET is_deleted = FALSE;
        """
        cur.execute(query, (uid, op_type, category, subcategory, article, clean_syn))
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
    Строит актуальное дерево структуры для пользователя.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    menu = {"Расход": {}, "Доход": {}}
    try:
        uid = _resolve_internal_user_id(cur, user_id)

        query = """
            SELECT g.type, g.category, g.subcategory, g.article
            FROM global_dictionary g
            WHERE NOT EXISTS (
                SELECT 1 FROM user_dictionary u
                WHERE u.user_id = %s
                  AND u.type = g.type
                  AND (
                      (u.category = g.category AND (u.subcategory = '' OR u.subcategory IS NULL) AND u.is_deleted = TRUE)
                      OR (u.category = g.category AND u.subcategory = g.subcategory AND (u.article = '' OR u.article IS NULL) AND u.is_deleted = TRUE)
                      OR (u.category = g.category AND u.subcategory = g.subcategory AND u.article = g.article AND u.is_deleted = TRUE)
                  )
            )
            UNION
            SELECT type, category, subcategory, article
            FROM user_dictionary
            WHERE user_id = %s AND is_deleted = FALSE
        """
        cur.execute(query, (uid, uid))
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
    """Возвращает нераспознанные операции."""
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
    """Счетчик неразобранных операций для кнопки."""
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
    """Подтверждает операцию и обучает личный словарь."""
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

        learn_user_word(user_id, op_type, category, subcategory, original_item, original_item)
        return updated_count
    except Exception as e:
        print(f"Ошибка разрешения завалов: {e}")
        return 0
    finally:
        cur.close()
        conn.close()

# ====================================================================
# НОВЫЕ ФУНКЦИИ: ИСТОРИЯ, РЕДАКТИРОВАНИЕ И УДАЛЕНИЕ ОПЕРАЦИЙ
# ====================================================================

def get_user_history(user_id, limit=10, period=None):
    """
    Возвращает список операций пользователя с фильтрацией по количеству или периоду,
    а также суммарные расходы и доходы.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        
        where_clauses = ["user_id = %s"]
        params = [uid]

        if period == "today":
            where_clauses.append("operation_date >= CURRENT_DATE")
        elif period == "yesterday":
            where_clauses.append("operation_date >= CURRENT_DATE - INTERVAL '1 day' AND operation_date < CURRENT_DATE")
        elif period == "week":
            where_clauses.append("operation_date >= CURRENT_DATE - INTERVAL '7 days'")
        elif period == "month":
            where_clauses.append("operation_date >= CURRENT_DATE - INTERVAL '30 days'")

        where_sql = " AND ".join(where_clauses)
        
        query = f"""
            SELECT id, operation_date, type, category, subcategory, article, amount, comment
            FROM transactions
            WHERE {where_sql}
            ORDER BY operation_date DESC, id DESC
            LIMIT %s;
        """
        params.append(min(max(limit, 1), 50))
        cur.execute(query, tuple(params))
        rows = cur.fetchall()

        items = []
        total_expense = 0.0
        total_income = 0.0

        for r in rows:
            amt = float(r[6])
            op_t = r[2]
            if op_t == "Доход":
                total_income += amt
            else:
                total_expense += amt

            items.append({
                "id": r[0],
                "date": r[1],
                "type": op_t,
                "category": r[3],
                "subcategory": r[4],
                "article": r[5],
                "amount": amt,
                "comment": r[7] or ""
            })

        return {
            "items": items,
            "total_expense": total_expense,
            "total_income": total_income,
            "count": len(items)
        }
    except Exception as e:
        print(f"Ошибка получения истории: {e}")
        return {"items": [], "total_expense": 0.0, "total_income": 0.0, "count": 0}
    finally:
        cur.close()
        conn.close()

def delete_transaction_by_id(user_id, tx_id):
    """Удаляет конкретную транзакцию пользователя по id."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        cur.execute("DELETE FROM transactions WHERE id = %s AND user_id = %s RETURNING id;", (tx_id, uid))
        deleted = cur.fetchone()
        conn.commit()
        return deleted is not None
    except Exception as e:
        print(f"Ошибка удаления операции: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def get_last_transaction(user_id):
    """Возвращает последнюю операцию пользователя."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        cur.execute("""
            SELECT id, operation_date, type, category, subcategory, article, amount
            FROM transactions
            WHERE user_id = %s
            ORDER BY id DESC
            LIMIT 1;
        """, (uid,))
        r = cur.fetchone()
        if r:
            return {
                "id": r[0],
                "date": r[1],
                "type": r[2],
                "category": r[3],
                "subcategory": r[4],
                "article": r[5],
                "amount": float(r[6])
            }
        return None
    except Exception as e:
        print(f"Ошибка получения последней операции: {e}")
        return None
    finally:
        cur.close()
        conn.close()

def update_transaction_amount(user_id, tx_id, new_amount):
    """Обновляет сумму существующей транзакции."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        cur.execute("""
            UPDATE transactions 
            SET amount = %s 
            WHERE id = %s AND user_id = %s 
            RETURNING id;
        """, (new_amount, tx_id, uid))
        ok = cur.fetchone() is not None
        conn.commit()
        return ok
    except Exception as e:
        print(f"Ошибка обновления суммы операции: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def update_transaction_category(user_id, tx_id, category, subcategory, article=None):
    """Обновляет категорию, подкатегорию и статью существующей транзакции."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        if article:
            cur.execute("""
                UPDATE transactions 
                SET category = %s, subcategory = %s, article = %s, status = 'verified'
                WHERE id = %s AND user_id = %s 
                RETURNING id;
            """, (category, subcategory, article, tx_id, uid))
        else:
            cur.execute("""
                UPDATE transactions 
                SET category = %s, subcategory = %s, status = 'verified'
                WHERE id = %s AND user_id = %s 
                RETURNING id;
            """, (category, subcategory, tx_id, uid))
        ok = cur.fetchone() is not None
        conn.commit()
        return ok
    except Exception as e:
        print(f"Ошибка обновления категории операции: {e}")
        return False
    finally:
        cur.close()
        conn.close()
