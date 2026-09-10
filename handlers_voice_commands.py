# -*- coding: utf-8 -*-
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

def handle_list_voice_commands(user_id, user_text, user_text_lower, state, user_states):
    """
    Универсальный обработчик голосовых команд над списками:
    - Исправление названия товара ("первая операция это огурцы")
    - Изменение суммы ("измени сумму у четвертой на 250")
    - Удаление нескольких позиций ("удали первую, третью и пятую")
    """
    target_states = ["multi_tx_review", "receipt_review", "queue_batch_review", "history_view"]
    internal_uid = get_or_create_user(user_id)

    # 1. ОБРАБОТКА ПОДТВЕРЖДЕНИЯ УДАЛЕНИЯ ("Да" / "Нет")
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

    # ====================================================================
    # КОМАНДА 1: ИСПРАВЛЕНИЕ НАЗВАНИЯ ТОВАРА/СТАТЬИ И КАТЕГОРИИ
    # ("Первая операция это огурцы" / "исправь первую на молоко")
    # ====================================================================
    if action in ["edit_item", "edit_category", "edit_item_and_amount"]:
        idx = int(parsed_cmd.get("index", 0)) - 1
        new_text = parsed_cmd.get("text", "").strip()
        new_amount = float(parsed_cmd.get("amount", 0)) if action == "edit_item_and_amount" else None

        if 0 <= idx < len(items) and new_text:
            it = items[idx]
            op_type = it.get("type", "Расход")

            # 1. Сначала ищем новое слово в базе данных (вдруг это знакомый товар!)
            db_match = smart_search_item(internal_uid, new_text, op_type=op_type)
            if db_match["status"] != "FOUND":
                db_match = smart_search_item(internal_uid, new_text, op_type=None)

            if db_match["status"] == "FOUND":
                # Найдено в базе -> обновляем и товар, и категорию из эталона базы!
                target_art = new_text.capitalize()
                target_cat = db_match["category"]
                target_sub = db_match["subcategory"]
                if db_match.get("type"):
                    op_type = db_match["type"]
            else:
                # 2. Проверяем: вдруг названа категория из меню
                menu_full = get_full_menu(internal_uid)
                u_clean = new_text.lower()
                found_in_tree = False
                target_art = new_text.capitalize()
                target_cat, target_sub = "Разное", "Требует проверки"

                for m_type in ["Расход", "Доход"]:
                    type_cats = menu_full.get(m_type, {})
                    for m_cat, m_subs in type_cats.items():
                        if m_cat.lower() == u_clean:
                            target_cat = m_cat
                            sub_keys = list(m_subs.keys()) if isinstance(m_subs, dict) else (m_subs if m_subs else [])
                            target_sub = sub_keys[0] if sub_keys else "Разное"
                            found_in_tree = True
                            break
                        sub_keys = list(m_subs.keys()) if isinstance(m_subs, dict) else (m_subs if m_subs else [])
                        for s_name in sub_keys:
                            if s_name.lower() == u_clean:
                                target_cat = m_cat
                                target_sub = s_name
                                found_in_tree = True
                                break
                        if found_in_tree:
                            break
                    if found_in_tree:
                        break

                # 3. Если нет — просим ИИ подобрать категорию под новое слово
                if not found_in_tree:
                    type_menu = menu_full.get(op_type, {})
                    menu_str = f"[{op_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])
                    ai_cat, ai_sub = categorize_with_ai(target_art, menu_str)
                    target_cat, target_sub = ai_cat, ai_sub

            # Применяем изменения
            if state == "history_view":
                update_transaction_category(internal_uid, it["id"], target_cat, target_sub, target_art)
                if new_amount:
                    update_transaction_amount(internal_uid, it["id"], new_amount)
                    it["amount"] = new_amount
                it["article"] = target_art
                it["category"] = target_cat
                it["subcategory"] = target_sub
            else:
                if "item" in it:
                    it["item"] = target_art
                elif "original_item" in it:
                    it["original_item"] = target_art
                elif "article" in it:
                    it["article"] = target_art

                it["category"] = target_cat
                it["subcategory"] = target_sub
                it["type"] = op_type
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
    # КОМАНДА 2: ИЗМЕНЕНИЕ СУММЫ ("Измени сумму у четвертой на 250")
    # ====================================================================
    if action == "edit_amount":
        idx = int(parsed_cmd.get("index", 0)) - 1
        new_amount = float(parsed_cmd.get("amount", 0))

        if 0 <= idx < len(items) and new_amount > 0:
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
    # КОМАНДА 3: МАССОВОЕ УДАЛЕНИЕ ("Удали первую и третью")
    # ====================================================================
    if action == "delete":
        raw_indices = parsed_cmd.get("indices", [])
        valid_indices = []
        for i in raw_indices:
            idx = int(i) - 1
            if 0 <= idx < len(items):
                valid_indices.append(idx)

        if not valid_indices:
            send_vk_message(user_id, "⚠️ Не удалось найти указанные номера в списке.")
            return True

        confirm_msg = f"⚠️ Вы уверены, что хотите удалить {len(valid_indices)} поз.:\n\n"
        for idx in valid_indices:
            it = items[idx]
            name = it.get("article") or it.get("original_item") or it.get("item") or "Операция"
            amt = it.get("amount", 0)
            confirm_msg += f"• №{idx+1}: {name} — {amt:g} руб.\n"

        user_states[user_id] = {
            "state": "confirm_voice_delete",
            "prev_state": state,
            "delete_indices": valid_indices,
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
