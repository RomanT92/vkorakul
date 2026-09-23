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
    """Формирует экран вывода списка операций пользователю с итоговыми суммами."""
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

def apply_edit_to_last_transaction(user_id, internal_uid, new_category_hint=None, new_amount=None, new_item_name=None, new_type=None, new_article_name=None):
    """
    Применяет изменения (категория, сумма, статья/название, тип операции, новая статья) к самой последней операции пользователя.
    Используется как быстрыми локальными командами, так и диспетчером ИИ (action: edit_tx).
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

    # 1. Изменение суммы последней операции
    if new_amount is not None:
        try:
            amt_val = float(new_amount)
            if amt_val > 0:
                update_transaction_amount(internal_uid, tx_id, amt_val)
                changes_made.append(f"💰 Сумма: {current_amt:g} руб. ➔ {amt_val:g} руб.")
                current_amt = amt_val
        except (ValueError, TypeError):
            pass

    # 1.1 Создание новой статьи и перенос последней операции туда
    if new_article_name:
        clean_new_art = re.sub(r'\bна\s+стенн', 'настенн', str(new_article_name).strip(), flags=re.IGNORECASE)
        clean_new_art = clean_new_art.strip().capitalize()
        target_cat = last_op.get("category", "Разное")
        target_sub = last_op.get("subcategory", "Разное")
        final_type = current_type

        # Создаем статью в структуре каталога и персональном словаре
        promote_synonym_to_article(internal_uid, final_type, target_cat, target_sub, clean_new_art)
        learn_user_word(internal_uid, final_type, target_cat, target_sub, clean_new_art, clean_new_art)
        orig_desc = last_op.get("original_text") or current_art
        if orig_desc and orig_desc.lower() != clean_new_art.lower():
            learn_user_word(internal_uid, final_type, target_cat, target_sub, clean_new_art, orig_desc)

        update_transaction_category(internal_uid, tx_id, target_cat, target_sub, clean_new_art, op_type=final_type)
        type_notice = f" ({final_type})" if final_type != last_op.get("type") else ""
        changes_made.append(f"🆕 Создана статья: «{clean_new_art}»\n📂 {target_cat} -> {target_sub} (статья: «{clean_new_art}»){type_notice}")
        current_art = clean_new_art

    # 2. Изменение категории / статьи / типа операции
    elif new_category_hint:
        hint_clean = new_category_hint.strip()
        op_type, is_exp_inc = detect_operation_type(hint_clean, current_type)
        menu_full = get_full_menu(internal_uid)
        orig_art = new_item_name or current_art

        # Шаг 2.1: Первоочередной поиск в персональном словаре и эталоне
        db_match = smart_search_item(internal_uid, hint_clean, op_type=op_type)
        if db_match.get("status") != "FOUND":
            # Проверяем альтернативный тип операции (например, если смена Расхода на Доход)
            alt_type = "Доход" if op_type == "Расход" else "Расход"
            alt_db_match = smart_search_item(internal_uid, hint_clean, op_type=alt_type)
            if alt_db_match.get("status") == "FOUND":
                db_match = alt_db_match
                op_type = alt_type
            else:
                db_match = smart_search_item(internal_uid, hint_clean, op_type=None)

        if db_match.get("status") == "FOUND":
            target_cat = db_match["category"]
            target_sub = db_match["subcategory"]
            target_art = db_match.get("article", orig_art)
            final_type = db_match.get("type", op_type)
        else:
            # Шаг 2.2: Сквозной поиск по дереву категорий пользователя
            c_tree, s_tree = _match_category_tree(menu_full, op_type, hint_clean)
            final_type = op_type
            if not c_tree:
                alt_type = "Доход" if op_type == "Расход" else "Расход"
                c_alt, s_alt = _match_category_tree(menu_full, alt_type, hint_clean)
                if c_alt:
                    c_tree, s_tree = c_alt, s_alt
                    final_type = alt_type

            if c_tree and s_tree:
                target_cat, target_sub = c_tree, s_tree
                target_art = _find_best_matching_article_in_sub(menu_full, final_type, target_cat, target_sub, orig_art)
            else:
                # Шаг 2.3: Интеллектуальный подбор через ИИ при отсутствии точных совпадений
                type_menu = menu_full.get(op_type, {})
                menu_str = f"[{op_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])
                ai_cat, ai_sub = categorize_with_ai(orig_art, menu_str, context=hint_clean)
                v_cat, v_sub = _validate_ai_category_choice(menu_full, op_type, ai_cat, ai_sub)

                if not v_cat:
                    alt_type = "Доход" if op_type == "Расход" else "Расход"
                    alt_menu = menu_full.get(alt_type, {})
                    alt_menu_str = f"[{alt_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in alt_menu.items()])
                    ai_cat2, ai_sub2 = categorize_with_ai(orig_art, alt_menu_str, context=hint_clean)
                    v_cat2, v_sub2 = _validate_ai_category_choice(menu_full, alt_type, ai_cat2, ai_sub2)
                    if v_cat2:
                        v_cat, v_sub = v_cat2, v_sub2
                        final_type = alt_type

                target_cat = v_cat or "Разное"
                target_sub = v_sub or "Требует проверки"
                target_art = _find_best_matching_article_in_sub(menu_full, final_type, target_cat, target_sub, orig_art)

        # Сохранение обновленной категории и типа в БД
        update_transaction_category(internal_uid, tx_id, target_cat, target_sub, target_art, op_type=final_type)
        if target_cat != "Разное" and target_sub != "Требует проверки":
            learn_user_word(internal_uid, final_type, target_cat, target_sub, target_art, orig_art)
            learn_user_word(internal_uid, final_type, target_cat, target_sub, target_art, hint_clean)

        type_notice = f" ({final_type})" if final_type != last_op.get("type") else ""
        changes_made.append(f"📂 Категория: {target_cat} -> {target_sub} (статья: «{target_art}»){type_notice}")

    elif new_item_name:
        # Переименование статьи без изменения категории
        clean_name = new_item_name.strip().capitalize()
        update_transaction_category(internal_uid, tx_id, last_op["category"], last_op["subcategory"], clean_name)
        changes_made.append(f"✏️ Статья: «{clean_name}»")

    if changes_made:
        res_text = f"✅ Последняя операция («{current_art}») успешно обновлена!\n\n" + "\n".join(changes_made)
        send_vk_message(user_id, res_text, get_main_keyboard(user_id))
        return True

    return False

def handle_history_and_edits(user_id, internal_uid, user_text, user_text_lower, state, user_states):
    """
    Быстрые команды просмотра, удаления и правки истории транзакций.
    Обеспечивает устойчивое распознавание речи при пунктуации Whisper.
    """
    # Нормализация строки: удаление точек, запятых, тире и кавычек
    clean_t = re.sub(r'[,.!?«»"\'\-]+', ' ', user_text_lower).strip()
    clean_t = re.sub(r'\s+', ' ', clean_t)

    # 1. СДЕЛАТЬ ОТДЕЛЬНОЙ СТАТЬЕЙ
    promote_triggers = [
        "сделать отдельной статьей", "сделать отдельной статьёй", "создать статью",
        "отдельной статьей", "отдельной статьёй", "сделай статьей", "сделай статьёй"
    ]
    if any(t in clean_t for t in promote_triggers):
        last_op = get_last_transaction(internal_uid)
        if last_op:
            orig = last_op.get("original_text") or last_op["article"]
            promote_synonym_to_article(internal_uid, last_op["type"], last_op["category"], last_op["subcategory"], orig)
            send_vk_message(user_id, f"✅ Готово! Статья «{orig.capitalize()}» теперь создана в подкатегории «{last_op['subcategory']}».", get_main_keyboard(user_id))
            if user_id in user_states:
                del user_states[user_id]
            return True

    # 1.1. ПЕРЕНОС В НОВУЮ СТАТЬЮ / СОЗДАНИЕ НОВОЙ СТАТЬИ ДЛЯ ПОСЛЕДНЕЙ ОПЕРАЦИИ (ГОЛОС/ТЕКСТ)
    # Примеры:
    # "у последней операции перенеси в новую статью на стенные часы"
    # "перенеси в новую статью настенные часы"
    # "в новую статью настенные часы"
    # "создай новую статью настенные часы"
    new_art_match = re.search(

        r'^(?:(?:у|в|для|о)?\s*(?:последней|прошлой|предыдущей)\s*(?:операции|траты|записи|покупки))?\s*(?:перенеси|перенести|создай|создать|сделай|сделать|добавь|добавить|запиши|отправь)?\s*(?:в|на|как)?\s*нов(?:ую|ая|ой)\s*стать(?:ю|я|е|и)\s*(?:под\s*названием|с\s*названием|название|это|как)?\s*(.+)$',
        clean_t
    )
    if not new_art_match:
        new_art_match = re.search(
            r'^(?:перенеси|перенести|создай|создать|сделай|сделать|добавь|добавить|запиши)?\s*(?:в|на|как)?\s*нов(?:ую|ая|ой)\s*стать(?:ю|я|е|и)\s*(?:под\s*названием|с\s*названием|название|это|как)?\s*(.+?)\s*(?:у|в|для|о)?\s*(?:последней|прошлой|предыдущей)\s*(?:операции|траты|записи|покупки)$',
            clean_t
        )
    if not new_art_match:
        new_art_match = re.search(
            r'^(?:у|в|для|о)?\s*(?:последней|прошлой|предыдущей)\s*(?:операции|траты|записи|покупки)\s*(?:перенеси|перенести)?\s*(?:в|на)?\s*(?:новую\s*статью|новую\s*статью\s*это)\s*(.+)$',
            clean_t
        )

    if new_art_match:
        raw_art = new_art_match.group(1).strip()
        stop_words_art = ["удали", "покажи", "история", "список", "отмена", "помощь"]
        if raw_art and not any(sw in raw_art for sw in stop_words_art):
            clean_art = re.sub(r'\bна\s+стенн', 'настенн', raw_art, flags=re.IGNORECASE).strip().capitalize()
            return apply_edit_to_last_transaction(user_id, internal_uid, new_article_name=clean_art)

    # 2. БЫСТРОЕ РЕДАКТИРОВАНИЕ КАТЕГОРИИ ПОСЛЕДНЕЙ ОПЕРАЦИИ (ГОЛОС/ТЕКСТ)
    # Шаблон А: "измени категорию в/у/о/для последней операции на самозанятость"
    cat_edit_match = re.search(
        r'^(?:измени|поменяй|поставь|смени|исправь|сделай|перенеси)\s+(?:категорию|подкатегорию|статью)?\s*(?:у|в|во|о|об|обо|для|по)?\s*(?:последней|прошлой|предыдущей)?\s*(?:операции|траты|записи|покупки)?\s*(?:на|в|как)?\s+(.+)$',
        clean_t
    )
    # Шаблон Б: "измени категорию на самозанятость в последней операции" (обратный порядок)
    if not cat_edit_match:
        cat_edit_match = re.search(
            r'^(?:измени|поменяй|поставь|смени|исправь|сделай|перенеси)\s+(?:категорию|подкатегорию|статью)?\s*(?:на|в|как)\s+(.+?)\s*(?:у|в|во|о|об|обо|для|по)?\s*(?:последней|прошлой|предыдущей)\s*(?:операции|траты|записи|покупки)?$',
            clean_t
        )
    # Шаблон В: "у последней операции категория самозанятость" / "последняя операция это самозанятость"
    if not cat_edit_match:
        cat_edit_match = re.search(
            r'^(?:у|в|во|о|для)?\s*(?:последней|прошлой|предыдущей)\s+(?:операции|траты|записи|покупки)\s*(?:категория|подкатегория|статья)?\s*(?:это|на|равна)?\s+(.+)$',
            clean_t
        )

    if cat_edit_match:
        target_hint = cat_edit_match.group(1).strip()
        stop_words_hint = ["удали", "покажи", "история", "список", "отмена"]
        if target_hint and not any(sw in target_hint for sw in stop_words_hint):
            return apply_edit_to_last_transaction(user_id, internal_uid, new_category_hint=target_hint)

    # 3. БЫСТРОЕ РЕДАКТИРОВАНИЕ СУММЫ ПОСЛЕДНЕЙ ОПЕРАЦИИ (ГОЛОС/ТЕКСТ)
    # Шаблон: "измени сумму у последней операции на 450" / "поменяй сумму на 500"
    amt_edit_match = re.search(
        r'^(?:измени|поменяй|поставь|смени|исправь|сделай)\s+сумму\s*(?:у|в|во|о|об|обо|для|по)?\s*(?:последней|прошлой|предыдущей)?\s*(?:операции|траты|записи|покупки)?\s*(?:на|в|равной)?\s*(\d+(?:[.,]\d+)?)$',
        clean_t
    )
    if not amt_edit_match:
        amt_edit_match = re.search(
            r'^(?:у|в|во|о|для)?\s*(?:последней|прошлой|предыдущей)\s+(?:операции|траты|записи|покупки)\s*сумма\s*(?:это|на|равна)?\s*(\d+(?:[.,]\d+)?)$',
            clean_t
        )
    if amt_edit_match:
        raw_amt = amt_edit_match.group(1).replace(',', '.')
        return apply_edit_to_last_transaction(user_id, internal_uid, new_amount=raw_amt)

    # 4. ПРОСМОТР ПОСЛЕДНЕЙ ОПЕРАЦИИ ИЛИ ИСТОРИИ
    history_fast_triggers = [
        "покажи последнюю операцию", "покажи последнюю", "последняя операция",
        "покажи последние операции", "покажи историю", "история операций",
        "история трат", "покажи траты", "покажи расходы", "мои операции", "мои расходы"
    ]
    if (state == "" or state == "history_view") and any(clean_t == trig or clean_t.startswith(trig) for trig in history_fast_triggers):
        limit = 1 if ("последнюю операцию" in clean_t or "последняя операция" in clean_t) else 10
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

    # 5. УДАЛИТЬ ВСЕ ОПЕРАЦИИ
    delete_all_fast_triggers = [
        "удали все операции", "удалить все операции", "очисти историю", "очистить историю",
        "удали все траты", "удалить все траты", "очисти журнал", "стереть все операции"
    ]
    if (state == "" or state == "history_view") and any(clean_t == trig for trig in delete_all_fast_triggers):
        check_hist = get_user_history(internal_uid, limit=50, period=None)
        total_ops = check_hist.get("count", 0)
        if total_ops == 0:
            send_vk_message(user_id, "📭 В журнале пока нет операций для удаления.", get_main_keyboard(user_id))
            return True
        user_states[user_id] = {"state": "confirm_delete_all_tx", "period": "all"}
        send_vk_message(user_id, f"⚠️ Вы уверены, что хотите удалить ВСЕ операции за всё время?\n\n• Найдено операций: {total_ops} шт.\n• Данные будут удалены безвозвратно!", get_yes_no_keyboard(show_back=True))\n        return True

    # 6. УДАЛИТЬ ПОСЛЕДНЮЮ ОПЕРАЦИЮ
    delete_last_fast_triggers = [
        "удали последнюю операцию", "удалить последнюю операцию", "отмени последнюю запись",
        "удали последнюю трату", "удалить последнюю", "удали последнюю"
    ]
    if (state == "" or state == "history_view") and any(clean_t == trig for trig in delete_last_fast_triggers):
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

    # 7. ИНТЕРАКТИВНОЕ МЕНЮ ИСТОРИИ
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
        if "удалить" in clean_t:
            user_states[user_id]["state"] = "confirm_delete_tx"
            send_vk_message(user_id, f"⚠️ Вы уверены, что хотите безвозвратно удалить операцию?\n\n• {sel_op['article']} — {sel_op['amount']:g} руб.\n• Категория: {sel_op['category']} -> {sel_op['subcategory']}", get_yes_no_keyboard(show_back=True))
            return True
        elif "сумму" in clean_t:
            user_states[user_id]["state"] = "history_edit_amount"
            send_vk_message(user_id, f"✏️ Текущая сумма: {sel_op['amount']:g} руб.\nВведите новую сумму (например: 550):", get_cancel_keyboard(show_back=True))
            return True
        elif "категорию" in clean_t or "подкатегорию" in clean_t:
            user_states[user_id]["state"] = "history_edit_category"
            send_vk_message(user_id, f"📂 Текущая категория: {sel_op['category']} -> {sel_op['subcategory']}\nНапишите правильную категорию или статью:", get_cancel_keyboard(show_back=True))
            return True
        elif any(t in clean_t for t in promote_triggers):
            orig = sel_op.get("original_text") or sel_op["article"]
            promote_synonym_to_article(internal_uid, sel_op["type"], sel_op["category"], sel_op["subcategory"], orig)
            send_vk_message(user_id, f"✅ Готово! Статья «{orig.capitalize()}» создана в подкатегории «{sel_op['subcategory']}».", get_main_keyboard(user_id))
            del user_states[user_id]
            return True

        # Перенос выбранной операции в новую статью
        new_art_sel_match = re.search(
            r'^(?:перенеси|перенести|создай|создать|сделай|сделать|добавь)?\s*(?:в|на)?\s*нов(?:ую|ая|ой)\s*стать(?:ю|я|е)\s*(?:под\s*названием|с\s*названием|это|как)?\s*(.+)$',
            clean_t
        )
        if new_art_sel_match:
            raw_art = new_art_sel_match.group(1).strip()
            clean_art = re.sub(r'\bна\s+стенн', 'настенн', raw_art, flags=re.IGNORECASE).strip().capitalize()
            promote_synonym_to_article(internal_uid, sel_op["type"], sel_op["category"], sel_op["subcategory"], clean_art)
            learn_user_word(internal_uid, sel_op["type"], sel_op["category"], sel_op["subcategory"], clean_art, clean_art)
            orig_desc = sel_op.get("original_text") or sel_op["article"]
            if orig_desc and orig_desc.lower() != clean_art.lower():
                learn_user_word(internal_uid, sel_op["type"], sel_op["category"], sel_op["subcategory"], clean_art, orig_desc)
            update_transaction_category(internal_uid, sel_op["id"], sel_op["category"], sel_op["subcategory"], clean_art, op_type=sel_op["type"])
            send_vk_message(user_id, f"✅ Создана новая статья «{clean_art}»!\nОперация успешно перенесена:\n📂 {sel_op['category']} -> {sel_op['subcategory']} (статья: «{clean_art}»)\n💰 {sel_op['amount']:g} руб.", get_main_keyboard(user_id))
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
        if db_match["status"] != "FOUND":
            alt_type = "Доход" if op_type == "Расход" else "Расход"
            alt_db_match = smart_search_item(internal_uid, user_text, op_type=alt_type)
            if alt_db_match.get("status") == "FOUND":
                db_match = alt_db_match
                op_type = alt_type
            else:
                db_match = smart_search_item(internal_uid, user_text, op_type=None)

        if db_match["status"] == "FOUND":
            target_cat = db_match["category"]
            target_sub = db_match["subcategory"]
            target_art = db_match.get("article", orig_art)
            final_type = db_match.get("type", op_type)
        else:
            c_tree, s_tree = _match_category_tree(menu_full, op_type, user_text)
            final_type = op_type
            if not c_tree:
                alt_type = "Доход" if op_type == "Расход" else "Расход"
                c_alt, s_alt = _match_category_tree(menu_full, alt_type, user_text)
                if c_alt:
                    c_tree, s_tree = c_alt, s_alt
                    final_type = alt_type

            if c_tree and s_tree:
                target_cat, target_sub = c_tree, s_tree
                target_art = _find_best_matching_article_in_sub(menu_full, final_type, target_cat, target_sub, orig_art)
            else:
                send_vk_message(user_id, "🧠 Подбираю категорию с помощью ИИ...", get_cancel_keyboard(show_back=True))
                type_menu = menu_full.get(op_type, {})
                menu_str = f"[{op_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])
                ai_cat, ai_sub = categorize_with_ai(orig_art, menu_str, context=user_text)
                v_cat, v_sub = _validate_ai_category_choice(menu_full, op_type, ai_cat, ai_sub)

                if not v_cat:
                    alt_type = "Доход" if op_type == "Расход" else "Расход"
                    alt_menu = menu_full.get(alt_type, {})
                    alt_menu_str = f"[{alt_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in alt_menu.items()])
                    ai_cat2, ai_sub2 = categorize_with_ai(orig_art, alt_menu_str, context=user_text)
                    v_cat2, v_sub2 = _validate_ai_category_choice(menu_full, alt_type, ai_cat2, ai_sub2)
                    if v_cat2:
                        v_cat, v_sub = v_cat2, v_sub2
                        final_type = alt_type

                target_cat = v_cat or "Разное"
                target_sub = v_sub or "Требует проверки"
                target_art = _find_best_matching_article_in_sub(menu_full, final_type, target_cat, target_sub, orig_art)

        update_transaction_category(internal_uid, sel_op["id"], target_cat, target_sub, target_art, op_type=final_type)
        if target_cat != "Разное" and target_sub != "Требует проверки":
            learn_user_word(internal_uid, final_type, target_cat, target_sub, target_art, orig_art)
            learn_user_word(internal_uid, final_type, target_cat, target_sub, target_art, user_text)
        
        type_str = f" ({final_type})" if final_type != sel_op.get("type") else ""
        send_vk_message(user_id, f"✅ Категория операции «{orig_art}» успешно изменена:\n📂 {target_cat} -> {target_sub} (статья: «{target_art}»){type_str}", get_main_keyboard(user_id))
        del user_states[user_id]
        return True

    if state == "confirm_delete_tx":
        if any(w in clean_t for w in ["да", "верно", "ага", "yes", "+", "удалить"]):
            tx_id = user_states[user_id].get("tx_id") or (user_states[user_id].get("sel_op", {}).get("id"))
            desc = user_states[user_id].get("desc") or (user_states[user_id].get("sel_op", {}).get("article", "Операция"))
            if tx_id and delete_transaction_by_id(internal_uid, tx_id):
                send_vk_message(user_id, f"🗑 Успешно удалено: «{desc}».", get_main_keyboard(user_id))
            del user_states[user_id]
            return True
        elif any(w in clean_t for w in ["нет", "неверно", "отмена"]):
            del user_states[user_id]
            send_vk_message(user_id, "Удаление отменено.", get_main_keyboard(user_id))
            return True

    if state == "confirm_delete_all_tx":
        if any(w in clean_t for w in ["да", "верно", "ага", "yes", "+", "удалить", "очисти"]):
            period = user_states[user_id].get("period", "all")
            cnt = delete_all_user_transactions(internal_uid, period=period)
            send_vk_message(user_id, f"🗑 Успешно удалено операций: {cnt} из базы данных.", get_main_keyboard(user_id))
            del user_states[user_id]
            return True
        elif any(w in clean_t for w in ["нет", "неверно", "отмена", "назад"]):
            del user_states[user_id]
            send_vk_message(user_id, "Массовое удаление отменено.", get_main_keyboard(user_id))
            return True

    return False
