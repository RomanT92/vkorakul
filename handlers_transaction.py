# -*- coding: utf-8 -*-
import json
import re
import difflib

from keyboards import (
    get_main_keyboard,
    get_yes_no_keyboard,
    get_cancel_keyboard,
    type_keyboard,
    get_numbered_keyboard,
    get_multi_tx_review_keyboard,
    get_tx_action_keyboard
)
from services import (
    send_vk_message,
    extract_transaction_with_ai,
    categorize_with_ai
)
from db import (
    get_or_create_user,
    smart_search_item,
    save_transaction,
    learn_user_word,
    get_full_menu,
    db_rename_category,
    db_rename_subcategory,
    db_rename_article,
    db_delete_entity,
    db_move_entity,
    get_user_history,
    delete_transaction_by_id,
    delete_all_user_transactions,
    get_last_transaction,
    update_transaction_amount,
    update_transaction_category
)

INCOME_KEYWORDS = [
    "доход", "приход", "поступление", "поступило", "пополнил", "пополнение",
    "зарплата", "зп", "аванс", "премия", "подарили", "подарок мне",
    "вернули долг", "отдали долг", "кэшбэк", "проценты", "дивиденды",
    "выручка", "оплата от клиента", "зачисление"
]

def detect_operation_type(user_text="", raw_type="Расход", item_name="", comment=""):
    """
    Определяет тип операции и возвращает кортеж: (op_type, is_explicit_income)
    Если пользователь явно указал признак дохода -> (Доход, True).
    """
    check_str = f"{user_text} {raw_type} {item_name} {comment}".lower()
    for kw in INCOME_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', check_str) or kw in check_str:
            return "Доход", True
    if str(raw_type).strip().lower() in ["доход", "приход", "income"]:
        return "Доход", True
    return "Расход", False

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

def clean_fallback_item(user_text):
    """Вырезает из текста пользователя сумму и служебные слова, оставляя реальное название."""
    text = re.sub(r'\d+([.,]\d+)?', '', user_text).strip()
    stop_words = ["руб", "рублей", "р", "к", "k", "приход", "доход", "расход", "трата", "купил", "оплатил"]
    words = [w for w in text.split() if w.lower() not in stop_words]
    clean = " ".join(words).strip()
    return clean if clean else "Операция"

def _clean_json_string(text):
    """Очищает строку от маркдауна ```json ... ``` если ИИ его добавил"""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:-3].strip()
    elif text.startswith("```"):
        text = text[3:-3].strip()
    return text

def _extract_json_data(text):
    """Надежно извлекает JSON объект или массив из текста с помощью регулярных выражений."""
    if not text:
        return None
    match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
    if match:
        raw_json = match.group(0).strip()
        try:
            return json.loads(raw_json)
        except Exception:
            pass
    return None

def _show_multi_tx_items(user_id, items, show_apply_all=False):
    """Выводит красивый пронумерованный список распознанных операций."""
    msg = f"📋 Распознанные операции (всего {len(items)}):\n\n"
    for i, item in enumerate(items):
        item_name = item.get("item", "Операция")
        amount = item.get("amount", 0)
        op_type = item.get("type", "Расход")
        cat = item.get("category", "?")
        sub = item.get("subcategory", "?")
        comm = f" ({item['comment']})" if item.get("comment") else ""
        type_icon = "📉" if op_type == "Расход" else "📈"
        msg += f"{i+1}. {item_name} — {amount} руб. {type_icon}{comm}\n"
        msg += f"   📂 {cat} -> {sub}\n\n"

    msg += "Если всё верно, жмите «✅ Готово».\n"
    if show_apply_all:
        msg += "Нажмите «⚡ Применить для всех оставшихся», чтобы продублировать категорию.\n"
    msg += "Если хотите изменить категорию статьи — отправьте её НОМЕР."
    send_vk_message(user_id, msg, get_multi_tx_review_keyboard(len(items), show_apply_all=show_apply_all, show_back=True))

def _save_items_batch(internal_uid, items):
    """Сохраняет пачку операций в БД и возвращает статистику."""
    saved_count = 0
    needs_review_count = 0

    for item in items:
        cat = item.get("category", "Разное")
        sub = item.get("subcategory", "Требует проверки")
        art = item.get("item", "Операция")
        amount = float(item.get("amount", 0))
        op_type = item.get("type", "Расход")
        comment = item.get("comment", "")

        if cat == "Разное" or sub == "Требует проверки":
            op_status = 'needs_review'
            needs_review_count += 1
        else:
            op_status = 'verified'

        ok = save_transaction(
            user_id=internal_uid,
            op_type=op_type,
            category=cat,
            subcategory=sub,
            article=art,
            amount=amount,
            comment=comment,
            original_text=art,
            status=op_status
        )
        if ok:
            saved_count += 1
            if op_status == 'verified':
                learn_user_word(internal_uid, op_type, cat, sub, art, art)

    return saved_count, needs_review_count

def _show_history_screen(user_id, items, title_period, total_expense, total_income, total_count=None):
    """Выводит список истории операций с клавиатурой выбора номера."""
    msg = f"📜 История операций ({title_period}):\n\n"
    for i, it in enumerate(items):
        t_icon = "📈" if it["type"] == "Доход" else "📉"
        date_str = it["date"].strftime("%d.%m %H:%M") if it.get("date") else ""
        comm = f" ({it['comment']})" if it.get("comment") else ""
        msg += f"{i+1}. {t_icon} {it['article']} — {it['amount']:g} руб. [{date_str}]{comm}\n"
        msg += f"   📂 {it['category']} -> {it['subcategory']}\n\n"

    msg += (
        f"💰 Итого за период:\n"
        f"• Расходы: {total_expense:g} руб.\n"
        f"• Доходы: {total_income:g} руб.\n"
    )
    if total_count and total_count > len(items):
        msg += f"ℹ️ Показано {len(items)} из {total_count} последних операций.\n"

    msg += "\n👉 Чтобы изменить сумму, категорию или удалить операцию — нажмите НОМЕР операции или скажите (например: «Удали вторую и третью»):"
    send_vk_message(user_id, msg, get_numbered_keyboard(min(len(items), 15), show_back=True))

def _match_category_tree(menu_full, op_type, text):
    """Быстрый локальный поиск по дереву категорий и подкатегорий."""
    clean = text.lower().strip()
    type_menu = menu_full.get(op_type, {})
    for cat, subs in type_menu.items():
        if cat.lower() == clean:
            sub_keys = list(subs.keys()) if isinstance(subs, dict) else (subs if subs else [])
            return cat, (sub_keys[0] if sub_keys else "Разное")
        sub_keys = list(subs.keys()) if isinstance(subs, dict) else (subs if subs else [])
        for s in sub_keys:
            if s.lower() == clean:
                return cat, s
    return None, None

def handle_transaction(user_id, user_text, state, user_states):
    user_text_lower = user_text.lower()
    internal_uid = get_or_create_user(user_id)

    # =========================================================
    # ОБРАБОТКА «НАЗАД»
    # =========================================================
    if "назад" in user_text_lower:
        if state == "multi_tx_edit_hint":
            user_states[user_id]["state"] = "multi_tx_review"
            _show_multi_tx_items(user_id, user_states[user_id]["items"], show_apply_all=False)
            return True
        elif state == "multi_tx_review":
            del user_states[user_id]
            send_vk_message(user_id, "Главное меню.", get_main_keyboard(user_id))
            return True
        elif state in ["history_action_select", "confirm_delete_tx"]:
            hist = user_states[user_id].get("history_data", {})
            items = hist.get("items", [])
            user_states[user_id]["state"] = "history_view"
            _show_history_screen(user_id, items, hist.get("title_period", "список"), hist.get("total_expense", 0), hist.get("total_income", 0), hist.get("count"))
            return True
        elif state in ["history_edit_amount", "history_edit_category"]:
            user_states[user_id]["state"] = "history_action_select"
            sel_op = user_states[user_id]["sel_op"]
            idx = user_states[user_id]["idx"]
            date_str = sel_op["date"].strftime("%d.%m.%Y %H:%M") if sel_op.get("date") else ""
            t_icon = "📈" if sel_op["type"] == "Доход" else "📉"
            msg = (
                f"📌 Операция №{idx+1}:\n"
                f"• {t_icon} {sel_op['article']} — {sel_op['amount']:g} руб.\n"
                f"• Категория: {sel_op['category']} -> {sel_op['subcategory']}\n"
                f"• Дата: {date_str}\n\n"
                f"Что вы хотите сделать с этой операцией?"
            )
            send_vk_message(user_id, msg, get_tx_action_keyboard())
            return True
        elif state == "history_view":
            del user_states[user_id]
            send_vk_message(user_id, "Главное меню.", get_main_keyboard(user_id))
            return True

    # =========================================================
    # ВЫБОР ДЕЙСТВИЯ НАД ОПЕРАЦИЕЙ ИЗ ИСТОРИИ
    # =========================================================
    if state == "history_action_select":
        sel_op = user_states[user_id].get("sel_op")
        if "удалить" in user_text_lower:
            user_states[user_id]["state"] = "confirm_delete_tx"
            send_vk_message(
                user_id,
                f"⚠️ Вы уверены, что хотите безвозвратно удалить операцию?\n\n"
                f"• {sel_op['article']} — {sel_op['amount']:g} руб.\n"
                f"• Категория: {sel_op['category']} -> {sel_op['subcategory']}",
                get_yes_no_keyboard(show_back=True)
            )
            return True
        elif "сумму" in user_text_lower:
            user_states[user_id]["state"] = "history_edit_amount"
            send_vk_message(
                user_id,
                f"✏️ Текущая сумма: {sel_op['amount']:g} руб.\n"
                f"Введите или надиктуйте новую сумму (например: 550):",
                get_cancel_keyboard(show_back=True)
            )
            return True
        elif "категорию" in user_text_lower:
            user_states[user_id]["state"] = "history_edit_category"
            send_vk_message(
                user_id,
                f"📂 Текущая категория: {sel_op['category']} -> {sel_op['subcategory']}\n"
                f"Напишите или надиктуйте правильную категорию или статью (например: «Кафе» или «Продукты»):",
                get_cancel_keyboard(show_back=True)
            )
            return True

    # =========================================================
    # ВВОД НОВОЙ СУММЫ ДЛЯ ОПЕРАЦИИ
    # =========================================================
    if state == "history_edit_amount":
        sel_op = user_states[user_id].get("sel_op")
        raw_num = re.sub(r'[^\d.,]', '', user_text).replace(',', '.')
        try:
            new_amount = float(raw_num)
            if new_amount > 0:
                ok = update_transaction_amount(internal_uid, sel_op["id"], new_amount)
                if ok:
                    send_vk_message(
                        user_id,
                        f"✅ Сумма операции «{sel_op['article']}» успешно изменена:\n"
                        f"💰 {sel_op['amount']:g} руб. ➔ {new_amount:g} руб.",
                        get_main_keyboard(user_id)
                    )
                else:
                    send_vk_message(user_id, "❌ Не удалось обновить сумму в базе данных.", get_main_keyboard(user_id))
                del user_states[user_id]
                return True
            else:
                send_vk_message(user_id, "⚠️ Сумма должна быть больше 0. Попробуйте еще раз:", get_cancel_keyboard(show_back=True))
                return True
        except ValueError:
            send_vk_message(user_id, "⚠️ Пожалуйста, укажите сумму числом (например: 450).", get_cancel_keyboard(show_back=True))
            return True

    # =========================================================
    # ВВОД НОВОЙ КАТЕГОРИИ ДЛЯ ОПЕРАЦИИ
    # =========================================================
    if state == "history_edit_category":
        sel_op = user_states[user_id].get("sel_op")
        op_type, is_exp_inc = detect_operation_type(user_text, sel_op.get("type", "Расход"))
        menu_full = get_full_menu(internal_uid)

        # 1. Поиск по БД строго в рамках целевого типа
        db_match = smart_search_item(internal_uid, user_text, op_type=op_type)
        if db_match["status"] != "FOUND" and not is_exp_inc:
            db_match = smart_search_item(internal_uid, user_text, op_type=None)

        if db_match["status"] == "FOUND":
            target_cat = db_match["category"]
            target_sub = db_match["subcategory"]
            target_art = db_match["article"]
        else:
            # 2. Поиск по дереву категорий
            c_tree, s_tree = _match_category_tree(menu_full, op_type, user_text)
            if c_tree and s_tree:
                target_cat, target_sub, target_art = c_tree, s_tree, sel_op["article"]
            else:
                # 3. Резерв через ИИ
                send_vk_message(user_id, "🧠 Подбираю категорию с помощью ИИ...", get_cancel_keyboard(show_back=True))
                type_menu = menu_full.get(op_type, {})
                menu_str = f"[{op_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])
                ai_cat, ai_sub = categorize_with_ai(sel_op["article"], menu_str, context=user_text)
                target_cat, target_sub, target_art = ai_cat, ai_sub, sel_op["article"]

        ok = update_transaction_category(internal_uid, sel_op["id"], target_cat, target_sub, target_art)
        if ok:
            if target_cat != "Разное" and target_sub != "Требует проверки":
                learn_user_word(internal_uid, op_type, target_cat, target_sub, target_art, user_text)
                learn_user_word(internal_uid, op_type, target_cat, target_sub, target_art, target_art)
            send_vk_message(
                user_id,
                f"✅ Категория операции «{target_art}» успешно изменена:\n"
                f"📂 {target_cat} -> {target_sub}",
                get_main_keyboard(user_id)
            )
        else:
            send_vk_message(user_id, "❌ Не удалось обновить категорию в базе данных.", get_main_keyboard(user_id))
        del user_states[user_id]
        return True

    # =========================================================
    # ВЫБОР НОМЕРА ОПЕРАЦИИ ИЗ СПИСКА ИСТОРИИ
    # =========================================================
    if state == "history_view":
        if user_text.isdigit():
            idx = int(user_text) - 1
            items = user_states[user_id].get("history_data", {}).get("items", [])
            if 0 <= idx < len(items):
                sel_op = items[idx]
                user_states[user_id]["state"] = "history_action_select"
                user_states[user_id]["sel_op"] = sel_op
                user_states[user_id]["idx"] = idx
                date_str = sel_op["date"].strftime("%d.%m.%Y %H:%M") if sel_op.get("date") else ""
                t_icon = "📈" if sel_op["type"] == "Доход" else "📉"
                msg = (
                    f"📌 **Выбрана операция №{idx+1}:**\n"
                    f"• {t_icon} {sel_op['article']} — {sel_op['amount']:g} руб.\n"
                    f"• 📂 {sel_op['category']} -> {sel_op['subcategory']}\n"
                    f"• 📅 Дата: {date_str}\n\n"
                    f"Что вы хотите сделать с этой операцией?"
                )
                send_vk_message(user_id, msg, get_tx_action_keyboard())
                return True
        else:
            del user_states[user_id]
            state = ""

    # =========================================================
    # ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ ОДНОЙ ОПЕРАЦИИ
    # =========================================================
    if state == "confirm_delete_tx":
        if any(w in user_text_lower for w in ["да", "верно", "ага", "yes", "+", "удалить"]):
            tx_id = user_states[user_id].get("tx_id") or (user_states[user_id].get("sel_op", {}).get("id"))
            desc = user_states[user_id].get("desc") or (user_states[user_id].get("sel_op", {}).get("article", "Операция"))
            if tx_id and delete_transaction_by_id(internal_uid, tx_id):
                send_vk_message(user_id, f"🗑 Успешно удалено: «{desc}».", get_main_keyboard(user_id))
            else:
                send_vk_message(user_id, "❌ Не удалось удалить операцию.", get_main_keyboard(user_id))
            del user_states[user_id]
            return True
        elif any(w in user_text_lower for w in ["нет", "неверно", "отмена"]):
            del user_states[user_id]
            send_vk_message(user_id, "Удаление отменено.", get_main_keyboard(user_id))
            return True

    # =========================================================
    # ПОДТВЕРЖДЕНИЕ МАССОВОГО УДАЛЕНИЯ ОПЕРАЦИЙ (DELETE ALL TX)
    # =========================================================
    if state == "confirm_delete_all_tx":
        if any(w in user_text_lower for w in ["да", "верно", "ага", "yes", "+", "удалить", "очисти"]):
            period = user_states[user_id].get("period", "all")
            cnt = delete_all_user_transactions(internal_uid, period=period)
            send_vk_message(user_id, f"🗑 Успешно удалено операций: {cnt} из базы данных.", get_main_keyboard(user_id))
            del user_states[user_id]
            return True
        elif any(w in user_text_lower for w in ["нет", "неверно", "отмена", "назад"]):
            del user_states[user_id]
            send_vk_message(user_id, "Массовое удаление отменено.", get_main_keyboard(user_id))
            return True

    # =========================================================
    # РЕВЬЮ ПАКЕТА ОПЕРАЦИЙ (МАССОВЫЙ ВВОД)
    # =========================================================
    if state == "multi_tx_review":
        state_data = user_states[user_id]
        items = state_data["items"]

        if any(w in user_text_lower for w in ["готово", "сохранить", "сохрани", "да", "ок", "+", "верно", "ага"]):
            send_vk_message(user_id, "⏳ Сохраняю операции в базу данных...", get_cancel_keyboard(show_back=False))
            saved_count, needs_review_count = _save_items_batch(internal_uid, items)
            report_msg = f"🎉 Успешно сохранено {saved_count} операций!\nЖурнал обновлен."
            if needs_review_count > 0:
                report_msg += f"\n\n⚠️ {needs_review_count} позиций требуют проверки. Вы можете распределить их кнопкой «📥 Разобрать операции»."
            send_vk_message(user_id, report_msg, get_main_keyboard(user_id))
            del user_states[user_id]
            return True

        elif any(phrase in user_text_lower for phrase in ["применить для всех", "применить ко всем"]):
            last_cat = state_data.get("last_category")
            last_sub = state_data.get("last_subcategory")
            start_idx = state_data.get("last_edit_idx", 0) + 1
            if not last_cat or not last_sub:
                send_vk_message(user_id, "⚠️ Сначала измените какую-нибудь одну операцию из списка.")
                return True
            applied = 0
            for i in range(start_idx, len(items)):
                items[i]["category"] = last_cat
                items[i]["subcategory"] = last_sub
                applied += 1
            if applied == 0:
                for it in items:
                    it["category"] = last_cat
                    it["subcategory"] = last_sub
                applied = len(items)
            send_vk_message(user_id, f"⚡ Категория «{last_cat} -> {last_sub}» применена к {applied} операциям!")
            _show_multi_tx_items(user_id, items, show_apply_all=True)
            return True

        elif user_text.isdigit():
            idx = int(user_text) - 1
            if 0 <= idx < len(items):
                state_data["edit_idx"] = idx
                state_data["state"] = "multi_tx_edit_hint"
                sel_item = items[idx]
                send_vk_message(
                    user_id,
                    f"✏️ Исправляем: «{sel_item.get('item')}» ({sel_item.get('amount')} руб.)\n"
                    f"Напишите правильную категорию или точное название статьи (например: «Детский сад» или «Образование»):",
                    get_cancel_keyboard(show_back=True)
                )
                return True

        elif re.search(r'\d+', user_text):
            saved_count, _ = _save_items_batch(internal_uid, items)
            send_vk_message(user_id, f"💾 Предыдущие операции ({saved_count} шт.) сохранены.")
            del user_states[user_id]
            state = ""

    # =========================================================
    # ПОДСКАЗКА ДЛЯ КОНКРЕТНОГО ПУНКТА ИЗ МАССОВОГО ВВОДА
    # =========================================================
    if state == "multi_tx_edit_hint":
        state_data = user_states[user_id]
        idx = state_data["edit_idx"]
        items = state_data["items"]
        sel_item = items[idx]
        op_type, is_exp_inc = detect_operation_type(user_text, sel_item.get("type", "Расход"))
        sel_item["type"] = op_type
        menu_full = get_full_menu(internal_uid)

        db_match = smart_search_item(internal_uid, user_text, op_type=op_type)
        if db_match["status"] != "FOUND" and not is_exp_inc:
            db_match = smart_search_item(internal_uid, user_text, op_type=None)

        if db_match["status"] == "FOUND":
            ai_cat = db_match["category"]
            ai_sub = db_match["subcategory"]
            if db_match.get("type"):
                sel_item["type"] = db_match["type"]
        else:
            c_tree, s_tree = _match_category_tree(menu_full, op_type, user_text)
            if c_tree and s_tree:
                ai_cat, ai_sub = c_tree, s_tree
            else:
                send_vk_message(user_id, "🧠 Подбираю категорию с помощью ИИ...", get_cancel_keyboard(show_back=True))
                type_menu = menu_full.get(op_type, {})
                menu_str = f"[{op_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])
                ai_cat, ai_sub = categorize_with_ai(sel_item.get("item"), menu_str, context=user_text)

        sel_item["category"] = ai_cat
        sel_item["subcategory"] = ai_sub
        state_data["last_category"] = ai_cat
        state_data["last_subcategory"] = ai_sub
        state_data["last_edit_idx"] = idx
        state_data["state"] = "multi_tx_review"
        _show_multi_tx_items(user_id, items, show_apply_all=True)
        return True

    if state != "":
        return False

    # =========================================================
    # ПЕРВИЧНЫЙ АНАЛИЗ ВВОДА (ГОЛОС ИЛИ ТЕКСТ) ЧЕРЕЗ ИИ
    # =========================================================
    reply_text = extract_transaction_with_ai(user_text)
    if not reply_text:
        return False

    parsed_data = _extract_json_data(reply_text)
    if parsed_data:
        try:
            if isinstance(parsed_data, list):
                parsed_data = {"operations": parsed_data}

            action = parsed_data.get("action")

            # 1. ПРОСМОТР ИСТОРИИ
            if action == "show_history":
                raw_limit = parsed_data.get("limit")
                limit = int(raw_limit) if raw_limit else 10
                limit = min(max(limit, 1), 15)
                period = parsed_data.get("period")

                send_vk_message(user_id, "⏳ Загружаю историю операций...")
                history_data = get_user_history(internal_uid, limit=limit, period=period)
                items = history_data["items"]
                if not items:
                    send_vk_message(user_id, "📭 За указанный период операций не найдено.", get_main_keyboard(user_id))
                    return True

                period_names = {
                    "today": "за сегодня",
                    "yesterday": "за вчера",
                    "week": "за последнюю неделю",
                    "month": "за последние 30 дней"
                }
                title_period = period_names.get(period, f"последние {len(items)}")
                history_data["title_period"] = title_period
                user_states[user_id] = {
                    "state": "history_view",
                    "history_data": history_data
                }
                _show_history_screen(
                    user_id,
                    items,
                    title_period,
                    history_data["total_expense"],
                    history_data["total_income"],
                    total_count=history_data.get("count")
                )
                return True

            # 2. МАССОВОЕ УДАЛЕНИЕ ОПЕРАЦИЙ
            if action == "delete_all_tx":
                period = parsed_data.get("period") or "all"
                check_hist = get_user_history(internal_uid, limit=50, period=None if period == "all" else period)
                total_ops = check_hist.get("count", 0)
                if total_ops == 0:
                    send_vk_message(user_id, "📭 В журнале пока нет операций для удаления.", get_main_keyboard(user_id))
                    return True

                period_desc = {
                    "today": "за сегодня",
                    "yesterday": "за вчера",
                    "week": "за последнюю неделю",
                    "month": "за месяц",
                    "all": "за всё время"
                }.get(period, "")

                user_states[user_id] = {
                    "state": "confirm_delete_all_tx",
                    "period": period
                }
                send_vk_message(
                    user_id,
                    f"⚠️ ВНИМАНИЕ: Вы уверены, что хотите удалить ВСЕ операции {period_desc}?\n\n"
                    f"• Найдено операций: {total_ops} шт.\n"
                    f"• Данные будут удалены безвозвратно!",
                    get_yes_no_keyboard(show_back=True)
                )
                return True

            # 3. БЫСТРОЕ УДАЛЕНИЕ ПОСЛЕДНЕЙ ОПЕРАЦИИ
            if action == "delete_last_tx":
                last_op = get_last_transaction(internal_uid)
                if not last_op:
                    send_vk_message(user_id, "📭 В журнале пока нет операций для удаления.", get_main_keyboard(user_id))
                    return True

                user_states[user_id] = {
                    "state": "confirm_delete_tx",
                    "tx_id": last_op["id"],
                    "desc": f"{last_op['article']} ({last_op['amount']:g} руб.)"
                }
                send_vk_message(
                    user_id,
                    f"⚠️ Вы уверены, что хотите удалить последнюю операцию?\n\n"
                    f"• {last_op['article']} — {last_op['amount']:g} руб. ({last_op['type']})\n"
                    f"• Категория: {last_op['category']} -> {last_op['subcategory']}",
                    get_yes_no_keyboard(show_back=True)
                )
                return True

            # 4. ТЕКСТОВОЕ УПРАВЛЕНИЕ СТРУКТУРОЙ (CRUD)
            if action in ["smart_rename", "smart_delete", "smart_move"]:
                target_name = parsed_data.get("old_name") if action == "smart_rename" else parsed_data.get("item", "")
                send_vk_message(user_id, f"⏳ Ищу '{target_name}' в структуре...")
                menu = get_full_menu(internal_uid)
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

            if action == "start_interactive":
                op = parsed_data.get("operation")
                item = parsed_data.get("item", "")
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

            # 5. ОБЫЧНЫЙ ИЛИ МАССОВЫЙ ВВОД ТРАТ/ДОХОДОВ
            raw_ops = parsed_data.get("operations", [])
            if not raw_ops and "item" in parsed_data:
                raw_ops = [parsed_data]
            if not raw_ops:
                return False

            menu_full = get_full_menu(internal_uid)
            processed_items = []

            for op in raw_ops:
                current_item = op.get("item", "").strip()
                if not current_item or current_item.lower() in ["приход", "доход", "расход", "трата", "поступление"]:
                    current_item = clean_fallback_item(user_text)

                amount = float(op.get("amount", 0))
                comment = op.get("comment", "").strip()

                # Надежное определение типа операции:
                op_type, is_explicit_income = detect_operation_type(user_text, op.get("type", "Расход"), current_item, comment)

                # 1. Полноценный поиск по БД:
                # Если явно указан ДОХОД — ищем ТОЛЬКО в Доходах! В Расходы не подглядываем!
                search_res = smart_search_item(internal_uid, current_item, op_type=op_type)
                if search_res["status"] != "FOUND" and not is_explicit_income:
                    search_res = smart_search_item(internal_uid, current_item, op_type=None)

                # Поиск по фразе вместе с комментарием
                if search_res["status"] != "FOUND" and comment:
                    full_phrase = f"{current_item} {comment}".strip()
                    phrase_res = smart_search_item(internal_uid, full_phrase, op_type=op_type)
                    if phrase_res["status"] != "FOUND" and not is_explicit_income:
                        phrase_res = smart_search_item(internal_uid, full_phrase, op_type=None)
                    if phrase_res["status"] == "FOUND":
                        search_res = phrase_res
                        current_item = full_phrase
                        comment = ""

                # КРИТИЧЕСКАЯ ЗАЩИТА: Если пользователь сказал "Доход", результат поиска не может быть "Расход"
                if search_res["status"] == "FOUND":
                    if is_explicit_income and search_res.get("type") == "Расход":
                        search_res = {"status": "NOT_FOUND"}

                if search_res["status"] == "FOUND":
                    processed_items.append({
                        "item": current_item,
                        "amount": amount,
                        "type": op_type if is_explicit_income else search_res.get("type", op_type),
                        "category": search_res["category"],
                        "subcategory": search_res["subcategory"],
                        "comment": comment,
                        "is_known": True
                    })
                else:
                    # 2. Локальный поиск по дереву категорий и подкатегорий (строго в op_type)
                    c_tree, s_tree = _match_category_tree(menu_full, op_type, current_item)
                    if c_tree and s_tree:
                        processed_items.append({
                            "item": current_item,
                            "amount": amount,
                            "type": op_type,
                            "category": c_tree,
                            "subcategory": s_tree,
                            "comment": comment,
                            "is_known": True
                        })
                    else:
                        # 3. Резервный подбор ИИ строго по меню выбранного типа (op_type)
                        type_menu = menu_full.get(op_type, {})
                        menu_str = f"[{op_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])
                        ai_cat, ai_sub = categorize_with_ai(current_item, menu_str)

                        valid_cat = ai_cat in type_menu and ai_sub in (type_menu[ai_cat].keys() if isinstance(type_menu[ai_cat], dict) else type_menu[ai_cat])
                        if valid_cat and ai_sub != "Требует проверки":
                            cat_res, sub_res = ai_cat, ai_sub
                        else:
                            cat_res, sub_res = "Разное", "Требует проверки"

                        processed_items.append({
                            "item": current_item,
                            "amount": amount,
                            "type": op_type,
                            "category": cat_res,
                            "subcategory": sub_res,
                            "comment": comment,
                            "is_known": False
                        })

            # =========================================================
            # СЦЕНАРИЙ А: РОВНО 1 ОПЕРАЦИЯ
            # =========================================================
            if len(processed_items) == 1:
                single = processed_items[0]

                # 1. Известна в базе -> мгновенная запись
                if single["is_known"]:
                    save_transaction(
                        user_id=internal_uid,
                        op_type=single["type"],
                        category=single["category"],
                        subcategory=single["subcategory"],
                        article=single["item"],
                        amount=single["amount"],
                        comment=single["comment"],
                        original_text=single["item"],
                        status='verified'
                    )
                    send_vk_message(
                        user_id,
                        f"✅ Успешно записано! ({single['type']})\n📂 {single['category']} -> {single['subcategory']}\n💰 {single['amount']:g} руб.",
                        get_main_keyboard(user_id)
                    )
                    return True

                # 2. Неизвестна точно, но ИИ подобрал категорию -> переспрашиваем "Да/Нет"
                if single["category"] != "Разное" and single["subcategory"] != "Требует проверки":
                    user_states[user_id] = {
                        "state": "confirm_category",
                        "payload": single,
                        "menu": menu_full,
                        "ai_cat": single["category"],
                        "ai_sub": single["subcategory"],
                        "attempts": 1
                    }
                    send_vk_message(
                        user_id,
                        f"🤖 Думаю, «{single['item']}» ({single['type']}) относится к:\n"
                        f"📂 {single['category']} -> {single['subcategory']}\n"
                        f"💰 {single['amount']:g} руб.\n\nВсё верно?",
                        get_yes_no_keyboard(show_back=True)
                    )
                    return True

                # 3. Полностью неизвестная статья -> начинаем цикл подсказок (попытка 1 из 3)
                user_states[user_id] = {
                    "state": "provide_context",
                    "payload": single,
                    "menu": menu_full,
                    "attempts": 1
                }
                send_vk_message(
                    user_id,
                    f"🤔 Я пока не знаю статью «{single['item']}» ({single['type']}, {single['amount']:g} руб.).\n"
                    f"Подскажи в двух словах, к чему это относится (или назови категорию):",
                    get_cancel_keyboard(show_back=True)
                )
                return True

            # =========================================================
            # СЦЕНАРИЙ Б: НЕСКОЛЬКО ОПЕРАЦИЙ (2 и более)
            # =========================================================
            send_vk_message(user_id, f"⚡ Распознаю {len(processed_items)} операций и сопоставляю с базой...")
            user_states[user_id] = {
                "state": "multi_tx_review",
                "items": processed_items,
                "menu": menu_full
            }
            _show_multi_tx_items(user_id, processed_items, show_apply_all=False)
            return True

        except Exception as e:
            send_vk_message(user_id, f"❌ Ошибка базы данных: {e}", get_main_keyboard(user_id))
            return True
    else:
        if reply_text:
            send_vk_message(user_id, reply_text, get_main_keyboard(user_id))
            return True

    return False
