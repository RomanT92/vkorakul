# -*- coding: utf-8 -*-
from datetime import datetime, timezone
import difflib
from psycopg2.extras import execute_values
from .connection import get_db_connection

def _resolve_internal_user_id(cur, user_id):
    """Гарантирует получение первичного ключа id (BIGINT) пользователя."""
    cur.execute("SELECT id FROM users WHERE id = %s OR vk_id = %s LIMIT 1;", (user_id, user_id))
    row = cur.fetchone()
    return row[0] if row else user_id

def import_parsed_operations(user_id, operations):
    """
    Массовая запись операций из выписок в PostgreSQL за один сетевой запрос.
    Поддерживает парсинг дат российских банков (dayfirst=True).
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)

        # 1. Загружаем активный словарь (глобальный + личный)
        cur.execute("""
            SELECT type, category, subcategory, article, LOWER(synonym)
            FROM user_dictionary
            WHERE user_id = %s AND is_deleted = FALSE
            UNION ALL
            SELECT type, category, subcategory, article, LOWER(synonym)
            FROM global_dictionary
            WHERE is_default = TRUE;
        """, (uid,))
        dict_rows = cur.fetchall()
        
        exact_dict = {}
        synonyms_by_type = {"Расход": [], "Доход": []}
        for r in dict_rows:
            t, c, s, a, syn = r[0], r[1], r[2], r[3], r[4].strip()
            exact_dict[(t, syn)] = (c, s, a)
            if t in synonyms_by_type:
                synonyms_by_type[t].append(syn)
        
        now = datetime.now(timezone.utc)
        records_to_insert = []
        verified_count = 0
        needs_review_count = 0
        
        try:
            import pandas as pd
            has_pd = True
        except ImportError:
            has_pd = False

        for op in operations:
            if len(op) < 4:
                continue
            raw_date, raw_type, amount, desc = op[0], op[1], float(op[2]), str(op[3]).strip()
            if not desc or amount <= 0:
                continue
            
            op_type = "Доход" if ("доход" in str(raw_type).lower() or "приход" in str(raw_type).lower()) else "Расход"
            desc_lower = desc.lower()
            op_date = now
            comment = ""
            
            if has_pd:
                # dayfirst=True гарантирует корректный парсинг ДД.ММ.ГГГГ для банков РФ
                parsed_ts = pd.to_datetime(raw_date, errors='coerce', dayfirst=True)
                if pd.notnull(parsed_ts):
                    op_date = parsed_ts.to_pydatetime()
                else:
                    op_date = now
                    comment = f"Файл: {raw_date}"
            else:
                op_date = now
                comment = f"Файл: {raw_date}"

            matched = exact_dict.get((op_type, desc_lower))
            if not matched:
                avail = synonyms_by_type.get(op_type, [])
                matches = difflib.get_close_matches(desc_lower, avail, n=1, cutoff=0.75)
                if matches:
                    matched = exact_dict.get((op_type, matches[0]))

            if matched:
                cat, sub, art = matched
                status = 'verified'
                verified_count += 1
            else:
                cat = 'Разное'
                sub = 'Требует проверки'
                art = desc
                status = 'needs_review'
                needs_review_count += 1

            records_to_insert.append((
                uid, op_date, op_type, cat, sub, art, amount, comment, desc, status
            ))

        if records_to_insert:
            query = """
                INSERT INTO transactions (user_id, operation_date, type, category, subcategory, article, amount, comment, original_text, status)
                VALUES %s
            """
            execute_values(cur, query, records_to_insert)
            conn.commit()

        return {
            "total": len(records_to_insert),
            "verified": verified_count,
            "needs_review": needs_review_count
        }
    except Exception as e:
        print(f"Ошибка массового импорта: {e}")
        return {"total": 0, "verified": 0, "needs_review": 0}
    finally:
        cur.close()
        conn.close()
