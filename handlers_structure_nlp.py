# -*- coding: utf-8 -*-
from keyboards import (
    type_keyboard,
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
import difflib

def find_entity_in_menu(menu, target_name):
    """Поиск сущности любого уровня (категория, подкатегория, статья) по названию."""
    target = target_name.lower().strip()
    all_entities = []
    for c_type in ["Расход", "Доход"]:
        type_menu = menu.get(c_type, {})
        for cat, subs in type_menu.items():
            all_entities.append({"level": "category", "type": c_type, "cat": cat, "sub": "", "art": "", "name": cat.lower().strip()})
            subs_items = subs.items() if isinstance(subs, dict) else [(s, []) for s in subs]
            for sub, arts in subs_items:
                all_entities.append({"level": "subcategory", "type": c_type, "cat": cat, "sub": sub, "art": "", "name": sub.lower().strip()})
                for art in arts:
                    all_entities.append({"level": "article", "type": c_type, "cat": cat, "sub": sub, "art": art, "name": art.lower().strip()})
    
    results = [ent for ent in all_entities if ent["name"] == target]
    if not results:
        names = [ent["name"] for ent in all_entities]
        matches = difflib.get_close_matches(target, names, n=1, cutoff=0.7)
        if matches:
            best_match = matches[0]
            results = [ent for ent in all_entities if ent["name"] == best_match]
    return results

def handle_structure_nlp_action(user_id, internal_uid, parsed_data, user_states):
    """Обрабатывает action: smart_rename, smart_delete, smart_move, start_interactive, edit_tx."""
    action = parsed_data.get("action")
    if not action:
        return False

    menu = get_full_menu(internal_uid)

    # 1. ЗАПУСК ИНТЕРАКТИВНОГО СОЗДАНИЯ (Создай статью/подкатегорию/категорию)
    if action == "start_interactive":
        op = parsed_data.get("operation")
        item = parsed_data.get("item", "").strip()
        if op == "create_article":
            user_states[user_id] = {"state": "create_art_type", "pending_name": item}
            send_vk_message(user_id, f"Создаем статью {f'«{item}»' if item else ''}.\nЭто статья Расходов или Доходов?", type_keyboard(show_back=True))
            return True
        elif op == "create_subcategory":
            user_states[user_id] = {"state": "create_sub_type", "pending_name": item}
            send_vk_message(user_id, f"Создаем подкатегорию {f'«{item}»' if item else ''}.\nЭто подкатегория Расходов или Доходов?", type_keyboard(show_back=True))
            return True
        elif op == "create_category":
            user_states[user_id] = {"state": "create_cat_type", "pending_name": item}
            send_vk_message(user_id, f"Создаем категорию {f'«{item}»' if item else ''}.\nЭто категория Расходов или Доходов?", type_keyboard(show_back=True))
            return True

    # 2. УМНОЕ ПЕРЕИМЕНОВАНИЕ / УДАЛЕНИЕ / ПЕРЕНОС
    if action in ["smart_rename", "smart_delete", "smart_move"]:
        target_name = parsed_data.get("old_name") if action == "smart_rename" else parsed_data.get("item", "")
        send_vk_message(user_id, f"⏳ Ищу '{target_name}' в структуре...")
        results = find_entity_in_menu(menu, target_name)
        if not results:
            send_vk_message(user_id, f"❌ Не нашел '{target_name}' в базе. Попробуйте через кнопки меню.", get_main_keyboard(user_id))
            return True
        elif len(results) > 1:
            send_vk_message(user_id, f"⚠️ Найдено несколько совпадений для '{target_name}'. Воспользуйтесь кнопками меню для выбора.", get_main_keyboard(user_id))
            return True

        r = results[0]
        found_name = r["cat"] if r["level"] == "category" else (r["sub"] if r["level"] == "subcategory" else r["art"])

        if action == "smart_rename":
            new_name = parsed_data.get("new_name", "")
            if r["level"] == "category":
                db_rename_category(internal_uid, r["type"], r["cat"], new_name)
            elif r["level"] == "subcategory":
                db_rename_subcategory(internal_uid, r["type"], r["cat"], r["sub"], new_name)
            else:
                db_rename_article(internal_uid, r["type"], r["cat"], r["sub"], r["art"], new_name)
            send_vk_message(user_id, f"✅ Успешно переименовано в '{new_name}'!", get_main_keyboard(user_id))
            return True

        elif action == "smart_delete":
            level_ru = {"category": "КАТЕГОРИЮ", "subcategory": "ПОДКАТЕГОРИЮ", "article": "СТАТЬЮ"}[r["level"]]
            user_states[user_id] = {
                "state": "delete_confirm",
                "del_level": r["level"],
                "c_type": r["type"],
                "sel_cat": r["cat"],
                "sel_sub": r["sub"],
                "sel_art": r["art"]
            }
            send_vk_message(user_id, f"⚠️ Вы уверены, что хотите удалить {level_ru} '{found_name}'?", get_yes_no_keyboard(show_back=True))
            return True

        elif action == "smart_move":
            if r["level"] == "category":
                send_vk_message(user_id, "❌ Категорию нельзя перенести. Только подкатегорию или статью.", get_main_keyboard(user_id))
                return True
            cats = sorted(list(menu.get(r["type"], {}).keys()))
            if r["level"] == "article":
                user_states[user_id] = {
                    "state": "move_target_cat",
                    "move_level": "article",
                    "c_type": r["type"],
                    "sel_cat": r["cat"],
                    "sel_sub": r["sub"],
                    "sel_art": r["art"],
                    "cats": cats
                }
                msg = f"В какую КАТЕГОРИЮ перенести статью '{found_name}'?\n\n"
                for i, c in enumerate(cats):
                    msg += f"{i+1}. {c}\n"
                send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))
            elif r["level"] == "subcategory":
                user_states[user_id] = {
                    "state": "move_target_parent",
                    "move_level": "subcategory",
                    "c_type": r["type"],
                    "sel_cat": r["cat"],
                    "sel_sub": r["sub"],
                    "cats": cats
                }
                msg = f"В какую КАТЕГОРИЮ перенести подкатегорию '{found_name}'?\n\n"
                for i, c in enumerate(cats):
                    msg += f"{i+1}. {c}\n"
                send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))
            return True

    return False
