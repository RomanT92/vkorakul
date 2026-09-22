# -*- coding: utf-8 -*-
import re
from keyboards import (
    get_main_keyboard,
    get_yes_no_keyboard,
    get_cancel_keyboard,
    get_numbered_keyboard,
    get_tx_action_keyboard
)
from services import send_vk_message, categorize_with_ai
from db import (
    get_full_menu,
    smart_search_item,
    learn_user_word,
    get_user_history,
    delete_transaction_by_id,
    delete_all_user_transactions,
    get_last_transaction,
    update_transaction_amount,
    update_transaction_category
)
from db.transactions import promote_synonym_to_article
from handlers_tx_parser import (
    detect_operation_type,
    _match_category_tree,
    _validate_ai_category_choice,
    _find_best_matching_article_in_sub
)

def _show_history_screen(user_id, items, title_period, total_expense, total_income, total_count=None):
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

def apply_edit_to_last_transaction(user_id, internal_uid, new_category_hint=None, new_amount=None, new_item_name=None, new_type=None):
    """
    Применяет изменения (категория, сумма, статья/название) к самой последней операции пользователя.
    Используется как быстрыми командами, так и парсером ИИ (action: edit_tx).
    """
    last_op = get_last_transaction(internal_uid)
    if not last_op:
        send_vk_message(user_id, "📭 В журнале пока нет операций для редактирования.", get_main_keyboard(user_id))
        return True

    tx_id = last_op["id"]
    current_art = last_op["article"]
    current_type = new_type or last_op.get("type", "Расход")
    current_amt = last_op["amount"]
    changes_made = []

    # 1. Изменение суммы
    if new_amount is not None:
        try:
            amt_val = float(new_amount)
            if amt_val > 0:
                update_transaction_amount(internal_uid, tx_id, amt_val)
                changes_made.append(f"💰 Сумма: {current_amt:g} руб. ➔ {amt_val:g} руб.")
                current_amt = amt_val
        except (ValueError, TypeError):
            pass

    # 2. Изменение категории / статьи
    if new_category_hint:
        hint_clean = new_category_hint.strip()
        op_type, is_exp_inc = detect_operation_type(hint_clean, current_type)
        menu_full = get_full_menu(internal_uid)
        orig_art = new_item_name or current_art

        db_match = smart_search_item(internal_uid, hint_clean, op_type=op_type)
        if db_match.get("status") != "FOUND" and not is_exp_inc:
            db_match = smart_search_item(internal_uid, hint_clean, op_type=None)

        if db_match.get("status") == "FOUND":
            target_cat = db_match["category"]
            target_sub = db_match["subcategory"]
            target_art = db_match.get("article", orig_art)
            final_type = db_match.get("type", op_type)
        else:
            c_tree, s_tree = _match_category_tree(menu_full, op_type, hint_clean)
            if c_tree and s_tree:
                target_cat, target_sub = c_tree, s_tree
                target_art = _find_best_matching_article_in_sub(menu_full, op_type, target_cat, target_sub, orig_art)
                final_type = op_type
            else:
                type_menu = menu_full.get(op_type, {})
                menu_str = f"[{op_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])
                ai_cat, ai_sub = categorize_with_ai(orig_art, menu_str, context=hint_clean)
                v_cat, v_sub = _validate_ai_category_choice(menu_full, op_type, ai_cat, ai_sub)
                target_cat = v_cat or "Разное"
                target_sub = v_sub or "Требует проверки"
                target_art = _find_best_matching_article_in_sub(menu_full, op_type, target_cat, target_sub, orig_art)
                final_type = op_type

        update_transaction_category(internal_uid, tx_id, target_cat, target_sub, target_art)
        if target_cat != "Разное" and target_sub != "Требует проверки":
            learn_user_word(internal_uid, final_type, target_cat, target_sub, target_art, orig_art)
            learn_user_word(internal_uid, final_type, target_cat, target_sub, target_art, hint_clean)

        changes_made.append(f"📂 Категория: {target_cat} -> {target_sub} (статья: «{target_art}»)")

    elif new_item_name:
        # Переименование статьи без смены категории
        clean_name = new_item_name.strip().capitalize()
        update_transaction_category(internal_uid, tx_id, last_op["category"], last_op["subcategory"], clean_name)
        changes_made.append(f"✏️ Статья: «{clean_name}»")

    if changes_made:
        res_text = f"✅ Последняя операция («{current_art}») успешно обновлена!\n\n" + "\n".join(changes_made)
        send_vk_message(user_id, res_text, get_main_keyboard(user_id))
        return True

    return False

def handle_history_and_edits(user_id, internal_uid, user_text, user_text_lower, state, user_states):
    """Быстрые команды просмотра, удаления и правки истории транзакций."""

    # 1. СДЕЛАТЬ ОТДЕЛЬНОЙ СТАТЬЕЙ
    promote_triggers = [
        "сделать отдельной статьей", "сделать отдельной статьёй", "создать статью",
        "отдельной статьей", "отдельной статьёй", "сделай статьей", "сделай статьёй"
    ]
    if any(t in user_text_lower for t in promote_triggers):
        last_op = get_last_transaction(internal_uid)
        if last_op:
            orig = last_op.get("original_text") or last_op["article"]
            promote_synonym_to_article(internal_uid, last_op["type"], last_op["category"], last_op["subcategory"], orig)
            send_vk_message(user_id, f"✅ Готово! Статья «{orig.capitalize()}» теперь создана в подкатегории «{last_op['subcategory']}».", get_main_keyboard(user_id))
            if user_id in user_states:
                del user_states[user_id]
            return True

    # 2. БЫСТРОЕ РЕДАКТИРОВАНИЕ ПОСЛЕДНЕЙ ОПЕРАЦИИ (ГОЛОС/ТЕКСТ)
    # Пример: "Измени категорию у последней операции на самозанятость"
    cat_edit_match = re.search(

        r'^(?:измени|поменяй|поставь|смени|исправь)\s+(?:категорию|подкатегорию|статью)?\s*(?:у\s+)?(?:последней|прошлой)\s+(?:операции|траты|записи)?\s*на\s+(.+)$',
        user_text_lower
    )
    if not cat_edit_match:
        cat_edit_match = re.search(
            r'^(?:у\s+)?(?:последней|прошлой)\s+(?:операции|траты|записи)\s+(?:категория|подкатегория|статья)?\s*это\s+(.+)$',
            user_text_lower
        )
    if cat_edit_match:
        target_hint = cat_edit_match.group(1).strip().strip('«»"\'.,')
        if target_hint:
            return apply_edit_to_last_transaction(user_id, internal_uid, new_category_hint=target_hint)

    # Пример: "Измени сумму у последней операции на 450"
    amt_edit_match = re.search(
        r'^(?:измени|поменяй|поставь|смени|исправь)\s+сумму\s+(?:у\s+)?(?:последней|прошлой)\s+(?:операции|траты|записи)?\s*на\s+(\d+(?:[.,]\d+)?)$',
        user_text_lower
    )
    if amt_edit_match:
        raw_amt = amt_edit_match.group(1).replace(',', '.')
        return apply_edit_to_last_transaction(user_id, internal_uid, new_amount=raw_amt)

    # 3. ПРОСМОТР ПОСЛЕДНЕЙ ОПЕРАЦИИ ИЛИ ИСТОРИИ
    history_fast_triggers = [
        "покажи последнюю операцию", "покажи последнюю", "последняя операция",
        "покажи последние операции", "покажи историю", "история операций",
        "история трат", "покажи траты", "покажи расходы", "мои операции", "мои расходы"
    ]
    if (state == "" or state == "history_view") and any(user_text_lower == trig or user_text_lower.startswith(trig) for trig in history_fast_triggers):
        limit = 1 if ("последнюю операцию" in user_text_lower or "последняя операция" in user_text_lower) else 10
        send_vk_message(user_id, "⏳ Загружаю историю операций...")
        history_data = get_user_history(internal_uid, limit=limit, period=None)
        items = history_data.get("items", [])
        if not items:
            send_vk_message(user_id, "📭 В журнале пока нет записанных операций.", get_main_keyboard(user_id))
            return True
        title = "последняя операция" if limit == 1 else f"последние {len(items)}"
        history_data["title_period"] = title
        user_states[user_id] = {"state": "history_view", "history_data": history_data}
        _show_history_screen(user_id, items, title, history_data["total_expense"], history_data["total_income"], total_count=history_data.get("count"))
        return True

    # 4. УДАЛИТЬ ВСЕ ОПЕРАЦИИ
    delete_all_fast_triggers = [
        "удали все операции", "удалить все операции", "очисти историю", "очистить историю",
        "удали все траты", "удалить все траты", "очисти журнал", "стереть все операции"
    ]
    if (state == "" or state == "history_view") and any(user_text_lower == trig for trig in delete_all_fast_triggers):
        check_hist = get_user_history(internal_uid, limit=50, period=None)
        total_ops = check_hist.get("count", 0)
        if total_ops == 0:
            send_vk_message(user_id, "📭 В журнале пока нет операций для удаления.", get_main_keyboard(user_id))
            return True
        user_states[user_id] = {"state": "confirm_delete_all_tx", "period": "all"}
        send_vk_message(user_id, f"⚠️ Вы уверены, что хотите удалить ВСЕ операции за всё время?\n\n• Найдено операций: {total_ops} шт.\n• Данные будут удалены безвозвратно!", get_yes_no_keyboard(show_back=True))
        return True

    # 5. УДАЛИТЬ ПОСЛЕДНЮЮ ОПЕРАЦИЮ
    delete_last_fast_triggers = [
        "удали последнюю операцию", "удалить последнюю операцию", "отмени последнюю запись",
        "удали последнюю трату", "удалить последнюю", "удали последнюю"
    ]
    if (state == "" or state == "history_view") and any(user_text_lower == trig for trig in delete_last_fast_triggers):
        last_op = get_last_transaction(internal_uid)
        if not last_op:
            send_vk_message(user_id, "📭 В журнале пока нет операций для удаления.", get_main_keyboard(user_id))
            return True
        user_states[user_id] = {
            "state": "confirm_delete_tx",
            "tx_id": last_op["id"],
            "desc": f"{last_op['article']} ({last_op['amount']:g} руб.)"
        }
        send_vk_message(user_id, f"⚠️ Вы уверены, что хотите удалить последнюю операцию?\n\n• {last_op['article']} — {last_op['amount']:g} руб. ({last_op['type']})\n• Категория: {last_op['category']} -> {last_op['subcategory']}", get_yes_no_keyboard(show_back=True))
        return True

    # 6. ИНТЕРАКТИВНОЕ МЕНЮ ИСТОРИИ
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

    if state == "history_action_select":
        sel_op = user_states[user_id].get("sel_op")
        if "удалить" in user_text_lower:
            user_states[user_id]["state"] = "confirm_delete_tx"
            send_vk_message(user_id, f"⚠️ Вы уверены, что хотите безвозвратно удалить операцию?\n\n• {sel_op['article']} — {sel_op['amount']:g} руб.\n• Категория: {sel_op['category']} -> {sel_op['subcategory']}", get_yes_no_keyboard(show_back=True))
            return True
        elif "сумму" in user_text_lower:
            user_states[user_id]["state"] = "history_edit_amount"
            send_vk_message(user_id, f"✏️ Текущая сумма: {sel_op['amount']:g} руб.\nВведите новую сумму (например: 550):", get_cancel_keyboard(show_back=True))
            return True
        elif "категорию" in user_text_lower or "подкатегорию" in user_text_lower:
            user_states[user_id]["state"] = "history_edit_category"
            send_vk_message(user_id, f"📂 Текущая категория: {sel_op['category']} -> {sel_op['subcategory']}\nНапишите правильную категорию или статью:", get_cancel_keyboard(show_back=True))
            return True
        elif any(t in user_text_lower for t in promote_triggers):
            orig = sel_op.get("original_text") or sel_op["article"]
            promote_synonym_to_article(internal_uid, sel_op["type"], sel_op["category"], sel_op["subcategory"], orig)
            send_vk_message(user_id, f"✅ Готово! Статья «{orig.capitalize()}» создана в подкатегории «{sel_op['subcategory']}».", get_main_keyboard(user_id))
            del user_states[user_id]
            return True

    if state == "history_edit_amount":
        sel_op = user_states[user_id].get("sel_op")
        raw_num = re.sub(r'[^\d.,]', '', user_text).replace(',', '.')
        try:
            new_amount = float(raw_num)
            if new_amount > 0:
                update_transaction_amount(internal_uid, sel_op["id"], new_amount)
                send_vk_message(user_id, f"✅ Сумма операции «{sel_op['article']}» успешно изменена:\n💰 {sel_op['amount']:g} руб. ➔ {new_amount:g} руб.", get_main_keyboard(user_id))
                del user_states[user_id]
                return True
            send_vk_message(user_id, "⚠️ Сумма должна быть больше 0.", get_cancel_keyboard(show_back=True))
            return True
        except ValueError:
            send_vk_message(user_id, "⚠️ Укажите сумму числом (например: 450).", get_cancel_keyboard(show_back=True))
            return True

    if state == "history_edit_category":
        sel_op = user_states[user_id].get("sel_op")
        op_type, is_exp_inc = detect_operation_type(user_text, sel_op.get("type", "Расход"))
        menu_full = get_full_menu(internal_uid)
        orig_art = sel_op["article"]

        db_match = smart_search_item(internal_uid, user_text, op_type=op_type)
        if db_match["status"] != "FOUND" and not is_exp_inc:
            db_match = smart_search_item(internal_uid, user_text, op_type=None)

        if db_match["status"] == "FOUND":
            target_cat = db_match["category"]
            target_sub = db_match["subcategory"]
            target_art = db_match.get("article", orig_art)
        else:
            c_tree, s_tree = _match_category_tree(menu_full, op_type, user_text)
            if c_tree and s_tree:
                target_cat, target_sub = c_tree, s_tree
                target_art = _find_best_matching_article_in_sub(menu_full, op_type, target_cat, target_sub, orig_art)
            else:
                send_vk_message(user_id, "🧠 Подбираю категорию с помощью ИИ...", get_cancel_keyboard(show_back=True))
                type_menu = menu_full.get(op_type, {})
                menu_str = f"[{op_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])
                ai_cat, ai_sub = categorize_with_ai(orig_art, menu_str, context=user_text)
                v_cat, v_sub = _validate_ai_category_choice(menu_full, op_type, ai_cat, ai_sub)
                target_cat = v_cat or "Разное"
                target_sub = v_sub or "Требует проверки"
                target_art = _find_best_matching_article_in_sub(menu_full, op_type, target_cat, target_sub, orig_art)

        update_transaction_category(internal_uid, sel_op["id"], target_cat, target_sub, target_art)
        if target_cat != "Разное" and target_sub != "Требует проверки":
            learn_user_word(internal_uid, op_type, target_cat, target_sub, target_art, orig_art)
            learn_user_word(internal_uid, op_type, target_cat, target_sub, target_art, user_text)
        send_vk_message(user_id, f"✅ Категория операции «{orig_art}» успешно изменена:\n📂 {target_cat} -> {target_sub} (статья: «{target_art}»)", get_main_keyboard(user_id))
        del user_states[user_id]
        return True

    if state == "confirm_delete_tx":
        if any(w in user_text_lower for w in ["да", "верно", "ага", "yes", "+", "удалить"]):
            tx_id = user_states[user_id].get("tx_id") or (user_states[user_id].get("sel_op", {}).get("id"))
            desc = user_states[user_id].get("desc") or (user_states[user_id].get("sel_op", {}).get("article", "Операция"))
            if tx_id and delete_transaction_by_id(internal_uid, tx_id):
                send_vk_message(user_id, f"🗑 Успешно удалено: «{desc}».", get_main_keyboard(user_id))
            del user_states[user_id]
            return True
        elif any(w in user_text_lower for w in ["нет", "неверно", "отмена"]):
            del user_states[user_id]
            send_vk_message(user_id, "Удаление отменено.", get_main_keyboard(user_id))
            return True

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

    return False
