# -*- coding: utf-8 -*-
from keyboards import (
    type_keyboard,
    get_cancel_keyboard,
    get_numbered_keyboard,
    get_main_keyboard,
    get_yes_no_keyboard
)
from services import send_vk_message
from db import (
    get_full_menu,
    db_rename_category,
    db_rename_subcategory,
    db_rename_article,
    db_delete_entity,
    db_move_entity
)

def handle_structure_manage(user_id, internal_uid, user_text, user_text_lower, state, user_states):
    """Сценарии переименования, удаления и перемещения сущностей."""
    
    # =========================================================
    # 1. ПЕРЕИМЕНОВАНИЕ
    # =========================================================
    if state == "rename_cat_select":
        if user_text.isdigit():
            idx = int(user_text) - 1
            cats = user_states[user_id]["cats"]
            if 0 <= idx < len(cats):
                old_cat = cats[idx]
                user_states[user_id]["state"] = "rename_cat_type"
                user_states[user_id]["old_cat"] = old_cat
                send_vk_message(user_id, f"Введите новое название для категории '{old_cat}':", get_cancel_keyboard(show_back=True))
                return True

    if state == "rename_cat_type":
        new_cat = user_text
        old_cat = user_states[user_id]["old_cat"]
        db_rename_category(internal_uid, None, old_cat, new_cat)
        send_vk_message(user_id, "✅ Категория успешно переименована!", get_main_keyboard(user_id))
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
                subs = sorted(list(set(subs_exp + subs_inc)))
                if not subs:
                    send_vk_message(user_id, f"В категории '{sel_cat}' нет подкатегорий.", get_main_keyboard(user_id))
                    del user_states[user_id]
                    return True
                msg = f"Какую подкатегорию в '{sel_cat}' переименовать?\n\n"
                for i, s in enumerate(subs):
                    msg += f"{i+1}. {s}\n"
                user_states[user_id]["state"] = "rename_sub_select_sub"
                user_states[user_id]["sel_cat"] = sel_cat
                user_states[user_id]["subs"] = subs
                send_vk_message(user_id, msg, get_numbered_keyboard(len(subs), show_back=True))
                return True

    if state == "rename_sub_select_sub":
        if user_text.isdigit():
            idx = int(user_text) - 1
            subs = user_states[user_id]["subs"]
            if 0 <= idx < len(subs):
                old_sub = subs[idx]
                user_states[user_id]["state"] = "rename_sub_type"
                user_states[user_id]["old_sub"] = old_sub
                send_vk_message(user_id, f"Введите новое название для '{old_sub}':", get_cancel_keyboard(show_back=True))
                return True

    if state == "rename_sub_type":
        new_sub = user_text
        sel_cat = user_states[user_id]["sel_cat"]
        old_sub = user_states[user_id]["old_sub"]
        db_rename_subcategory(internal_uid, None, sel_cat, old_sub, new_sub)
        send_vk_message(user_id, "✅ Подкатегория успешно переименована!", get_main_keyboard(user_id))
        del user_states[user_id]
        return True

    if state == "rename_art_type":
        c_type = "Доход" if "доход" in user_text_lower else "Расход"
        user_states[user_id]["c_type"] = c_type
        menu = user_states[user_id]["menu"].get(c_type, {})
        cats = sorted(list(menu.keys()))
        msg = f"Выберите категорию ({c_type}):\n\n"
        for i, c in enumerate(cats):
            msg += f"{i+1}. {c}\n"
        user_states[user_id]["state"] = "rename_art_cat"
        user_states[user_id]["cats"] = cats
        send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))
        return True

    if state == "rename_art_cat":
        if user_text.isdigit():
            idx = int(user_text) - 1
            cats = user_states[user_id]["cats"]
            if 0 <= idx < len(cats):
                sel_cat = cats[idx]
                c_type = user_states[user_id]["c_type"]
                subs_dict = user_states[user_id]["menu"][c_type].get(sel_cat, {})
                subs = sorted(list(subs_dict.keys())) if isinstance(subs_dict, dict) else sorted(subs_dict)
                msg = f"Выберите подкатегорию в '{sel_cat}':\n\n"
                for i, s in enumerate(subs):
                    msg += f"{i+1}. {s}\n"
                user_states[user_id]["state"] = "rename_art_sub"
                user_states[user_id]["sel_cat"] = sel_cat
                user_states[user_id]["subs"] = subs
                send_vk_message(user_id, msg, get_numbered_keyboard(len(subs), show_back=True))
                return True

    if state == "rename_art_sub":
        if user_text.isdigit():
            idx = int(user_text) - 1
            subs = user_states[user_id]["subs"]
            if 0 <= idx < len(subs):
                sel_sub = subs[idx]
                c_type = user_states[user_id]["c_type"]
                sel_cat = user_states[user_id]["sel_cat"]
                arts = sorted(user_states[user_id]["menu"][c_type][sel_cat].get(sel_sub, []))
                if not arts:
                    send_vk_message(user_id, "В этой подкатегории нет статей.", get_main_keyboard(user_id))
                    del user_states[user_id]
                    return True
                msg = f"Какую статью переименовать?\n\n"
                for i, a in enumerate(arts):
                    msg += f"{i+1}. {a}\n"
                user_states[user_id]["state"] = "rename_art_select"
                user_states[user_id]["sel_sub"] = sel_sub
                user_states[user_id]["arts"] = arts
                send_vk_message(user_id, msg, get_numbered_keyboard(len(arts), show_back=True))
                return True

    if state == "rename_art_select":
        if user_text.isdigit():
            idx = int(user_text) - 1
            arts = user_states[user_id]["arts"]
            if 0 <= idx < len(arts):
                old_art = arts[idx]
                user_states[user_id]["state"] = "rename_art_newname"
                user_states[user_id]["old_art"] = old_art
                send_vk_message(user_id, f"Введите новое название для статьи '{old_art}':", get_cancel_keyboard(show_back=True))
                return True

    if state == "rename_art_newname":
        new_art = user_text
        db_rename_article(
            internal_uid,
            user_states[user_id]["c_type"],
            user_states[user_id]["sel_cat"],
            user_states[user_id]["sel_sub"],
            user_states[user_id]["old_art"],
            new_art
        )
        send_vk_message(user_id, "✅ Статья успешно переименована!", get_main_keyboard(user_id))
        del user_states[user_id]
        return True

    # =========================================================
    # 2. УДАЛЕНИЕ
    # =========================================================
    if state == "delete_select_level":
        if "категорию" in user_text_lower:
            user_states[user_id]["del_level"] = "category"
        elif "подкатегорию" in user_text_lower:
            user_states[user_id]["del_level"] = "subcategory"
        elif "статью" in user_text_lower:
            user_states[user_id]["del_level"] = "article"
        else:
            return True
        user_states[user_id]["state"] = "delete_select_type"
        send_vk_message(user_id, "В Расходах или Доходах?", type_keyboard(show_back=True))
        return True

    if state == "delete_select_type":
        c_type = "Доход" if "доход" in user_text_lower else "Расход"
        menu = get_full_menu(internal_uid).get(c_type, {})
        cats = sorted(list(menu.keys()))
        user_states[user_id]["menu"] = menu
        user_states[user_id]["c_type"] = c_type
        user_states[user_id]["cats"] = cats
        user_states[user_id]["state"] = "delete_select_cat"
        msg = f"Выберите категорию ({c_type}):\n\n"
        for i, c in enumerate(cats):
            msg += f"{i+1}. {c}\n"
        send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))
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
                    send_vk_message(user_id, f"⚠️ Вы уверены, что хотите удалить КАТЕГОРИЮ '{sel_cat}' со всеми подкатегориями и статьями?", get_yes_no_keyboard(show_back=True))
                else:
                    subs_dict = user_states[user_id]["menu"].get(sel_cat, {})
                    subs = sorted(list(subs_dict.keys())) if isinstance(subs_dict, dict) else sorted(subs_dict)
                    user_states[user_id]["subs"] = subs
                    user_states[user_id]["state"] = "delete_select_sub"
                    msg = f"Выберите подкатегорию в '{sel_cat}':\n\n"
                    for i, s in enumerate(subs):
                        msg += f"{i+1}. {s}\n"
                    send_vk_message(user_id, msg, get_numbered_keyboard(len(subs), show_back=True))
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
                    send_vk_message(user_id, f"⚠️ Вы уверены, что хотите удалить ПОДКАТЕГОРИЮ '{sel_sub}' со всеми её статьями?", get_yes_no_keyboard(show_back=True))
                else:
                    arts = sorted(user_states[user_id]["menu"][user_states[user_id]["sel_cat"]].get(sel_sub, []))
                    user_states[user_id]["arts"] = arts
                    user_states[user_id]["state"] = "delete_select_art"
                    msg = f"Выберите статью в '{sel_sub}':\n\n"
                    for i, a in enumerate(arts):
                        msg += f"{i+1}. {a}\n"
                    send_vk_message(user_id, msg, get_numbered_keyboard(len(arts), show_back=True))
                return True

    if state == "delete_select_art":
        if user_text.isdigit():
            idx = int(user_text) - 1
            arts = user_states[user_id]["arts"]
            if 0 <= idx < len(arts):
                sel_art = arts[idx]
                user_states[user_id]["sel_art"] = sel_art
                user_states[user_id]["state"] = "delete_confirm"
                send_vk_message(user_id, f"⚠️ Вы уверены, что хотите удалить СТАТЬЮ '{sel_art}'?", get_yes_no_keyboard(show_back=True))
                return True

    if state == "delete_confirm":
        if any(w in user_text_lower for w in ["да", "верно", "ага", "yes", "+"]):
            db_delete_entity(
                internal_uid,
                user_states[user_id]["del_level"],
                user_states[user_id]["c_type"],
                user_states[user_id].get("sel_cat", ""),
                user_states[user_id].get("sel_sub", ""),
                user_states[user_id].get("sel_art", "")
            )
            send_vk_message(user_id, "✅ Успешно удалено!", get_main_keyboard(user_id))
            del user_states[user_id]
        elif any(w in user_text_lower for w in ["нет", "неверно", "не", "no", "-"]):
            send_vk_message(user_id, "Удаление отменено.", get_main_keyboard(user_id))
            del user_states[user_id]
        return True

    # =========================================================
    # 3. ПЕРЕНОС
    # =========================================================
    if state == "move_select_level":
        if "подкатегорию" in user_text_lower:
            user_states[user_id]["move_level"] = "subcategory"
        elif "статью" in user_text_lower:
            user_states[user_id]["move_level"] = "article"
        else:
            return True
        user_states[user_id]["state"] = "move_select_type"
        send_vk_message(user_id, "В Расходах или Доходах?", type_keyboard(show_back=True))
        return True

    if state == "move_select_type":
        c_type = "Доход" if "доход" in user_text_lower else "Расход"
        menu = get_full_menu(internal_uid).get(c_type, {})
        cats = sorted(list(menu.keys()))
        user_states[user_id]["menu"] = menu
        user_states[user_id]["c_type"] = c_type
        user_states[user_id]["cats"] = cats
        user_states[user_id]["state"] = "move_select_cat"
        msg = f"Выберите категорию ({c_type}):\n\n"
        for i, c in enumerate(cats):
            msg += f"{i+1}. {c}\n"
        send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))
        return True

    if state == "move_select_cat":
        if user_text.isdigit():
            idx = int(user_text) - 1
            cats = user_states[user_id]["cats"]
            if 0 <= idx < len(cats):
                sel_cat = cats[idx]
                user_states[user_id]["sel_cat"] = sel_cat
                subs_dict = user_states[user_id]["menu"].get(sel_cat, {})
                subs = sorted(list(subs_dict.keys())) if isinstance(subs_dict, dict) else sorted(subs_dict)
                user_states[user_id]["subs"] = subs
                user_states[user_id]["state"] = "move_select_sub"
                msg = f"Выберите подкатегорию в '{sel_cat}':\n\n"
                for i, s in enumerate(subs):
                    msg += f"{i+1}. {s}\n"
                send_vk_message(user_id, msg, get_numbered_keyboard(len(subs), show_back=True))
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
                    send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))
                else:
                    arts = sorted(user_states[user_id]["menu"][user_states[user_id]["sel_cat"]].get(sel_sub, []))
                    user_states[user_id]["arts"] = arts
                    user_states[user_id]["state"] = "move_select_art"
                    msg = f"Выберите статью в '{sel_sub}':\n\n"
                    for i, a in enumerate(arts):
                        msg += f"{i+1}. {a}\n"
                    send_vk_message(user_id, msg, get_numbered_keyboard(len(arts), show_back=True))
                return True

    if state == "move_select_art":
        if user_text.isdigit():
            idx = int(user_text) - 1
            arts = user_states[user_id]["arts"]
            if 0 <= idx < len(arts):
                sel_art = arts[idx]
                user_states[user_id]["sel_art"] = sel_art
                user_states[user_id]["state"] = "move_target_cat"
                cats = user_states[user_id]["cats"]
                msg = f"В какую КАТЕГОРИЮ перенести статью '{sel_art}'?\n\n"
                for i, c in enumerate(cats):
                    msg += f"{i+1}. {c}\n"
                send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))
                return True

    if state == "move_target_cat":
        if user_text.isdigit():
            idx = int(user_text) - 1
            cats = user_states[user_id]["cats"]
            if 0 <= idx < len(cats):
                new_cat = cats[idx]
                user_states[user_id]["new_cat"] = new_cat
                c_type = user_states[user_id].get("c_type", "Расход")
                full_menu = get_full_menu(internal_uid)
                subs_dict = full_menu.get(c_type, {}).get(new_cat, {})
                new_subs = sorted(list(subs_dict.keys())) if isinstance(subs_dict, dict) else sorted(subs_dict)
                if not new_subs:
                    send_vk_message(user_id, f"В категории '{new_cat}' нет подкатегорий. Выберите другую.", get_main_keyboard(user_id))
                    del user_states[user_id]
                    return True
                user_states[user_id]["new_subs"] = new_subs
                user_states[user_id]["state"] = "move_target_sub"
                msg = f"В какую ПОДКАТЕГОРИЮ перенести статью?\n\n"
                for i, s in enumerate(new_subs):
                    msg += f"{i+1}. {s}\n"
                send_vk_message(user_id, msg, get_numbered_keyboard(len(new_subs), show_back=True))
                return True

    if state == "move_target_sub":
        if user_text.isdigit():
            idx = int(user_text) - 1
            new_subs = user_states[user_id].get("new_subs", [])
            if 0 <= idx < len(new_subs):
                new_sub = new_subs[idx]
                db_move_entity(
                    internal_uid,
                    "article",
                    user_states[user_id]["c_type"],
                    user_states[user_id]["sel_cat"],
                    user_states[user_id]["sel_sub"],
                    user_states[user_id]["sel_art"],
                    new_sub,
                    user_states[user_id]["new_cat"]
                )
                send_vk_message(user_id, "✅ Успешно перенесено!", get_main_keyboard(user_id))
                del user_states[user_id]
                return True

    if state == "move_target_parent":
        if user_text.isdigit():
            targets = user_states[user_id]["cats"]
            idx = int(user_text) - 1
            if 0 <= idx < len(targets):
                new_parent = targets[idx]
                db_move_entity(
                    internal_uid,
                    "subcategory",
                    user_states[user_id]["c_type"],
                    user_states[user_id]["sel_cat"],
                    user_states[user_id]["sel_sub"],
                    "",
                    new_parent
                )
                send_vk_message(user_id, "✅ Успешно перенесено!", get_main_keyboard(user_id))
                del user_states[user_id]
                return True

    return False
