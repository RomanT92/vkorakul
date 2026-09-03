# -*- coding: utf-8 -*-
from keyboards import (
    get_main_keyboard,
    get_yes_no_keyboard,
    get_cancel_keyboard,
    get_queue_review_keyboard,
    get_numbered_keyboard,
    type_keyboard  # <-- Добавили клавиатуру выбора типа
)
from services import (
    send_vk_message,
    categorize_with_ai,
    categorize_batch_with_ai
)
from db import (
    get_or_create_user,
    save_transaction,
    learn_user_word,
    smart_search_item,
    get_full_menu,  # <-- Берем меню из базы
    get_unverified_transactions,
    resolve_unverified_item
)

BATCH_SIZE = 7

def _show_batch_items(user_id, batch, total_left):
    """Выводит пакет статей на проверку пользователю"""
    msg = f"📋 Пакет уникальных статей (осталось разобрать: {total_left + len(batch)}):\n\n"
    for i, item in enumerate(batch):
        msg += f"{i+1}. {item['original_item']} ({item['count']} операций)\n"
        msg += f"   📂 {item.get('category', '?')} -> {item.get('subcategory', '?')}\n\n"
    msg += "Если всё верно, жмите «Сохранить пакет».\nЕсли есть ошибка — отправьте НОМЕР для исправления."
    send_vk_message(user_id, msg, get_queue_review_keyboard(len(batch)))

def _process_next_batch(user_id, user_states):
    """Берет следующую пачку из очереди завалов и прогоняет через ИИ"""
    state_data = user_states[user_id]
    queue = state_data.get("queue", [])
    
    if not queue:
        send_vk_message(user_id, "🎉 Ура! Завалы разобраны! Журнал чист.", get_main_keyboard())
        del user_states[user_id]
        return

    batch = queue[:BATCH_SIZE]
    state_data["queue"] = queue[BATCH_SIZE:]
    
    menu = state_data["menu"]
    menu_str = "\n".join([f"{c}: {', '.join(subs)}" for c, subs in menu.items()])

    send_vk_message(user_id, f"🧠 ИИ анализирует {len(batch)} новых статей...", get_cancel_keyboard())
    ai_results = categorize_batch_with_ai(batch, menu_str)

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
    internal_uid = get_or_create_user(user_id)

    # =========================================================
    # 1. ЗАПУСК РАЗБОРА ЗАВАЛОВ (Из базы PostgreSQL)
    # =========================================================
    if user_text_lower in ["импорт статистики прошлого", "разобрать завалы", "разобрать"]:
        send_vk_message(user_id, "⏳ Проверяю нераспознанные операции в базе...")
        unverified_raw = get_unverified_transactions(internal_uid)
        
        if not unverified_raw:
            send_vk_message(user_id, "🎉 Всё чисто! Нераспознанных операций нет.", get_main_keyboard())
        else:
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
            
            unverified_grouped = list(unique_items.values())
            
            full_menu = get_full_menu(internal_uid)
            combined_menu = {}
            for t in ["Расход", "Доход"]:
                for c, s in full_menu.get(t, {}).items():
                    combined_menu[c] = s

            user_states[user_id] = {
                "state": "queue_process",
                "queue": unverified_grouped,
                "menu": combined_menu
            }
            _process_next_batch(user_id, user_states)
        return True

    # =========================================================
    # 2. РЕВЬЮ ПАКЕТА ЗАВАЛОВ
    # =========================================================
    if state == "queue_batch_review":
        if user_text_lower == "сохранить пакет":
            batch = user_states[user_id]["current_batch"]
            send_vk_message(user_id, "⏳ Сохраняю и обучаю систему...", get_cancel_keyboard())
            
            for item in batch:
                resolve_unverified_item(
                    user_id=internal_uid,
                    original_item=item["original_item"],
                    op_type=item["type"],
                    category=item["category"],
                    subcategory=item["subcategory"]
                )
            
            send_vk_message(user_id, f"✅ Успешно сохранено {len(batch)} статей!")
            _process_next_batch(user_id, user_states)
            return True

        elif user_text.isdigit():
            idx = int(user_text) - 1
            batch = user_states[user_id]["current_batch"]
            if 0 <= idx < len(batch):
                user_states[user_id]["edit_idx"] = idx
                user_states[user_id]["state"] = "queue_batch_edit_hint"
                sel_item = batch[idx]
                send_vk_message(user_id, f"✏️ Исправляем: {sel_item['original_item']}\nДайте подсказку:", get_cancel_keyboard())
                return True

    if state == "queue_batch_edit_hint":
        idx = user_states[user_id]["edit_idx"]
        batch = user_states[user_id]["current_batch"]
        sel_item = batch[idx]
        menu_str = "\n".join([f"{c}: {', '.join(subs)}" for c, subs in user_states[user_id]["menu"].items()])
        send_vk_message(user_id, "🧠 Думаю...", get_cancel_keyboard())
        
        ai_cat, ai_sub = categorize_with_ai(sel_item["original_item"], menu_str, context=user_text)
        sel_item["category"] = ai_cat
        sel_item["subcategory"] = ai_sub
        user_states[user_id]["state"] = "queue_batch_review"
        _show_batch_items(user_id, batch, len(user_states[user_id]["queue"]))
        return True

    # =========================================================
    # 3. ОБУЧЕНИЕ ОДИНОЧНОЙ ОПЕРАЦИИ (Подтверждение "Да/Нет")
    # =========================================================
    if state == "confirm_category":
        if user_text_lower in ["да", "верно", "ага", "давай", "ок", "yes", "+"]:
            payload = user_states[user_id]["payload"]
            cat = user_states[user_id]["ai_cat"]
            sub = user_states[user_id]["ai_sub"]
            item_name = payload["item"]
            amount = float(payload.get("amount", 0))
            op_type = payload.get("type", "Расход")
            comment = payload.get("comment", "")

            send_vk_message(user_id, "⏳ Запоминаю и записываю в базу...")
            
            # 1. Сохраняем операцию в PostgreSQL
            save_transaction(
                user_id=internal_uid,
                op_type=op_type,
                category=cat,
                subcategory=sub,
                article=item_name,
                amount=amount,
                comment=comment,
                original_text=item_name,
                status='verified'
            )
            
            # 2. Обучаем личный словарь пользователя
            learn_user_word(
                user_id=internal_uid,
                op_type=op_type,
                category=cat,
                subcategory=sub,
                article=item_name,
                synonym=item_name
            )

            send_vk_message(user_id, "✅ Успешно записано и выучено!", get_main_keyboard())
            del user_states[user_id]
            return True

        elif user_text_lower in ["нет", "неверно", "не", "no", "-"]:
            if user_states[user_id]["attempts"] < MAX_ATTEMPTS:
                user_states[user_id]["state"] = "provide_context"
                user_states[user_id]["context_history"] = ""
                send_vk_message(user_id, f"Понял, ошибся 😔 (Попытка {user_states[user_id]['attempts']} из {MAX_ATTEMPTS})\nПодскажи другими словами, что это за операция?", get_cancel_keyboard())
            else:
                # Переход к ручному выбору (начинаем с типа)
                user_states[user_id]["state"] = "tx_manual_type"
                send_vk_message(user_id, "🤷‍♂️ Я сдаюсь. Давайте выберем вручную!\n\nЭто Расход или Доход?", type_keyboard())
            return True
        else:
            send_vk_message(user_id, "Пожалуйста, ответь 'Да' или 'Нет'.", get_yes_no_keyboard())
            return True

    # =========================================================
    # 4. ОБРАБОТКА ПОДСКАЗКИ ОТ ПОЛЬЗОВАТЕЛЯ
    # =========================================================
    if state == "provide_context":
        send_vk_message(user_id, "🧠 Думаю...")
        user_states[user_id]["attempts"] += 1
        payload = user_states[user_id]["payload"]
        op_type = payload.get("type", "Расход")

        if "доход" in user_text_lower or "приход" in user_text_lower:
            op_type = "Доход"
            payload["type"] = "Доход"
        elif "расход" in user_text_lower or "трата" in user_text_lower:
            op_type = "Расход"
            payload["type"] = "Расход"

        # Ищем подсказку в PostgreSQL
        check_res = smart_search_item(internal_uid, user_text, op_type)
        if check_res.get("status") == "FOUND":
            user_states[user_id]["state"] = "confirm_category"
            user_states[user_id]["ai_cat"] = check_res.get("category")
            user_states[user_id]["ai_sub"] = check_res.get("subcategory")
            send_vk_message(user_id, f"Ага! Слово '{user_text}' мне знакомо.\n📂 {check_res.get('category')} -> {check_res.get('subcategory')}\n\nВсё верно?", get_yes_no_keyboard())
            return True

        menu_full = get_full_menu(internal_uid)
        menu = menu_full.get(op_type, {})
        menu_str = "\n".join([f"{c}: {', '.join(subs)}" for c, subs in menu.items()])

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
                # Переход к ручному выбору
                user_states[user_id]["state"] = "tx_manual_type"
                send_vk_message(user_id, "🤷‍♂️ Я сдаюсь. Давайте выберем вручную!\n\nЭто Расход или Доход?", type_keyboard())
        return True

    # =========================================================
    # 5. ИНТЕРАКТИВНЫЙ РУЧНОЙ ВЫБОР (ШАГ 1: ТИП)
    # =========================================================
    if state == "tx_manual_type":
        if "доход" in user_text_lower or "расход" in user_text_lower:
            op_type = "Доход" if "доход" in user_text_lower else "Расход"
            user_states[user_id]["payload"]["type"] = op_type
            
            menu_full = get_full_menu(internal_uid)
            type_menu = menu_full.get(op_type, {})
            cats = sorted(list(type_menu.keys()))
            
            if not cats:
                send_vk_message(user_id, f"Категорий типа '{op_type}' пока нет.", get_main_keyboard())
                del user_states[user_id]
                return True
                
            user_states[user_id]["type_menu"] = type_menu
            user_states[user_id]["cats"] = cats
            user_states[user_id]["state"] = "tx_manual_cat"
            
            msg = f"Выберите КАТЕГОРИЮ ({op_type}):\n\n"
            for i, c in enumerate(cats):
                msg += f"{i+1}. {c}\n"
            send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
            return True
        else:
            send_vk_message(user_id, "Пожалуйста, выберите 'Расход' или 'Доход' кнопками внизу.", type_keyboard())
            return True

    # =========================================================
    # 6. ИНТЕРАКТИВНЫЙ РУЧНОЙ ВЫБОР (ШАГ 2: КАТЕГОРИЯ)
    # =========================================================
    if state == "tx_manual_cat":
        if user_text.isdigit():
            idx = int(user_text) - 1
            cats = user_states[user_id].get("cats", [])
            if 0 <= idx < len(cats):
                sel_cat = cats[idx]
                user_states[user_id]["sel_cat"] = sel_cat
                type_menu = user_states[user_id].get("type_menu", {})
                subs = sorted(list(type_menu.get(sel_cat, [])))
                
                if not subs:
                    subs = ["Другое"]
                    
                user_states[user_id]["subs"] = subs
                user_states[user_id]["state"] = "tx_manual_sub"
                
                msg = f"Категория: {sel_cat}\nВыберите ПОДКАТЕГОРИЮ:\n\n"
                for i, s in enumerate(subs):
                    msg += f"{i+1}. {s}\n"
                send_vk_message(user_id, msg, get_numbered_keyboard(len(subs)))
            return True

    # =========================================================
    # 7. ИНТЕРАКТИВНЫЙ РУЧНОЙ ВЫБОР (ШАГ 3: ПОДКАТЕГОРИЯ И СОХРАНЕНИЕ)
    # =========================================================
    if state == "tx_manual_sub":
        if user_text.isdigit():
            idx = int(user_text) - 1
            subs = user_states[user_id].get("subs", [])
            if 0 <= idx < len(subs):
                sel_sub = subs[idx]
                payload = user_states[user_id]["payload"]
                item_name = payload["item"]
                amount = float(payload.get("amount", 0))
                op_type = payload.get("type", "Расход")
                comment = payload.get("comment", "")
                sel_cat = user_states[user_id]["sel_cat"]

                send_vk_message(user_id, "⏳ Обучаюсь и записываю в базу...")
                
                # 1. Записываем операцию в PostgreSQL
                save_transaction(
                    user_id=internal_uid,
                    op_type=op_type,
                    category=sel_cat,
                    subcategory=sel_sub,
                    article=item_name,
                    amount=amount,
                    comment=comment,
                    original_text=item_name,
                    status='verified'
                )
                
                # 2. Обучаем личный словарь пользователя в PostgreSQL
                learn_user_word(
                    user_id=internal_uid,
                    op_type=op_type,
                    category=sel_cat,
                    subcategory=sel_sub,
                    article=item_name,
                    synonym=item_name
                )

                send_vk_message(user_id, f"✅ Успешно! Я запомнил, что '{item_name}' — это {sel_cat} -> {sel_sub}.", get_main_keyboard())
                del user_states[user_id]
            return True

    return False
