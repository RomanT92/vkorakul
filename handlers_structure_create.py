# -*- coding: utf-8 -*-
from keyboards import (
    type_keyboard,
    get_cancel_keyboard,
    get_numbered_keyboard,
    get_main_keyboard,
    get_entity_keyboard
)
from services import send_vk_message
from db import (
    get_full_menu,
    db_add_subcategory,
    db_add_article
)

def handle_structure_create(user_id, internal_uid, user_text, user_text_lower, state, user_states):
    """Сценарии создания категорий, подкатегорий и статей."""
    
    # 1. СОЗДАНИЕ КАТЕГОРИИ
    if state == "create_cat_type":
        c_type = "Доход" if "доход" in user_text_lower else "Расход"
        user_states[user_id]["c_type"] = c_type
        pending_name = user_states[user_id].get("pending_name")
        if pending_name:
            user_states[user_id]["new_cat"] = pending_name
            user_states[user_id]["state"] = "create_cat_subname"
            send_vk_message(user_id, f"Выбран тип: {c_type}.\nКатегория: {pending_name}.\n\nТеперь введите название ПЕРВОЙ ПОДКАТЕГОРИИ для неё:", get_cancel_keyboard(show_back=True))
        else:
            user_states[user_id]["state"] = "create_cat_name"
            send_vk_message(user_id, f"Выбран тип: {c_type}.\n\nВведите название НОВОЙ КАТЕГОРИИ:", get_cancel_keyboard(show_back=True))
        return True

    if state == "create_cat_name":
        user_states[user_id]["new_cat"] = user_text
        user_states[user_id]["state"] = "create_cat_subname"
        send_vk_message(user_id, f"Категория: {user_text}.\n\nТеперь введите название ПЕРВОЙ ПОДКАТЕГОРИИ для неё:", get_cancel_keyboard(show_back=True))
        return True

    if state == "create_cat_subname":
        new_sub = user_text
        c_type = user_states[user_id]["c_type"]
        new_cat = user_states[user_id]["new_cat"]
        db_add_subcategory(internal_uid, c_type, new_cat, new_sub)
        send_vk_message(user_id, f"✅ Успешно! Создана категория '{new_cat} -> {new_sub}'.\nСтатьи-заглушки добавлены автоматически.", get_main_keyboard(user_id))
        del user_states[user_id]
        return True

    # 2. СОЗДАНИЕ ПОДКАТЕГОРИИ
    if state == "create_sub_type":
        c_type = "Доход" if "доход" in user_text_lower else "Расход"
        menu = get_full_menu(internal_uid).get(c_type, {})
        cats = sorted(list(menu.keys()))
        if not cats:
            send_vk_message(user_id, f"Категорий типа '{c_type}' пока нет. Сначала создайте категорию.", get_main_keyboard(user_id))
            del user_states[user_id]
            return True
        msg = f"Выберите категорию ({c_type}), в которую добавим подкатегорию:\n\n"
        for i, c in enumerate(cats):
            msg += f"{i+1}. {c}\n"
        user_states[user_id] = {"state": "create_sub_catselect", "c_type": c_type, "cats": cats, "menu": menu, "pending_name": user_states[user_id].get("pending_name")}
        send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))
        return True

    if state == "create_sub_catselect":
        if user_text.isdigit():
            idx = int(user_text) - 1
            cats = user_states[user_id].get("cats", [])
            if 0 <= idx < len(cats):
                sel_cat = cats[idx]
                user_states[user_id]["sel_cat"] = sel_cat
                pending_name = user_states[user_id].get("pending_name")
                if pending_name:
                    c_type = user_states[user_id]["c_type"]
                    db_add_subcategory(internal_uid, c_type, sel_cat, pending_name)
                    send_vk_message(user_id, f"✅ Успешно! Добавлена подкатегория '{sel_cat} -> {pending_name}'.", get_main_keyboard(user_id))
                    del user_states[user_id]
                else:
                    user_states[user_id]["state"] = "create_sub_name"
                    send_vk_message(user_id, f"Категория: {sel_cat}.\n\nВведите название НОВОЙ ПОДКАТЕГОРИИ:", get_cancel_keyboard(show_back=True))
                return True

    if state == "create_sub_name":
        new_sub = user_text
        c_type = user_states[user_id]["c_type"]
        sel_cat = user_states[user_id]["sel_cat"]
        db_add_subcategory(internal_uid, c_type, sel_cat, new_sub)
        send_vk_message(user_id, f"✅ Успешно! Добавлена подкатегория '{sel_cat} -> {new_sub}'.", get_main_keyboard(user_id))
        del user_states[user_id]
        return True

    # 3. СОЗДАНИЕ СТАТЬИ
    if state == "create_art_type":
        c_type = "Доход" if "доход" in user_text_lower else "Расход"
        full_menu = get_full_menu(internal_uid)
        menu = full_menu.get(c_type, {})
        cats = sorted(list(menu.keys()))
        msg = f"Выберите категорию ({c_type}):\n\n"
        for i, c in enumerate(cats):
            msg += f"{i+1}. {c}\n"
        user_states[user_id] = {"state": "create_art_catselect", "c_type": c_type, "cats": cats, "menu": full_menu, "pending_name": user_states[user_id].get("pending_name")}
        send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))
        return True

    if state == "create_art_catselect":
        if user_text.isdigit():
            idx = int(user_text) - 1
            cats = user_states[user_id].get("cats", [])
            if 0 <= idx < len(cats):
                sel_cat = cats[idx]
                c_type = user_states[user_id].get("c_type", "Расход")
                full_menu = user_states[user_id].get("menu", {})
                subs_dict = full_menu.get(c_type, {}).get(sel_cat, {})
                subs = sorted(list(subs_dict.keys())) if isinstance(subs_dict, dict) else sorted(subs_dict)
                if not subs:
                    send_vk_message(user_id, f"В категории '{sel_cat}' пока нет подкатегорий. Сначала создайте её.", get_main_keyboard(user_id))
                    del user_states[user_id]
                    return True
                msg = f"Выберите подкатегорию в '{sel_cat}':\n\n"
                for i, s in enumerate(subs):
                    msg += f"{i+1}. {s}\n"
                user_states[user_id]["state"] = "create_art_subselect"
                user_states[user_id]["sel_cat"] = sel_cat
                user_states[user_id]["subs"] = subs
                send_vk_message(user_id, msg, get_numbered_keyboard(len(subs), show_back=True))
                return True

    if state == "create_art_subselect":
        if user_text.isdigit():
            idx = int(user_text) - 1
            subs = user_states[user_id].get("subs", [])
            if 0 <= idx < len(subs):
                sel_sub = subs[idx]
                user_states[user_id]["sel_sub"] = sel_sub
                pending_name = user_states[user_id].get("pending_name")
                if pending_name:
                    db_add_article(internal_uid, user_states[user_id]["c_type"], user_states[user_id]["sel_cat"], sel_sub, pending_name)
                    send_vk_message(user_id, f"✅ Статья '{pending_name}' успешно создана!", get_main_keyboard(user_id))
                    del user_states[user_id]
                else:
                    user_states[user_id]["state"] = "create_art_name"
                    send_vk_message(user_id, f"Отлично: {user_states[user_id]['sel_cat']} -> {sel_sub}.\n\nВведите название НОВОЙ СТАТЬИ:", get_cancel_keyboard(show_back=True))
                return True

    if state == "create_art_name":
        art_name = user_text
        db_add_article(internal_uid, user_states[user_id]["c_type"], user_states[user_id]["sel_cat"], user_states[user_id]["sel_sub"], art_name)
        send_vk_message(user_id, f"✅ Статья '{art_name}' успешно создана!", get_main_keyboard(user_id))
        del user_states[user_id]
        return True

    return False
