# -*- coding: utf-8 -*-
from .connection import get_db_connection

def _resolve_internal_user_id(cur, user_id):
    """
    Гарантирует получение первичного ключа id (BIGINT) из таблицы users, даже если передан vk_id.
    """
    cur.execute("SELECT id FROM users WHERE id = %s OR vk_id = %s LIMIT 1;", (user_id, user_id))
    row = cur.fetchone()
    return row[0] if row else user_id

def smart_search_item(user_id, item_name, op_type=None):
    """
    Поиск с наивысшим приоритетом персонального словаря пользователя:
    1. Точное совпадение в user_dictionary (синоним или статья)
    2. Поиск в global_dictionary (с фильтрацией удаленных и переопределенных пользователем слов)
    3. Поиск по названиям подкатегорий и категорий с приоритизацией базовых статей (не экзотических тарифов)
    4. Нечёткий поиск триграммами pg_trgm (сходство >= 0.65)
    """
    conn = get_db_connection()
    cur = conn.cursor()
    clean_item = item_name.lower().strip()
    clean_type = op_type.lower().strip() if op_type else None

    try:
        uid = _resolve_internal_user_id(cur, user_id)

        # 1. АБСОЛЮТНЫЙ ПРИОРИТЕТ: ЛИЧНЫЙ СЛОВАРЬ ПОЛЬЗОВАТЕЛЯ
        if clean_type:
            user_sql = """
                SELECT type, category, subcategory, article
                FROM user_dictionary
                WHERE user_id = %s AND is_deleted = FALSE AND LOWER(TRIM(type)) = %s
                  AND (LOWER(TRIM(synonym)) = %s OR LOWER(TRIM(article)) = %s)
                ORDER BY id DESC LIMIT 1;
            """
            cur.execute(user_sql, (uid, clean_type, clean_item, clean_item))
        else:
            user_sql = """
                SELECT type, category, subcategory, article
                FROM user_dictionary
                WHERE user_id = %s AND is_deleted = FALSE
                  AND (LOWER(TRIM(synonym)) = %s OR LOWER(TRIM(article)) = %s)
                ORDER BY id DESC LIMIT 1;
            """
            cur.execute(user_sql, (uid, clean_item, clean_item))

        user_match = cur.fetchone()
        if user_match:
            return {
                "status": "FOUND",
                "type": user_match[0].strip(),
                "category": user_match[1].strip(),
                "subcategory": user_match[2].strip(),
                "article": user_match[3].strip()
            }

        # 2. ГЛОБАЛЬНЫЙ ЭТАЛОН (с корректной изоляцией удалений по конкретным синонимам)
        type_clause_global = "AND LOWER(TRIM(g.type)) = %s" if clean_type else ""
        global_sql = f"""
            SELECT g.type, g.category, g.subcategory, g.article
            FROM global_dictionary g
            WHERE (LOWER(TRIM(g.synonym)) = %s OR LOWER(TRIM(g.article)) = %s) {type_clause_global}
              AND NOT EXISTS (
                  SELECT 1 FROM user_dictionary u
                  WHERE u.user_id = %s
                    AND LOWER(TRIM(u.type)) = LOWER(TRIM(g.type))
                    AND (
                        (LOWER(TRIM(u.synonym)) = LOWER(TRIM(g.synonym)))
                        OR (
                            LOWER(TRIM(u.category)) = LOWER(TRIM(g.category))
                            AND (u.subcategory = '' OR u.subcategory IS NULL)
                            AND u.is_deleted = TRUE
                        )
                        OR (
                            LOWER(TRIM(u.category)) = LOWER(TRIM(g.category))
                            AND LOWER(TRIM(u.subcategory)) = LOWER(TRIM(g.subcategory))
                            AND (u.article = '' OR u.article IS NULL)
                            AND u.is_deleted = TRUE
                        )
                        OR (
                            LOWER(TRIM(u.category)) = LOWER(TRIM(g.category))
                            AND LOWER(TRIM(u.subcategory)) = LOWER(TRIM(g.subcategory))
                            AND LOWER(TRIM(u.article)) = LOWER(TRIM(g.article))
                            AND u.is_deleted = TRUE
                        )
                    )
              )
            LIMIT 1;
        """
        if clean_type:
            cur.execute(global_sql, (clean_item, clean_item, clean_type, uid))
        else:
            cur.execute(global_sql, (clean_item, clean_item, uid))

        global_match = cur.fetchone()
        if global_match:
            return {
                "status": "FOUND",
                "type": global_match[0].strip(),
                "category": global_match[1].strip(),
                "subcategory": global_match[2].strip(),
                "article": global_match[3].strip()
            }

        # 3. ПРОВЕРКА ПО ИМЕНАМ ПОДКАТЕГОРИЙ И КАТЕГОРИЙ (с защитой от тарифов вроде 'Элит')
        group_sql = f"""
            SELECT type, category, subcategory, article
            FROM (
                SELECT type, category, subcategory, article, 1 as prio
                FROM user_dictionary
                WHERE user_id = %s AND is_deleted = FALSE
                UNION ALL
                SELECT type, category, subcategory, article, 2 as prio
                FROM global_dictionary
                WHERE is_default IS NOT FALSE
            ) AS combined
            WHERE (LOWER(TRIM(subcategory)) = %s OR LOWER(TRIM(category)) = %s)
            {'AND LOWER(TRIM(type)) = %s' if clean_type else ''}
            ORDER BY
                prio ASC,
                CASE
                    WHEN LOWER(TRIM(subcategory)) = %s THEN 1
                    WHEN LOWER(TRIM(category)) = %s THEN 2
                    ELSE 3
                END,
                CASE
                    WHEN LOWER(TRIM(article)) = %s THEN 1
                    WHEN LOWER(TRIM(article)) = LOWER(TRIM(subcategory)) THEN 2
                    WHEN LOWER(TRIM(article)) LIKE 'другое %%' THEN 3
                    WHEN LOWER(TRIM(article)) = 'эконом' THEN 4
                    ELSE 10
                END
            LIMIT 1;
        """
        if clean_type:
            cur.execute(group_sql, (uid, clean_item, clean_item, clean_type, clean_item, clean_item, clean_item))
        else:
            cur.execute(group_sql, (uid, clean_item, clean_item, clean_item, clean_item, clean_item))

        group_match = cur.fetchone()
        if group_match:
            m_type = group_match[0].strip()
            m_cat = group_match[1].strip()
            m_sub = group_match[2].strip()
            raw_art = (group_match[3] or "").strip()

            if clean_item == m_sub.lower():
                if raw_art.lower() == clean_item or "другое" in raw_art.lower():
                    final_art = raw_art
                else:
                    canonical = get_canonical_article_for_sub(uid, m_type, m_cat, m_sub, m_sub)
                    final_art = canonical
            else:
                final_art = raw_art if raw_art else item_name.strip().capitalize()

            return {
                "status": "FOUND",
                "type": m_type,
                "category": m_cat,
                "subcategory": m_sub,
                "article": final_art
            }

        # 4. НЕЧЁТКИЙ ТРИГРАММНЫЙ ПОИСК (pg_trgm)
        fuzzy_sql = f"""
            SELECT type, category, subcategory, article, synonym,
                   1 - (synonym <-> %s) AS similarity_score
            FROM (
                SELECT type, category, subcategory, article, LOWER(TRIM(synonym)) as synonym, 1 as prio
                FROM user_dictionary
                WHERE user_id = %s AND is_deleted = FALSE
                UNION ALL
                SELECT type, category, subcategory, article, LOWER(TRIM(synonym)) as synonym, 2 as prio
                FROM global_dictionary
                WHERE is_default IS NOT FALSE
            ) AS combined
            WHERE 1=1
            {'AND LOWER(TRIM(type)) = %s' if clean_type else ''}
            ORDER BY prio ASC, synonym <-> %s
            LIMIT 1;
        """
        if clean_type:
            cur.execute(fuzzy_sql, (clean_item, uid, clean_type, clean_item))
        else:
            cur.execute(fuzzy_sql, (clean_item, uid, clean_item))

        fuzzy_match = cur.fetchone()
        if fuzzy_match and fuzzy_match[5] is not None and fuzzy_match[5] >= 0.65:
            return {
                "status": "FOUND",
                "type": fuzzy_match[0].strip(),
                "category": fuzzy_match[1].strip(),
                "subcategory": fuzzy_match[2].strip(),
                "article": fuzzy_match[3].strip()
            }

        return {"status": "NOT_FOUND"}
    except Exception as e:
        print(f"Ошибка в smart_search_item: {e}")
        return {"status": "NOT_FOUND"}
    finally:
        cur.close()
        conn.close()

def save_transaction(user_id, op_type, category, subcategory, article, amount, comment, original_text, status='verified'):
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
    """
    Записывает синоним к конкретной канонической статье.
    Если article совпадает с synonym — регистрируется новая статья.
    Если article != synonym — регистрируется синоним к существующей статье.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        clean_syn = synonym.lower().strip()
        clean_art = article.strip()
        query = """
            INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
            VALUES (%s, %s, %s, %s, %s, %s, FALSE)
            ON CONFLICT (user_id, type, category, subcategory, article, synonym)
            DO UPDATE SET is_deleted = FALSE;
        """
        cur.execute(query, (uid, op_type, category, subcategory, clean_art, clean_syn))
        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка запоминания слова: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def promote_synonym_to_article(user_id, op_type, category, subcategory, word_name):
    """
    Повышает синоним до самостоятельной статьи пользователя и перепривязывает последние транзакции.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        clean_w = word_name.strip()
        clean_w_lower = clean_w.lower()

        # 1. Удаляем запись, где это слово было просто синонимом к чужой статье
        cur.execute("""
            DELETE FROM user_dictionary
            WHERE user_id = %s AND LOWER(TRIM(type)) = LOWER(TRIM(%s))
              AND LOWER(TRIM(synonym)) = %s AND LOWER(TRIM(article)) != %s;
        """, (uid, op_type, clean_w_lower, clean_w_lower))

        # 2. Создаем новую полноценную статью, где article == synonym
        cur.execute("""
            INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
            VALUES (%s, %s, %s, %s, %s, %s, FALSE)
            ON CONFLICT (user_id, type, category, subcategory, article, synonym)
            DO UPDATE SET is_deleted = FALSE;
        """, (uid, op_type, category, subcategory, clean_w.capitalize(), clean_w_lower))

        # 3. Обновляем последнюю транзакцию с этим исходным текстом
        cur.execute("""
            UPDATE transactions
            SET article = %s
            WHERE id = (
                SELECT id FROM transactions
                WHERE user_id = %s AND LOWER(TRIM(original_text)) = %s
                ORDER BY id DESC LIMIT 1
            );
        """, (clean_w.capitalize(), uid, clean_w_lower))

        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка повышения синонима до статьи: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def get_canonical_article_for_sub(user_id, op_type, category, subcategory, default_item):
    """
    Находит наиболее релевантную существующую каноническую статью в подкатегории.
    Если статей нет — возвращает default_item.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        cur.execute("""
            SELECT article FROM (
                SELECT article, 1 as prio FROM user_dictionary
                WHERE user_id = %s AND is_deleted = FALSE
                  AND LOWER(TRIM(type)) = LOWER(TRIM(%s))
                  AND LOWER(TRIM(category)) = LOWER(TRIM(%s))
                  AND LOWER(TRIM(subcategory)) = LOWER(TRIM(%s))
                  AND article != '' AND article IS NOT NULL
                UNION ALL
                SELECT article, 2 as prio FROM global_dictionary
                WHERE is_default IS NOT FALSE
                  AND LOWER(TRIM(type)) = LOWER(TRIM(%s))
                  AND LOWER(TRIM(category)) = LOWER(TRIM(%s))
                  AND LOWER(TRIM(subcategory)) = LOWER(TRIM(%s))
                  AND article != '' AND article IS NOT NULL
            ) AS arts
            ORDER BY prio ASC, length(article) ASC
            LIMIT 1;
        """, (uid, op_type, category, subcategory, op_type, category, subcategory))
        row = cur.fetchone()
        if row and row[0]:
            return row[0].strip()
        return default_item
    except Exception as e:
        print(f"Ошибка поиска канонической статьи: {e}")
        return default_item
    finally:
        cur.close()
        conn.close()

def get_full_menu(user_id):
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
                  AND LOWER(TRIM(u.type)) = LOWER(TRIM(g.type))
                  AND (
                      (LOWER(TRIM(u.category)) = LOWER(TRIM(g.category)) AND (u.subcategory = '' OR u.subcategory IS NULL) AND u.is_deleted = TRUE)
                      OR (LOWER(TRIM(u.category)) = LOWER(TRIM(g.category)) AND LOWER(TRIM(u.subcategory)) = LOWER(TRIM(g.subcategory)) AND (u.article = '' OR u.article IS NULL) AND u.is_deleted = TRUE)
                      OR (LOWER(TRIM(u.category)) = LOWER(TRIM(g.category)) AND LOWER(TRIM(u.subcategory)) = LOWER(TRIM(g.subcategory)) AND LOWER(TRIM(u.article)) = LOWER(TRIM(g.article)) AND u.is_deleted = TRUE)
                  )
            )
            UNION
            SELECT type, category, subcategory, article
            FROM user_dictionary
            WHERE user_id = %s AND is_deleted = FALSE
        """
        cur.execute(query, (uid, uid))
        for row in cur.fetchall():
            t, c, s, a = row[0].strip(), row[1].strip(), row[2].strip(), (row[3] or "").strip()
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
    """Возвращает сгруппированные нераспознанные операции."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        cur.execute("""
            SELECT t.id, t.type, t.original_text, t.amount, t.comment
            FROM transactions t
            WHERE t.user_id = %s
              AND (
                  t.status = 'needs_review'
                  OR LOWER(t.subcategory) = 'требует проверки'
                  OR LOWER(t.category) = 'разное'
              )
            ORDER BY t.id DESC;
        """, (uid,))
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
        uid = _resolve_internal_user_id(cur, user_id)
        cur.execute("""
            SELECT COUNT(*)
            FROM transactions t
            WHERE t.user_id = %s
              AND (
                  t.status = 'needs_review'
                  OR LOWER(t.subcategory) = 'требует проверки'
                  OR LOWER(t.category) = 'разное'
              );
        """, (uid,))
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
    Подтверждает операцию, обучает личный словарь синонимов к канонической статье
    и МГНОВЕННО каскадно обновляет ВСЕ транзакции с таким текстом у этого пользователя.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        clean_text = original_item.strip()
        canonical_article = get_canonical_article_for_sub(uid, op_type, category, subcategory, clean_text)

        # Обновляем абсолютно все совпадения по тексту у этого пользователя
        cur.execute("""
            UPDATE transactions
            SET category = %s, subcategory = %s, article = %s, type = %s, status = 'verified'
            WHERE user_id = %s
              AND LOWER(TRIM(original_text)) = LOWER(TRIM(%s))
              AND (
                  status = 'needs_review'
                  OR LOWER(subcategory) = 'требует проверки'
                  OR LOWER(category) = 'разное'
              );
        """, (category, subcategory, canonical_article, op_type, uid, clean_text))
        updated_count = cur.rowcount
        conn.commit()

        # Обучаем словарь синонимов
        learn_user_word(uid, op_type, category, subcategory, canonical_article, clean_text)
        return updated_count
    except Exception as e:
        print(f"Ошибка разрешения завалов: {e}")
        return 0
    finally:
        cur.close()
        conn.close()

def delete_unverified_by_text(user_id, original_item, op_type=None):
    """
    Удаляет ВСЕ транзакции с данным текстом (мусорные заголовки выписок)
    и заносит слово в теневой фильтр (is_deleted = TRUE), чтобы не появлялось вновь.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        clean_text = original_item.strip()
        cur.execute("""
            DELETE FROM transactions
            WHERE user_id = %s AND LOWER(TRIM(original_text)) = LOWER(TRIM(%s));
        """, (uid, clean_text))
        deleted_count = cur.rowcount

        target_types = [op_type] if op_type else ["Расход", "Доход"]
        for t in target_types:
            cur.execute("""
                INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
                VALUES (%s, %s, 'Мусор', 'Мусор', %s, %s, TRUE)
                ON CONFLICT (user_id, type, category, subcategory, article, synonym)
                DO UPDATE SET is_deleted = TRUE;
            """, (uid, t, clean_text, clean_text.lower()))
        conn.commit()
        return deleted_count
    except Exception as e:
        print(f"Ошибка удаления мусора из завалов: {e}")
        return 0
    finally:
        cur.close()
        conn.close()

def skip_unverified_by_text(user_id, original_item):
    """
    Пропускает нераспознанную операцию (помечает как skipped, исключая из очереди разбора).
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        clean_text = original_item.strip()
        cur.execute("""
            UPDATE transactions
            SET status = 'skipped'
            WHERE user_id = %s AND LOWER(TRIM(original_text)) = LOWER(TRIM(%s)) AND status = 'needs_review';
        """, (uid, clean_text))
        updated_count = cur.rowcount
        conn.commit()
        return updated_count
    except Exception as e:
        print(f"Ошибка пропуска операции: {e}")
        return 0
    finally:
        cur.close()
        conn.close()

def get_user_history(user_id, limit=10, period=None):
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

def delete_all_user_transactions(user_id, period=None):
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
        query = f"DELETE FROM transactions WHERE {where_sql};"
        cur.execute(query, tuple(params))
        deleted_count = cur.rowcount
        conn.commit()
        return deleted_count
    except Exception as e:
        print(f"Ошибка массового удаления операций: {e}")
        return 0
    finally:
        cur.close()
        conn.close()

def get_last_transaction(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        cur.execute("""
            SELECT id, operation_date, type, category, subcategory, article, amount, original_text
            FROM transactions
            WHERE user_id = %s
            ORDER BY id DESC LIMIT 1;
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
                "amount": float(r[6]),
                "original_text": r[7] or r[5]
            }
        return None
    except Exception as e:
        print(f"Ошибка получения последней операции: {e}")
        return None
    finally:
        cur.close()
        conn.close()

def update_transaction_amount(user_id, tx_id, new_amount):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        cur.execute("""
            UPDATE transactions SET amount = %s WHERE id = %s AND user_id = %s RETURNING id;
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

def update_transaction_category(user_id, tx_id, category, subcategory, article=None, op_type=None):
    """
    Обновляет категорию, подкатегорию, статью и опционально тип транзакции (Расход/Доход).
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        set_parts = ["category = %s", "subcategory = %s", "status = 'verified'"]
        params = [category, subcategory]
        if article:
            set_parts.append("article = %s")
            params.append(article)
        if op_type:
            set_parts.append("type = %s")
            params.append(op_type)
        params.extend([tx_id, uid])

        query = f"UPDATE transactions SET {', '.join(set_parts)} WHERE id = %s AND user_id = %s RETURNING id;"
        cur.execute(query, tuple(params))
        ok = cur.fetchone() is not None
        conn.commit()
        return ok
    except Exception as e:
        print(f"Ошибка обновления категории операции: {e}")
        return False
    finally:
        cur.close()
        conn.close()
