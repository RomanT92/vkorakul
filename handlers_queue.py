# -*- coding: utf-8 -*-
from keyboards import (
    get_main_keyboard, get_yes_no_keyboard, get_cancel_keyboard, get_queue_review_keyboard
)
from services import (
    send_vk_message, send_to_google_sheets, 
    categorize_with_ai, categorize_batch_with_ai
)

BATCH_SIZE = 7  # Количество операций в одном пакете

def _show_batch_items(user_id, batch, total_left):
    """Выводит пронумерованный список операций пакета"""
    msg = f"📋 Пакет операций (осталось в завалах: {total_left + len(batch)}):\n\n"
    for i, item in enumerate(batch):
        msg += f"{i+1}. {item['original_item']} — {item['amount']} руб.\n"
        msg += f"   📂 {item.get('category', '?')} -> {item.get('subcategory', '?')}\n\n"
    msg += "Если всё верно, жмите «Сохранить пакет».\nЕсли есть ошибка — отправьте НОМЕР операции для исправления."
    
    send_vk_message(user_id, msg, get_queue_review_keyboard(len(batch)))

def _process_next_batch(user_id, user_states):
    """Берет следующие N операций из очереди и отправляет их в ИИ"""
    state_data = user_states[user_id]
    queue = state_data.get("queue", [])
    
    if not queue:
        send_vk_message(user_id, "🎉 Ура! Все завалы разобраны! Журнал чист.", get_main_keyboard())
        del user_states[user_id]
        return
        
    # Берем пачку операций
    batch = queue[:BATCH_SIZE]
    state_data["queue"] = queue[BATCH_SIZE:] # Убираем их из основной очереди
    
    menu = state_data["menu"]
    menu_str = "\n".join([f"{c}: {', '.join(subs)}" for c, subs in menu.items()])
    
    send_vk_message(user_id, f"🧠 ИИ анализирует {len(batch)} операций...", get_cancel_keyboard())
    
    # Отправляем весь пакет в ИИ одним запросом
    ai_results = categorize_batch_with_ai(batch, menu_str)
    
    # Объединяем ответы ИИ с нашими операциями
    for item in batch:
        cat, sub = "Разное", "Требует проверки"
        for res in ai_results:
            if res.get("original_item") == item["original_item"]:
                cat = res.get("category", "Разное")
                sub = res.get("subcategory", "Требует проверки")
                break
        item["category"] = cat
        item["subcategory"] = sub
        
    state_data["current_batch"] = batch
    state_data["state"] = "queue_batch_review"
    
    _show_batch_items(user_id, batch, len(state_data["queue"]))


def handle_queue_and_learning(user_id, user_text, user_text_lower, state, user_states, MAX_ATTEMPTS):
    """
    Обрабатывает ветку "Разобрать завалы" (пакетно) и процесс одиночного обучения.
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
                user_states[user_id] = {
                    "state": "queue_process", 
                    "queue": unverified, 
                    "menu": res.get("available_menu", {})
                }
                _process_next_batch(user_id, user_states)
        else:
            send_vk_message(user_id, f"❌ Ошибка: {res.get('message')}", get_main_keyboard())
        return True

    # =========================================================
    # РЕВЬЮ ПАКЕТА И СОХРАНЕНИЕ
    # =========================================================
    if state == "queue_batch_review":
        if user_text_lower == "сохранить пакет":
            batch = user_states[user_id]["current_batch"]
            send_vk_message(user_id, f"⏳ Сохраняю {len(batch)} операций и обучаю систему...", get_cancel_keyboard())
            
            success_count = 0
            for item in batch:
                payload = {
                    "action": "resolve_unverified",
                    "original_item": item["original_item"],
                    "amount": item["amount"],
                    "type": item["type"],
                    "category": item["category"],
                    "subcategory": item["subcategory"]
                }
                res = send_to_google_sheets(payload)
                if res.get("status") == "SUCCESS":
                    success_count += 1
                    
            send_vk_message(user_id, f"✅ Успешно сохранено {success_count} из {len(batch)}!")
            
            # Автоматически переходим к следующему пакету
            _process_next_batch(user_id, user_states)
            return True
            
        elif user_text.isdigit():
            idx = int(user_text) - 1
            batch = user_states[user_id]["current_batch"]
            if 0 <= idx < len(batch):
                user_states[user_id]["edit_idx"] = idx
                user_states[user_id]["state"] = "queue_batch_edit_hint"
                sel_item = batch[idx]
                send_vk_message(user_id, f"✏️ Исправляем: {sel_item['original_item']}\nНапишите правильную категорию (например, 'Транспорт - Такси') или дайте подсказку:", get_cancel_keyboard())
            return True

    # =========================================================
    # ИСПРАВЛЕНИЕ КОНКРЕТНОЙ ОПЕРАЦИИ ИЗ ПАКЕТА
    # =========================================================
    if state == "queue_batch_edit_hint":
        idx = user_states[user_id]["edit_idx"]
        batch = user_states[user_id]["current_batch"]
        sel_item = batch[idx]
        menu_str = "\n".join([f"{c}: {', '.join(subs)}" for c, subs in user_states[user_id]["menu"].items()])
        
        send_vk_message(user_id, "🧠 Думаю...", get_cancel_keyboard())
        
        # Если пользователь ввел точную категорию через дефис
        if "-" in user_text:
            parts = user_text.split("-")
            if len(parts) >= 2:
                sel_item["category"] = parts[0].strip()
                sel_item["subcategory"] = parts[1].strip()
                user_states[user_id]["state"] = "queue_batch_review"
                _show_batch_items(user_id, batch, len(user_states[user_id]["queue"]))
                return True
                
        # Иначе просим ИИ подобрать по подсказке
        ai_cat, ai_sub = categorize_with_ai(sel_item["original_item"], menu_str, context=user_text)
        
        sel_item["category"] = ai_cat
        sel_item["subcategory"] = ai_sub
        
        # Возвращаемся в режим ревью пакета
        user_states[user_id]["state"] = "queue_batch_review"
        _show_batch_items(user_id, batch, len(user_states[user_id]["queue"]))
        return True

    # =========================================================
    # ОБУЧЕНИЕ ОДИНОЧНОЙ ОПЕРАЦИИ (Для обычного режима)
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
                user_states[user_id]["context_history"] = "" 
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
        
        if "доход" in user_text_lower or "приход" in user_text_lower:
            payload["type"] = "Доход"
        elif "расход" in user_text_lower or "трата" in user_text_lower:
            payload["type"] = "Расход"

        prev_context = user_states[user_id].get("context_history", "")
        current_context = f"{prev_context}\n- {user_text}" if prev_context else f"- {user_text}"
        user_states[user_id]["context_history"] = current_context
        
        check_payload = {"action": "check_item", "item": user_text, "type": payload.get("type", "Расход")}
        check_res = send_to_google_sheets(check_payload)
        if check_res.get("status") == "FOUND":
            user_states[user_id]["state"] = "confirm_category"
            user_states[user_id]["ai_cat"] = check_res.get("cat")
            user_states[user_id]["ai_sub"] = check_res.get("sub")
            send_vk_message(user_id, f"Ага! Слово '{user_text}' мне знакомо.\n📂 {check_res.get('cat')} -> {check_res.get('sub')}\n\nВсё верно?", get_yes_no_keyboard())
            return True
            
        ai_cat, ai_sub = categorize_with_ai(payload["item"], menu_str, context=current_context)
        if ai_cat in menu and ai_sub in menu[ai_cat]:
            user_states[user_id]["state"] = "confirm_category"
            user_states[user_id]["ai_cat"] = ai_cat
            user_states[user_id]["ai_sub"] = ai_sub
            send_vk_message(user_id, f"Ага! С учетом всех подсказок, думаю это:\n📂 {ai_cat} -> {ai_sub}\n\nВсё верно?", get_yes_no_keyboard())
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
