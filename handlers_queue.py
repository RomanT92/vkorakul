# -*- coding: utf-8 -*-
import re
from keyboards import (
    get_main_keyboard,
    get_yes_no_keyboard,
    get_cancel_keyboard,
    get_queue_review_keyboard,
    get_queue_item_action_keyboard,
    get_numbered_keyboard,
    type_keyboard
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
    get_full_menu,
    get_unverified_transactions,
    resolve_unverified_item
)
from db.transactions import delete_unverified_by_text, skip_unverified_by_text

BATCH_SIZE = 7

def _format_amt(amount):
    """Форматирует число без экспоненциальной записи."""
    try:
        val = float(amount)
        if val.is_integer():
            return f"{int(val):,}".replace(",", " ")
        return f"{val:,.2f}".replace(",", " ")
    except Exception:
        return str(amount)

def _show_batch_items(user_id, batch, total_left, show_apply_all=False):
    """Выводит пронумерованный список пакета операций с кнопками управления."""
    if not batch:
        return

    msg = f"📋 Пакет операций (осталось распределить: {total_left + len(batch)}):\n\n"
    for i, item in enumerate(batch):
        amt_str = _format_amt(item['amount'])
        cat = item.get('category', '?')
        sub = item.get('subcategory', '?')
        msg += f"{i+1}. {item['original_item']} ({item['count']} шт., ~{amt_str} руб.)\n"
        msg += f"   📂 {cat} -> {sub}\n\n"

    msg += "👉 Если всё верно — жмите «💾 Сохранить пакет».\n"
    msg += "👉 Если здесь мусор (заголовки выписки) — скажите «Всё в мусор», «Удали 2 и 3» или нажмите «🗑 Удалить мусор».\n"
    if show_apply_all:
        msg += "👉 Нажмите «⚡ Применить для всех оставшихся», чтобы продублировать категорию.\n"
    msg += "👉 Для изменения категории — отправьте НОМЕР позиции или скажите (например: «это всё подарок»)."
    send_vk_message(user_id, msg, get_queue_review_keyboard(len(batch), show_apply_all=show_apply_all, show_back=True))

def _process_next_batch(user_id, user_states):
    """Запускает следующий пакет, автоматически фильтруя уже выученные статьи."""
    if user_id not in user_states:
        return

    state_data = user_states[user_id]
    internal_uid = get_or_create_user(user_id)
    queue = state_data.get("queue", [])

    filtered_queue = []
    for item in queue:
        match = smart_search_item(internal_uid, item["original_item"], op_type=item.get("type"))
        # Если слово уже имеет точную подкатегорию — мгновенно разрешаем без лишних вопросов!
        if match["status"] == "FOUND" and match.get("subcategory") not in ["Требует проверки", ""]:
            resolve_unverified_item(internal_uid, item["original_item"], match["type"], match["category"], match["subcategory"])
        else:
            filtered_queue.append(item)

    if not filtered_queue:
        send_vk_message(user_id, "🎉 Все операции успешно распределены! Журнал чист.", get_main_keyboard(user_id))
        if user_id in user_states:
            del user_states[user_id]
        return

    batch = filtered_queue[:BATCH_SIZE]
    state_data["queue"] = filtered_queue[BATCH_SIZE:]
    menu = state_data["menu"]
    menu_str = "\n".join([f"{c}: {', '.join(subs)}" for c, subs in menu.items()])

    state_data.pop("last_category", None)
    state_data.pop("last_subcategory", None)
    state_data.pop("last_edit_idx", None)

    send_vk_message(user_id, f"🧠 Анализирую {len(batch)} операций...", get_cancel_keyboard(show_back=False))
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
    _show_batch_items(user_id, batch, len(state_data["queue"]), show_apply_all=False)

def handle_queue_and_learning(user_id, user_text, user_text_lower, state, user_states, MAX_ATTEMPTS):
    internal_uid = get_or_create_user(user_id)

    # =========================================================
    # 1. ЗАПУСК РАЗБОРА ОПЕРАЦИЙ
    # =========================================================
    triggers = [
        "разобрать операции", "разобрать завалы", "разобрать", "завалы", "импорт статистики прошлого"
    ]
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

        unverified_grouped = list(unique_items.values())
        full_menu = get_full_menu(internal_uid)
        combined_menu = {}
        for t in ["Расход", "Доход"]:
            for c, s in full_menu.get(t, {}).items():
                combined_menu[c] = list(s.keys()) if isinstance(s, dict) else s

        user_states[user_id] = {
            "state": "queue_process",
            "queue": unverified_grouped,
            "menu": combined_menu
        }
        _process_next_batch(user_id, user_states)
        return True

    # =========================================================
    # ОБРАБОТКА «НАЗАД» В ОЧЕРЕДИ
    # =========================================================
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

    # =========================================================
    # 2. РЕВЬЮ ПАКЕТА ОПЕРАЦИЙ
    # =========================================================
    if state == "queue_batch_review":
        state_data = user_states[user_id]
        batch = state_data.get("current_batch", [])

        if not batch:
            _process_next_batch(user_id, user_states)
            return True

        # СТРОГАЯ ПРОВЕРКА НА СОХРАНЕНИЕ ПАКЕТА (только явные команды сохранения)
        save_triggers = ["сохранить пакет", "сохрани пакет", "сохранить", "готово", "сохрани"]
        if any(trig == user_text_lower or user_text_lower.startswith("сохранить") for trig in save_triggers):
            send_vk_message(user_id, "⏳ Сохраняю и каскадно обновляю базу...", get_cancel_keyboard(show_back=False))
            saved_count = 0
            for item in batch:
                # ВАЖНО: сохраняем, если подкатегория НЕ "Требует проверки"
                if item.get("subcategory") != "Требует проверки":
                    resolve_unverified_item(
                        user_id=internal_uid,
                        original_item=item["original_item"],
                        op_type=item.get("type", "Расход"),
                        category=item.get("category", "Другое"),
                        subcategory=item.get("subcategory", "Другое")
                    )
                    saved_count += 1
            send_vk_message(user_id, f"✅ Успешно распределено {saved_count} статей!")
            _process_next_batch(user_id, user_states)
            return True

        # --- УДАЛЕНИЕ ВСЕГО ПАКЕТА В МУСОР ---
        all_trash_triggers = [
            "все эти операции в мусор", "все в мусор", "всё в мусор", "в мусор всё",
            "в мусор все", "это всё мусор", "это все мусор", "в корзину все", "в корзину всё",
            "удали всё", "удали все", "стереть всё", "очисти пакет", "всё в корзину", "все в корзину"
        ]
        if any(trig in user_text_lower for trig in all_trash_triggers):
            user_states[user_id]["state"] = "confirm_delete_all_batch_trash"
            send_vk_message(
                user_id,
                f"⚠️ Вы уверены, что хотите отправить ВСЕ {len(batch)} позиций текущего пакета в мусор?\n"
                f"Они будут удалены из журнала и больше никогда не появятся.",
                get_yes_no_keyboard(show_back=True)
            )
            return True

        # --- УДАЛЕНИЕ МУСОРА ПО КНОПКЕ («🗑 Удалить мусор») ---
        if "удалить мусор" in user_text_lower or "удали мусор" in user_text_lower:
            user_states[user_id]["state"] = "queue_select_trash_numbers"
            send_vk_message(
                user_id,
                "🗑 Напишите или отправьте номера позиций, которые нужно БЕЗВОЗВРАТНО УДАЛИТЬ как мусор (например: «1, 3» или «2»):",
                get_numbered_keyboard(len(batch), show_back=True)
            )
            return True

        # --- КОМАНДЫ С НОМЕРАМИ: «удали 1 и 3», «в мусор 2, 4», «мусор 3» ---
        if any(w in user_text_lower for w in ["удали", "мусор", "исключи", "выкинь", "убери"]):
            raw_nums = re.findall(r'\d+', user_text)
            del_indices = [int(n) - 1 for n in raw_nums if 0 <= int(n) - 1 < len(batch)]
            if del_indices:
                total_deleted = 0
                del_names = []
                for idx in sorted(del_indices, reverse=True):
                    it = batch.pop(idx)
                    del_names.append(it["original_item"])
                    total_deleted += delete_unverified_by_text(internal_uid, it["original_item"], it.get("type"))
                send_vk_message(
                    user_id,
                    f"🗑 Удалено {len(del_names)} мусорных позиций ({total_deleted} транзакций из базы)!\n"
                    f"Они занесены в чёрный список."
                )
                if not batch:
                    _process_next_batch(user_id, user_states)
                else:
                    _show_batch_items(user_id, batch, len(state_data["queue"]), show_apply_all=False)
                return True

        # --- ПРИМЕНИТЬ ДЛЯ ВСЕХ ОСТАВШИХСЯ ---
        elif any(phrase in user_text_lower for phrase in ["применить для всех", "применить ко всем"]):
            last_cat = state_data.get("last_category")
            last_sub = state_data.get("last_subcategory")
            start_idx = state_data.get("last_edit_idx", 0) + 1
            if not last_cat or not last_sub:
                send_vk_message(user_id, "⚠️ Сначала укажите категорию для какой-нибудь одной операции из списка.")
                return True
            applied_count = 0
            for i in range(start_idx, len(batch)):
                batch[i]["category"] = last_cat
                batch[i]["subcategory"] = last_sub
                applied_count += 1
            if applied_count == 0:
                for item in batch:
                    item["category"] = last_cat
                    item["subcategory"] = last_sub
                applied_count = len(batch)
            send_vk_message(user_id, f"⚡ Категория «{last_cat} -> {last_sub}» применена к {applied_count} операциям!")
            _show_batch_items(user_id, batch, len(state_data["queue"]), show_apply_all=True)
            return True

        # --- ВЫБОР ПОЗИЦИИ ПО НОМЕРУ ---
        elif user_text.isdigit():
            idx = int(user_text) - 1
            if 0 <= idx < len(batch):
                state_data["edit_idx"] = idx
                sel_item = batch[idx]
                user_states[user_id]["state"] = "queue_item_action_select"
                amt_str = _format_amt(sel_item['amount'])
                msg = (
                    f"📌 **Позиция №{idx+1}: «{sel_item['original_item']}»**\n"
                    f"• Повторений: {sel_item['count']} шт.\n"
                    f"• Примерная сумма: {amt_str} руб.\n"
                    f"• Текущая категория: {sel_item.get('category')} -> {sel_item.get('subcategory')}\n\n"
                    f"Что сделать с этой позицией?"
                )
                send_vk_message(user_id, msg, get_queue_item_action_keyboard())
                return True

    # =========================================================
    # 2.0 ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ ВСЕХ ОПЕРАЦИЙ ПАКЕТА В МУСОР
    # =========================================================
    if state == "confirm_delete_all_batch_trash":
        if any(w in user_text_lower for w in ["да", "верно", "ага", "yes", "+", "в мусор", "удалить"]):
            state_data = user_states[user_id]
            batch = state_data["current_batch"]
            total_del = 0
            for it in batch:
                total_del += delete_unverified_by_text(internal_uid, it["original_item"], it.get("type"))
            send_vk_message(user_id, f"🗑 Все {len(batch)} позиций ({total_del} транзакций) отправлены в мусор и занесены в чёрный список!")
            state_data["current_batch"] = []
            _process_next_batch(user_id, user_states)
            return True
        elif any(w in user_text_lower for w in ["нет", "отмена", "не", "назад"]):
            user_states[user_id]["state"] = "queue_batch_review"
            send_vk_message(user_id, "Удаление отменено.")
            _show_batch_items(user_id, user_states[user_id]["current_batch"], len(user_states[user_id]["queue"]), show_apply_all=False)
            return True

    # =========================================================
    # 2.0.1 ДЕЙСТВИЕ НАД КОНКРЕТНОЙ ПОЗИЦИЕЙ В ОЧЕРЕДИ
    # =========================================================
    if state == "queue_item_action_select":
        state_data = user_states[user_id]
        idx = state_data["edit_idx"]
        batch = state_data["current_batch"]
        sel_item = batch[idx]

        if "категори" in user_text_lower or "изменить" in user_text_lower:
            state_data["state"] = "queue_batch_edit_hint"
            send_vk_message(
                user_id,
                f"✏️ Введите правильную категорию или статью для «{sel_item['original_item']}»:",
                get_cancel_keyboard(show_back=True)
            )
            return True
        elif "мусор" in user_text_lower or "удалить" in user_text_lower:
            batch.pop(idx)
            cnt = delete_unverified_by_text(internal_uid, sel_item["original_item"], sel_item.get("type"))
            send_vk_message(user_id, f"🗑 «{sel_item['original_item']}» удалено ({cnt} транзакций стерто из базы) и занесено в Чёрный список!")
            if not batch:
                _process_next_batch(user_id, user_states)
            else:
                state_data["state"] = "queue_batch_review"
                _show_batch_items(user_id, batch, len(state_data["queue"]), show_apply_all=False)
            return True
        elif "пропустить" in user_text_lower:
            batch.pop(idx)
            skip_unverified_by_text(internal_uid, sel_item["original_item"])
            send_vk_message(user_id, f"⏩ Позиция «{sel_item['original_item']}» пропущена.")
            if not batch:
                _process_next_batch(user_id, user_states)
            else:
                state_data["state"] = "queue_batch_review"
                _show_batch_items(user_id, batch, len(state_data["queue"]), show_apply_all=False)
            return True

    # =========================================================
    # 2.0.2 ВЫБОР НОМЕРОВ МУСОРА ДЛЯ МАССОВОГО УДАЛЕНИЯ
    # =========================================================
    if state == "queue_select_trash_numbers":
        state_data = user_states[user_id]
        batch = state_data["current_batch"]
        raw_nums = re.findall(r'\d+', user_text)
        del_indices = [int(n) - 1 for n in raw_nums if 0 <= int(n) - 1 < len(batch)]
        if not del_indices:
            send_vk_message(user_id, "⚠️ Номера не распознаны. Укажите номера цифрами (например: 1, 2, 4):", get_numbered_keyboard(len(batch), show_back=True))
            return True

        total_del = 0
        names = []
        for idx in sorted(del_indices, reverse=True):
            it = batch.pop(idx)
            names.append(it["original_item"])
            total_del += delete_unverified_by_text(internal_uid, it["original_item"], it.get("type"))

        send_vk_message(user_id, f"🗑 Успешно стерто {len(names)} позиций ({total_del} операций) из журнала!")
        if not batch:
            _process_next_batch(user_id, user_states)
        else:
            state_data["state"] = "queue_batch_review"
            _show_batch_items(user_id, batch, len(state_data["queue"]), show_apply_all=False)
        return True

    # =========================================================
    # 2.1 ВВОД ПОДСКАЗКИ ДЛЯ КОНКРЕТНОЙ ОПЕРАЦИИ
    # =========================================================
    if state == "queue_batch_edit_hint":
        state_data = user_states[user_id]
        idx = state_data["edit_idx"]
        batch = state_data["current_batch"]
        sel_item = batch[idx]
        from handlers_voice_commands import _apply_category_to_item

        menu_full = get_full_menu(internal_uid)
        found_cat, found_sub = _apply_category_to_item(internal_uid, sel_item, user_text, menu_full, state)

        state_data["last_category"] = found_cat
        state_data["last_subcategory"] = found_sub
        state_data["last_edit_idx"] = idx
        state_data["state"] = "queue_batch_review"
        _show_batch_items(user_id, batch, len(state_data["queue"]), show_apply_all=True)
        return True

    # =========================================================
    # 3. ОДИНОЧНОЕ ОБУЧЕНИЕ: ПОДТВЕРЖДЕНИЕ "ДА / НЕТ"
    # =========================================================
    if state == "confirm_category":
        if any(w in user_text_lower for w in ["да", "верно", "ага", "давай", "ок", "yes", "+"]):
            payload = user_states[user_id]["payload"]
            cat = user_states[user_id]["ai_cat"]
            sub = user_states[user_id]["ai_sub"]
            item_name = payload["item"]
            amount = float(payload.get("amount", 0))
            op_type = payload.get("type", "Расход")
            comment = payload.get("comment", "")

            send_vk_message(user_id, "⏳ Запоминаю и записываю в базу...")
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
            learn_user_word(
                user_id=internal_uid,
                op_type=op_type,
                category=cat,
                subcategory=sub,
                article=item_name,
                synonym=item_name
            )
            send_vk_message(user_id, f"✅ Успешно выучено и записано!\n📂 {cat} -> {sub}", get_main_keyboard(user_id))
            del user_states[user_id]
            return True
        elif any(w in user_text_lower for w in ["нет", "неверно", "не", "no", "-"]):
            if user_states[user_id]["attempts"] < MAX_ATTEMPTS:
                user_states[user_id]["state"] = "provide_context"
                user_states[user_id]["context_history"] = ""
                send_vk_message(user_id, f"Понял, ошибся 😔 (Попытка {user_states[user_id]['attempts']} из {MAX_ATTEMPTS})\nПодскажи другими словами, к чему относится «{user_states[user_id]['payload']['item']}»?", get_cancel_keyboard(show_back=True))
            else:
                user_states[user_id]["state"] = "tx_manual_type"
                send_vk_message(user_id, "🤷‍♂️ Я сдаюсь. Давайте выберем вручную!\n\nЭто Расход или Доход?", type_keyboard(show_back=True))
            return True
        else:
            send_vk_message(user_id, "Пожалуйста, ответьте «✅ Да» или «❌ Нет».", get_yes_no_keyboard(show_back=True))
            return True

    # =========================================================
    # 4. ОБРАБОТКА ПОДСКАЗКИ ОТ ПОЛЬЗОВАТЕЛЯ (ОДИНОЧНЫЙ РЕЖИМ)
    # =========================================================
    if state == "provide_context":
        user_states[user_id]["attempts"] += 1
        payload = user_states[user_id]["payload"]
        if "доход" in user_text_lower or "приход" in user_text_lower:
            payload["type"] = "Доход"
        elif "расход" in user_text_lower or "трата" in user_text_lower:
            payload["type"] = "Расход"

        op_type = payload.get("type", "Расход")
        check_res = smart_search_item(internal_uid, user_text, op_type=op_type)
        if check_res.get("status") != "FOUND":
            check_res = smart_search_item(internal_uid, user_text, op_type=None)

        if check_res.get("status") == "FOUND":
            user_states[user_id]["state"] = "confirm_category"
            user_states[user_id]["ai_cat"] = check_res.get("category")
            user_states[user_id]["ai_sub"] = check_res.get("subcategory")
            if check_res.get("type"):
                payload["type"] = check_res["type"]
            send_vk_message(user_id, f"Ага! «{user_text}» — это знакомая категория:\n📂 {check_res.get('category')} -> {check_res.get('subcategory')}\n\nПривязать «{payload['item']}» сюда?", get_yes_no_keyboard(show_back=True))
            return True

        send_vk_message(user_id, "🧠 Думаю...")
        menu_full = get_full_menu(internal_uid)
        type_menu = menu_full.get(op_type, {})
        menu_str = f"[{op_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])
        ai_cat, ai_sub = categorize_with_ai(payload["item"], menu_str, context=user_text)

        valid_cat = ai_cat in type_menu and ai_sub in (type_menu[ai_cat].keys() if isinstance(type_menu[ai_cat], dict) else type_menu[ai_cat])
        if valid_cat and ai_sub != "Требует проверки":
            user_states[user_id]["state"] = "confirm_category"
            user_states[user_id]["ai_cat"] = ai_cat
            user_states[user_id]["ai_sub"] = ai_sub
            send_vk_message(user_id, f"Ага! С учетом подсказки, думаю «{payload['item']}» относится к:\n📂 {ai_cat} -> {ai_sub}\n\nВсё верно?", get_yes_no_keyboard(show_back=True))
        else:
            if user_states[user_id]["attempts"] < MAX_ATTEMPTS:
                send_vk_message(user_id, f"Всё равно не могу сообразить 🤔 (Попытка {user_states[user_id]['attempts']} из {MAX_ATTEMPTS})\nПопробуй назвать точную категорию из твоего меню?", get_cancel_keyboard(show_back=True))
            else:
                user_states[user_id]["state"] = "tx_manual_type"
                send_vk_message(user_id, "🤷‍♂️ Я сдаюсь. Давайте выберем вручную!\n\nЭто Расход или Доход?", type_keyboard(show_back=True))
        return True

    # =========================================================
    # 5. ИНТЕРАКТИВНЫЙ РУЧНОЙ ВЫБОР (ТИП -> КАТЕГОРИЯ -> ПОДКАТЕГОРИЯ)
    # =========================================================
    if state == "tx_manual_type":
        if "доход" in user_text_lower or "расход" in user_text_lower:
            op_type = "Доход" if "доход" in user_text_lower else "Расход"
            user_states[user_id]["payload"]["type"] = op_type
            menu_full = get_full_menu(internal_uid)
            type_menu = menu_full.get(op_type, {})
            cats = sorted(list(type_menu.keys()))
            if not cats:
                send_vk_message(user_id, f"Категорий типа '{op_type}' пока нет.", get_main_keyboard(user_id))
                del user_states[user_id]
                return True
            user_states[user_id]["type_menu"] = type_menu
            user_states[user_id]["cats"] = cats
            user_states[user_id]["state"] = "tx_manual_cat"
            msg = f"Выберите КАТЕГОРИЮ ({op_type}):\n\n"
            for i, c in enumerate(cats):
                msg += f"{i+1}. {c}\n"
            send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))
            return True
        else:
            send_vk_message(user_id, "Пожалуйста, выберите «📉 Расход» или «📈 Доход» кнопками внизу.", type_keyboard(show_back=True))
            return True

    if state == "tx_manual_cat":
        if user_text.isdigit():
            idx = int(user_text) - 1
            cats = user_states[user_id].get("cats", [])
            if 0 <= idx < len(cats):
                sel_cat = cats[idx]
                user_states[user_id]["sel_cat"] = sel_cat
                type_menu = user_states[user_id].get("type_menu", {})
                raw_subs = type_menu.get(sel_cat, [])
                subs = sorted(list(raw_subs.keys() if isinstance(raw_subs, dict) else raw_subs))
                if not subs:
                    subs = ["Другое"]
                user_states[user_id]["subs"] = subs
                user_states[user_id]["state"] = "tx_manual_sub"
                msg = f"Категория: {sel_cat}\nВыберите ПОДКАТЕГОРИЮ:\n\n"
                for i, s in enumerate(subs):
                    msg += f"{i+1}. {s}\n"
                send_vk_message(user_id, msg, get_numbered_keyboard(len(subs), show_back=True))
                return True

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
                learn_user_word(
                    user_id=internal_uid,
                    op_type=op_type,
                    category=sel_cat,
                    subcategory=sel_sub,
                    article=item_name,
                    synonym=item_name
                )
                send_vk_message(user_id, f"✅ Успешно! Я запомнил, что «{item_name}» — это {sel_cat} -> {sel_sub}.", get_main_keyboard(user_id))
                del user_states[user_id]
                return True

    return False
