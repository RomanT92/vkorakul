# -*- coding: utf-8 -*-
import json
from keyboards import (
    get_main_keyboard,
    get_cancel_keyboard,
    get_receipt_review_keyboard,
    get_yes_no_keyboard
)
from services import (
    send_vk_message,
    extract_receipt_total_with_ai,
    extract_receipt_items_with_ai,
    categorize_with_ai
)
from db import (
    get_or_create_user,
    smart_search_item,
    save_transaction,
    get_full_menu,
    learn_user_word
)

def _clean_json_string(text):
    """Очищает строку от маркдауна ```json ... ``` если ИИ его добавил"""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:-3].strip()
    elif text.startswith("```"):
        text = text[3:-3].strip()
    return text

def _show_receipt_items(user_id, items):
    """Выводит пронумерованный список товаров из чека"""
    msg = "📋 Распознанные позиции:\n\n"
    for i, item in enumerate(items):
        msg += f"{i+1}. {item.get('item')} — {item.get('amount')} руб.\n"
        msg += f"   📂 {item.get('category', '?')} -> {item.get('subcategory', '?')}\n\n"
    msg += "Если всё верно, жмите «Готово».\nЕсли ИИ ошибся — отправьте НОМЕР товара, чтобы дать подсказку."
    send_vk_message(user_id, msg, get_receipt_review_keyboard(len(items)))

def handle_receipt(user_id, user_text, user_text_lower, state, user_states):
    """
    Обрабатывает логику работы с фотографиями чеков через PostgreSQL.
    """
    internal_uid = get_or_create_user(user_id)

    # =========================================================
    # 1. ВЫБОР РЕЖИМА (Общий итог или По позициям)
    # =========================================================
    if state == "receipt_mode_select":
        photo_url = user_states[user_id].get("photo_url")
        
        # --- РЕЖИМ 1: ОБЩИЙ ИТОГ ---
        if user_text_lower == "общий итог":
            send_vk_message(user_id, "👀 Изучаю чек (общий итог)...", get_cancel_keyboard())
            reply_text = extract_receipt_total_with_ai(photo_url)
            del user_states[user_id]

            if reply_text:
                reply_text = _clean_json_string(reply_text)
                try:
                    parsed_data = json.loads(reply_text)
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
                        send_vk_message(user_id, f"✅ Чек успешно записан!\n📂 {search_res['category']} -> {search_res['subcategory']}", get_main_keyboard())
                    else:
                        # Магазин неизвестен — просим ИИ подобрать категорию
                        menu_full = get_full_menu(internal_uid)
                        menu = menu_full.get("Расход", {})
                        menu_str = "\n".join([f"{c}: {', '.join(subs)}" for c, subs in menu.items()])
                        ai_cat, ai_sub = categorize_with_ai(shop_name, menu_str)

                        if ai_cat in menu and ai_sub in menu[ai_cat]:
                            user_states[user_id] = {
                                "state": "confirm_category",
                                "payload": {"item": shop_name, "amount": amount, "type": "Расход", "comment": comment},
                                "menu": menu_full,
                                "menu_str": menu_str,
                                "ai_cat": ai_cat,
                                "ai_sub": ai_sub,
                                "attempts": 1
                            }
                            send_vk_message(user_id, f"🤖 Думаю, '{shop_name}' относится к:\n📂 {ai_cat} -> {ai_sub}\n\nВсё верно?", get_yes_no_keyboard())
                        else:
                            user_states[user_id] = {
                                "state": "provide_context",
                                "payload": {"item": shop_name, "amount": amount, "type": "Расход", "comment": comment},
                                "menu": menu_full,
                                "menu_str": menu_str,
                                "attempts": 1
                            }
                            send_vk_message(user_id, f"🤔 Я пока не знаю магазин/статью '{shop_name}'.\nПодскажи буквально в двух словах, что это?", get_cancel_keyboard())
                except json.JSONDecodeError:
                    send_vk_message(user_id, "❌ Ошибка: ИИ вернул неправильный формат.", get_main_keyboard())
                except Exception as e:
                    send_vk_message(user_id, f"❌ Ошибка базы данных: {e}", get_main_keyboard())
            else:
                send_vk_message(user_id, "❌ Не удалось прочитать чек.", get_main_keyboard())
            return True

        # --- РЕЖИМ 2: ПО ПОЗИЦИЯМ ---
        elif user_text_lower == "по позициям":
            send_vk_message(user_id, "⏳ Загружаю структуру категорий...", get_cancel_keyboard())
            menu_full = get_full_menu(internal_uid)
            
            menu_str = ""
            for c_type in ["Расход", "Доход"]:
                menu_str += f"[{c_type}]\n"
                for c, subs in menu_full.get(c_type, {}).items():
                    menu_str += f"{c}: {', '.join(subs)}\n"

            send_vk_message(user_id, "👀 Изучаю каждую позицию в чеке (GPT-4o Vision)...")
            reply_text = extract_receipt_items_with_ai(photo_url, menu_str)

            if reply_text:
                reply_text = _clean_json_string(reply_text)
                if reply_text.startswith("[") and reply_text.endswith("]"):
                    try:
                        items = json.loads(reply_text)
                        user_states[user_id] = {
                            "state": "receipt_review",
                            "items": items,
                            "menu": menu_full,
                            "menu_str": menu_str
                        }
                        _show_receipt_items(user_id, items)
                    except json.JSONDecodeError:
                        send_vk_message(user_id, "❌ Ошибка: ИИ вернул неверный формат списка.", get_main_keyboard())
                        del user_states[user_id]
                else:
                    send_vk_message(user_id, "❌ Не удалось распознать товары на чеке.", get_main_keyboard())
                    del user_states[user_id]
            else:
                send_vk_message(user_id, "❌ Ошибка связи с ИИ при чтении чека.", get_main_keyboard())
                del user_states[user_id]
            return True

    # =========================================================
    # 2. РЕВЬЮ ПОЗИЦИЙ (Кнопка "Готово" или выбор номера)
    # =========================================================
    if state == "receipt_review":
        if user_text_lower == "готово":
            items = user_states[user_id]["items"]
            send_vk_message(user_id, "⏳ Сохраняю товары в базу данных...", get_cancel_keyboard())
            
            success_count = 0
            for item in items:
                item_name = item.get("item", "Товар")
                amount = float(item.get("amount", 0))
                cat = item.get("category", "Разное")
                sub = item.get("subcategory", "Требует проверки")
                
                # Сохраняем в PostgreSQL
                ok = save_transaction(
                    user_id=internal_uid,
                    op_type="Расход",
                    category=cat,
                    subcategory=sub,
                    article=item_name,
                    amount=amount,
                    comment="Чек по позициям",
                    original_text=item_name,
                    status='verified'
                )
                if ok:
                    success_count += 1
                    # Обучаем личный словарь товару
                    learn_user_word(internal_uid, "Расход", cat, sub, item_name, item_name)

            send_vk_message(user_id, f"🎉 Успешно сохранено {success_count} из {len(items)} позиций в базу!", get_main_keyboard())
            del user_states[user_id]
            return True

        elif user_text.isdigit():
            idx = int(user_text) - 1
            items = user_states[user_id]["items"]
            if 0 <= idx < len(items):
                user_states[user_id]["edit_idx"] = idx
                user_states[user_id]["state"] = "receipt_edit_hint"
                sel_item = items[idx]
                send_vk_message(user_id, f"✏️ Исправляем: {sel_item.get('item')}\nНапишите правильную категорию или дайте подсказку:", get_cancel_keyboard())
                return True

    # =========================================================
    # 3. ИСПРАВЛЕНИЕ КАТЕГОРИИ У КОНКРЕТНОГО ТОВАРА
    # =========================================================
    if state == "receipt_edit_hint":
        idx = user_states[user_id]["edit_idx"]
        items = user_states[user_id]["items"]
        sel_item = items[idx]
        send_vk_message(user_id, "🧠 Думаю...", get_cancel_keyboard())
        
        menu_str = user_states[user_id]["menu_str"]
        ai_cat, ai_sub = categorize_with_ai(sel_item.get("item"), menu_str, context=user_text)
        
        sel_item["category"] = ai_cat
        sel_item["subcategory"] = ai_sub
        user_states[user_id]["state"] = "receipt_review"
        _show_receipt_items(user_id, items)
        return True

    return False
