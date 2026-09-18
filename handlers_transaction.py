# -*- coding: utf-8 -*-
import json
import re
from keyboards import (
    get_main_keyboard,
    get_yes_no_keyboard,
    get_cancel_keyboard,
    type_keyboard,
    get_numbered_keyboard,
    get_multi_tx_review_keyboard
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
    get_last_transaction,
    update_transaction_amount,
    update_transaction_category
)
from handlers_history import handle_history_and_edits, _show_history_screen
from handlers_tx_parser import (
    detect_operation_type,
    clean_fallback_item,
    _try_fast_single_transaction_parse,
    _validate_ai_category_choice,
    _find_best_matching_article_in_sub,
    _match_category_tree
)

def _extract_json_data(text):
    if not text:
        return None
    match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0).strip())
        except Exception:
            pass
    return None

def _show_multi_tx_items(user_id, items, show_apply_all=False):
    msg = f"📋 Распознанные операции (всего {len(items)}):\n\n"
    for i, item in enumerate(items):
        item_name = item.get("item", "Операция")
        amount = item.get("amount", 0)
        op_type = item.get("type", "Расход")
        cat = item.get("category", "?")
        sub = item.get("subcategory", "?")
        art = item.get("article", item_name)
        comm = f" ({item['comment']})" if item.get("comment") else ""
        type_icon = "📉" if op_type == "Расход" else "📈"
        msg += f"{i+1}. {item_name} — {amount} руб. {type_icon}{comm}\n"
        msg += f"   📂 {cat} -> {sub} (статья: {art})\n\n"

    msg += "Если всё верно, жмите «✅ Готово».\n"
    if show_apply_all:
        msg += "Нажмите «⚡ Применить для всех оставшихся», чтобы продублировать категорию.\n"
    msg += "Если хотите изменить категорию статьи — отправьте её НОМЕР."
    send_vk_message(user_id, msg, get_multi_tx_review_keyboard(len(items), show_apply_all=show_apply_all, show_back=True))

def _save_items_batch(internal_uid, items):
    saved_count = 0
    needs_review_count = 0
    menu_full = get_full_menu(internal_uid)

    for item in items:
        cat = item.get("category", "Разное")
        sub = item.get("subcategory", "Требует проверки")
        orig_text = item.get("item", "Операция")
        op_type = item.get("type", "Расход")
        amount = float(item.get("amount", 0))
        comment = item.get("comment", "")
        art = item.get("article") or _find_best_matching_article_in_sub(menu_full, op_type, cat, sub, orig_text)

        status = 'needs_review' if (cat == "Разное" or sub == "Требует проверки") else 'verified'
        if status == 'needs_review':
            needs_review_count += 1
        ok = save_transaction(internal_uid, op_type, cat, sub, art, amount, comment, orig_text, status)
        if ok:
            saved_count += 1
            if status == 'verified':
                learn_user_word(internal_uid, op_type, cat, sub, art, orig_text)

    return saved_count, needs_review_count

def handle_transaction(user_id, user_text, state, user_states):
    user_text_lower = user_text.lower().strip()
    internal_uid = get_or_create_user(user_id)

    # 1. Сначала проверяем сценарии истории и правок
    if handle_history_and_edits(user_id, internal_uid, user_text, user_text_lower, state, user_states):
        return True

    # 2. Обработка кнопки Назад для массового ввода
    if "назад" in user_text_lower:
        if state == "multi_tx_edit_hint":
            user_states[user_id]["state"] = "multi_tx_review"
            _show_multi_tx_items(user_id, user_states[user_id]["items"], show_apply_all=False)
            return True
        elif state == "multi_tx_review":
            del user_states[user_id]
            send_vk_message(user_id, "Главное меню.", get_main_keyboard(user_id))
            return True

    # 3. FAST-PATH: Детерминированная запись 'Шиномонтаж 2600' за 1 миллисекунду
    fast_parsed = _try_fast_single_transaction_parse(user_text)
    if fast_parsed:
        if user_id in user_states:
            del user_states[user_id]
        f_item = fast_parsed["item"]
        f_amt = fast_parsed["amount"]
        f_op_type, _ = detect_operation_type(user_text, "Расход", f_item)

        db_res = smart_search_item(internal_uid, f_item, op_type=f_op_type)
        if db_res.get("status") != "FOUND":
            db_res = smart_search_item(internal_uid, f_item, op_type=None)

        if db_res.get("status") == "FOUND":
            final_type = db_res.get("type", f_op_type)
            cat, sub = db_res["category"], db_res["subcategory"]
            canonical_art = db_res.get("article") or f_item.capitalize()

            save_transaction(internal_uid, final_type, cat, sub, canonical_art, f_amt, "", f_item, 'verified')
            learn_user_word(internal_uid, final_type, cat, sub, canonical_art, f_item)

            syn_info = f" (статья: «{canonical_art}»)" if canonical_art.lower() != f_item.lower() else ""
            send_vk_message(user_id, f"✅ Успешно записано! ({final_type})\n📂 {cat} -> {sub}{syn_info}\n💰 {f_amt:g} руб.", get_main_keyboard(user_id))
            return True
        else:
            menu_full = get_full_menu(internal_uid)
            type_menu = menu_full.get(f_op_type, {})
            menu_str = f"[{f_op_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])
            raw_c, raw_s = categorize_with_ai(f_item, menu_str)
            v_c, v_s = _validate_ai_category_choice(menu_full, f_op_type, raw_c, raw_s)

            if v_c and v_s and v_s != "Требует проверки":
                matched_art = _find_best_matching_article_in_sub(menu_full, f_op_type, v_c, v_s, f_item)
                user_states[user_id] = {
                    "state": "confirm_category",
                    "payload": {"item": f_item, "article": matched_art, "amount": f_amt, "type": f_op_type, "category": v_c, "subcategory": v_s, "comment": ""},
                    "menu": menu_full,
                    "ai_cat": v_c,
                    "ai_sub": v_s,
                    "canonical_art": matched_art,
                    "attempts": 1
                }
                c_text = f"🤖 Думаю, «{f_item}» относится к:\n📂 {v_c} -> {v_s} (статья: «{matched_art}»)\n💰 {f_amt:g} руб.\n\nПривязать как синоним к «{matched_art}»?" if matched_art.lower() != f_item.lower() else f"🤖 Думаю, «{f_item}» относится к:\n📂 {v_c} -> {v_s}\n💰 {f_amt:g} руб.\n\nСоздать статью «{f_item.capitalize()}»?"
                send_vk_message(user_id, c_text, get_yes_no_keyboard(show_back=True, show_promote_article=(matched_art.lower() != f_item.lower())))
            else:
                user_states[user_id] = {
                    "state": "provide_context",
                    "payload": {"item": f_item, "article": f_item.capitalize(), "amount": f_amt, "type": f_op_type, "category": "Разное", "subcategory": "Требует проверки", "comment": ""},
                    "menu": menu_full,
                    "attempts": 1
                }
                send_vk_message(user_id, f"🤔 Я записал операцию на {f_amt:g} руб., но не знаю статью «{f_item}».\nПодскажи в двух словах, к чему это относится:", get_cancel_keyboard(show_back=True))
            return True

    # 4. Перехват слова без суммы (защита от «Неверный ввод»)
    if state == "" and not re.search(r'\d+', user_text) and len(user_text.split()) <= 3:
        clean_name = user_text.strip().capitalize()
        check_m = smart_search_item(internal_uid, user_text)
        cat_info = f" (📂 {check_m['category']} -> {check_m['subcategory']})" if check_m.get("status") == "FOUND" else ""
        send_vk_message(user_id, f"💡 Вижу операцию «{clean_name}»{cat_info}.\nУкажите сумму (например: «{user_text} 500»):", get_cancel_keyboard(show_back=False))
        return True

    # 5. Массовый ввод: ревью списка
    if state == "multi_tx_review":
        state_data = user_states[user_id]
        items = state_data["items"]
        if any(w in user_text_lower for w in ["готово", "сохранить", "сохрани", "да", "ок", "+", "верно", "ага"]):
            send_vk_message(user_id, "⏳ Сохраняю операции в базу данных...", get_cancel_keyboard(show_back=False))
            saved, needs = _save_items_batch(internal_uid, items)
            rep = f"🎉 Успешно сохранено {saved} операций!" + (f"\n⚠️ {needs} позиций требуют проверки." if needs else "")
            send_vk_message(user_id, rep, get_main_keyboard(user_id))
            del user_states[user_id]
            return True
        elif user_text.isdigit():
            idx = int(user_text) - 1
            if 0 <= idx < len(items):
                state_data["edit_idx"] = idx
                state_data["state"] = "multi_tx_edit_hint"
                send_vk_message(user_id, f"✏️ Исправляем: «{items[idx]['item']}» ({items[idx]['amount']} руб.)\nНапишите правильную категорию или статью:", get_cancel_keyboard(show_back=True))
                return True

    if state != "":
        return False

    # 6. Анализ сложного ввода через ИИ
    reply_text = extract_transaction_with_ai(user_text)
    if not reply_text:
        return False

    parsed_data = _extract_json_data(reply_text)
    if parsed_data:
        raw_ops = parsed_data.get("operations", [])
        if not raw_ops and "item" in parsed_data:
            raw_ops = [parsed_data]
        if not raw_ops:
            return False

        menu_full = get_full_menu(internal_uid)
        processed_items = []

        for op in raw_ops:
            amt = float(op.get("amount", 0))
            if amt <= 0 and not re.search(r'\d+', user_text):
                continue
            cur_item = op.get("item", "").strip() or clean_fallback_item(user_text)
            op_t, is_inc = detect_operation_type(user_text, op.get("type", "Расход"), cur_item)
            
            s_res = smart_search_item(internal_uid, cur_item, op_type=op_t)
            if s_res["status"] == "FOUND":
                processed_items.append({
                    "item": cur_item, "article": s_res.get("article", cur_item),
                    "amount": amt, "type": op_t, "category": s_res["category"],
                    "subcategory": s_res["subcategory"], "comment": "", "is_known": True
                })
            else:
                type_menu = menu_full.get(op_t, {})
                menu_str = f"[{op_t}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])
                rc, rs = categorize_with_ai(cur_item, menu_str)
                vc, vs = _validate_ai_category_choice(menu_full, op_t, rc, rs)
                final_c = vc or "Разное"
                final_s = vs or "Требует проверки"
                art = _find_best_matching_article_in_sub(menu_full, op_t, final_c, final_s, cur_item)
                processed_items.append({
                    "item": cur_item, "article": art, "amount": amt, "type": op_t,
                    "category": final_c, "subcategory": final_s, "comment": "", "is_known": (final_s != "Требует проверки")
                })

        if len(processed_items) == 1:
            it = processed_items[0]
            if it["is_known"]:
                save_transaction(internal_uid, it["type"], it["category"], it["subcategory"], it["article"], it["amount"], "", it["item"], 'verified')
                learn_user_word(internal_uid, it["type"], it["category"], it["subcategory"], it["article"], it["item"])
                send_vk_message(user_id, f"✅ Успешно записано! ({it['type']})\n📂 {it['category']} -> {it['subcategory']}\n💰 {it['amount']:g} руб.", get_main_keyboard(user_id))
                return True
            else:
                user_states[user_id] = {
                    "state": "confirm_category", "payload": it, "menu": menu_full,
                    "ai_cat": it["category"], "ai_sub": it["subcategory"],
                    "canonical_art": it["article"], "attempts": 1
                }
                send_vk_message(user_id, f"🤖 Думаю, «{it['item']}» относится к:\n📂 {it['category']} -> {it['subcategory']}\n💰 {it['amount']:g} руб.\n\nВсё верно?", get_yes_no_keyboard(show_back=True, show_promote_article=True))
                return True

        if len(processed_items) > 1:
            user_states[user_id] = {"state": "multi_tx_review", "items": processed_items, "menu": menu_full}
            _show_multi_tx_items(user_id, processed_items, show_apply_all=False)
            return True

    return False
