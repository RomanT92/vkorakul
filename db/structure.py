# -*- coding: utf-8 -*-
from .connection import get_db_connection
from .transactions import learn_user_word

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
                UPDATE transactions SET category = %s
                WHERE user_id = %s AND type = %s AND category = %s;
            """, (new_cat, user_id, t, old_cat))
            cur.execute("""
                UPDATE user_dictionary SET category = %s
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
                UPDATE transactions SET subcategory = %s
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s;
            """, (new_sub, user_id, t, category, old_sub))
            cur.execute("""
                UPDATE user_dictionary SET subcategory = %s
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s;
            """, (new_sub, user_id, t, category, old_sub))
            cur.execute("""
                INSERT INTO user_dictionary (user_id, type, category, %s, article, synonym, FALSE)
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
            UPDATE user_dictionary SET article = %s, synonym = %s
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
            UPDATE transactions SET article = %s
            WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s AND article = %s;
        """, (new_art, user_id, op_type, category, subcategory, old_art))
        cur.execute("""
            UPDATE user_dictionary SET article = %s, synonym = %s
            WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s AND article = %s;
        """, (new_art, new_art.lower().strip(), user_id, op_type, category, subcategory, old_art))
        cur.execute("""
            INSERT INTO user_dictionary (user_id, type, category, subcategory, %s, %s, FALSE)
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
                UPDATE transactions SET category = %s
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s;
            """, (new_parent, user_id, op_type, category, subcategory))
            cur.execute("""
                UPDATE user_dictionary SET category = %s
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s;
            """, (new_parent, user_id, op_type, category, subcategory))
        elif level == "article":
            target_cat = new_cat if new_cat else category
            cur.execute("""
                UPDATE transactions SET category = %s, subcategory = %s
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s AND article = %s;
            """, (target_cat, new_parent, user_id, op_type, category, subcategory, article))
            cur.execute("""
                UPDATE user_dictionary SET category = %s, subcategory = %s
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
