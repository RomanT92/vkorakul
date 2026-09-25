# -*- coding: utf-8 -*-
import re
from services import send_vk_message, parse_voice_list_command_with_ai
from keyboards import get_yes_no_keyboard, get_main_keyboard
from db import (
    get_or_create_user,
    get_full_menu,
    learn_user_word,
    delete_transaction_by_id,
    update_transaction_amount,
    update_transaction_category
)
from db.transactions import delete_unverified_by_text, promote_synonym_to_article

from voice_matcher import _find_category_in_menu, _apply_category_to_item
from voice_parser import _parse_compound_voice_command

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
        "операци", "строк", "пункт", "корзин", "мусор", "стать", "нов", "по"
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
    # 1.1 БЫСТРЫЙ ДИАПАЗОН («С 24 ПО 28 ЭТО ГОТОВАЯ ЕДА, НАПИТКИ»)
    # ====================================================================
    range_match = re.search(r'(?:с|от)\s*(\d+)\s*(?:по|до|-)\s*(\d+)\s*(?:это|как)?\s*(.+)$', user_text_lower)
    if range_match:
        start_n = int(range_match.group(1))
        end_n = int(range_match.group(2))
        hint_str = range_match.group(3).strip()
        if start_n > end_n:
            start_n, end_n = end_n, start_n
        target_idxs = [i - 1 for i in range(start_n, end_n + 1) if 0 <= i - 1 < len(items)]
        if target_idxs and hint_str:
            for idx in target_idxs:
                it = items[idx]
                old_n = it.get("item") or it.get("article", "Операция")
                c, s = _apply_category_to_item(internal_uid, it, hint_str, menu_full, state)
                report_lines.append(f"• №{idx+1} («{old_n}»): категория 📂 {c} -> {s}")
            send_vk_message(user_id, "✅ Изменения применены:\n" + "\n".join(report_lines))
            _refresh_screen(user_id, state, state_data)
            return True

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

    # 3.4 RENAME ITEM ИЛИ ПОДСКАЗКА КАТЕГОРИИ
    if action in ["rename_item", "rename_item_and_amount"]:
        new_name = (parsed_cmd.get("name") or parsed_cmd.get("new_name") or "").strip()
        new_amount = float(parsed_cmd.get("amount", 0)) if action == "rename_item_and_amount" else None

        # Проверяем, действительно ли пользователь хотел ПЕРЕИМЕНОВАТЬ товар из чека
        is_rename_intent = any(w in user_text_lower for w in ["назови", "переименуй", "название", "исправь название", "вместо"])

        # Если явного желания переименовывать не было — трактуем как подсказку категории/статьи!
        if not is_rename_intent:
            if valid_indices and new_name:
                for idx in valid_indices:
                    cat, sub = _apply_category_to_item(internal_uid, items[idx], new_name, menu_full, state)
                    old_n = items[idx].get("item") or items[idx].get("article", "Операция")
                    report_lines.append(f"• №{idx+1} («{old_n}»): категория 📂 {cat} -> {sub}")
                if new_amount:
                    idx = valid_indices[0]
                    items[idx]["amount"] = new_amount
                    if state == "history_view" and "id" in items[idx]:
                        update_transaction_amount(internal_uid, items[idx]["id"], new_amount)
                    report_lines.append(f"• №{idx+1}: сумма изменена на {new_amount:g} руб.")
                send_vk_message(user_id, "✅ Изменения применены:\n" + "\n".join(report_lines))
                _refresh_screen(user_id, state, state_data)
                return True

        # Только если БЫЛ явный приказ на переименование ("назови", "переименуй"):
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
