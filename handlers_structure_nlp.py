# -*- coding: utf-8 -*-
import re
import difflib
from keyboards import (
    type_keyboard,
    get_numbered_keyboard,
    get_main_keyboard,
    get_yes_no_keyboard,
    get_smart_move_confirm_keyboard
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
        matches = difflib.get_close_matches(target, names, n=3, cutoff=0.65)
        if matches:
            results = [ent for ent in all_entities if ent["name"] in matches]
    return results

def start_manual_move_flow(user_id, internal_uid, r, menu, user_states):
    """Запускает пошаговый ручной выбор целевой категории/подкатегории через клавиатуры."""
    cats = sorted(list(menu.get(r["type"], {}).keys()))
    found_name = r["art"] if r["level"] == "article" else r["sub"]
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
        msg = f"🖐 Перенос вручную:\nВ какую КАТЕГОРИЮ перенести статью '{found_name}'?\n\n"
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
        msg = f"🖐 Перенос вручную:\nВ какую КАТЕГОРИЮ перенести подкатегорию '{found_name}'?\n\n"
        for i, c in enumerate(cats):
            msg += f"{i+1}. {c}\n"
        send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))
    return True

def _resolve_target_location(menu, op_type, to_cat_hint, to_sub_hint):
    """Определяет целевую категорию и подкатегорию по подсказкам пользователя."""
    type_menu = menu.get(op_type, {})
    all_cats = list(type_menu.keys())

    dest_cat = None
    dest_sub = None

    # 1. Поиск точной или нечеткой категории
    if to_cat_hint:
        c_hint = to_cat_hint.lower().strip()
        matched = next((c for c in all_cats if c.lower() == c_hint), None)
        if not matched:
            c_matches = difflib.get_close_matches(c_hint, [c.lower() for c in all_cats], n=1, cutoff=0.7)
            if c_matches:
                matched = next((c for c in all_cats if c.lower() == c_matches[0]), None)
        dest_cat = matched

    # 2. Поиск подкатегории
    if to_sub_hint:
        s_hint = to_sub_hint.lower().strip()
        search_cats = [dest_cat] if dest_cat else all_cats
        for cat in search_cats:
            raw_subs = type_menu.get(cat, {})
            sub_list = list(raw_subs.keys()) if isinstance(raw_subs, dict) else raw_subs
            matched_s = next((s for s in sub_list if s.lower() == s_hint), None)
            if not matched_s:
                s_matches = difflib.get_close_matches(s_hint, [s.lower() for s in sub_list], n=1, cutoff=0.7)
                if s_matches:
                    matched_s = next((s for s in sub_list if s.lower() == s_matches[0]), None)
            if matched_s:
                dest_sub = matched_s
                if not dest_cat:
                    dest_cat = cat
                break

    return dest_cat, dest_sub

def _execute_entity_action(user_id, internal_uid, action, r, parsed_data, user_states, menu=None):
    """Применяет подтверждённое действие smart_rename, smart_delete или smart_move к сущности r."""
    if menu is None:
        menu = get_full_menu(internal_uid)

    found_name = r["cat"] if r["level"] == "category" else (r["sub"] if r["level"] == "subcategory" else r["art"])

    if action == "smart_rename":
        new_name = parsed_data.get("new_name", "")
        if not new_name:
            send_vk_message(user_id, "⚠️ Не указано новое название для переименования.", get_main_keyboard(user_id))
            return True
        if r["level"] == "category":
            db_rename_category(internal_uid, r["type"], r["cat"], new_name)
        elif r["level"] == "subcategory":
            db_rename_subcategory(internal_uid, r["type"], r["cat"], r["sub"], new_name)
        else:
            db_rename_article(internal_uid, r["type"], r["cat"], r["sub"], r["art"], new_name)
        send_vk_message(user_id, f"✅ Успешно переименовано в '{new_name}'!", get_main_keyboard(user_id))
        return True

    elif action == "smart_delete":
        level_ru = {"category": "КАТЕГОРИЮ", "subcategory": "ПОДКАТЕГОРИЮ", "article": "СТАТЬЮ"}.get(r["level"], "СУЩНОСТЬ")
        user_states[user_id] = {
            "state": "delete_confirm",
            "del_level": r["level"],
            "c_type": r["type"],
            "sel_cat": r["cat"],
            "sel_sub": r["sub"],
            "sel_art": r["art"]
        }
        send_vk_message(user_id, f"⚠️ Вы уверены, что хотите удалить {level_ru} '{found_name}' ({r['type']})?", get_yes_no_keyboard(show_back=True))
        return True

    elif action == "smart_move":
        if r["level"] == "category":
            send_vk_message(user_id, "❌ Категорию нельзя перенести. Только подкатегорию или статью.", get_main_keyboard(user_id))
            return True

        to_cat_hint = parsed_data.get("to_cat")
        to_sub_hint = parsed_data.get("to_sub")

        dest_cat, dest_sub = _resolve_target_location(menu, r["type"], to_cat_hint, to_sub_hint)

        # Если цель успешно определена — переходим к экрану подтверждения
        if (r["level"] == "article" and dest_cat and dest_sub) or (r["level"] == "subcategory" and dest_cat):
            target_desc = f"{dest_cat} -> {dest_sub}" if r["level"] == "article" else dest_cat
            source_desc = f"{r['cat']} -> {r['sub']}" if r["level"] == "article" else r["cat"]
            level_ru = "статью" if r["level"] == "article" else "подкатегорию"

            user_states[user_id] = {
                "state": "smart_move_confirm",
                "entity": r,
                "dest_cat": dest_cat,
                "dest_sub": dest_sub or "",
                "menu": menu,
                "attempts": 1
            }
            msg = (
                f"🔀 Перенести {level_ru} «{found_name}»?\n\n"
                f"📤 Откуда: {source_desc}\n"
                f"📥 Куда: {target_desc}\n\n"
                f"Всё верно?"
            )
            send_vk_message(user_id, msg, get_smart_move_confirm_keyboard(show_back=True))
            return True

        # Если цель сразу не распознана — запускаем ручной выбор
        return start_manual_move_flow(user_id, internal_uid, r, menu, user_states)

    return False

def handle_structure_nlp_disambiguate(user_id, internal_uid, user_text, user_text_lower, state, user_states):
    """Обрабатывает состояния подтверждения переноса smart_move_confirm и устранения неоднозначности."""

    # 1. СЦЕНАРИЙ УМНОГО ПОДТВЕРЖДЕНИЯ ПЕРЕНОСА (smart_move_confirm)
    if state == "smart_move_confirm":
        state_data = user_states[user_id]
        r = state_data["entity"]
        dest_cat = state_data["dest_cat"]
        dest_sub = state_data["dest_sub"]
        menu = state_data["menu"]

        # Прямой переход к ручному переносу по кнопке
        if "перенести вручную" in user_text_lower or "вручную" in user_text_lower:
            return start_manual_move_flow(user_id, internal_uid, r, menu, user_states)

        # Подтверждение "Да"
        if any(w in user_text_lower for w in ["да", "верно", "ага", "давай", "ок", "yes", "+", "правильно", "перенести"]):
            db_move_entity(
                internal_uid,
                r["level"],
                r["type"],
                r["cat"],
                r["sub"],
                r["art"],
                dest_sub,
                dest_cat
            )
            target_str = f"{dest_cat} -> {dest_sub}" if r["level"] == "article" else dest_cat
            send_vk_message(user_id, f"✅ Успешно перенесено в '{target_str}'!", get_main_keyboard(user_id))
            del user_states[user_id]
            return True

        # Отказ или уточнение (Вторая попытка)
        attempts = state_data.get("attempts", 1)
        if attempts < 2:
            state_data["attempts"] = 2
            # Пробуем распознать новый целевой адрес из реплики пользователя
            new_cat, new_sub = _resolve_target_location(menu, r["type"], user_text, user_text)
            if (r["level"] == "article" and new_cat and new_sub) or (r["level"] == "subcategory" and new_cat):
                state_data["dest_cat"] = new_cat
                state_data["dest_sub"] = new_sub or ""
                target_desc = f"{new_cat} -> {new_sub}" if r["level"] == "article" else new_cat
                msg = f"Понял! Перенести в «{target_desc}»?\nВсё верно?"
                send_vk_message(user_id, msg, get_smart_move_confirm_keyboard(show_back=True))
                return True
            else:
                send_vk_message(
                    user_id,
                    f"Не совсем понял целевую папку 🤔 (Попытка 2 из 2).\n"
                    f"Назови категорию и подкатегорию, куда перенести (или нажми «🖐 Перенести вручную»):",
                    get_smart_move_confirm_keyboard(show_back=True)
                )
                return True
        else:
            # После неудачной второй попытки — автоматический переход к ручному выбору
            send_vk_message(user_id, "Переключаемся на выбор кнопками:")
            return start_manual_move_flow(user_id, internal_uid, r, menu, user_states)

    # 2. РАЗРЕШЕНИЕ НЕОДНОЗНАЧНОСТИ ИМЕНИ
    if state != "structure_nlp_disambiguate":
        return False

    if any(w in user_text_lower for w in ["отмена", "назад"]):
        del user_states[user_id]
        send_vk_message(user_id, "Действие отменено.", get_main_keyboard(user_id))
        return True

    state_data = user_states[user_id]
    results = state_data.get("results", [])
    action = state_data.get("action")
    parsed_data = state_data.get("parsed_data", {})

    selected = None
    from voice_parser import _parse_token_to_number
    num = None
    for token in user_text_lower.split():
        n = _parse_token_to_number(token)
        if n is not None:
            num = len(results) if n == -1 else n
            break

    if num is not None and 1 <= num <= len(results):
        selected = results[num - 1]
    else:
        candidates = results
        if "расход" in user_text_lower:
            candidates = [res for res in candidates if res["type"] == "Расход"]
        elif "доход" in user_text_lower:
            candidates = [res for res in candidates if res["type"] == "Доход"]

        if "категори" in user_text_lower and not any(w in user_text_lower for w in ["подкатегори", "стать"]):
            c_match = [res for res in candidates if res["level"] == "category"]
            if c_match:
                candidates = c_match
        elif "подкатегори" in user_text_lower:
            s_match = [res for res in candidates if res["level"] == "subcategory"]
            if s_match:
                candidates = s_match
        elif "стать" in user_text_lower:
            a_match = [res for res in candidates if res["level"] == "article"]
            if a_match:
                candidates = a_match

        if len(candidates) == 1:
            selected = candidates[0]

    if not selected:
        send_vk_message(
            user_id,
            "⚠️ Не удалось точно определить пункт.\nУточните, сказав или написав: в Расходах или Доходах Категория (статья).\nЛибо просто нажмите номер нужного пункта на клавиатуре:",
            get_numbered_keyboard(len(results), show_back=True)
        )
        return True

    del user_states[user_id]
    return _execute_entity_action(user_id, internal_uid, action, selected, parsed_data, user_states)

def handle_structure_nlp_action(user_id, internal_uid, parsed_data, user_states, user_text=""):
    """Обрабатывает action: smart_rename, smart_delete, smart_move, start_interactive."""
    action = parsed_data.get("action")
    if not action:
        return False

    menu = get_full_menu(internal_uid)

    # 1. ЗАПУСК ИНТЕРАКТИВНОГО СОЗДАНИЯ
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

        u_lower = user_text.lower() if user_text else ""
        if len(results) > 1 and u_lower:
            filtered = results
            if "расход" in u_lower:
                filtered = [r for r in filtered if r["type"] == "Расход"]
            elif "доход" in u_lower:
                filtered = [r for r in filtered if r["type"] == "Доход"]

            if "категори" in u_lower and not any(w in u_lower for w in ["подкатегори", "стать"]):
                c_f = [r for r in filtered if r["level"] == "category"]
                if c_f:
                    filtered = c_f
            elif "подкатегори" in u_lower:
                s_f = [r for r in filtered if r["level"] == "subcategory"]
                if s_f:
                    filtered = s_f
            elif "стать" in u_lower:
                a_f = [r for r in filtered if r["level"] == "article"]
                if a_f:
                    filtered = a_f

            if filtered:
                results = filtered

        if len(results) == 1:
            return _execute_entity_action(user_id, internal_uid, action, results[0], parsed_data, user_states, menu=menu)

        act_verb = {"smart_delete": "удалить", "smart_rename": "переименовать", "smart_move": "перенести"}.get(action, "выбрать")
        msg = f"⚠️ Найдено несколько совпадений для «{target_name}»:\n\n"
        for i, ent in enumerate(results):
            level_ru = {"category": "Категория", "subcategory": "Подкатегория", "article": "Статья"}.get(ent["level"], "Сущность")
            type_str = "📉 Расход" if ent["type"] == "Расход" else "📈 Доход"
            chain = f"{type_str} -> {ent['cat']}"
            if ent["sub"]:
                chain += f" -> {ent['sub']}"
            if ent["art"]:
                chain += f" (статья: «{ent['art']}»)"
            msg += f"{i+1}. {level_ru}: {chain}\n"

        msg += (
            f"\n👉 Напишите или скажите голосом, где именно {act_verb}:\n"
            f"в Расходах или Доходах Категория (статья).\n"
            f"Либо просто нажмите номер нужного пункта на клавиатуре:"
        )

        user_states[user_id] = {
            "state": "structure_nlp_disambiguate",
            "action": action,
            "target_name": target_name,
            "results": results,
            "parsed_data": parsed_data
        }
        send_vk_message(user_id, msg, get_numbered_keyboard(len(results), show_back=True))
        return True

    return False 
