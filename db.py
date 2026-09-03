# -*- coding: utf-8 -*-
import os
import sys
import subprocess
from datetime import datetime, timezone
import difflib

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
# 1. ПОДКЛЮЧЕНИЕ И УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ
# ====================================================================

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

# ====================================================================
# 2. ОСНОВНАЯ ЛОГИКА ТРАНЗАКЦИЙ И ПОИСКА
# ====================================================================

def smart_search_item(user_id, item_name, op_type):
    """
    Нечеткий поиск синонима с учетом опечаток через триграммы (pg_trgm).
    Сначала проверяет личный словарь пользователя, затем глобальный эталон (где стоит галочка).
    Исключает скрытые пользователем категории/статьи.
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
            
            SELECT g.type, g.category, g.subcategory, g.article, g.synonym 
            FROM global_dictionary g
            LEFT JOIN user_dictionary u ON (
                u.user_id = %s 
                AND u.type = g.type 
                AND u.category = g.category 
                AND u.subcategory = g.subcategory 
                AND u.article = g.article 
                AND u.is_deleted = TRUE
            )
            WHERE g.type = %s AND g.is_default = TRUE AND u.id IS NULL
        ) AS combined
        ORDER BY synonym <-> %s
        LIMIT 1;
        """
        cur.execute(query, (item_name, user_id, op_type, user_id, op_type, item_name))
        result = cur.fetchone()
        
        if result:
            score = result[5]
            # Порог соответствия 70%
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
    """Сохраняет новое слово в персональный словарь пользователя (user_dictionary)."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        query = """
        INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
        VALUES (%s, %s, %s, %s, %s, %s, FALSE)
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
                u.user_id = %s 
                AND u.type = g.type 
                AND u.category = g.category 
                AND u.subcategory = g.subcategory 
                AND u.article = g.article 
                AND u.is_deleted = TRUE
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
    """Возвращает список нераспознанных операций пользователя со статусом 'needs_review'."""
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
    Массово подтверждает операции из завалов, устанавливая категорию,
    и одновременно вносит термин в личный словарь.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE transactions 
            SET category = %s, subcategory = %s, article = %s, status = 'verified'
            WHERE user_id = %s AND original_text = %s AND status = 'needs_review';
        """, (category, subcategory, original_item, user_id, original_item))
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
# 3. УПРАВЛЕНИЕ СТРУКТУРОЙ (CRUD)
# ====================================================================

def db_add_subcategory(user_id, op_type, category, subcategory):
    """Добавляет подкатегорию и служебную статью 'Другое <подкатегория>'."""
    dummy_article = f"Другое {subcategory.lower()}"
    return learn_user_word(user_id, op_type, category, subcategory, dummy_article, dummy_article)

def db_add_article(user_id, op_type, category, subcategory, article):
    """Добавляет новую статью пользователю."""
    return learn_user_word(user_id, op_type, category, subcategory, article, article)

def db_rename_category(user_id, op_type, old_cat, new_cat):
    """Переименовывает категорию в журнале и словаре пользователя."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        types_to_update = ["Расход", "Доход"] if not op_type else [op_type]
        for t in types_to_update:
            cur.execute("""
                UPDATE transactions 
                SET category = %s 
                WHERE user_id = %s AND type = %s AND category = %s;
            """, (new_cat, user_id, t, old_cat))

            cur.execute("""
                UPDATE user_dictionary 
                SET category = %s 
                WHERE user_id = %s AND type = %s AND category = %s;
            """, (new_cat, user_id, t, old_cat))

            cur.execute("""
                INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
                SELECT %s, type, %s, subcategory, article, synonym, FALSE
                FROM global_dictionary
                WHERE is_default = TRUE AND type = %s AND category = %s
                ON CONFLICT DO NOTHING;
            """, (user_id, new_cat, t, old_cat))

            cur.execute("""
                INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
                SELECT %s, type, category, subcategory, article, synonym, TRUE
                FROM global_dictionary
                WHERE is_default = TRUE AND type = %s AND category = %s
                ON CONFLICT (user_id, type, category, subcategory, article, synonym)
                DO UPDATE SET is_deleted = TRUE;
            """, (user_id, t, old_cat))

        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка переименования категории: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def db_rename_subcategory(user_id, op_type, category, old_sub, new_sub):
    """Переименовывает подкатегорию в журнале и словаре пользователя."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        types_to_update = ["Расход", "Доход"] if not op_type else [op_type]
        for t in types_to_update:
            cur.execute("""
                UPDATE transactions 
                SET subcategory = %s 
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s;
            """, (new_sub, user_id, t, category, old_sub))

            cur.execute("""
                UPDATE user_dictionary 
                SET subcategory = %s 
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s;
            """, (new_sub, user_id, t, category, old_sub))

            cur.execute("""
                INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
                SELECT %s, type, category, %s, article, synonym, FALSE
                FROM global_dictionary
                WHERE is_default = TRUE AND type = %s AND category = %s AND subcategory = %s
                ON CONFLICT DO NOTHING;
            """, (user_id, new_sub, t, category, old_sub))

            cur.execute("""
                INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
                SELECT %s, type, category, subcategory, article, synonym, TRUE
                FROM global_dictionary
                WHERE is_default = TRUE AND type = %s AND category = %s AND subcategory = %s
                ON CONFLICT (user_id, type, category, subcategory, article, synonym)
                DO UPDATE SET is_deleted = TRUE;
            """, (user_id, t, category, old_sub))

            old_dummy = f"Другое {old_sub.lower()}"
            new_dummy = f"Другое {new_sub.lower()}"
            cur.execute("""
                UPDATE user_dictionary 
                SET article = %s, synonym = %s 
                WHERE user_id = %s AND article = %s;
            """, (new_dummy, new_dummy.lower(), user_id, old_dummy))

        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка переименования подкатегории: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def db_rename_article(user_id, op_type, category, subcategory, old_art, new_art):
    """Переименовывает статью в журнале и словаре пользователя."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE transactions 
            SET article = %s 
            WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s AND article = %s;
        """, (new_art, user_id, op_type, category, subcategory, old_art))

        cur.execute("""
            UPDATE user_dictionary 
            SET article = %s, synonym = %s 
            WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s AND article = %s;
        """, (new_art, new_art.lower().strip(), user_id, op_type, category, subcategory, old_art))

        cur.execute("""
            INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
            SELECT %s, type, category, subcategory, %s, %s, FALSE
            FROM global_dictionary
            WHERE is_default = TRUE AND type = %s AND category = %s AND subcategory = %s AND article = %s
            ON CONFLICT DO NOTHING;
        """, (user_id, new_art, new_art.lower().strip(), op_type, category, subcategory, old_art))

        cur.execute("""
            INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
            SELECT %s, type, category, subcategory, article, synonym, TRUE
            FROM global_dictionary
            WHERE is_default = TRUE AND type = %s AND category = %s AND subcategory = %s AND article = %s
            ON CONFLICT (user_id, type, category, subcategory, article, synonym)
            DO UPDATE SET is_deleted = TRUE;
        """, (user_id, op_type, category, subcategory, old_art))

        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка переименования статьи: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def db_delete_entity(user_id, level, op_type, category, subcategory='', article=''):
    """Удаляет категорию, подкатегорию или статью исключительно для текущего пользователя."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if level == "category":
            cur.execute("""
                UPDATE user_dictionary SET is_deleted = TRUE 
                WHERE user_id = %s AND type = %s AND category = %s;
            """, (user_id, op_type, category))

            cur.execute("""
                INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
                SELECT %s, type, category, subcategory, article, synonym, TRUE
                FROM global_dictionary
                WHERE is_default = TRUE AND type = %s AND category = %s
                ON CONFLICT (user_id, type, category, subcategory, article, synonym)
                DO UPDATE SET is_deleted = TRUE;
            """, (user_id, op_type, category))

        elif level == "subcategory":
            cur.execute("""
                UPDATE user_dictionary SET is_deleted = TRUE 
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s;
            """, (user_id, op_type, category, subcategory))

            cur.execute("""
                INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
                SELECT %s, type, category, subcategory, article, synonym, TRUE
                FROM global_dictionary
                WHERE is_default = TRUE AND type = %s AND category = %s AND subcategory = %s
                ON CONFLICT (user_id, type, category, subcategory, article, synonym)
                DO UPDATE SET is_deleted = TRUE;
            """, (user_id, op_type, category, subcategory))

        elif level == "article":
            cur.execute("""
                UPDATE user_dictionary SET is_deleted = TRUE 
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s AND article = %s;
            """, (user_id, op_type, category, subcategory, article))

            cur.execute("""
                INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
                SELECT %s, type, category, subcategory, article, synonym, TRUE
                FROM global_dictionary
                WHERE is_default = TRUE AND type = %s AND category = %s AND subcategory = %s AND article = %s
                ON CONFLICT (user_id, type, category, subcategory, article, synonym)
                DO UPDATE SET is_deleted = TRUE;
            """, (user_id, op_type, category, subcategory, article))

        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка удаления сущности: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def db_move_entity(user_id, level, op_type, category, subcategory, article, new_parent, new_cat=None):
    """Переносит подкатегорию или статью в новую родительскую папку."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if level == "subcategory":
            cur.execute("""
                UPDATE transactions 
                SET category = %s 
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s;
            """, (new_parent, user_id, op_type, category, subcategory))

            cur.execute("""
                UPDATE user_dictionary 
                SET category = %s 
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s;
            """, (new_parent, user_id, op_type, category, subcategory))

        elif level == "article":
            target_cat = new_cat if new_cat else category
            cur.execute("""
                UPDATE transactions 
                SET category = %s, subcategory = %s 
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s AND article = %s;
            """, (target_cat, new_parent, user_id, op_type, category, subcategory, article))

            cur.execute("""
                UPDATE user_dictionary 
                SET category = %s, subcategory = %s 
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s AND article = %s;
            """, (target_cat, new_parent, user_id, op_type, category, subcategory, article))

        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка перемещения: {e}")
        return False
    finally:
        cur.close()
        conn.close()

# ====================================================================
# 4. МАССОВЫЙ ИНТЕЛЛЕКТУАЛЬНЫЙ ИМПОРТ ФАЙЛОВ
# ====================================================================

def import_parsed_operations(user_id, operations):
    """Массовая запись операций из выписок в PostgreSQL за один запрос."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT type, category, subcategory, article, synonym 
            FROM user_dictionary 
            WHERE user_id = %s AND is_deleted = FALSE
            UNION ALL
            SELECT type, category, subcategory, article, synonym 
            FROM global_dictionary 
            WHERE is_default = TRUE;
        """, (user_id,))
        
        dict_rows = cur.fetchall()
        exact_dict = {}
        synonyms_by_type = {"Расход": [], "Доход": []}
        
        for r in dict_rows:
            t, c, s, a, syn = r[0], r[1], r[2], r[3], r[4].lower().strip()
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
            if len(op) < 4: continue
            raw_date, raw_type, amount, desc = op[0], op[1], float(op[2]), str(op[3]).strip()
            if not desc or amount <= 0: continue

            op_type = "Доход" if ("доход" in raw_type.lower() or "приход" in raw_type.lower()) else "Расход"
            desc_lower = desc.lower()

            op_date = now
            comment = ""
            if has_pd:
                parsed_ts = pd.to_datetime(raw_date, errors='coerce')
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
                user_id, op_date, op_type, cat, sub, art, amount, comment, desc, status
            ))

        if records_to_insert:
            query = """
                INSERT INTO transactions 
                (user_id, operation_date, type, category, subcategory, article, amount, comment, original_text, status)
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

# ====================================================================
# 5. МИГРАЦИЯ И СБОР НОВЫХ СЛОВ (ДЛЯ АДМИНИСТРАТОРА)
# ====================================================================

def migrate_dictionary_from_gs(raw_data):
    """
    Умный парсер миграции с авто-детектором сдвига колонок и галочек.
    Корректно обрабатывает и строки с галочками [TRUE, Расход, ...],
    и строки без галочек [Расход, Категория, ...].
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("TRUNCATE TABLE global_dictionary RESTART IDENTITY CASCADE;")
        
        data_to_insert = []
        for i, row in enumerate(raw_data):
            if i == 0: continue # Пропускаем шапку
            if not row or len(row) < 3: continue
            
            # Приводим строку к чистому списку непустых ячеек
            clean_row = [str(cell).strip() for cell in row if str(cell).strip() != ""]
            if len(clean_row) < 3: continue
            
            first_val = clean_row[0].lower()
            
            # --- СЛУЧАЙ А: Первая колонка - это чекбокс (true/false) ---
            if first_val in ['true', 'false']:
                is_default = (first_val == 'true')
                clean_row = clean_row[1:] # Сдвигаем вправо
            else:
                # Если явной галочки нет, по умолчанию включаем статью в активные
                is_default = True

            if len(clean_row) < 3: continue

            # --- ОПРЕДЕЛЯЕМ ТИП (Расход / Доход) ---
            second_val = clean_row[0]
            if second_val in ["Расход", "Доход", "Приход"]:
                op_type = "Доход" if second_val in ["Доход", "Приход"] else "Расход"
                clean_row = clean_row[1:]
            else:
                op_type = "Расход" # По умолчанию Расход

            if len(clean_row) < 2: continue

            # --- РАСКЛАДЫВАЕМ ИЕРАРХИЮ ---
            if len(clean_row) >= 3:
                cat = clean_row[0]
                sub = clean_row[1]
                article = clean_row[2]
                synonyms_raw = clean_row[3:]
            elif len(clean_row) == 2:
                cat = clean_row[0]
                sub = clean_row[1]
                article = f"Другое {sub.lower()}"
                synonyms_raw = []
            else:
                continue

            # Собираем синонимы: само название статьи + подкатегория + все остальные колонки
            synonyms = [article.lower()]
            if sub.lower() not in synonyms:
                synonyms.append(sub.lower())
                
            for syn in synonyms_raw:
                s_clean = syn.lower().strip()
                if s_clean and s_clean not in synonyms:
                    synonyms.append(s_clean)
                    
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

def get_new_unharvested_words():
    """
    Находит все уникальные слова, которые пользователи добавили в свои личные словари,
    но которых ещё нет в Глобальной базе.
    Возвращает список строк для Google Таблицы: [FALSE, Тип, Категория, Подкатегория, Статья, Синоним]
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        query = """
            SELECT DISTINCT u.type, u.category, u.subcategory, u.article, u.synonym
            FROM user_dictionary u
            WHERE u.is_deleted = FALSE
              AND NOT EXISTS (
                  SELECT 1 FROM global_dictionary g
                  WHERE LOWER(g.synonym) = LOWER(u.synonym)
                    AND g.type = u.type
              )
            ORDER BY u.type, u.category, u.subcategory, u.article;
        """
        cur.execute(query)
        rows = cur.fetchall()
        
        harvested_rows = []
        for r in rows:
            harvested_rows.append([False, r[0], r[1], r[2], r[3], r[4]])
            
        return harvested_rows
    finally:
        cur.close()
        conn.close()
