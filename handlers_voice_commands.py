# -*- coding: utf-8 -*-
import difflib
from services import send_vk_message, parse_voice_list_command_with_ai, categorize_with_ai
from keyboards import get_yes_no_keyboard, get_main_keyboard
from db import (
    get_or_create_user,
    smart_search_item,
    get_full_menu,
    learn_user_word,
    delete_transaction_by_id,
    update_transaction_amount,
    update_transaction_category
)

def _find_category_in_menu(menu_full, hint_text):
    """
    Умный трехуровневый поиск категории/подкатегории:
    1. Точное совпадение
    2. Частичное вхождение ("быт другое", "уход за собой")
    3. Нечеткий поиск опечаток и падежей (difflib)
    """
    clean = hint_text.lower().strip()
    cat_candidates = []
    sub_candidates = []

    for m_type in ["Расход", "Доход"]:
        type_cats = menu_full.get(m_type, {})
        for cat_name, subs in type_cats.items():
            sub_keys = list(subs.keys()) if isinstance(subs, dict) else (subs if subs else [])

            # 1. ТОЧНОЕ СОВПАДЕНИЕ
            if cat_name.lower() == clean:
                matching_sub = next((s for s in sub_keys if s.lower() == clean), (sub_keys[0] if sub_keys else "Разное"))
                return True, m_type, cat_name, matching_sub

            for s_name in sub_keys:
                if s_name.lower() == clean:
                    return True, m_type, cat_name, s_name

            # 2. ЧАСТИЧНОЕ ВХОЖДЕНИЕ
            if len(clean) >= 3:
                if clean in cat_name.lower() or cat_name.lower() in clean:
                    matching_sub = sub_keys[0] if sub_keys else "Разное"
                    return True, m_type, cat_name, matching_sub
                for s_name in sub_keys:
                    if clean in s_name.lower() or s_name.lower() in clean:
                        return True, m_type, cat_name, s_name

            cat_candidates.append((cat_name.lower(), m_type, cat_name, sub_keys))
            for s_name in sub_keys:
                sub_candidates.append((s_name.lower(), m_type, cat_name, s_name))

    # 3. НЕЧЕТКИЙ ПОИСК (difflib)
    all_sub_names = [item[0] for item in sub_candidates]
    matches_sub = difflib.get_close_matches(clean, all_sub_names, n=1, cutoff=0.68)
    if matches_sub:
        matched_str = matches_sub[0]
        for item in sub_candidates:
            if item[0] == matched_str:
                return True, item[1], item[2], item[3]

    all_cat_names = [item[0] for item in cat_candidates]
    matches_cat = difflib.get_close_matches(clean, all_cat_names, n=1, cutoff=0.68)
    if matches_cat:
        matched_str = matches_cat[0]
        for item in cat_candidates:
            if item[0] == matched_str:
                sub_keys = item[3]
                matching_sub = sub_keys[0] if sub_keys else "Разное"
                return True, item[1], item[2], matching_sub

    return False, None, None, None

def _apply_category_to_item(internal_uid, it, hint_text, menu_full, state):
    """Определяет категорию по подсказке и применяет ее к элементу."""
    current_art_name = it.get("article") or it.get("original_item") or it.get("item") or "Операция"
    op_type = it.get("type", "Расход")

    # 1. Поиск по меню
    is_match, m_type, found_cat, found_sub = _find_category_in_menu(menu_full, hint_text)

    # 2. Поиск по базе синонимов
    if not is_match:
        db_match = smart_search_item(internal_uid, hint_text, op_type=None)
        if db_match["status"] == "FOUND":
            is_match = True
            m_type = db_match.get("type", "Расход")
            found_cat = db_match["category"]
            found_sub = db_match["subcategory"]

    # 3. Резерв через ИИ
    if not is_match:
        type_menu = menu_full.get(op_type, {})
        menu_str = f"[{op_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])
        ai_c, ai_s = categorize_with_ai(current_art_name, menu_str, context=hint_text)
        m_type, found_cat, found_sub = op_type, ai_c, ai_s

    # Сохраняем результат
    if state == "history_view":
        update_transaction_category(internal_uid, it["id"], found_cat, found_sub, it["article"])
        it["category"] = found_cat
        it["subcategory"] = found_sub
    else:
        it["category"] = found_cat
        it["subcategory"] = found_sub
        if m_type:
            it["type"] = m_type

    return found_cat, found_sub

def handle_list_voice_commands(user_id, user_text, user_text_lower, state, user_states):
    """
    Универсальный обработчик голосовых команд над списками.
    Поддерживает как одиночные, так и комплексные команды (batch_set).
    """
    target_states = ["multi_tx_review", "receipt_review", "queue_batch_review", "history_view"]
    internal_uid = get_or_create_user(user_id)

    # ====================================================================
    # 1. ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ ("Да" / "Нет")
    # ====================================================================
    if state == "confirm_voice_delete":
        state_data = user_states[user_id]
        prev_state = state_data["prev_state"]
        indices = state_data["delete_indices"]

        if any(w in user_text_lower for w in ["да", "верно", "ок", "удалить", "+", "yes"]):
            if prev_state == "history_view":
                items = state_data["history_items"]
                deleted_cnt = 0
                for idx in sorted(indices, reverse=True):
                    if 0 <= idx < len(items):
                        tx_id = items[idx]["id"]
                        if delete_transaction_by_id(internal_uid, tx_id):
                            deleted_cnt += 1
                send_vk_message(user_id, f"🗑 Успешно удалено {deleted_cnt} операций из базы данных.", get_main_keyboard(user_id))
                del user_states[user_id]
                return True
            else:
                items_key = "current_batch" if prev_state == "queue_batch_review" else "items"
                items = state_data[items_key]
                for idx in sorted(indices, reverse=True):
                    if 0 <= idx < len(items):
                        items.pop(idx)

                user_states[user_id]["state"] = prev_state
                send_vk_message(user_id, f"🗑 Удалено {len(indices)} позиций из списка.")
                _refresh_screen(user_id, prev_state, user_states[user_id])
                return True

        elif any(w in user_text_lower for w in ["нет", "отмена", "назад", "не"]):
            user_states[user_id]["state"] = prev_state
            send_vk_message(user_id, "Удаление отменено.")
            _refresh_screen(user_id, prev_state, user_states[user_id])
            return True

    if state not in target_states:
        return False

    cmd_triggers = [
        "удали", "убери", "измени", "поставь", "исправь", "это", "рубл", "сумму", "название", "товар",
        "все", "всё", "всех", "очисти", "категори", "тоже", "также",
        "перв", "втор", "трет", "четверт", "пят", "шест", "седьм", "восьм", "девят", "десят",
        "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "операци", "строк", "пункт"
    ]
    if not any(t in user_text_lower for t in cmd_triggers):
        return False

    parsed_cmd = parse_voice_list_command_with_ai(user_text)
    action = parsed_cmd.get("action")

    if action == "unknown" or not action:
        return False

    state_data = user_states[user_id]
    items_key = "history_items" if state == "history_view" else ("current_batch" if state == "queue_batch_review" else "items")

    if state == "history_view":
        items = state_data.get("history_data", {}).get("items", [])
    else:
        items = state_data.get(items_key, [])

    if not items:
        return False

    menu_full = get_full_menu(internal_uid)

    # ====================================================================
    # КОМАНДА 1: СОСТАВНОЙ ПАКЕТНЫЙ ВВОД (BATCH SET)
    # «Второе это другое-другое. Третье быт. Четвертое стирка. Пятое гигиена...»
    # ====================================================================
    if action == "batch_set":
        updates = parsed_cmd.get("updates", [])
        applied_indices = []

        for up in updates:
            idx = int(up.get("index", 0)) - 1
            hint = up.get("hint", "").strip()
            if 0 <= idx < len(items) and hint:
                _apply_category_to_item(internal_uid, items[idx], hint, menu_full, state)
                applied_indices.append(idx + 1)

        if applied_indices:
            report_str = ", ".join([f"№{i}" for i in applied_indices])
            send_vk_message(user_id, f"✅ Обновлены позиции: {report_str}")
            _refresh_screen(user_id, state, state_data)
            return True

    # Извлекаем индексы для одиночных команд
    raw_indices = parsed_cmd.get("indices")
    if not raw_indices and "index" in parsed_cmd:
        raw_indices = [parsed_cmd["index"]]
    if not raw_indices:
        raw_indices = []

    valid_indices = [int(i) - 1 for i in raw_indices if 0 <= int(i) - 1 < len(items)]

    # ====================================================================
    # КОМАНДА 2: УКАЗАНИЕ КАТЕГОРИИ К ОДНОЙ ИЛИ НЕСКОЛЬКИМ ПОЗИЦИЯМ
    # ====================================================================
    if action == "set_category":
        hint_text = (parsed_cmd.get("hint") or "").strip()
        if valid_indices and hint_text:
            found_cat, found_sub = None, None
            for idx in valid_indices:
                found_cat, found_sub = _apply_category_to_item(internal_uid, items[idx], hint_text, menu_full, state)

            indices_str = ", ".join([f"№{i+1}" for i in valid_indices])
            send_vk_message(
                user_id,
                f"✅ Позиции {indices_str} обновлены:\n"
                f"📂 {found_cat} -> {found_sub}"
            )
            _refresh_screen(user_id, state, state_data)
            return True

    # ====================================================================
    # КОМАНДА 3: ПЕРЕИМЕНОВАНИЕ НАЗВАНИЯ ТОВАРА
    # ====================================================================
    if action in ["rename_item", "rename_item_and_amount"]:
        new_name = (parsed_cmd.get("name") or "").strip()
        new_amount = float(parsed_cmd.get("amount", 0)) if action == "rename_item_and_amount" else None

        if valid_indices and new_name:
            idx = valid_indices[0]
            it = items[idx]
            op_type = it.get("type", "Расход")

            db_match = smart_search_item(internal_uid, new_name, op_type=op_type)
            if db_match["status"] != "FOUND":
                db_match = smart_search_item(internal_uid, new_name, op_type=None)

            if db_match["status"] == "FOUND":
                target_art = new_name.capitalize()
                target_cat = db_match["category"]
                target_sub = db_match["subcategory"]
            else:
                target_art = new_name.capitalize()
                target_cat = it.get("category", "Разное")
                target_sub = it.get("subcategory", "Требует проверки")

            if state == "history_view":
                update_transaction_category(internal_uid, it["id"], target_cat, target_sub, target_art)
                if new_amount:
                    update_transaction_amount(internal_uid, it["id"], new_amount)
                    it["amount"] = new_amount
                it["article"] = target_art
                it["category"] = target_cat
                it["subcategory"] = target_sub
            else:
                if "item" in it: it["item"] = target_art
                elif "original_item" in it: it["original_item"] = target_art
                elif "article" in it: it["article"] = target_art

                it["category"] = target_cat
                it["subcategory"] = target_sub
                if new_amount:
                    it["amount"] = new_amount

            amt_info = f" ({new_amount:g} руб.)" if new_amount else ""
            send_vk_message(
                user_id,
                f"✅ Позиция №{idx+1} обновлена:\n"
                f"• Статья: «{target_art}»{amt_info}\n"
                f"• Категория: 📂 {target_cat} -> {target_sub}"
            )
            _refresh_screen(user_id, state, state_data)
            return True

    # ====================================================================
    # КОМАНДА 4: ИЗМЕНЕНИЕ СУММЫ
    # ====================================================================
    if action == "edit_amount":
        new_amount = float(parsed_cmd.get("amount", 0))
        if valid_indices and new_amount > 0:
            idx = valid_indices[0]
            it = items[idx]
            name = it.get("article") or it.get("original_item") or it.get("item") or "Операция"
            old_amt = it.get("amount", 0)

            if state == "history_view":
                update_transaction_amount(internal_uid, it["id"], new_amount)
                it["amount"] = new_amount
            else:
                it["amount"] = new_amount

            send_vk_message(user_id, f"✅ Сумма позиции №{idx+1} («{name}») изменена: {old_amt:g} руб. ➔ {new_amount:g} руб.")
            _refresh_screen(user_id, state, state_data)
            return True

    # ====================================================================
    # КОМАНДА 5: УДАЛЕНИЕ (ВСЕ, НОМЕРА ИЛИ ПОСЛЕДНИЕ N)
    # ====================================================================
    if action in ["delete", "delete_all", "delete_last_n"]:
        del_indices = []

        if action == "delete_all":
            del_indices = list(range(len(items)))
        elif action == "delete_last_n":
            count_n = int(parsed_cmd.get("count", 1))
            del_indices = list(range(max(0, len(items) - count_n), len(items)))
        else:
            del_indices = valid_indices

        if not del_indices:
            send_vk_message(user_id, "⚠️ Не удалось определить позиции для удаления в списке.")
            return True

        if len(del_indices) == len(items):
            confirm_msg = f"⚠️ Вы уверены, что хотите удалить ВСЕ {len(items)} операций из списка?\n\n"
        else:
            confirm_msg = f"⚠️ Вы уверены, что хотите удалить {len(del_indices)} поз.:\n\n"

        for idx in del_indices[:10]:
            it = items[idx]
            name = it.get("article") or it.get("original_item") or it.get("item") or "Операция"
            amt = it.get("amount", 0)
            confirm_msg += f"• №{idx+1}: {name} — {amt:g} руб.\n"
        if len(del_indices) > 10:
            confirm_msg += f"... и еще {len(del_indices) - 10} операций.\n"

        user_states[user_id] = {
            "state": "confirm_voice_delete",
            "prev_state": state,
            "delete_indices": del_indices,
            "history_items": items if state == "history_view" else None,
            items_key: items
        }
        send_vk_message(user_id, confirm_msg, get_yes_no_keyboard(show_back=True))
        return True

    return False

def _refresh_screen(user_id, state, state_data):
    """Перерисовывает экран после изменений."""
    if state == "multi_tx_review":
        from handlers_transaction import _show_multi_tx_items
        _show_multi_tx_items(user_id, state_data["items"], show_apply_all=False)
    elif state == "receipt_review":
        from handlers_receipt import _show_receipt_items
        _show_receipt_items(user_id, state_data["items"])
    elif state == "queue_batch_review":
        from handlers_queue import _show_batch_items
        _show_batch_items(user_id, state_data["current_batch"], len(state_data.get("queue", [])), show_apply_all=False)
    elif state == "history_view":
        from handlers_transaction import _show_history_screen
        hist = state_data.get("history_data", {})
        _show_history_screen(user_id, hist.get("items", []), hist.get("title_period", "список"), hist.get("total_expense", 0), hist.get("total_income", 0))
