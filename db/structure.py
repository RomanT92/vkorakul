# -*- coding: utf-8 -*-
from .connection import get_db_connection
from .transactions import learn_user_word, _resolve_internal_user_id

def db_add_subcategory(user_id, op_type, category, subcategory):
    dummy_article = f"Другое {subcategory.lower()}"
    return learn_user_word(user_id, op_type, category, subcategory, dummy_article, dummy_article)

def db_add_article(user_id, op_type, category, subcategory, article):
    return learn_user_word(user_id, op_type, category, subcategory, article, article)

def db_rename_category(user_id, op_type, old_cat, new_cat):
    """Переименовывает категорию ТОЛЬКО для текущего пользователя."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        types_to_update = ["Расход", "Доход"] if not op_type else [op_type]
        for t in types_to_update:
            # 1. Обновляем журнал транзакций пользователя
            cur.execute("""
                UPDATE transactions SET category = %s
                WHERE user_id = %s AND type = %s AND category = %s;
            """, (new_cat, uid, t, old_cat))

            # 2. Обновляем личный словарь пользователя
            cur.execute("""
                UPDATE user_dictionary SET category = %s
                WHERE user_id = %s AND type = %s AND category = %s;
            """, (new_cat, uid, t, old_cat))

            # 3. Скрываем старую глобальную категорию для этого пользователя
            cur.execute("""
                INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
                VALUES (%s, %s, %s, '', '', '', TRUE)
                ON CONFLICT (user_id, type, category, subcategory, article, synonym)
                DO UPDATE SET is_deleted = TRUE;
            """, (uid, t, old_cat))

            # 4. Копируем все подкатегории и статьи из глобальной базы под новым именем в личный словарь
            cur.execute("""
                INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
                SELECT %s, type, %s, subcategory, article, synonym, FALSE
                FROM global_dictionary
                WHERE type = %s AND category = %s
                ON CONFLICT (user_id, type, category, subcategory, article, synonym)
                DO UPDATE SET is_deleted = FALSE;
            """, (uid, new_cat, t, old_cat))
        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка переименования категории: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def db_rename_subcategory(user_id, op_type, category, old_sub, new_sub):
    """Переименовывает подкатегорию ТОЛЬКО для текущего пользователя."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        types_to_update = ["Расход", "Доход"] if not op_type else [op_type]
        for t in types_to_update:
            cur.execute("""
                UPDATE transactions SET subcategory = %s
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s;
            """, (new_sub, uid, t, category, old_sub))

            cur.execute("""
                UPDATE user_dictionary SET subcategory = %s
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s;
            """, (new_sub, uid, t, category, old_sub))

            # Скрываем старую подкатегорию
            cur.execute("""
                INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
                VALUES (%s, %s, %s, %s, '', '', TRUE)
                ON CONFLICT (user_id, type, category, subcategory, article, synonym)
                DO UPDATE SET is_deleted = TRUE;
            """, (uid, t, category, old_sub))

            # Переносим статьи под новым именем
            cur.execute("""
                INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
                SELECT %s, type, category, %s, article, synonym, FALSE
                FROM global_dictionary
                WHERE type = %s AND category = %s AND subcategory = %s
                ON CONFLICT (user_id, type, category, subcategory, article, synonym)
                DO UPDATE SET is_deleted = FALSE;
            """, (uid, new_sub, t, category, old_sub))

        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка переименования подкатегории: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def db_rename_article(user_id, op_type, category, subcategory, old_art, new_art):
    """Переименовывает статью ТОЛЬКО для текущего пользователя."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        cur.execute("""
            UPDATE transactions SET article = %s
            WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s AND article = %s;
        """, (new_art, uid, op_type, category, subcategory, old_art))

        # Скрываем старую статью
        cur.execute("""
            INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (user_id, type, category, subcategory, article, synonym)
            DO UPDATE SET is_deleted = TRUE;
        """, (uid, op_type, category, subcategory, old_art, old_art.lower().strip()))

        # Записываем новую статью
        learn_user_word(uid, op_type, category, subcategory, new_art, new_art)
        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка переименования статьи: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def db_delete_entity(user_id, level, op_type, category, subcategory='', article=''):
    """
    Удаляет категорию, подкатегорию или статью ИСКЛЮЧИТЕЛЬНО для текущего пользователя.
    Глобальная база не изменяется!
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)

        if level == "category":
            # Мягкое удаление в личном словаре
            cur.execute("""
                UPDATE user_dictionary SET is_deleted = TRUE
                WHERE user_id = %s AND type = %s AND category = %s;
            """, (uid, op_type, category))

            # Скрытие категории из глобальной базы для данного пользователя
            cur.execute("""
                INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
                VALUES (%s, %s, %s, '', '', '', TRUE)
                ON CONFLICT (user_id, type, category, subcategory, article, synonym)
                DO UPDATE SET is_deleted = TRUE;
            """, (uid, op_type, category))

        elif level == "subcategory":
            cur.execute("""
                UPDATE user_dictionary SET is_deleted = TRUE
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s;
            """, (uid, op_type, category, subcategory))

            cur.execute("""
                INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
                VALUES (%s, %s, %s, %s, '', '', TRUE)
                ON CONFLICT (user_id, type, category, subcategory, article, synonym)
                DO UPDATE SET is_deleted = TRUE;
            """, (uid, op_type, category, subcategory))

        elif level == "article":
            cur.execute("""
                UPDATE user_dictionary SET is_deleted = TRUE
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s AND article = %s;
            """, (uid, op_type, category, subcategory, article))

            cur.execute("""
                INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                ON CONFLICT (user_id, type, category, subcategory, article, synonym)
                DO UPDATE SET is_deleted = TRUE;
            """, (uid, op_type, category, subcategory, article, article.lower().strip()))

        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка изоляционного удаления: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def db_move_entity(user_id, level, op_type, category, subcategory, article, new_parent, new_cat=None):
    """Переносит подкатегорию или статью изолированно для пользователя."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        if level == "subcategory":
            cur.execute("""
                UPDATE transactions SET category = %s
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s;
            """, (new_parent, uid, op_type, category, subcategory))

            # Скрываем старую связку
            db_delete_entity(uid, "subcategory", op_type, category, subcategory)

            # Добавляем в новую категорию
            cur.execute("""
                INSERT INTO user_dictionary (user_id, type, category, subcategory, article, synonym, is_deleted)
                SELECT %s, type, %s, subcategory, article, synonym, FALSE
                FROM global_dictionary
                WHERE type = %s AND category = %s AND subcategory = %s
                ON CONFLICT (user_id, type, category, subcategory, article, synonym)
                DO UPDATE SET is_deleted = FALSE;
            """, (uid, new_parent, op_type, category, subcategory))

        elif level == "article":
            target_cat = new_cat if new_cat else category
            cur.execute("""
                UPDATE transactions SET category = %s, subcategory = %s
                WHERE user_id = %s AND type = %s AND category = %s AND subcategory = %s AND article = %s;
            """, (target_cat, new_parent, uid, op_type, category, subcategory, article))

            db_delete_entity(uid, "article", op_type, category, subcategory, article)
            learn_user_word(uid, op_type, target_cat, new_parent, article, article)

        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка изолированного перемещения: {e}")
        return False
    finally:
        cur.close()
        conn.close()
