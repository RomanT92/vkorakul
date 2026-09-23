# -*- coding: utf-8 -*-
import difflib
import json
import re
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
from db.transactions import delete_unverified_by_text, promote_synonym_to_article
from handlers_tx_parser import (
    detect_operation_type,
    _match_category_tree,
    _validate_ai_category_choice,
    _find_best_matching_article_in_sub
)

ORDINAL_MAP = {
    "перв": 1, "один": 1, "1": 1,
    "втор": 2, "два": 2, "2": 2,
    "трет": 3, "три": 3, "3": 3,
    "четверт": 4, "четыр": 4, "4": 4,
    "пят": 5, "5": 5,
    "шест": 6, "6": 6,
    "сед": 7, "сем": 7, "7": 7,
    "восьм": 8, "8": 8,
    "девят": 9, "9": 9,
    "десят": 10, "10": 10,
    "одиннадцат": 11, "11": 11,
    "двенадцат": 12, "12": 12,
    "тринадцат": 13, "13": 13,
    "четырнадцат": 14, "14": 14,
    "пятнадцат": 15, "15": 15,
    "последн": -1
}

def _find_category_in_menu(menu_full, hint_text):
    """Полноценный трехуровневый поиск по меню категорий и подкатегорий."""
    clean = hint_text.lower().strip()
    cat_candidates = []
    sub_candidates = []

    for m_type in ["Расход", "Доход"]:
        type_cats = menu_full.get(m_type, {})
        for cat_name, subs in type_cats.items():
            sub_keys = list(subs.keys()) if isinstance(subs, dict) else (subs if subs else [])

            # 1. ТОЧНОЕ СОВПАДЕНИЕ
            if cat_name.lower() == clean:
                matching_sub = next((s for s in sub_keys if s.lower() == clean), (sub_keys[0] if sub_keys else "Разное"))
                return True, m_type, cat_name, matching_sub

            for s_name in sub_keys:
                if s_name.lower() == clean:
                    return True, m_type, cat_name, s_name

            # 2. ЧАСТИЧНОЕ ВХОЖДЕНИЕ
            if len(clean) >= 3:
                if clean in cat_name.lower() or cat_name.lower() in clean:
                    matching_sub = sub_keys[0] if sub_keys else "Разное"
                    return True, m_type, cat_name, matching_sub
                for s_name in sub_keys:
                    if clean in s_name.lower() or s_name.lower() in clean:
                        return True, m_type, cat_name, s_name

            cat_candidates.append((cat_name.lower(), m_type, cat_name, sub_keys))
            for s_name in sub_keys:
                sub_candidates.append((s_name.lower(), m_type, cat_name, s_name))

    # 3. НЕЧЕТКИЙ ПОИСК
    all_sub_names = [item[0] for item in sub_candidates]
    matches_sub = difflib.get_close_matches(clean, all_sub_names, n=1, cutoff=0.68)
    if matches_sub:
        matched_str = matches_sub[0]
        for item in sub_candidates:
            if item[0] == matched_str:
                return True, item[1], item[2], item[3]

    all_cat_names = [item[0] for item in cat_candidates]
    matches_cat = difflib.get_close_matches(clean, all_cat_names, n=1, cutoff=0.68)
    if matches_cat:
        matched_str = matches_cat[0]
        for item in cat_candidates:
            if item[0] == matched_str:
                sub_keys = item[3]
                matching_sub = sub_keys[0] if sub_keys else "Разное"
                return True, item[1], item[2], matching_sub

    return False, None, None, None

def _apply_category_to_item(internal_uid, it, hint_text, menu_full, state):
    """
    Определяет правильную пару Категория -> Подкатегория -> Статья по подсказке пользователя:
    1. Поиск по БД через smart_search_item (знает 'подарок', 'мясо', 'аптека', 'самозанятость')
    2. Поиск по дереву категорий
    3. Резерв через ИИ с валидацией
    """
    current_art_name = it.get("article") or it.get("original_item") or it.get("item") or "Операция"
    op_type = it.get("type", "Расход")
    found_cat, found_sub = None, None
    m_type = op_type
    target_art = current_art_name

    # 1. ПРИОРИТЕТ: Поиск подсказки в базе данных
    db_match = smart_search_item(internal_uid, hint_text, op_type=op_type)
    if db_match.get("status") != "FOUND":
        alt_type = "Доход" if op_type == "Расход" else "Расход"
        alt_db = smart_search_item(internal_uid, hint_text, op_type=alt_type)
        if alt_db.get("status") == "FOUND":
            db_match = alt_db
            m_type = alt_type
        else:
            db_match = smart_search_item(internal_uid, hint_text, op_type=None)

    if db_match.get("status") == "FOUND":
        m_type = db_match.get("type", op_type)
        found_cat = db_match["category"]
        found_sub = db_match["subcategory"]
        target_art = db_match.get("article") or _find_best_matching_article_in_sub(menu_full, m_type, found_cat, found_sub, current_art_name)
    else:
        # 2. Поиск по дереву меню
        is_match, menu_m_type, c_name, s_name = _find_category_in_menu(menu_full, hint_text)
        if is_match:
            m_type = menu_m_type
            found_cat = c_name
            found_sub = s_name
            target_art = _find_best_matching_article_in_sub(menu_full, m_type, found_cat, found_sub, current_art_name)
        else:
            # 3. Резерв через ИИ
            type_menu = menu_full.get(op_type, {})
            menu_str = f"[{op_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])
            ai_c, ai_s = categorize_with_ai(current_art_name, menu_str, context=hint_text)
            v_c, v_s = _validate_ai_category_choice(menu_full, op_type, ai_c, ai_s)
            found_cat = v_c or "Разное"
            found_sub = v_s or "Требует проверки"
            target_art = _find_best_matching_article_in_sub(menu_full, op_type, found_cat, found_sub, current_art_name)

    # Сохраняем результат
    if state == "history_view" and "id" in it:
        update_transaction_category(internal_uid, it["id"], found_cat, found_sub, target_art, op_type=m_type)
        it["category"] = found_cat
        it["subcategory"] = found_sub
        it["article"] = target_art
        it["type"] = m_type
    else:
        it["category"] = found_cat
        it["subcategory"] = found_sub
        it["article"] = target_art
        if m_type:
            it["type"] = m_type
        it["is_known"] = (found_sub != "Требует проверки" and found_cat != "Разное")

    if found_cat != "Разное" and found_sub != "Требует проверки":
        learn_user_word(internal_uid, m_type, found_cat, found_sub, target_art, current_art_name)
        learn_user_word(internal_uid, m_type, found_cat, found_sub, target_art, hint_text)

    return found_cat, found_sub

def _try_fast_deterministic_single_clause(clause_text, items_len):
    """
    Разбор одной клаузы (например: 'у первой измени сумму на 600') за 1 мс.
    """
    clean = clause_text.strip()
    target_idx = None
    for token in clean.split():
        for prefix, num in ORDINAL_MAP.items():
            if token.startswith(prefix):
                target_idx = (items_len - 1) if num == -1 else (num - 1)
                break
        if target_idx is not None:
            break

    if target_idx is None or not (0 <= target_idx < items_len):
        return None

    # 1. Создание новой статьи для конкретной операции
    # Примеры: "у второго это настенные часы в новую статью", "перенеси в новую статью настенные часы", "в новую статью настенные часы"

    new_art_m = re.search(r'(?:перенеси|перенести|создай|создать|сделай|сделать|запиши)?\s*(?:в|на)?\s*нов(?:ую|ая|ой)\s*стать(?:ю|я|е)\s*(?:под\s*названием|с\s*названием|это|как)?\s*(.+)$', clean)
    if not new_art_m:
        new_art_m = re.search(r'(?:это|назови)?\s*(.+?)\s*(?:в|на)?\s*нов(?:ую|ая|ой)\s*стать(?:ю|я|е)$', clean)
    if new_art_m:
        val_art = new_art_m.group(1).strip()
        val_art = re.sub(r'^(?:в|на|под\s*названием|это|как)\s+', '', val_art).strip()
        val_art = re.sub(r'\bна\s+стенн', 'настенн', val_art, flags=re.IGNORECASE).strip()
        if val_art and not any(sw in val_art for sw in ["удали", "отмена", "назад", "сумм"]):
            return {"action": "create_article", "index": target_idx, "name": val_art}

    # 2. Изменение суммы
    amt_m = re.search(r'(?:сумму|сумма|поменяй сумму|измени сумму|поставь сумму)\s*(?:на|в|равна)?\s*(\d+(?:[.,]\d+)?)$', clean)
    if not amt_m:
        amt_m = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:руб|рублей|р)?$', clean)
    if amt_m and ("сумм" in clean or "на" in clean):
        try:
            return {"action": "edit_amount", "index": target_idx, "amount": float(amt_m.group(1).replace(',', '.'))}
        except ValueError:
            pass

    # 3. Переименование названия товара
    rename_m = re.search(r'(?:назови|переименуй|исправь название|название)\s*(?:как|в|на)?\s+(.+)$', clean)
    if rename_m:
        val = rename_m.group(1).strip()
        val = re.sub(r'^(?:как|в|на)\s+', '', val).strip()
        return {"action": "rename_item", "index": target_idx, "name": val}

    # 4. Удаление
    if any(w in clean for w in ["удали", "стереть", "убрать", "вычеркни"]):
        return {"action": "delete", "index": target_idx}

    # 5. Изменение категории / статьи
    cat_m = re.search(r'(?:категорию|категория|статью|статья)\s*(?:это|в|на|как)?\s+(.+)$', clean)
    if not cat_m:
        cat_m = re.search(r'(?:измени|поменяй|поставь|смени|перенеси)\s*(?:на|в|как)\s+(.+)$', clean)
    if cat_m:
        hint = cat_m.group(1).strip()
        hint = re.sub(r'^(?:на|в|как|категорию|статью)\s+', '', hint).strip()
        stop_words = ["удали", "готово", "сохрани", "отмена", "назад"]
        if hint and not any(sw in hint for sw in stop_words):
            return {"action": "set_category", "index": target_idx, "hint": hint}

    return None

def _parse_compound_voice_command(user_text_lower, items_len):
    """
    Разбивает составную фразу на несколько клауз по знакам препинания и союзам.
    Пример: 'У первой измени сумму на 600, у второй название на обед, а у третьей категорию на быт.'
    """
    clean_text = re.sub(r'[!?«»"\'\-]+', ' ', user_text_lower).strip()
    raw_clauses = re.split(r'[,.]+|\s+(?:а|и)\s+(?=(?:у\s+)?(?:перв|втор|трет|четверт|пят|шест|сед|сем|восьм|девят|десят|\d+))', clean_text)

    actions = []
    for cl in raw_clauses:
        cl_clean = cl.strip()
        if not cl_clean:
            continue
        parsed = _try_fast_deterministic_single_clause(cl_clean, items_len)
        if parsed:
            actions.append(parsed)

    return actions

def handle_list_voice_commands(user_id, user_text, user_text_lower, state, user_states):
    target_states = ["multi_tx_review", "receipt_review", "queue_batch_review", "history_view"]
    internal_uid = get_or_create_user(user_id)

    # ====================================================================
    # 1. ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ ("Да" / "Нет")
    # ====================================================================
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

            elif prev_state == "queue_batch_review":
                batch = state_data["current_batch"]
                total_deleted = 0
                del_names = []
                for idx in sorted(indices, reverse=True):
                    if 0 <= idx < len(batch):
                        it = batch.pop(idx)
                        del_names.append(it["original_item"])
                        total_deleted += delete_unverified_by_text(internal_uid, it["original_item"], it.get("type"))

                send_vk_message(
                    user_id,
                    f"🗑 Удалено {len(del_names)} позиций ({total_deleted} транзакций из базы)!\n"
                    f"Они занесены в чёрный список."
                )
                user_states[user_id]["state"] = prev_state
                from handlers_queue import _process_next_batch, _show_batch_items
                if not batch:
                    _process_next_batch(user_id, user_states)
                else:
                    _show_batch_items(user_id, batch, len(state_data.get("queue", [])), show_apply_all=False)
                return True

            else:
                items = state_data["items"]
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
        "удали", "убери", "измени", "поставь", "исправь", "это", "рубл", "сумму",
        "название", "товар", "все", "всё", "всех", "очисти", "категори", "тоже",
        "также", "перв", "втор", "трет", "четверт", "пят", "шест", "седьм", "восьм",
        "девят", "десят", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
        "операци", "строк", "пункт", "корзин", "мусор", "стать", "нов"
    ]
    if not any(t in user_text_lower for t in cmd_triggers):
        return False

    state_data = user_states[user_id]
    items_key = "history_items" if state == "history_view" else ("current_batch" if state == "queue_batch_review" else "items")
    if state == "history_view":
        items = state_data.get("history_data", {}).get("items", [])
    else:
        items = state_data.get(items_key, [])

    if not items:
        return False

    menu_full = get_full_menu(internal_uid)
    report_lines = []

    # ====================================================================
    # 2. МУЛЬТИ-КОМАНДЫ (БЫСТРЫЙ РАЗБОР СОСТАВНЫХ ПРЕДЛОЖЕНИЙ)
    # ====================================================================
    compound_actions = _parse_compound_voice_command(user_text_lower, len(items))
    if compound_actions:
        indices_to_delete = []
        for act in compound_actions:
            idx = act["index"]
            it = items[idx]
            old_name = it.get("item") or it.get("article", "Операция")

            if act["action"] == "create_article":
                clean_art = act["name"].strip()
                clean_art = re.sub(r'\bна\s+стенн', 'настенн', clean_art, flags=re.IGNORECASE).strip().capitalize()
                cur_cat = it.get("category", "Разное")
                cur_sub = it.get("subcategory", "Разное")
                op_type = it.get("type", "Расход")

                promote_synonym_to_article(internal_uid, op_type, cur_cat, cur_sub, clean_art)
                learn_user_word(internal_uid, op_type, cur_cat, cur_sub, clean_art, clean_art)
                orig_desc = it.get("original_text") or it.get("article") or it.get("item")
                if orig_desc and orig_desc.lower() != clean_art.lower():
                    learn_user_word(internal_uid, op_type, cur_cat, cur_sub, clean_art, orig_desc)

                if state == "history_view" and "id" in it:
                    update_transaction_category(internal_uid, it["id"], cur_cat, cur_sub, clean_art, op_type=op_type)

                it["article"] = clean_art
                it["item"] = clean_art
                report_lines.append(f"• №{idx+1}: 🆕 создана статья «{clean_art}» (📂 {cur_cat} -> {cur_sub})")

            elif act["action"] == "edit_amount":
                new_amt = act["amount"]
                old_amt = it.get("amount", 0)
                it["amount"] = new_amt
                if state == "history_view" and "id" in it:
                    update_transaction_amount(internal_uid, it["id"], new_amt)
                report_lines.append(f"• №{idx+1} («{old_name}»): сумма {old_amt:g} ➔ {new_amt:g} руб.")

            elif act["action"] == "rename_item":
                new_n = act["name"].capitalize()
                it["item"] = new_n
                it["article"] = new_n
                cat, sub = _apply_category_to_item(internal_uid, it, new_n, menu_full, state)
                report_lines.append(f"• №{idx+1}: название изменено на «{new_n}» (📂 {cat} -> {sub})")

            elif act["action"] == "set_category":
                cat, sub = _apply_category_to_item(internal_uid, it, act["hint"], menu_full, state)
                report_lines.append(f"• №{idx+1} («{old_name}»): категория 📂 {cat} -> {sub}")

            elif act["action"] == "delete":
                indices_to_delete.append(idx)

        if indices_to_delete:
            for d_idx in sorted(set(indices_to_delete), reverse=True):
                del_it = items.pop(d_idx)
                d_name = del_it.get("item") or del_it.get("article", "Операция")
                if state == "history_view" and "id" in del_it:
                    delete_transaction_by_id(internal_uid, del_it["id"])
                report_lines.append(f"• №{d_idx+1} («{d_name}»): удалено из списка")

        if report_lines:
            send_vk_message(user_id, "✅ Изменения применены:\n" + "\n".join(report_lines))
            _refresh_screen(user_id, state, state_data)
            return True

    # ====================================================================
    # 3. ЕСЛИ СОСТАВНОЙ ШАБЛОН НЕ СРАБОТАЛ — ПЕРЕДАЕМ В ИИ-ПАРСЕР
    # ====================================================================
    parsed_cmd = parse_voice_list_command_with_ai(user_text)
    action = parsed_cmd.get("action") if parsed_cmd else None
    if action == "unknown" or not action:
        return False

    # 3.1 BATCH SET / BATCH UPDATE (УНИВЕРСАЛЬНЫЙ ПАКЕТ ИЗ ИИ)
    if action in ["batch_set", "batch_update"]:
        updates = parsed_cmd.get("updates", [])
        for up in updates:
            idx = int(up.get("index", 0)) - 1
            if not (0 <= idx < len(items)):
                continue
            it = items[idx]
            old_name = it.get("item") or it.get("article", "Операция")

            if "new_article" in up or "new_article_name" in up:
                raw_new_art = up.get("new_article") or up.get("new_article_name")
                clean_art = re.sub(r'\bна\s+стенн', 'настенн', str(raw_new_art).strip(), flags=re.IGNORECASE).strip().capitalize()
                cur_cat = it.get("category", "Разное")
                cur_sub = it.get("subcategory", "Разное")
                op_type = it.get("type", "Расход")

                promote_synonym_to_article(internal_uid, op_type, cur_cat, cur_sub, clean_art)
                learn_user_word(internal_uid, op_type, cur_cat, cur_sub, clean_art, clean_art)
                orig_desc = it.get("original_text") or it.get("article") or it.get("item")
                if orig_desc and orig_desc.lower() != clean_art.lower():
                    learn_user_word(internal_uid, op_type, cur_cat, cur_sub, clean_art, orig_desc)

                if state == "history_view" and "id" in it:
                    update_transaction_category(internal_uid, it["id"], cur_cat, cur_sub, clean_art, op_type=op_type)

                it["article"] = clean_art
                it["item"] = clean_art
                report_lines.append(f"• №{idx+1}: 🆕 создана статья «{clean_art}» (📂 {cur_cat} -> {cur_sub})")

            if "amount" in up:
                new_a = float(up["amount"])
                it["amount"] = new_a
                if state == "history_view" and "id" in it:
                    update_transaction_amount(internal_uid, it["id"], new_a)
                report_lines.append(f"• №{idx+1} («{old_name}»): сумма изменена на {new_a:g} руб.")

            if "name" in up or "new_name" in up:
                new_n = (up.get("name") or up.get("new_name")).capitalize()
                it["item"] = new_n
                it["article"] = new_n
                cat, sub = _apply_category_to_item(internal_uid, it, new_n, menu_full, state)
                report_lines.append(f"• №{idx+1}: название изменено на «{new_n}» (📂 {cat} -> {sub})")

            if "hint" in up or "category" in up:
                h = up.get("hint") or up.get("category")
                cat, sub = _apply_category_to_item(internal_uid, it, h, menu_full, state)
                report_lines.append(f"• №{idx+1} («{old_name}»): категория 📂 {cat} -> {sub}")

        if report_lines:
            send_vk_message(user_id, "✅ Изменения применены:\n" + "\n".join(report_lines))
            _refresh_screen(user_id, state, state_data)
            return True

    raw_indices = parsed_cmd.get("indices")
    if not raw_indices and "index" in parsed_cmd:
        raw_indices = [parsed_cmd["index"]]
    if not raw_indices:
        raw_indices = []
    valid_indices = [int(i) - 1 for i in raw_indices if 0 <= int(i) - 1 < len(items)]

    # 3.2 CREATE ARTICLE (СОЗДАНИЕ СТАТЬИ И ПРИВЯЗКА ЧЕРЕЗ ИИ)
    if action == "create_article":
        new_art = (parsed_cmd.get("name") or parsed_cmd.get("new_article_name") or "").strip()
        if valid_indices and new_art:
            idx = valid_indices[0]
            it = items[idx]
            clean_art = re.sub(r'\bна\s+стенн', 'настенн', new_art, flags=re.IGNORECASE).strip().capitalize()
            cur_cat = it.get("category", "Разное")
            cur_sub = it.get("subcategory", "Разное")
            op_type = it.get("type", "Расход")

            promote_synonym_to_article(internal_uid, op_type, cur_cat, cur_sub, clean_art)
            learn_user_word(internal_uid, op_type, cur_cat, cur_sub, clean_art, clean_art)
            orig_desc = it.get("original_text") or it.get("article") or it.get("item")
            if orig_desc and orig_desc.lower() != clean_art.lower():
                learn_user_word(internal_uid, op_type, cur_cat, cur_sub, clean_art, orig_desc)

            if state == "history_view" and "id" in it:
                update_transaction_category(internal_uid, it["id"], cur_cat, cur_sub, clean_art, op_type=op_type)

            it["article"] = clean_art
            it["item"] = clean_art
            send_vk_message(
                user_id,
                f"✅ Позиция №{idx+1} обновлена:\n🆕 Создана статья «{clean_art}»!\n📂 {cur_cat} -> {cur_sub}"
            )
            _refresh_screen(user_id, state, state_data)
            return True

    # 3.3 SET CATEGORY
    if action == "set_category":
        hint_text = (parsed_cmd.get("hint") or parsed_cmd.get("category") or "").strip()
        if not valid_indices and any(w in user_text_lower for w in ["все", "всё"]):
            valid_indices = list(range(len(items)))

        if valid_indices and hint_text:
            found_cat, found_sub = None, None
            for idx in valid_indices:
                found_cat, found_sub = _apply_category_to_item(internal_uid, items[idx], hint_text, menu_full, state)
            indices_str = ", ".join([f"№{i+1}" for i in valid_indices])
            send_vk_message(user_id, f"✅ Позиции {indices_str} обновлены:\n📂 {found_cat} -> {found_sub}")
            _refresh_screen(user_id, state, state_data)
            return True

    # 3.4 RENAME ITEM
    if action in ["rename_item", "rename_item_and_amount"]:
        new_name = (parsed_cmd.get("name") or parsed_cmd.get("new_name") or "").strip()
        new_amount = float(parsed_cmd.get("amount", 0)) if action == "rename_item_and_amount" else None

        is_menu_match, m_type, c_name, s_name = _find_category_in_menu(menu_full, new_name)
        if is_menu_match and not any(w in user_text_lower for w in ["назови", "переименуй", "название"]):
            if valid_indices:
                for idx in valid_indices:
                    _apply_category_to_item(internal_uid, items[idx], new_name, menu_full, state)
                indices_str = ", ".join([f"№{i+1}" for i in valid_indices])
                send_vk_message(user_id, f"✅ Позиции {indices_str} обновлены:\n📂 {c_name} -> {s_name}")
                _refresh_screen(user_id, state, state_data)
                return True

        if valid_indices and new_name:
            idx = valid_indices[0]
            it = items[idx]
            clean_name = new_name.capitalize()
            it["item"] = clean_name
            it["article"] = clean_name
            cat, sub = _apply_category_to_item(internal_uid, it, clean_name, menu_full, state)

            if new_amount:
                it["amount"] = new_amount
                if state == "history_view" and "id" in it:
                    update_transaction_amount(internal_uid, it["id"], new_amount)

            amt_info = f" ({new_amount:g} руб.)" if new_amount else ""
            send_vk_message(
                user_id,
                f"✅ Позиция №{idx+1} обновлена:\n• Название: «{clean_name}»{amt_info}\n• Категория: 📂 {cat} -> {sub}"
            )
            _refresh_screen(user_id, state, state_data)
            return True

    # 3.5 EDIT AMOUNT
    if action == "edit_amount":
        new_amount = float(parsed_cmd.get("amount", 0))
        if valid_indices and new_amount > 0:
            idx = valid_indices[0]
            it = items[idx]
            name = it.get("article") or it.get("original_item") or it.get("item") or "Операция"
            old_amt = it.get("amount", 0)
            it["amount"] = new_amount
            if state == "history_view" and "id" in it:
                update_transaction_amount(internal_uid, it["id"], new_amount)
            send_vk_message(user_id, f"✅ Сумма позиции №{idx+1} («{name}») изменена: {old_amt:g} руб. ➔ {new_amount:g} руб.")
            _refresh_screen(user_id, state, state_data)
            return True

    # 3.6 DELETE
    if action in ["delete", "delete_all", "delete_last_n"]:
        del_indices = []
        if action == "delete_all":
            del_indices = list(range(len(items)))
        elif action == "delete_last_n":
            count_n = int(parsed_cmd.get("count", 1))
            del_indices = list(range(max(0, len(items) - count_n), len(items)))
        else:
            del_indices = valid_indices

        if not del_indices:
            send_vk_message(user_id, "⚠️ Не удалось определить позиции для удаления в списке.")
            return True

        if len(del_indices) == len(items):
            confirm_msg = f"⚠️ Вы уверены, что хотите удалить ВСЕ {len(items)} операций из списка?\n\n"
        else:
            confirm_msg = f"⚠️ Вы уверены, что хотите удалить {len(del_indices)} поз.:\n\n"

        for idx in del_indices[:10]:
            it = items[idx]
            name = it.get("article") or it.get("original_item") or it.get("item") or "Операция"
            amt = it.get("amount", 0)
            confirm_msg += f"• №{idx+1}: {name} — {amt:g} руб.\n"

        if len(del_indices) > 10:
            confirm_msg += f"... и еще {len(del_indices) - 10} операций.\n"

        user_states[user_id] = {
            "state": "confirm_voice_delete",
            "prev_state": state,
            "delete_indices": del_indices,
            "history_items": items if state == "history_view" else None,
            "current_batch": items if state == "queue_batch_review" else None,
            items_key: items
        }
        send_vk_message(user_id, confirm_msg, get_yes_no_keyboard(show_back=True))
        return True

    return False

def _refresh_screen(user_id, state, state_data):
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
