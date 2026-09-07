# -*- coding: utf-8 -*-
from psycopg2.extras import execute_values
from .connection import get_db_connection

def migrate_dictionary_from_gs(raw_data):
    """
    Загружает в PostgreSQL обе базы:
    1. Глобальные Синонимы Категорий
    2. Глобальная База Синонимов
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("TRUNCATE TABLE global_dictionary RESTART IDENTITY CASCADE;")
        data_to_insert = []
        
        if isinstance(raw_data, dict):
            if "data" in raw_data and isinstance(raw_data["data"], dict):
                art_rows = raw_data["data"].get("articles", [])
                cat_rows = raw_data["data"].get("categories", [])
            elif "articles" in raw_data or "categories" in raw_data:
                art_rows = raw_data.get("articles", [])
                cat_rows = raw_data.get("categories", [])
            elif "data" in raw_data and isinstance(raw_data["data"], list):
                art_rows = raw_data["data"]
                cat_rows = []
            else:
                art_rows = []
                cat_rows = []
        elif isinstance(raw_data, list):
            art_rows = raw_data
            cat_rows = []
        else:
            art_rows = []
            cat_rows = []

        # 1. ЗАГРУЗКА СИНОНИМОВ КАТЕГОРИЙ
        for i, row in enumerate(cat_rows):
            if i == 0:
                continue
            clean = [str(c).strip() for c in row if str(c).strip() != ""]
            if len(clean) < 2:
                continue
            is_default = True
            if clean[0].lower() in ['true', 'false']:
                is_default = (clean[0].lower() == 'true')
                clean = clean[1:]
            if len(clean) < 2:
                continue
            if clean[0] in ["Расход", "Доход", "Приход"]:
                op_type = "Доход" if clean[0] in ["Доход", "Приход"] else "Расход"
                clean = clean[1:]
            else:
                op_type = "Расход"
            if len(clean) < 2:
                continue
            cat = clean[0]
            sub = clean[1]
            article = f"Другое {sub.lower()}"
            synonyms_raw = clean[2:]
            syns = [sub.lower()]
            first_sub_word = sub.lower().split()[0]
            if len(first_sub_word) > 3 and first_sub_word not in syns:
                syns.append(first_sub_word)
            for s in synonyms_raw:
                s_clean = s.lower().strip()
                if s_clean and s_clean not in syns:
                    syns.append(s_clean)
            for syn in syns:
                data_to_insert.append((op_type, cat, sub, article, syn, is_default))

        # 2. ЗАГРУЗКА СТАТЕЙ И ТОВАРОВ
        for i, row in enumerate(art_rows):
            if i == 0:
                continue
            clean = [str(c).strip() for c in row if str(c).strip() != ""]
            if len(clean) < 3:
                continue
            is_default = True
            if clean[0].lower() in ['true', 'false']:
                is_default = (clean[0].lower() == 'true')
                clean = clean[1:]
            if len(clean) < 3:
                continue
            if clean[0] in ["Расход", "Доход", "Приход"]:
                op_type = "Доход" if clean[0] in ["Доход", "Приход"] else "Расход"
                clean = clean[1:]
            else:
                op_type = "Расход"
            if len(clean) < 3:
                continue
            cat = clean[0]
            sub = clean[1]
            article = clean[2]
            synonyms_raw = clean[3:]
            syns = [article.lower()]
            for s in synonyms_raw:
                s_clean = s.lower().strip()
                if s_clean and s_clean not in syns:
                    syns.append(s_clean)
            for syn in syns:
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
