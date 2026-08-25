# -*- coding: utf-8 -*-
from keyboards import (
    get_main_keyboard, get_yes_no_keyboard, get_cancel_keyboard
)
from services import send_vk_message, send_to_google_sheets, categorize_with_ai

def process_next_in_queue(user_id, user_states):
    """Обрабатывает следующую операцию из очереди 'Требует проверки'"""
    state_data = user_states[user_id]
    queue = state_data["queue"]
    
    if not queue:
        send_vk_message(user_id, "🎉 Ура! Все завалы разобраны! Журнал чист.", get_main_keyboard())
        del user_states[user_id]
        return
        
    current = queue[0]
    menu = state_data["menu"]
    menu_str = "\n".join([f"{c}: {', '.join(subs)}" for c, subs in menu.items()])
    
    send_vk_message(user_id, f"Осталось разобрать: {len(queue)} шт.\n🧠 Анализирую: '{current['original_item']}'...")
    ai_cat, ai_sub = categorize_with_ai(current['original_item'], menu_str)
    
    state_data["state"] = "queue_confirm"
    state_data["ai_cat"] = ai_cat
    state_data["ai_sub"] = ai_sub
    state_data["attempts"] = 0
    
    msg = f"📅 Дата: {current['date'][:10]}\n💰 Сумма: {current['amount']}\n🛒 Операция: {current['original_item']}\n\n🤖 ИИ думает, это:\n📂 {ai_cat} -> {ai_sub}\n\nВерно?"
    send_vk_message(user_id, msg, get_yes_no_keyboard())


def handle_queue_and_learning(user_id, user_text, user_text_lower, state, user_states, MAX_ATTEMPTS):
    """
    Обрабатывает ветку "Разобрать завалы" и процесс обучения (когда ИИ не знает категорию).
    Возвращает True, если стейт относится к этой ветке и был обработан.
    """

    # =========================================================
    # РАЗБОР ИМПОРТА (ЗАВАЛОВ) - СТАРТ
    # =========================================================
    if user_text_lower in ["разобрать завалы", "разобрать"]:
        send_vk_message(user_id, "⏳ Запрашиваю список нераспознанных операций из Таблицы...")
        res = send_to_google_sheets({"action": "get_unverified"})
        if res.get("status") == "SUCCESS":
            unverified = res.get("data", [])
            if not unverified:
                send_vk_message(user_id, "🎉 Всё чисто! Нераспознанных операций нет.", get_main_keyboard())
            else:
                user_states[user_id] = {"state": "queue_process", "queue": unverified, "menu": res.get("available_menu", {})}
                process_next_in_queue(user_id, user_states)
        else:
            send_vk_message(user_id, f"❌ Ошибка: {res.get('message')}", get_main_keyboard())
        return True

    # =========================================================
    # ЛОГИКА ДЛЯ ОЧЕРЕДИ ЗАВАЛОВ
    # =========================================================
    if state == "queue_confirm":
        if user_text_lower in ["да", "верно", "ага", "давай", "ок", "yes", "+"]:
            current = user_states[user_id]["queue"][0]
            payload = {
                "action": "resolve_unverified",
                "original_item": current["original_item"],
                "amount": current["amount"],
                "type": current["type"],
                "category": user_states[user_id]["ai_cat"],
                "subcategory": user_states[user_id]["ai_sub"]
            }
            send_vk_message(user_id, "⏳ Записываю и обучаюсь...")
            send_to_google_sheets(payload)
            user_states[user_id]["queue"].pop(0)
            process_next_in_queue(user_id, user_states)
        elif user_text_lower in ["нет", "неверно", "не", "no", "-"]:
            user_states[user_id]["state"] = "queue_hint"
            send_vk_message(user_id, "Понял, ошибся. Подскажи другими словами, что это за операция?", get_cancel_keyboard())
        else:
            send_vk_message(user_id, "Пожалуйста, ответь 'Да' или 'Нет'.", get_yes_no_keyboard())
        return True

    if state == "queue_hint":
        send_vk_message(user_id, "🧠 Думаю...")
        current = user_states[user_id]["queue"][0]
        menu = user_states[user_id]["menu"]
        menu_str = "\n".join([f"{c}: {', '.join(subs)}" for c, subs in menu.items()])
        
        check_payload = {"action": "check_item", "item": user_text, "type": current.get("type", "Расход")}
        check_res = send_to_google_sheets(check_payload)
        if check_res.get("status") == "FOUND":
            user_states[user_id]["state"] = "queue_confirm"
            user_states[user_id]["ai_cat"] = check_res.get("cat")
            user_states[user_id]["ai_sub"] = check_res.get("sub")
            send_vk_message(user_id, f"Ага! Слово '{user_text}' мне знакомо.\n📂 {check_res.get('cat')} -> {check_res.get('sub')}\n\nВсё верно?", get_yes_no_keyboard())
            return True
            
        ai_cat, ai_sub = categorize_with_ai(current["original_item"], menu_str, context=user_text)
        if ai_cat in menu and ai_sub in menu[ai_cat]:
            user_states[user_id]["state"] = "queue_confirm"
            user_states[user_id]["ai_cat"] = ai_cat
            user_states[user_id]["ai_sub"] = ai_sub
            send_vk_message(user_id, f"Ага! С учетом подсказки, думаю это:\n📂 {ai_cat} -> {ai_sub}\n\nВсё верно?", get_yes_no_keyboard())
        else:
            user_states[user_id]["state"] = "queue_manual"
            cats_list = "\n".join([f"• {k}" for k in menu.keys()])
            send_vk_message(user_id, "🤷‍♂️ Я сдаюсь. Напиши точную категорию из списка через дефис:\n\n" + cats_list, get_cancel_keyboard())
        return True

    if state == "queue_manual":
        parts = user_text.split("-")
        if len(parts) >= 2:
            current = user_states[user_id]["queue"][0]
            payload = {
                "action": "resolve_unverified",
                "original_item": current["original_item"],
                "amount": current["amount"],
                "type": current["type"],
                "category": parts[0].strip(),
                "subcategory": parts[1].strip()
            }
            send_vk_message(user_id, "⏳ Записываю и обучаюсь...")
            send_to_google_sheets(payload)
            user_states[user_id]["queue"].pop(0)
            process_next_in_queue(user_id, user_states)
        else:
            send_vk_message(user_id, "⚠️ Напиши через дефис. Пример: Транспорт - Такси", get_cancel_keyboard())
        return True

    # =========================================================
    # ОБУЧЕНИЕ ОДИНОЧНОЙ ОПЕРАЦИИ (ДА/НЕТ, ПОДСКАЗКИ)
    # =========================================================
    if state == "confirm_category":
        if user_text_lower in ["да", "верно", "ага", "давай", "ок", "yes", "+"]:
            payload = user_states[user_id]["payload"]
            payload["category"] = user_states[user_id]["ai_cat"]
            payload["subcategory"] = user_states[user_id]["ai_sub"]
            send_vk_message(user_id, "⏳ Записываю...")
            gs_response = send_to_google_sheets(payload)
            if gs_response.get("status") == "SUCCESS":
                send_vk_message(user_id, "✅ Успешно записано и выучено!", get_main_keyboard())
            else:
                send_vk_message(user_id, f"❌ Ошибка таблицы: {gs_response.get('message')}", get_main_keyboard())
            del user_states[user_id]
        elif user_text_lower in ["нет", "неверно", "не", "no", "-"]:
            if user_states[user_id]["attempts"] < MAX_ATTEMPTS:
                user_states[user_id]["state"] = "provide_context"
                send_vk_message(user_id, f"Понял, ошибся 😔 (Попытка {user_states[user_id]['attempts']} из {MAX_ATTEMPTS})\nПодскажи другими словами, что это за операция?", get_cancel_keyboard())
            else:
                user_states[user_id]["state"] = "manual_category"
                menu = user_states[user_id]["menu"]
                cats_list = "\n".join([f"• {k}" for k in menu.keys()])
                send_vk_message(user_id, "🤷‍♂️ Я сдаюсь. Напиши точную категорию из списка через дефис:\n\n" + cats_list, get_cancel_keyboard())
        else:
            send_vk_message(user_id, "Пожалуйста, ответь 'Да' или 'Нет'.", get_yes_no_keyboard())
        return True

    if state == "provide_context":
        send_vk_message(user_id, "🧠 Думаю...")
        user_states[user_id]["attempts"] += 1
        payload = user_states[user_id]["payload"]
        menu = user_states[user_id]["menu"]
        menu_str = "\n".join([f"{c}: {', '.join(subs)}" for c, subs in menu.items()])
        
        check_payload = {"action": "check_item", "item": user_text, "type": payload.get("type", "Расход")}
        check_res = send_to_google_sheets(check_payload)
        if check_res.get("status") == "FOUND":
            user_states[user_id]["state"] = "confirm_category"
            user_states[user_id]["ai_cat"] = check_res.get("cat")
            user_states[user_id]["ai_sub"] = check_res.get("sub")
            send_vk_message(user_id, f"Ага! Слово '{user_text}' мне знакомо.\n📂 {check_res.get('cat')} -> {check_res.get('sub')}\n\nВсё верно?", get_yes_no_keyboard())
            return True
            
        ai_cat, ai_sub = categorize_with_ai(payload["item"], menu_str, context=user_text)
        if ai_cat in menu and ai_sub in menu[ai_cat]:
            user_states[user_id]["state"] = "confirm_category"
            user_states[user_id]["ai_cat"] = ai_cat
            user_states[user_id]["ai_sub"] = ai_sub
            send_vk_message(user_id, f"Ага! С учетом подсказки, думаю это:\n📂 {ai_cat} -> {ai_sub}\n\nВсё верно?", get_yes_no_keyboard())
        else:
            if user_states[user_id]["attempts"] < MAX_ATTEMPTS:
                send_vk_message(user_id, f"Всё равно не могу сообразить 🤔 (Попытка {user_states[user_id]['attempts']} из {MAX_ATTEMPTS})\nПопробуй объяснить чуть подробнее?", get_cancel_keyboard())
            else:
                user_states[user_id]["state"] = "manual_category"
                cats_list = "\n".join([f"• {k}" for k in menu.keys()])
                send_vk_message(user_id, "🤷‍♂️ Я сдаюсь. Напиши точную категорию из списка через дефис:\n\n" + cats_list, get_cancel_keyboard())
        return True

    if state == "manual_category":
        parts = user_text.split("-")
        if len(parts) >= 2:
            cat = parts[0].strip()
            sub = parts[1].strip()
            payload = user_states[user_id]["payload"]
            payload["category"] = cat
            payload["subcategory"] = sub
            send_vk_message(user_id, "⏳ Обучаюсь и записываю...")
            gs_response = send_to_google_sheets(payload)
            if gs_response.get("status") == "SUCCESS":
                send_vk_message(user_id, f"✅ Успешно! Я запомнил, что '{payload['item']}' — это {cat} -> {sub}.", get_main_keyboard())
            else:
                send_vk_message(user_id, f"❌ Ошибка: {gs_response.get('message')}", get_main_keyboard())
            del user_states[user_id]
        else:
            send_vk_message(user_id, "⚠️ Напиши через дефис. Пример: Транспорт - Такси", get_cancel_keyboard())
        return True

    return False
