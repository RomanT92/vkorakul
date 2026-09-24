# -*- coding: utf-8 -*-
import json
import re
from keyboards import (
    get_main_keyboard,
    get_cancel_keyboard,
    get_receipt_review_keyboard,
    get_receipt_mode_keyboard,
    get_yes_no_keyboard
)
from services import (
    send_vk_message,
    extract_receipt_total_with_ai,
    extract_receipt_items_with_ai,
    categorize_batch_with_ai,
    categorize_with_ai
)
from db import (
    get_or_create_user,
    smart_search_item,
    save_transaction,
    get_full_menu,
    learn_user_word
)
from handlers_tx_parser import _match_category_tree, _find_best_matching_article_in_sub

def _extract_json_object(text):
    """Безопасно вырезает JSON-объект {...} из ответа нейросети."""
    match = re.search(r'\{.*\}', text, re.DOTALL)
    return match.group(0) if match else text.strip()

def _extract_json_array(text):
    """Безопасно вырезает JSON-массив [...] из ответа нейросети."""
    match = re.search(r'\[.*\]', text, re.DOTALL)
    return match.group(0) if match else text.strip()

def _show_receipt_items(user_id, items):
    """Выводит пронумерованный список товаров из чека."""
    msg = "📋 Распознанные позиции чека:\n\n"
    total_amt = 0.0
    for i, item in enumerate(items):
        amt = float(item.get('amount', 0))
        total_amt += amt
        cat = item.get('category', 'Разное')
        sub = item.get('subcategory', 'Требует проверки')
        icon = "✅" if (cat != "Разное" and sub != "Требует проверки") else "⚠️"
        msg += f"{i+1}. {icon} {item.get('item')} — {amt:g} руб.\n"
        msg += f"   📂 {cat} -> {sub}\n\n"

    msg += f"💰 Итого по позициям: {total_amt:g} руб.\n\n"
    msg += "👉 Если всё верно — нажмите «✅ Готово» (или скажите «Записать всё»).\n"
    msg += "👉 Чтобы изменить категорию — отправьте НОМЕР товара или скажите голосом (например: «второе это быт»)."
    send_vk_message(user_id, msg, get_receipt_review_keyboard(len(items), show_back=True))

def handle_receipt(user_id, user_text, user_text_lower, state, user_states):
    """Обрабатывает логику работы с фотографиями чеков через PostgreSQL."""
    internal_uid = get_or_create_user(user_id)

    # =========================================================
    # ОБРАБОТКА «НАЗАД» И СБРОСА В ЧЕКАХ
    # =========================================================
    if any(w in user_text_lower for w in ["назад", "отмена", "отменить"]):
        if state == "receipt_mode_select":
            del user_states[user_id]
            send_vk_message(user_id, "Главное меню.", get_main_keyboard(user_id))
            return True
        elif state == "receipt_review":
            user_states[user_id]["state"] = "receipt_mode_select"
            send_vk_message(user_id, "👀 Выберите режим записи чека:", get_receipt_mode_keyboard(show_back=True))
            return True
        elif state == "receipt_edit_hint":
            user_states[user_id]["state"] = "receipt_review"
            _show_receipt_items(user_id, user_states[user_id]["items"])
            return True

    # =========================================================
    # 1. ВЫБОР РЕЖИМА (Общий итог или По позициям)
    # =========================================================
    if state == "receipt_mode_select":
        photo_url = user_states[user_id].get("photo_url")

        # --- РЕЖИМ 1: ОБЩИЙ ИТОГ ---
        if any(w in user_text_lower for w in ["общий итог", "общий", "целиком", "быстро", "суммой"]):
            send_vk_message(user_id, "👀 Изучаю чек (общий итог)...", get_cancel_keyboard(show_back=True))
            reply_text = extract_receipt_total_with_ai(photo_url)
            del user_states[user_id]

            if reply_text:
                clean_json = _extract_json_object(reply_text)
                try:
                    parsed_data = json.loads(clean_json)
                    shop_name = parsed_data.get('item', 'Покупка по чеку')
                    amount = float(parsed_data.get('amount', 0))
                    comment = parsed_data.get('comment', '')

                    send_vk_message(user_id, f"⚡ Ищу '{shop_name}' в базе...")
                    search_res = smart_search_item(internal_uid, shop_name, "Расход")

                    if search_res["status"] == "FOUND":
                        save_transaction(
                            user_id=internal_uid,
                            op_type="Расход",
                            category=search_res["category"],
                            subcategory=search_res["subcategory"],
                            article=search_res["article"],
                            amount=amount,
                            comment=comment,
                            original_text=shop_name,
                            status='verified'
                        )
                        send_vk_message(
                            user_id,
                            f"✅ Чек успешно записан!\n📂 {search_res['category']} -> {search_res['subcategory']}\n💰 {amount:g} руб.",
                            get_main_keyboard(user_id)
                        )
                    else:
                        menu_full = get_full_menu(internal_uid)
                        menu = menu_full.get("Расход", {})
                        menu_str = "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in menu.items()])
                        ai_cat, ai_sub = categorize_with_ai(shop_name, menu_str)

                        valid_cat = ai_cat in menu and ai_sub in (menu[ai_cat].keys() if isinstance(menu[ai_cat], dict) else menu[ai_cat])

                        if valid_cat and ai_sub != "Требует проверки":
                            user_states[user_id] = {
                                "state": "confirm_category",
                                "payload": {"item": shop_name, "amount": amount, "type": "Расход", "comment": comment},
                                "menu": menu_full,
                                "menu_str": menu_str,
                                "ai_cat": ai_cat,
                                "ai_sub": ai_sub,
                                "attempts": 1
                            }
                            send_vk_message(user_id, f"🤖 Думаю, '{shop_name}' относится к:\n📂 {ai_cat} -> {ai_sub}\n\nВсё верно?", get_yes_no_keyboard(show_back=True))
                        else:
                            user_states[user_id] = {
                                "state": "provide_context",
                                "payload": {"item": shop_name, "amount": amount, "type": "Расход", "comment": comment},
                                "menu": menu_full,
                                "menu_str": menu_str,
                                "attempts": 1
                            }
                            send_vk_message(user_id, f"🤔 Я пока не знаю магазин '{shop_name}'.\nПодскажи буквально в двух словах, что это?", get_cancel_keyboard(show_back=True))
                except json.JSONDecodeError:
                    send_vk_message(user_id, "❌ Ошибка: ИИ вернул некорректный формат ответа.", get_main_keyboard(user_id))
                except Exception as e:
                    send_vk_message(user_id, f"❌ Ошибка базы данных: {e}", get_main_keyboard(user_id))
            else:
                send_vk_message(user_id, "❌ Не удалось прочитать чек.", get_main_keyboard(user_id))
            return True

        # --- РЕЖИМ 2: ПО ПОЗИЦИЯМ (ДВУХЭТАПНЫЙ БЕСШОВНЫЙ КОНВЕЙЕР) ---
        elif any(w in user_text_lower for w in ["по позициям", "позициям", "разбей", "товарам", "построчно"]):
            send_vk_message(user_id, "👀 Изучаю чек и считываю товары (GPT-4o Vision)...", get_cancel_keyboard(show_back=True))

            # ЭТАП 1: Чистый OCR строк и сумм
            reply_text = extract_receipt_items_with_ai(photo_url)

            if reply_text:
                clean_json = _extract_json_array(reply_text)
                try:
                    raw_items = json.loads(clean_json)
                    if not isinstance(raw_items, list) or len(raw_items) == 0:
                        send_vk_message(user_id, "❌ Не удалось распознать позиции на чеке. Попробуйте сфотографировать ровнее или ближе.", get_main_keyboard(user_id))
                        del user_states[user_id]
                        return True

                    # ЭТАП 2: Умная гибридная классификация (БД + быстрый батч ИИ)
                    menu_full = get_full_menu(internal_uid)
                    exp_menu = menu_full.get("Расход", {})
                    menu_str = "[Расход]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in exp_menu.items()])

                    final_items = []
                    unknown_items_for_ai = []

                    for it in raw_items:
                        item_name = str(it.get("item", "")).strip()
                        try:
                            amt = float(it.get("amount", 0))
                        except (ValueError, TypeError):
                            amt = 0.0

                        if not item_name or amt <= 0:
                            continue

                        # 1. Поиск в персональной базе синонимов
                        db_match = smart_search_item(internal_uid, item_name, op_type="Расход")
                        if db_match.get("status") != "FOUND":
                            db_match = smart_search_item(internal_uid, item_name, op_type=None)

                        if db_match.get("status") == "FOUND":
                            final_items.append({
                                "item": item_name,
                                "original_item": item_name,
                                "amount": amt,
                                "category": db_match["category"],
                                "subcategory": db_match["subcategory"]
                            })
                        else:
                            # 2. Локальный поиск по дереву категорий пользователя
                            c_tree, s_tree = _match_category_tree(menu_full, "Расход", item_name)
                            if c_tree and s_tree:
                                final_items.append({
                                    "item": item_name,
                                    "original_item": item_name,
                                    "amount": amt,
                                    "category": c_tree,
                                    "subcategory": s_tree
                                })
                            else:
                                item_obj = {
                                    "item": item_name,
                                    "original_item": item_name,
                                    "amount": amt,
                                    "category": "Разное",
                                    "subcategory": "Требует проверки"
                                }
                                final_items.append(item_obj)
                                unknown_items_for_ai.append(item_obj)

                    # 3. Пакетная классификация неизвестных позиций через ИИ
                    if unknown_items_for_ai:
                        ai_categorized = categorize_batch_with_ai(unknown_items_for_ai, menu_str)
                        for idx_unk, unk in enumerate(unknown_items_for_ai):
                            matched_res = None
                            unk_norm = unk["item"].strip().lower()

                            # Сначала ищем по точному/нормализованному названию
                            for res in ai_categorized:
                                orig_res = str(res.get("original_item", "")).strip().lower()
                                if orig_res == unk_norm:
                                    matched_res = res
                                    break

                            # Если по названию не сошлось — страхуем по индексу
                            if not matched_res and idx_unk < len(ai_categorized):
                                matched_res = ai_categorized[idx_unk]

                            if matched_res:
                                c = matched_res.get("category", "Разное")
                                s = matched_res.get("subcategory", "Требует проверки")
                                if c in exp_menu:
                                    unk["category"] = c
                                    unk["subcategory"] = s
                                else:
                                    c_fallback, s_fallback = _match_category_tree(menu_full, "Расход", unk["item"])
                                    if c_fallback and s_fallback:
                                        unk["category"] = c_fallback
                                        unk["subcategory"] = s_fallback

                    if not final_items:
                        send_vk_message(user_id, "⚠️ В чеке не найдено товаров с суммами больше нуля.", get_main_keyboard(user_id))
                        del user_states[user_id]
                        return True

                    user_states[user_id] = {
                        "state": "receipt_review",
                        "items": final_items,
                        "menu": menu_full,
                        "menu_str": menu_str
                    }
                    _show_receipt_items(user_id, final_items)
                    return True

                except json.JSONDecodeError:
                    send_vk_message(user_id, "❌ Ошибка: ИИ вернул поврежденный список товаров. Попробуйте еще раз.", get_main_keyboard(user_id))
                    del user_states[user_id]
                    return True
            else:
                send_vk_message(user_id, "❌ Ошибка связи с сервером распознавания чеков.", get_main_keyboard(user_id))
                del user_states[user_id]
                return True

    # =========================================================
    # 2. РЕВЬЮ ПОЗИЦИЙ (Кнопка "Готово" или выбор номера)
    # =========================================================
    if state == "receipt_review":
        if any(w in user_text_lower for w in ["готово", "записать всё", "записать все", "сохранить", "подтвердить"]):
            items = user_states[user_id]["items"]
            send_vk_message(user_id, "⏳ Сохраняю товары в базу данных...", get_cancel_keyboard(show_back=False))
            success_count = 0
            needs_review_count = 0

            for item in items:
                item_name = item.get("item", "Товар")
                amount = float(item.get("amount", 0))
                cat = item.get("category", "Разное")
                sub = item.get("subcategory", "Требует проверки")

                if cat == "Разное" or sub == "Требует проверки":
                    op_status = 'needs_review'
                    needs_review_count += 1
                else:
                    op_status = 'verified'

                ok = save_transaction(
                    user_id=internal_uid,
                    op_type="Расход",
                    category=cat,
                    subcategory=sub,
                    article=item_name,
                    amount=amount,
                    comment="Чек по позициям",
                    original_text=item.get("original_item", item_name),
                    status=op_status
                )
                if ok:
                    success_count += 1

                if op_status == 'verified':
                    learn_user_word(internal_uid, "Расход", cat, sub, item_name, item_name)

            report_msg = f"🎉 Успешно сохранено {success_count} позиций!"
            if needs_review_count > 0:
                report_msg += f"\n\n⚠️ {needs_review_count} позиций требуют уточнения. Вы можете распределить их кнопкой «📥 Разобрать операции»."

            send_vk_message(user_id, report_msg, get_main_keyboard(user_id))
            del user_states[user_id]
            return True

        elif user_text.isdigit():
            idx = int(user_text) - 1
            items = user_states[user_id]["items"]
            if 0 <= idx < len(items):
                user_states[user_id]["edit_idx"] = idx
                user_states[user_id]["state"] = "receipt_edit_hint"
                sel_item = items[idx]
                send_vk_message(
                    user_id,
                    f"✏️ Исправляем: «{sel_item.get('item')}» ({sel_item.get('amount')} руб.)\n"
                    f"Напишите правильную категорию или точное название статьи (например: «Хлеб», «Молоко»):",
                    get_cancel_keyboard(show_back=True)
                )
                return True

    # =========================================================
    # 3. ИСПРАВЛЕНИЕ КАТЕГОРИИ У КОНКРЕТНОГО ТОВАРА
    # =========================================================
    if state == "receipt_edit_hint":
        idx = user_states[user_id]["edit_idx"]
        items = user_states[user_id]["items"]
        sel_item = items[idx]

        db_match = smart_search_item(internal_uid, user_text, op_type="Расход")
        if db_match["status"] != "FOUND":
            db_match = smart_search_item(internal_uid, user_text, op_type=None)

        if db_match["status"] == "FOUND":
            ai_cat = db_match["category"]
            ai_sub = db_match["subcategory"]
        else:
            menu_full = get_full_menu(internal_uid)
            u_clean = user_text.lower().strip()
            found_in_tree = False
            type_cats = menu_full.get("Расход", {})
            for m_cat, m_subs in type_cats.items():
                if m_cat.lower() == u_clean:
                    ai_cat = m_cat
                    sub_keys = list(m_subs.keys()) if isinstance(m_subs, dict) else (m_subs if m_subs else [])
                    ai_sub = sub_keys[0] if sub_keys else "Разное"
                    found_in_tree = True
                    break
                sub_keys = list(m_subs.keys()) if isinstance(m_subs, dict) else (m_subs if m_subs else [])
                for s_name in sub_keys:
                    if s_name.lower() == u_clean:
                        ai_cat = m_cat
                        ai_sub = s_name
                        found_in_tree = True
                        break
                if found_in_tree:
                    break

            if not found_in_tree:
                send_vk_message(user_id, "🧠 Подбираю категорию с помощью ИИ...", get_cancel_keyboard(show_back=True))
                menu_str = user_states[user_id]["menu_str"]
                ai_cat, ai_sub = categorize_with_ai(sel_item.get("item"), menu_str, context=user_text)

        sel_item["category"] = ai_cat
        sel_item["subcategory"] = ai_sub
        user_states[user_id]["state"] = "receipt_review"
        _show_receipt_items(user_id, items)
        return True

    return False
