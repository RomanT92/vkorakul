# -*- coding: utf-8 -*-
from keyboards import (
    type_keyboard,
    get_cancel_keyboard,
    get_numbered_keyboard,
    get_main_keyboard,
    get_entity_keyboard,
    get_move_entity_keyboard,
    get_del_move_keyboard
)
from services import send_vk_message
from db import get_or_create_user, get_full_menu

from handlers_structure_create import handle_structure_create
from handlers_structure_manage import handle_structure_manage
from handlers_structure_nlp import handle_structure_nlp_disambiguate

def handle_structure(user_id, user_text, user_text_lower, state, user_states):
    """Единый диспетчер меню 'Категории и статьи' и логика «Назад»."""
    internal_uid = get_or_create_user(user_id)

    # 0. ОБРАБОТКА РАЗРЕШЕНИЯ НЕОДНОЗНАЧНОСТИ NLP
    if state == "structure_nlp_disambiguate":
        if handle_structure_nlp_disambiguate(user_id, internal_uid, user_text, user_text_lower, state, user_states):
            return True

    # 1. ОБРАБОТКА НАВИГАЦИИ «НАЗАД» ДЛЯ ВСЕХ ПОДШАГОВ
    if "назад" in user_text_lower:
        # Назад при создании
        if state in ["create_cat_type", "create_sub_type", "create_art_type"]:
            user_states[user_id]["state"] = "wait_entity_create"
            send_vk_message(user_id, "Что именно вы хотите создать?", get_entity_keyboard())
            return True
        elif state == "create_cat_name":
            user_states[user_id]["state"] = "create_cat_type"
            send_vk_message(user_id, "Это будет категория Расходов или Доходов?", type_keyboard(show_back=True))
            return True
        elif state == "create_cat_subname":
            user_states[user_id]["state"] = "create_cat_name"
            send_vk_message(user_id, "Введите название категории заново:", get_cancel_keyboard(show_back=True))
            return True
        elif state == "create_sub_catselect":
            user_states[user_id]["state"] = "create_sub_type"
            send_vk_message(user_id, "Это будет подкатегория Расходов или Доходов?", type_keyboard(show_back=True))
            return True
        elif state == "create_sub_name":
            c_type = user_states[user_id].get("c_type", "Расход")
            cats = user_states[user_id].get("cats", [])
            user_states[user_id]["state"] = "create_sub_catselect"
            msg = f"Выберите категорию ({c_type}), в которую добавим подкатегорию:\n\n"
            for i, c in enumerate(cats):
                msg += f"{i+1}. {c}\n"
            send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))
            return True
        elif state == "create_art_catselect":
            user_states[user_id]["state"] = "create_art_type"
            send_vk_message(user_id, "Это будет статья Расходов или Доходов?", type_keyboard(show_back=True))
            return True
        elif state == "create_art_subselect":
            c_type = user_states[user_id].get("c_type", "Расход")
            cats = user_states[user_id].get("cats", [])
            user_states[user_id]["state"] = "create_art_catselect"
            msg = f"Выберите категорию ({c_type}):\n\n"
            for i, c in enumerate(cats):
                msg += f"{i+1}. {c}\n"
            send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))
            return True
        elif state == "create_art_name":
            user_states[user_id]["state"] = "create_art_subselect"
            subs = user_states[user_id].get("subs", [])
            sel_cat = user_states[user_id].get("sel_cat", "")
            msg = f"Выберите подкатегорию в '{sel_cat}':\n\n"
            for i, s in enumerate(subs):
                msg += f"{i+1}. {s}\n"
            send_vk_message(user_id, msg, get_numbered_keyboard(len(subs), show_back=True))
            return True

        # Назад при переименовании, удалении, переносе
        elif state in ["rename_cat_select", "rename_sub_select_cat", "rename_art_type"]:
            user_states[user_id]["state"] = "wait_entity_rename"
            send_vk_message(user_id, "Что именно вы хотите переименовать?", get_entity_keyboard())
            return True
        elif state in ["delete_select_level", "move_select_level"]:
            user_states[user_id]["state"] = "wait_del_move_action"
            send_vk_message(user_id, "Что вы хотите сделать?", get_del_move_keyboard())
            return True
        elif state in ["delete_select_type", "move_select_type"]:
            user_states[user_id]["state"] = "delete_select_level" if "delete" in state else "move_select_level"
            send_vk_message(user_id, "Что именно выбрать?", get_entity_keyboard())
            return True

    # 2. МАРШРУТИЗАЦИЯ НАЧАЛА CRUD-ДЕЙСТВИЙ
    if state == "wait_entity_create":
        if "категорию" in user_text_lower:
            user_states[user_id] = {"state": "create_cat_type"}
            send_vk_message(user_id, "Это будет категория Расходов или Доходов?", type_keyboard(show_back=True))
            return True
        elif "подкатегорию" in user_text_lower:
            user_states[user_id] = {"state": "create_sub_type"}
            send_vk_message(user_id, "Это будет подкатегория Расходов или Доходов?", type_keyboard(show_back=True))
            return True
        elif "статью" in user_text_lower:
            user_states[user_id] = {"state": "create_art_type"}
            send_vk_message(user_id, "Это будет статья Расходов или Доходов?", type_keyboard(show_back=True))
            return True

    if state == "wait_entity_rename":
        menu = get_full_menu(internal_uid)
        cats = sorted(list(set(list(menu.get("Расход", {}).keys()) + list(menu.get("Доход", {}).keys()))))
        if not cats:
            send_vk_message(user_id, "Категорий пока нет.", get_main_keyboard(user_id))
            return True

        if "категорию" in user_text_lower:
            msg = "Какую категорию переименовать?\n\n"
            for i, c in enumerate(cats):
                msg += f"{i+1}. {c}\n"
            user_states[user_id] = {"state": "rename_cat_select", "cats": cats, "menu": menu}
            send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))
            return True
        elif "подкатегорию" in user_text_lower:
            msg = "В какой категории находится подкатегория?\n\n"
            for i, c in enumerate(cats):
                msg += f"{i+1}. {c}\n"
            user_states[user_id] = {"state": "rename_sub_select_cat", "cats": cats, "menu": menu}
            send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))
            return True
        elif "статью" in user_text_lower:
            user_states[user_id] = {"state": "rename_art_type", "menu": menu}
            send_vk_message(user_id, "Статья находится в Расходах или Доходах?", type_keyboard(show_back=True))
            return True

    if state == "wait_del_move_action":
        if "удалить" in user_text_lower:
            user_states[user_id]["state"] = "delete_select_level"
            send_vk_message(user_id, "Что именно удалить?", get_entity_keyboard())
            return True
        elif "перенести" in user_text_lower:
            user_states[user_id]["state"] = "move_select_level"
            send_vk_message(user_id, "Что именно перенести?", get_move_entity_keyboard())
            return True

    # 3. ДЕЛЕГИРОВАНИЕ В ПОДМОДУЛИ
    if handle_structure_create(user_id, internal_uid, user_text, user_text_lower, state, user_states):
        return True

    if handle_structure_manage(user_id, internal_uid, user_text, user_text_lower, state, user_states):
        return True

    return False
