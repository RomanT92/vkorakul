# -*- coding: utf-8 -*-
import re
from keyboards import (
    get_main_keyboard,
    get_yes_no_keyboard,
    get_cancel_keyboard,
    get_queue_review_keyboard,
    get_queue_item_action_keyboard,
    get_numbered_keyboard
)
from services import send_vk_message, categorize_batch_with_ai
from db import (
    get_or_create_user,
    smart_search_item,
    get_full_menu,
    get_unverified_transactions,
    resolve_unverified_item
)
from db.transactions import delete_unverified_by_text, skip_unverified_by_text

BATCH_SIZE = 7

def _format_amt(amount):
    try:
        val = float(amount)
        if val.is_integer():
            return f"{int(val):,}".replace(",", " ")
        return f"{val:,.2f}".replace(",", " ")
    except Exception:
        return str(amount)

def _validate_ai_category(menu_full, op_type, cat, sub):
    type_menu = menu_full.get(op_type, {})
    if cat not in type_menu:
        matched_cat = next((c for c in type_menu if c.lower() == str(cat).lower().strip()), None)
        if not matched_cat:
            return None, None
        cat = matched_cat

    subs = type_menu[cat]
    sub_list = list(subs.keys()) if isinstance(subs, dict) else subs
    if sub not in sub_list:
        matched_sub = next((s for s in sub_list if s.lower() == str(sub).lower().strip()), None)
        if matched_sub:
            return cat, matched_sub
        default_sub = next((s for s in sub_list if "другое" in s.lower()), None)
        if default_sub:
            return cat, default_sub
        return cat, (sub_list[0] if sub_list else "Разное")

    return cat, sub

def _find_matching_article(menu_full, op_type, cat, sub, word):
    clean_w = word.lower().strip()
    sub_articles = menu_full.get(op_type, {}).get(cat, {}).get(sub, [])
    if not sub_articles:
        return word.capitalize()
    for art in sub_articles:
        if art.lower() == clean_w or (len(clean_w) >= 4 and clean_w in art.lower()):
            return art
    return word.capitalize()

def _show_batch_items(user_id, batch, total_left, show_apply_all=False):
    if not batch:
        return
    msg = f"📋 Пакет операций (осталось распределить: {total_left + len(batch)}):\n\n"
    for i, item in enumerate(batch):
        amt_str = _format_amt(item['amount'])
        cat = item.get('category', '?')
        sub = item.get('subcategory', '?')
        art = item.get('article', item['original_item'])
        msg += f"{i+1}. {item['original_item']} ({item['count']} шт., ~{amt_str} руб.)\n"
        msg += f"   📂 {cat} -> {sub} (статья: {art})\n\n"

    msg += "👉 Если всё верно — жмите «💾 Сохранить пакет».\n"
    msg += "👉 Если здесь мусор — скажите «Всё в мусор», «Удали 2 и 3» или нажмите «🗑 Удалить мусор».\n"
    if show_apply_all:
        msg += "👉 Нажмите «⚡ Применить для всех оставшихся», чтобы продублировать категорию.\n"
    msg += "👉 Для изменения категории — отправьте НОМЕР позиции или подсказку."
    send_vk_message(user_id, msg, get_queue_review_keyboard(len(batch), show_apply_all=show_apply_all, show_back=True))

def _process_next_batch(user_id, user_states):
    if user_id not in user_states:
        return

    state_data = user_states[user_id]
    internal_uid = get_or_create_user(user_id)
    queue = state_data.get("queue", [])

    filtered_queue = []
    for item in queue:
        match = smart_search_item(internal_uid, item["original_item"], op_type=item.get("type"))
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
    state_data.pop("last_article", None)
    state_data.pop("last_edit_idx", None)

    send_vk_message(user_id, f"🧠 Анализирую {len(batch)} операций...", get_cancel_keyboard(show_back=False))
    ai_results = categorize_batch_with_ai(batch, menu_str)
    menu_full = get_full_menu(internal_uid)

    for item in batch:
        raw_c, raw_s = "Разное", "Требует проверки"
        for res in ai_results:
            if res.get("original_item") == item["original_item"]:
                raw_c = res.get("category", "Разное")
                raw_s = res.get("subcategory", "Требует проверки")
                break
        v_c, v_s = _validate_ai_category(menu_full, item.get("type", "Расход"), raw_c, raw_s)
        final_c = v_c or "Разное"
        final_s = v_s or "Требует проверки"

        item["category"] = final_c
        item["subcategory"] = final_s
        item["article"] = _find_matching_article(menu_full, item.get("type", "Расход"), final_c, final_s, item["original_item"])

    state_data["current_batch"] = batch
    state_data["state"] = "queue_batch_review"
    _show_batch_items(user_id, batch, len(state_data["queue"]), show_apply_all=False)

def handle_queue_batch(user_id, internal_uid, user_text, user_text_lower, state, user_states):
    """Обработчик интерактивных действий с пакетом в очереди разбора."""
    if state == "queue_batch_review":
        state_data = user_states[user_id]
        batch = state_data.get("current_batch", [])
        if not batch:
            _process_next_batch(user_id, user_states)
            return True

        save_triggers = ["сохранить пакет", "сохрани пакет", "сохранить", "готово", "сохрани"]
        if any(trig == user_text_lower or user_text_lower.startswith("сохранить") for trig in save_triggers):
            send_vk_message(user_id, "⏳ Сохраняю и обновляю базу...", get_cancel_keyboard(show_back=False))
            saved_count = 0
            for item in batch:
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

        if "удалить мусор" in user_text_lower or "удали мусор" in user_text_lower:
            user_states[user_id]["state"] = "queue_select_trash_numbers"
            send_vk_message(
                user_id,
                "🗑 Напишите или отправьте номера позиций, которые нужно БЕЗВОЗВРАТНО УДАЛИТЬ как мусор (например: «1, 3» или «2»):",
                get_numbered_keyboard(len(batch), show_back=True)
            )
            return True

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

        elif any(phrase in user_text_lower for phrase in ["применить для всех", "применить ко всем"]):
            last_cat = state_data.get("last_category")
            last_sub = state_data.get("last_subcategory")
            last_art = state_data.get("last_article")
            start_idx = state_data.get("last_edit_idx", 0) + 1
            if not last_cat or not last_sub:
                send_vk_message(user_id, "⚠️ Сначала укажите категорию для какой-нибудь одной операции из списка.")
                return True
            applied_count = 0
            for i in range(start_idx, len(batch)):
                batch[i]["category"] = last_cat
                batch[i]["subcategory"] = last_sub
                if last_art:
                    batch[i]["article"] = last_art
                applied_count += 1
            if applied_count == 0:
                for item in batch:
                    item["category"] = last_cat
                    item["subcategory"] = last_sub
                    if last_art:
                        item["article"] = last_art
                applied_count = len(batch)
            send_vk_message(user_id, f"⚡ Категория «{last_cat} -> {last_sub}» применена к {applied_count} операциям!")
            _show_batch_items(user_id, batch, len(state_data["queue"]), show_apply_all=True)
            return True

        elif user_text.isdigit():
            idx = int(user_text) - 1
            if 0 <= idx < len(batch):
                state_data["edit_idx"] = idx
                sel_item = batch[idx]
                user_states[user_id]["state"] = "queue_item_action_select"
                amt_str = _format_amt(sel_item['amount'])
                art_name = sel_item.get('article', sel_item['original_item'])
                msg = (
                    f"📌 **Позиция №{idx+1}: «{sel_item['original_item']}»**\n"
                    f"• Повторений: {sel_item['count']} шт.\n"
                    f"• Примерная сумма: {amt_str} руб.\n"
                    f"• Текущая привязка: {sel_item.get('category')} -> {sel_item.get('subcategory')} (статья: «{art_name}»)\n\n"
                    f"Что сделать с этой позицией?"
                )
                send_vk_message(user_id, msg, get_queue_item_action_keyboard())
                return True

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

    if state == "queue_batch_edit_hint":
        state_data = user_states[user_id]
        idx = state_data["edit_idx"]
        batch = state_data["current_batch"]
        sel_item = batch[idx]
        from handlers_voice_commands import _apply_category_to_item

        menu_full = get_full_menu(internal_uid)
        found_cat, found_sub = _apply_category_to_item(internal_uid, sel_item, user_text, menu_full, state)
        v_c, v_s = _validate_ai_category(menu_full, sel_item.get("type", "Расход"), found_cat, found_sub)
        final_c = v_c or "Разное"
        final_s = v_s or "Требует проверки"
        canon_art = _find_matching_article(menu_full, sel_item.get("type", "Расход"), final_c, final_s, sel_item["original_item"])

        sel_item["category"] = final_c
        sel_item["subcategory"] = final_s
        sel_item["article"] = canon_art

        state_data["last_category"] = final_c
        state_data["last_subcategory"] = final_s
        state_data["last_article"] = canon_art
        state_data["last_edit_idx"] = idx
        state_data["state"] = "queue_batch_review"
        _show_batch_items(user_id, batch, len(state_data["queue"]), show_apply_all=True)
        return True

    return False
