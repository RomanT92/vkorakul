# -*- coding: utf-8 -*-
from keyboards import (
    type_keyboard, get_cancel_keyboard, get_numbered_keyboard, 
    get_main_keyboard, get_yes_no_keyboard, get_entity_keyboard, get_move_entity_keyboard
)
from services import send_vk_message, send_to_google_sheets

def handle_structure(user_id, user_text, user_text_lower, state, user_states):
    """
    Обрабатывает ветку "Категории и статьи" (Создание, Переименование, Удаление, Перенос).
    Возвращает True, если стейт относится к структуре и был обработан.
    """
    
    # ====================================================================
    # 0. МАРШРУТИЗАЦИЯ ВЫБОРА (СВЯЗУЮЩИЕ БЛОКИ)
    # ====================================================================
    if state == "wait_entity_create":
        if user_text_lower == "категорию":
            user_states[user_id] = {"state": "create_cat_type"}
            send_vk_message(user_id, "Это будет категория Расходов или Доходов?", type_keyboard())
            return True
        elif user_text_lower == "подкатегорию":
            user_states[user_id] = {"state": "create_sub_type"}
            send_vk_message(user_id, "Это будет подкатегория Расходов или Доходов?", type_keyboard())
            return True
        elif user_text_lower == "статью":
            user_states[user_id] = {"state": "create_art_type"}
            send_vk_message(user_id, "Это будет статья Расходов или Доходов?", type_keyboard())
            return True

    if state == "wait_entity_rename":
        if user_text_lower == "категорию":
            send_vk_message(user_id, "⏳ Загружаю список категорий...")
            res = send_to_google_sheets({"action": "get_full_menu"})
            if res.get("status") == "SUCCESS":
                menu = res.get("menu", {})
                cats = list(set(list(menu.get("Расход", {}).keys()) + list(menu.get("Доход", {}).keys())))
                cats.sort()
                if not cats:
                    send_vk_message(user_id, "Категорий пока нет.", get_main_keyboard())
                    return True
                msg = "Какую категорию переименовать?\n\n"
                for i, c in enumerate(cats):
                    msg += f"{i+1}. {c}\n"
                user_states[user_id] = {"state": "rename_cat_select", "cats": cats, "menu": menu}
                send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
            return True
            
        elif user_text_lower == "подкатегорию":
            send_vk_message(user_id, "⏳ Загружаю список...")
            res = send_to_google_sheets({"action": "get_full_menu"})
            if res.get("status") == "SUCCESS":
                menu = res.get("menu", {})
                cats = list(set(list(menu.get("Расход", {}).keys()) + list(menu.get("Доход", {}).keys())))
                cats.sort()
                msg = "В какой категории находится подкатегория?\n\n"
                for i, c in enumerate(cats):
                    msg += f"{i+1}. {c}\n"
                user_states[user_id] = {"state": "rename_sub_select_cat", "cats": cats, "menu": menu}
                send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
            return True
            
        elif user_text_lower == "статью":
            send_vk_message(user_id, "⏳ Загружаю меню...")
            res = send_to_google_sheets({"action": "get_full_menu"})
            if res.get("status") == "SUCCESS":
                user_states[user_id] = {"state": "rename_art_type", "menu": res.get("menu", {})}
                send_vk_message(user_id, "Статья находится в Расходах или Доходах?", type_keyboard())
            return True

    if state == "wait_del_move_action":
        if user_text_lower == "удалить":
            user_states[user_id]["state"] = "delete_select_level"
            send_vk_message(user_id, "Что именно удалить?", get_entity_keyboard())
            return True
        elif user_text_lower == "перенести":
            user_states[user_id]["state"] = "move_select_level"
            send_vk_message(user_id, "Что именно перенести?", get_move_entity_keyboard())
            return True

    # ====================================================================
    # 1. ВЕТКА: СОЗДАТЬ
    # ====================================================================
    if state == "create_cat_type":
        c_type = "Доход" if "доход" in user_text_lower else "Расход"
        user_states[user_id]["c_type"] = c_type
        user_states[user_id]["state"] = "create_cat_name"
        send_vk_message(user_id, f"Выбран тип: {c_type}.\n\nВведите название НОВОЙ КАТЕГОРИИ:", get_cancel_keyboard())
        return True

    if state == "create_cat_name":
        user_states[user_id]["new_cat"] = user_text
        user_states[user_id]["state"] = "create_cat_subname"
        send_vk_message(user_id, f"Категория: {user_text}.\n\nТеперь введите название ПЕРВОЙ ПОДКАТЕГОРИИ для неё:", get_cancel_keyboard())
        return True

    if state == "create_cat_subname":
        new_sub = user_text
        c_type = user_states[user_id]["c_type"]
        new_cat = user_states[user_id]["new_cat"]
        payload = {"action": "add_subcategory", "type": c_type, "category": new_cat, "subcategory": new_sub}
        send_vk_message(user_id, "⏳ Создаю категорию и подкатегорию...")
        send_to_google_sheets(payload)
        send_vk_message(user_id, f"✅ Успешно! Создана категория '{new_cat} -> {new_sub}'.\nСтатьи-заглушки добавлены автоматически.", get_main_keyboard())
        del user_states[user_id]
        return True

    if state == "create_sub_type":
        c_type = "Доход" if "доход" in user_text_lower else "Расход"
        send_vk_message(user_id, "⏳ Загружаю список категорий...")
        res = send_to_google_sheets({"action": "get_full_menu"})
        if res.get("status") == "SUCCESS":
            menu = res.get("menu", {}).get(c_type, {})
            cats = list(menu.keys())
            cats.sort()
            if not cats:
                send_vk_message(user_id, f"Категорий типа '{c_type}' пока нет. Сначала создайте категорию.", get_main_keyboard())
                del user_states[user_id]
                return True
            msg = f"Выберите категорию ({c_type}), в которую добавим подкатегорию:\n\n"
            for i, c in enumerate(cats):
                msg += f"{i+1}. {c}\n"
            user_states[user_id] = {"state": "create_sub_catselect", "c_type": c_type, "cats": cats, "menu": menu}
            send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
        return True

    if state == "create_sub_catselect":
        if user_text.isdigit():
            idx = int(user_text) - 1
            cats = user_states[user_id].get("cats", [])
            if 0 <= idx < len(cats):
                sel_cat = cats[idx]
                user_states[user_id]["sel_cat"] = sel_cat
                user_states[user_id]["state"] = "create_sub_name"
                send_vk_message(user_id, f"Категория: {sel_cat}.\n\nВведите название НОВОЙ ПОДКАТЕГОРИИ:", get_cancel_keyboard())
                return True

    if state == "create_sub_name":
        new_sub = user_text
        c_type = user_states[user_id]["c_type"]
        sel_cat = user_states[user_id]["sel_cat"]
        payload = {"action": "add_subcategory", "type": c_type, "category": sel_cat, "subcategory": new_sub}
        send_vk_message(user_id, "⏳ Создаю подкатегорию...")
        send_to_google_sheets(payload)
        send_vk_message(user_id, f"✅ Успешно! Добавлена подкатегория '{sel_cat} -> {new_sub}'.\nСтатья-заглушка добавлена автоматически.", get_main_keyboard())
        del user_states[user_id]
        return True

    if state == "create_art_type":
        c_type = "Доход" if "доход" in user_text_lower else "Расход"
        send_vk_message(user_id, "⏳ Загружаю список категорий...")
        res = send_to_google_sheets({"action": "get_full_menu"})
        if res.get("status") == "SUCCESS":
            menu = res.get("menu", {}).get(c_type, {})
            cats = list(menu.keys())
            cats.sort()
            msg = f"Выберите категорию ({c_type}):\n\n"
            for i, c in enumerate(cats):
                msg += f"{i+1}. {c}\n"
            user_states[user_id] = {"state": "create_art_catselect", "c_type": c_type, "cats": cats, "menu": res.get("menu", {})}
            send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
        return True

    if state == "create_art_catselect":
        if user_text.isdigit():
            idx = int(user_text) - 1
            cats = user_states[user_id].get("cats", [])
            if 0 <= idx < len(cats):
                sel_cat = cats[idx]
                c_type = user_states[user_id].get("c_type", "Расход")
                
                full_menu = user_states[user_id].get("menu", {})
                type_menu = full_menu.get(c_type, {}) if isinstance(full_menu, dict) else {}
                subs_dict = type_menu.get(sel_cat, {}) if isinstance(type_menu, dict) else {}
                
                if isinstance(subs_dict, dict):
                    subs = list(subs_dict.keys())
                else:
                    subs = []
                subs.sort()
                
                if not subs:
                    send_vk_message(user_id, f"В категории '{sel_cat}' пока нет подкатегорий. Сначала создайте её.", get_main_keyboard())
                    del user_states[user_id]
                    return True
                    
                msg = f"Выберите подкатегорию в '{sel_cat}':\n\n"
                for i, s in enumerate(subs):
                    msg += f"{i+1}. {s}\n"
                user_states[user_id]["state"] = "create_art_subselect"
                user_states[user_id]["sel_cat"] = sel_cat
                user_states[user_id]["subs"] = subs
                send_vk_message(user_id, msg, get_numbered_keyboard(len(subs)))
                return True

    if state == "create_art_subselect":
        if user_text.isdigit():
            idx = int(user_text) - 1
            subs = user_states[user_id].get("subs", [])
            if 0 <= idx < len(subs):
                sel_sub = subs[idx]
                user_states[user_id]["state"] = "create_art_name"
                user_states[user_id]["sel_sub"] = sel_sub
                send_vk_message(user_id, f"Отлично: {user_states[user_id]['sel_cat']} -> {sel_sub}.\n\nВведите название НОВОЙ СТАТЬИ:", get_cancel_keyboard())
                return True

    if state == "create_art_name":
        art_name = user_text
        payload = {
            "action": "add_article",
            "type": user_states[user_id]["c_type"],
            "category": user_states[user_id]["sel_cat"],
            "subcategory": user_states[user_id]["sel_sub"],
            "item": art_name
        }
        send_vk_message(user_id, "⏳ Добавляю статью в базу...")
        send_to_google_sheets(payload)
        send_vk_message(user_id, f"✅ Статья '{art_name}' успешно создана!", get_main_keyboard())
        del user_states[user_id]
        return True

    # ====================================================================
    # 2. ВЕТКА: ПЕРЕИМЕНОВАТЬ
    # ====================================================================
    if state == "rename_cat_select":
        if user_text.isdigit():
            idx = int(user_text) - 1
            cats = user_states[user_id]["cats"]
            if 0 <= idx < len(cats):
                old_cat = cats[idx]
                user_states[user_id]["state"] = "rename_cat_type"
                user_states[user_id]["old_cat"] = old_cat
                send_vk_message(user_id, f"Введите новое название для категории '{old_cat}':", get_cancel_keyboard())
                return True

    if state == "rename_cat_type":
        new_cat = user_text
        old_cat = user_states[user_id]["old_cat"]
        send_vk_message(user_id, f"⏳ Переименовываю '{old_cat}' в '{new_cat}' во всех базах...")
        send_to_google_sheets({"action": "rename_category", "old_cat": old_cat, "new_cat": new_cat, "type": "Расход"})
        send_to_google_sheets({"action": "rename_category", "old_cat": old_cat, "new_cat": new_cat, "type": "Доход"})
        send_vk_message(user_id, "✅ Категория успешно переименована!", get_main_keyboard())
        del user_states[user_id]
        return True

    if state == "rename_sub_select_cat":
        if user_text.isdigit():
            idx = int(user_text) - 1
            cats = user_states[user_id]["cats"]
            if 0 <= idx < len(cats):
                sel_cat = cats[idx]
                menu = user_states[user_id]["menu"]
                subs_exp = list(menu.get("Расход", {}).get(sel_cat, {}).keys())
                subs_inc = list(menu.get("Доход", {}).get(sel_cat, {}).keys())
                subs = list(set(subs_exp + subs_inc))
                subs.sort()
                if not subs:
                    send_vk_message(user_id, f"В категории '{sel_cat}' нет подкатегорий.", get_main_keyboard())
                    del user_states[user_id]
                    return True
                msg = f"Какую подкатегорию в '{sel_cat}' переименовать?\n\n"
                for i, s in enumerate(subs):
                    msg += f"{i+1}. {s}\n"
                user_states[user_id]["state"] = "rename_sub_select_sub"
                user_states[user_id]["sel_cat"] = sel_cat
                user_states[user_id]["subs"] = subs
                send_vk_message(user_id, msg, get_numbered_keyboard(len(subs)))
                return True

    if state == "rename_sub_select_sub":
        if user_text.isdigit():
            idx = int(user_text) - 1
            subs = user_states[user_id]["subs"]
            if 0 <= idx < len(subs):
                old_sub = subs[idx]
                user_states[user_id]["state"] = "rename_sub_type"
                user_states[user_id]["old_sub"] = old_sub
                send_vk_message(user_id, f"Введите новое название для '{old_sub}':", get_cancel_keyboard())
                return True

    if state == "rename_sub_type":
        new_sub = user_text
        sel_cat = user_states[user_id]["sel_cat"]
        old_sub = user_states[user_id]["old_sub"]
        send_vk_message(user_id, f"⏳ Переименовываю '{old_sub}' в '{new_sub}'...")
        send_to_google_sheets({"action": "rename_subcategory", "cat": sel_cat, "old_sub": old_sub, "new_sub": new_sub, "type": "Расход"})
        send_to_google_sheets({"action": "rename_subcategory", "cat": sel_cat, "old_sub": old_sub, "new_sub": new_sub, "type": "Доход"})
        send_vk_message(user_id, "✅ Подкатегория успешно переименована!", get_main_keyboard())
        del user_states[user_id]
        return True

    if state == "rename_art_cat":
        if user_text.isdigit():
            idx = int(user_text) - 1
            cats = user_states[user_id]["cats"]
            if 0 <= idx < len(cats):
                sel_cat = cats[idx]
                c_type = user_states[user_id]["c_type"]
                subs_dict = user_states[user_id]["menu"][c_type].get(sel_cat, {})
                subs = list(subs_dict.keys())
                subs.sort()
                msg = f"Выберите подкатегорию в '{sel_cat}':\n\n"
                for i, s in enumerate(subs):
                    msg += f"{i+1}. {s}\n"
                user_states[user_id]["state"] = "rename_art_sub"
                user_states[user_id]["sel_cat"] = sel_cat
                user_states[user_id]["subs"] = subs
                send_vk_message(user_id, msg, get_numbered_keyboard(len(subs)))
                return True

    if state == "rename_art_sub":
        if user_text.isdigit():
            idx = int(user_text) - 1
            subs = user_states[user_id]["subs"]
            if 0 <= idx < len(subs):
                sel_sub = subs[idx]
                c_type = user_states[user_id]["c_type"]
                sel_cat = user_states[user_id]["sel_cat"]
                arts = user_states[user_id]["menu"][c_type][sel_cat].get(sel_sub, [])
                arts.sort()
                if not arts:
                    send_vk_message(user_id, "В этой подкатегории нет статей.", get_main_keyboard())
                    del user_states[user_id]
                    return True
                msg = f"Какую статью переименовать?\n\n"
                for i, a in enumerate(arts):
                    msg += f"{i+1}. {a}\n"
                user_states[user_id]["state"] = "rename_art_select"
                user_states[user_id]["sel_sub"] = sel_sub
                user_states[user_id]["arts"] = arts
                send_vk_message(user_id, msg, get_numbered_keyboard(len(arts)))
                return True

    if state == "rename_art_select":
        if user_text.isdigit():
            idx = int(user_text) - 1
            arts = user_states[user_id]["arts"]
            if 0 <= idx < len(arts):
                old_art = arts[idx]
                user_states[user_id]["state"] = "rename_art_newname"
                user_states[user_id]["old_art"] = old_art
                send_vk_message(user_id, f"Введите новое название для статьи '{old_art}':", get_cancel_keyboard())
                return True

    if state == "rename_art_newname":
        new_art = user_text
        payload = {
            "action": "rename_article",
            "type": user_states[user_id]["c_type"],
            "cat": user_states[user_id]["sel_cat"],
            "sub": user_states[user_id]["sel_sub"],
            "old_art": user_states[user_id]["old_art"],
            "new_art": new_art
        }
        send_vk_message(user_id, "⏳ Переименовываю статью...")
        send_to_google_sheets(payload)
        send_vk_message(user_id, "✅ Статья успешно переименована!", get_main_keyboard())
        del user_states[user_id]
        return True

    # ====================================================================
    # 3. ВЕТКА: УДАЛИТЬ
    # ====================================================================
    if state == "delete_select_level":
        if user_text_lower in ["категорию", "подкатегорию", "статью"]:
            level_map = {"категорию": "category", "подкатегорию": "subcategory", "статью": "article"}
            user_states[user_id]["del_level"] = level_map[user_text_lower]
            user_states[user_id]["state"] = "delete_select_type"
            send_vk_message(user_id, "В Расходах или Доходах?", type_keyboard())
            return True

    if state == "delete_select_type":
        c_type = "Доход" if "доход" in user_text_lower else "Расход"
        send_vk_message(user_id, "⏳ Загружаю структуру...")
        res = send_to_google_sheets({"action": "get_full_menu"})
        if res.get("status") == "SUCCESS":
            menu = res.get("menu", {}).get(c_type, {})
            cats = list(menu.keys())
            cats.sort()
            user_states[user_id]["menu"] = menu
            user_states[user_id]["c_type"] = c_type
            user_states[user_id]["cats"] = cats
            user_states[user_id]["state"] = "delete_select_cat"
            msg = f"Выберите категорию ({c_type}):\n\n"
            for i, c in enumerate(cats):
                msg += f"{i+1}. {c}\n"
            send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
        return True

    if state == "delete_select_cat":
        if user_text.isdigit():
            idx = int(user_text) - 1
            cats = user_states[user_id]["cats"]
            if 0 <= idx < len(cats):
                sel_cat = cats[idx]
                user_states[user_id]["sel_cat"] = sel_cat
                level = user_states[user_id]["del_level"]
                if level == "category":
                    user_states[user_id]["state"] = "delete_confirm"
                    send_vk_message(user_id, f"⚠️ Вы уверены, что хотите удалить КАТЕГОРИЮ '{sel_cat}' со всеми подкатегориями и статьями?\n\n(Она удалится из вашей личной таблицы, но останется в Глобальной)", get_yes_no_keyboard())
                else:
                    subs = list(user_states[user_id]["menu"].get(sel_cat, {}).keys())
                    subs.sort()
                    user_states[user_id]["subs"] = subs
                    user_states[user_id]["state"] = "delete_select_sub"
                    msg = f"Выберите подкатегорию в '{sel_cat}':\n\n"
                    for i, s in enumerate(subs):
                        msg += f"{i+1}. {s}\n"
                    send_vk_message(user_id, msg, get_numbered_keyboard(len(subs)))
                return True

    if state == "delete_select_sub":
        if user_text.isdigit():
            idx = int(user_text) - 1
            subs = user_states[user_id]["subs"]
            if 0 <= idx < len(subs):
                sel_sub = subs[idx]
                user_states[user_id]["sel_sub"] = sel_sub
                level = user_states[user_id]["del_level"]
                if level == "subcategory":
                    user_states[user_id]["state"] = "delete_confirm"
                    send_vk_message(user_id, f"⚠️ Вы уверены, что хотите удалить ПОДКАТЕГОРИЮ '{sel_sub}' со всеми её статьями?", get_yes_no_keyboard())
                else:
                    arts = user_states[user_id]["menu"][user_states[user_id]["sel_cat"]].get(sel_sub, [])
                    arts.sort()
                    user_states[user_id]["arts"] = arts
                    user_states[user_id]["state"] = "delete_select_art"
                    msg = f"Выберите статью в '{sel_sub}':\n\n"
                    for i, a in enumerate(arts):
                        msg += f"{i+1}. {a}\n"
                    send_vk_message(user_id, msg, get_numbered_keyboard(len(arts)))
                return True

    if state == "delete_select_art":
        if user_text.isdigit():
            idx = int(user_text) - 1
            arts = user_states[user_id]["arts"]
            if 0 <= idx < len(arts):
                sel_art = arts[idx]
                user_states[user_id]["sel_art"] = sel_art
                user_states[user_id]["state"] = "delete_confirm"
                send_vk_message(user_id, f"⚠️ Вы уверены, что хотите удалить СТАТЬЮ '{sel_art}'?", get_yes_no_keyboard())
                return True

    if state == "delete_confirm":
        if user_text_lower in ["да", "верно", "ага", "yes", "+"]:
            payload = {
                "action": "delete_entity",
                "level": user_states[user_id]["del_level"],
                "type": user_states[user_id]["c_type"],
                "cat": user_states[user_id].get("sel_cat", ""),
                "sub": user_states[user_id].get("sel_sub", ""),
                "art": user_states[user_id].get("sel_art", "")
            }
            send_vk_message(user_id, "⏳ Удаляю...")
            send_to_google_sheets(payload)
            send_vk_message(user_id, "✅ Успешно удалено!", get_main_keyboard())
            del user_states[user_id]
        elif user_text_lower in ["нет", "неверно", "не", "no", "-"]:
            send_vk_message(user_id, "Удаление отменено.", get_main_keyboard())
            del user_states[user_id]
        return True

    # ====================================================================
    # 4. ВЕТКА: ПЕРЕНЕСТИ
    # ====================================================================
    if state == "move_select_level":
        if user_text_lower in ["подкатегорию", "статью"]:
            level_map = {"подкатегорию": "subcategory", "статью": "article"}
            user_states[user_id]["move_level"] = level_map[user_text_lower]
            user_states[user_id]["state"] = "move_select_type"
            send_vk_message(user_id, "В Расходах или Доходах?", type_keyboard())
            return True

    if state == "move_select_type":
        c_type = "Доход" if "доход" in user_text_lower else "Расход"
        send_vk_message(user_id, "⏳ Загружаю структуру...")
        res = send_to_google_sheets({"action": "get_full_menu"})
        if res.get("status") == "SUCCESS":
            menu = res.get("menu", {}).get(c_type, {})
            cats = list(menu.keys())
            cats.sort()
            user_states[user_id]["menu"] = menu
            user_states[user_id]["c_type"] = c_type
            user_states[user_id]["cats"] = cats
            user_states[user_id]["state"] = "move_select_cat"
            msg = f"Выберите категорию ({c_type}):\n\n"
            for i, c in enumerate(cats):
                msg += f"{i+1}. {c}\n"
            send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
        return True

    if state == "move_select_cat":
        if user_text.isdigit():
            idx = int(user_text) - 1
            cats = user_states[user_id]["cats"]
            if 0 <= idx < len(cats):
                sel_cat = cats[idx]
                user_states[user_id]["sel_cat"] = sel_cat
                subs = list(user_states[user_id]["menu"].get(sel_cat, {}).keys())
                subs.sort()
                user_states[user_id]["subs"] = subs
                user_states[user_id]["state"] = "move_select_sub"
                msg = f"Выберите подкатегорию в '{sel_cat}':\n\n"
                for i, s in enumerate(subs):
                    msg += f"{i+1}. {s}\n"
                send_vk_message(user_id, msg, get_numbered_keyboard(len(subs)))
                return True

    if state == "move_select_sub":
        if user_text.isdigit():
            idx = int(user_text) - 1
            subs = user_states[user_id]["subs"]
            if 0 <= idx < len(subs):
                sel_sub = subs[idx]
                user_states[user_id]["sel_sub"] = sel_sub
                level = user_states[user_id]["move_level"]
                if level == "subcategory":
                    user_states[user_id]["state"] = "move_target_parent"
                    cats = user_states[user_id]["cats"]
                    msg = f"В какую категорию перенести '{sel_sub}'?\n\n"
                    for i, c in enumerate(cats):
                        msg += f"{i+1}. {c}\n"
                    send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
                else:
                    arts = user_states[user_id]["menu"][user_states[user_id]["sel_cat"]].get(sel_sub, [])
                    arts.sort()
                    user_states[user_id]["arts"] = arts
                    user_states[user_id]["state"] = "move_select_art"
                    msg = f"Выберите статью в '{sel_sub}':\n\n"
                    for i, a in enumerate(arts):
                        msg += f"{i+1}. {a}\n"
                    send_vk_message(user_id, msg, get_numbered_keyboard(len(arts)))
                return True

    if state == "move_select_art":
        if user_text.isdigit():
            idx = int(user_text) - 1
            arts = user_states[user_id].get("arts", [])
            if 0 <= idx < len(arts):
                sel_art = arts[idx]
                user_states[user_id]["sel_art"] = sel_art
                user_states[user_id]["state"] = "move_target_cat"
                cats = user_states[user_id]["cats"]
                msg = f"В какую КАТЕГОРИЮ перенести статью '{sel_art}'?\n\n"
                for i, c in enumerate(cats):
                    msg += f"{i+1}. {c}\n"
                send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
                return True

    if state == "move_target_cat":
        if user_text.isdigit():
            idx = int(user_text) - 1
            cats = user_states[user_id].get("cats", [])
            if 0 <= idx < len(cats):
                new_cat = cats[idx]
                user_states[user_id]["new_cat"] = new_cat
                c_type = user_states[user_id].get("c_type", "Расход")
                full_menu = user_states[user_id].get("menu", {})
                type_menu = full_menu.get(c_type, {}) if isinstance(full_menu, dict) else {}
                subs_dict = type_menu.get(new_cat, {}) if isinstance(type_menu, dict) else {}
                
                if isinstance(subs_dict, dict):
                    new_subs = list(subs_dict.keys())
                else:
                    new_subs = []
                new_subs.sort()
                
                if not new_subs:
                    send_vk_message(user_id, f"В категории '{new_cat}' нет подкатегорий. Выберите другую.", get_main_keyboard())
                    del user_states[user_id]
                    return True
                    
                user_states[user_id]["new_subs"] = new_subs
                user_states[user_id]["state"] = "move_target_sub"
                msg = f"В какую ПОДКАТЕГОРИЮ перенести статью?\n\n"
                for i, s in enumerate(new_subs):
                    msg += f"{i+1}. {s}\n"
                send_vk_message(user_id, msg, get_numbered_keyboard(len(new_subs)))
                return True

    if state == "move_target_sub":
        if user_text.isdigit():
            idx = int(user_text) - 1
            new_subs = user_states[user_id].get("new_subs", [])
            if 0 <= idx < len(new_subs):
                new_sub = new_subs[idx]
                payload = {
                    "action": "move_entity",
                    "level": "article",
                    "type": user_states[user_id]["c_type"],
                    "cat": user_states[user_id]["sel_cat"],
                    "sub": user_states[user_id]["sel_sub"],
                    "art": user_states[user_id]["sel_art"],
                    "new_cat": user_states[user_id]["new_cat"],
                    "new_parent": new_sub
                }
                send_vk_message(user_id, "⏳ Переношу...")
                send_to_google_sheets(payload)
                send_vk_message(user_id, "✅ Успешно перенесено!", get_main_keyboard())
                del user_states[user_id]
                return True

    if state == "move_target_parent":
        if user_text.isdigit():
            level = user_states[user_id]["move_level"]
            if level == "subcategory":
                targets = user_states[user_id]["cats"]
                idx = int(user_text) - 1
                if 0 <= idx < len(targets):
                    new_parent = targets[idx]
                    payload = {
                        "action": "move_entity",
                        "level": level,
                        "type": user_states[user_id]["c_type"],
                        "cat": user_states[user_id]["sel_cat"],
                        "sub": user_states[user_id]["sel_sub"],
                        "new_parent": new_parent
                    }
                    send_vk_message(user_id, "⏳ Переношу...")
                    send_to_google_sheets(payload)
                    send_vk_message(user_id, "✅ Успешно перенесено!", get_main_keyboard())
                    del user_states[user_id]
                    return True

    # Если ни один if не сработал (например, ввели текст вместо цифры), возвращаем False, 
    # чтобы сработала защита от дурака в main.py
    return False
