# -*- coding: utf-8 -*-
import json
from keyboards import (
    get_main_keyboard, get_cancel_keyboard, get_receipt_review_keyboard
)
from services import (
    send_vk_message, send_to_google_sheets, 
    extract_receipt_total_with_ai, extract_receipt_items_with_ai, categorize_with_ai
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
    Обрабатывает логику работы с фотографиями чеков.
    """
    
    # 1. ВЫБОР РЕЖИМА (Итог или По позициям)
    if state == "receipt_mode_select":
        photo_url = user_states[user_id].get("photo_url")
        
        if user_text_lower == "общий итог":
            send_vk_message(user_id, "👀 Изучаю чек (общий итог)...", get_cancel_keyboard())
            reply_text = extract_receipt_total_with_ai(photo_url)
            
            # Сбрасываем стейт
            del user_states[user_id]
            
            if reply_text:
                reply_text = _clean_json_string(reply_text)
                # Передаем полученный от ИИ JSON в обычный обработчик транзакций!
                # Он сам всё проверит, запишет в таблицу или спросит категорию.
                from handlers_transaction import handle_transaction
                handle_transaction(user_id, reply_text, "", user_states)
            else:
                send_vk_message(user_id, "❌ Не удалось прочитать чек.", get_main_keyboard())
            return True
            
        elif user_text_lower == "по позициям":
            send_vk_message(user_id, "⏳ Запрашиваю структуру меню...", get_cancel_keyboard())
            res = send_to_google_sheets({"action": "get_full_menu"})
            
            if res.get("status") == "SUCCESS":
                menu = res.get("menu", {})
                # Собираем меню в текст для ИИ
                menu_str = ""
                for c_type in ["Расход", "Доход"]:
                    menu_str += f"[{c_type}]\n"
                    for c, subs in menu.get(c_type, {}).items():
                        menu_str += f"{c}: {', '.join(subs)}\n"
                
                send_vk_message(user_id, "👀 Изучаю каждую позицию в чеке. Это может занять 10-15 секунд...")
                reply_text = extract_receipt_items_with_ai(photo_url, menu_str)
                
                if reply_text:
                    reply_text = _clean_json_string(reply_text)
                    if reply_text.startswith("[") and reply_text.endswith("]"):
                        try:
                            items = json.loads(reply_text)
                            user_states[user_id] = {
                                "state": "receipt_review",
                                "items": items,
                                "menu": menu,
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
            else:
                send_vk_message(user_id, "❌ Ошибка получения меню из Таблицы.", get_main_keyboard())
                del user_states[user_id]
            return True

    # 2. РЕВЬЮ (Проверка списка товаров)
    if state == "receipt_review":
        if user_text_lower == "готово":
            items = user_states[user_id]["items"]
            send_vk_message(user_id, "⏳ Сохраняю товары в таблицу...", get_cancel_keyboard())
            
            success_count = 0
            for item in items:
                # Формируем payload для прямой записи в Журнал
                payload = {
                    "item": item.get("item"),
                    "amount": item.get("amount"),
                    "type": "Расход",
                    "category": item.get("category"),
                    "subcategory": item.get("subcategory")
                }
                res = send_to_google_sheets(payload)
                if res.get("status") == "SUCCESS":
                    success_count += 1
            
            send_vk_message(user_id, f"✅ Успешно сохранено {success_count} из {len(items)} позиций!", get_main_keyboard())
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

    # 3. ИСПРАВЛЕНИЕ КАТЕГОРИИ У ТОВАРА
    if state == "receipt_edit_hint":
        idx = user_states[user_id]["edit_idx"]
        items = user_states[user_id]["items"]
        sel_item = items[idx]
        
        send_vk_message(user_id, "🧠 Думаю...", get_cancel_keyboard())
        menu_str = user_states[user_id]["menu_str"]
        
        # Просим ИИ подобрать категорию на основе подсказки
        ai_cat, ai_sub = categorize_with_ai(sel_item.get("item"), menu_str, context=user_text)
        
        # Обновляем товар в списке
        sel_item["category"] = ai_cat
        sel_item["subcategory"] = ai_sub
        
        # Возвращаемся в режим ревью
        user_states[user_id]["state"] = "receipt_review"
        _show_receipt_items(user_id, items)
        return True

    return False
