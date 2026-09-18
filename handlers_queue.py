# -*- coding: utf-8 -*-
from keyboards import get_main_keyboard, type_keyboard, get_numbered_keyboard
from services import send_vk_message
from db import get_or_create_user, get_full_menu, get_unverified_transactions
from handlers_queue_batch import handle_queue_batch, _process_next_batch, _show_batch_items
from handlers_learning import handle_learning_flow

def handle_queue_and_learning(user_id, user_text, user_text_lower, state, user_states, MAX_ATTEMPTS):
    """Точка входа: инициализация разбора очереди, навигация «Назад» и маршрутизация."""
    internal_uid = get_or_create_user(user_id)

    # 1. ЗАПУСК РАЗБОРА ОПЕРАЦИЙ
    triggers = ["разобрать операции", "разобрать завалы", "разобрать", "завалы", "импорт статистики прошлого"]
    if any(trigger in user_text_lower for trigger in triggers):
        send_vk_message(user_id, "⏳ Проверяю нераспознанные операции в базе...")
        unverified_raw = get_unverified_transactions(user_id)
        if not unverified_raw:
            send_vk_message(user_id, "🎉 Всё чисто! Нераспределенных операций нет.", get_main_keyboard(user_id))
            if user_id in user_states:
                del user_states[user_id]
            return True

        unique_items = {}
        for row in unverified_raw:
            key = f"{row['type']}_{row['original_item']}"
            if key not in unique_items:
                unique_items[key] = {
                    "type": row["type"],
                    "original_item": row["original_item"],
                    "count": 1,
                    "amount": row["amount"]
                }
            else:
                unique_items[key]["count"] += 1
                unique_items[key]["amount"] += row["amount"]

        full_menu = get_full_menu(internal_uid)
        combined_menu = {}
        for t in ["Расход", "Доход"]:
            for c, s in full_menu.get(t, {}).items():
                combined_menu[c] = list(s.keys()) if isinstance(s, dict) else s

        user_states[user_id] = {
            "state": "queue_process",
            "queue": list(unique_items.values()),
            "menu": combined_menu
        }
        _process_next_batch(user_id, user_states)
        return True

    # 2. ОБРАБОТКА «НАЗАД»
    if "назад" in user_text_lower:
        if state in ["queue_batch_edit_hint", "queue_item_action_select", "queue_select_trash_numbers", "confirm_delete_all_batch_trash"]:
            user_states[user_id]["state"] = "queue_batch_review"
            _show_batch_items(user_id, user_states[user_id]["current_batch"], len(user_states[user_id]["queue"]), show_apply_all=False)
            return True
        elif state == "queue_batch_review":
            del user_states[user_id]
            send_vk_message(user_id, "Главное меню.", get_main_keyboard(user_id))
            return True
        elif state == "tx_manual_cat":
            user_states[user_id]["state"] = "tx_manual_type"
            send_vk_message(user_id, "Это Расход или Доход?", type_keyboard(show_back=True))
            return True
        elif state == "tx_manual_sub":
            cats = user_states[user_id].get("cats", [])
            op_type = user_states[user_id]["payload"].get("type", "Расход")
            user_states[user_id]["state"] = "tx_manual_cat"
            msg = f"Выберите КАТЕГОРИЮ ({op_type}):\n\n"
            for i, c in enumerate(cats):
                msg += f"{i+1}. {c}\n"
            send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))
            return True

    # 3. ДЕЛЕГИРОВАНИЕ В ПОДМОДУЛИ
    if handle_queue_batch(user_id, internal_uid, user_text, user_text_lower, state, user_states):
        return True

    if handle_learning_flow(user_id, internal_uid, user_text, user_text_lower, state, user_states, MAX_ATTEMPTS):
        return True

    return False
