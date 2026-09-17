# -*- coding: utf-8 -*-
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
    extract_receipt_items_pipeline,
    categorize_with_ai
)
from db import (
    get_or_create_user,
    smart_search_item,
    save_transaction,
    get_full_menu,
    learn_user_word
)

def _format_amt(amount):
    """Форматирует число без лишних нулей для удобного чтения."""
    try:
        val = float(amount)
        if val.is_integer():
            return f"{int(val)}"
        return f"{val:.2f}"
    except Exception:
        return str(amount)

def _show_receipt_items(user_id, items):
    """Выводит пронумерованный список товаров из чека с подсчетом общей суммы."""
    msg = "📋 Распознанные позиции чека:\n\n"
    total_sum = 0.0
    for i, item in enumerate(items):
        amt = float(item.get('amount', 0))
        total_sum += amt
        amt_str = _format_amt(amt)
        cat = item.get('category', '?')
        sub = item.get('subcategory', '?')
        msg += f"{i+1}. {item.get('item')} — {amt_str} руб.\n"
        msg += f"   📁 {cat} ➔ {sub}\n\n"

    msg += f"💰 Сумма всех позиций: {_format_amt(total_sum)} руб.\n\n"
    msg += "👉 Если всё верно — нажмите «✅ Готово».\n"
    msg += "👉 Если нужно исправить категорию или товар — отправьте его НОМЕР."
    send_vk_message(user_id, msg, get_receipt_review_keyboard(len(items), show_back=True))

def handle_receipt(user_id, user_text, user_text_lower, state, user_states):
    """Обрабатывает логику работы с фотографиями чеков через двухэтапный конвейер."""
    internal_uid = get_or_create_user(user_id)

    # =========================================================
    # ОБРАБОТКА «НАЗАД» В ЧЕКАХ
    # =========================================================
    if "назад" in user_text_lower:
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
        if "общий итог" in user_text_lower:
            send_vk_message(user_id, "👀 Изучаю чек (общий итог)...", get_cancel_keyboard(show_back=True))
            reply_text = extract_receipt_total_with_ai(photo_url)
            del user_states[user_id]

            if reply_text:
                import re, json
                match = re.search(r'\{.*\}', reply_text, re.DOTALL)
                clean_json = match.group(0) if match else reply_text
                try:
                    parsed_data = json.loads(clean_json)
                    shop_name = str(parsed_data.get('item', 'Покупка по чеку')).strip()
                    amount = abs(float(parsed_data.get('amount', 0)))
                    comment = str(parsed_data.get('comment', '')).strip()

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
                            f"✅ Чек успешно записан!\n📁 {search_res['category']} ➔ {search_res['subcategory']}\nСумма: {_format_amt(amount)} руб.",
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
                            send_vk_message(user_id, f"🤖 Думаю, '{shop_name}' относится к:\n📁 {ai_cat} ➔ {ai_sub}\n\nВсё верно?", get_yes_no_keyboard(show_back=True))
                        else:
                            user_states[user_id] = {
                                "state": "provide_context",
                                "payload": {"item": shop_name, "amount": amount, "type": "Расход", "comment": comment},
                                "menu": menu_full,
                                "menu_str": menu_str,
                                "attempts": 1
                            }
                            send_vk_message(user_id, f"🤔 Я пока не знаю магазин '{shop_name}'.\nПодскажи буквально в двух словах, что это?", get_cancel_keyboard(show_back=True))
                except Exception as e:
                    send_vk_message(user_id, f"❌ Ошибка обработки чека: {e}", get_main_keyboard(user_id))
            else:
                send_vk_message(user_id, "❌ Не удалось прочитать чек.", get_main_keyboard(user_id))
            return True

        # --- РЕЖИМ 2: ПО ПОЗИЦИЯМ (ДВУХЭТАПНЫЙ КОНВЕЙЕР) ---
        elif "по позициям" in user_text_lower:
            send_vk_message(user_id, "⏳ Подготавливаю структуру категорий...", get_cancel_keyboard(show_back=True))
            menu_full = get_full_menu(internal_uid)

            exp_menu = menu_full.get("Расход", {})
            menu_str = "[Расход]\n"
            for c, subs in exp_menu.items():
                sub_list = subs.keys() if isinstance(subs, dict) else subs
                menu_str += f"{c}: {', '.join(sub_list)}\n"

            send_vk_message(user_id, "👀 Считываю товары и проверяю цены по чеку... Это займет около 10 секунд.")
            
            # ВЫЗОВ ДВУХЭТАПНОГО КОНВЕЙЕРА:
            valid_items = extract_receipt_items_pipeline(photo_url, menu_str)

            if valid_items:
                user_states[user_id] = {
                    "state": "receipt_review",
                    "items": valid_items,
                    "menu": menu_full,
                    "menu_str": menu_str
                }
                _show_receipt_items(user_id, valid_items)
            else:
                send_vk_message(user_id, "❌ Не удалось распознать позиции на чеке. Попробуйте сфотографировать ближе или использовать «Общий итог».", get_main_keyboard(user_id))
                del user_states[user_id]
            return True

    # =========================================================
    # 2. РЕВЬЮ ПОЗИЦИЙ (Кнопка "Готово" или выбор номера)
    # =========================================================
    if state == "receipt_review":
        if "готово" in user_text_lower:
            items = user_states[user_id]["items"]
            send_vk_message(user_id, "⏳ Сохраняю позиции в базу данных...", get_cancel_keyboard(show_back=False))
            success_count = 0
            needs_review_count = 0

            for item in items:
                item_name = item.get("item", "Товар")
                amount = abs(float(item.get("amount", 0)))
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
                    original_text=item_name,
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
                    f"✏️ Исправляем: «{sel_item.get('item')}» ({_format_amt(sel_item.get('amount'))} руб.)\n"
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
