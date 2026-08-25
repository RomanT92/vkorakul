# -*- coding: utf-8 -*-
import json
from keyboards import get_main_keyboard, get_yes_no_keyboard, get_cancel_keyboard
from services import (
    send_vk_message, send_to_google_sheets, 
    extract_transaction_with_ai, categorize_with_ai
)

def handle_transaction(user_id, user_text, state, user_states):
    """
    Обрабатывает свободный ввод (обычный режим записи трат/доходов).
    Срабатывает только если у пользователя нет активного стейта (state == "").
    Возвращает True, если обработано.
    """
    if state != "":
        return False
        
    reply_text = extract_transaction_with_ai(user_text)
    
    if reply_text and reply_text.startswith("{") and reply_text.endswith("}"):
        try:
            transaction_data = json.loads(reply_text)
            transaction_data.pop("category", None)
            transaction_data.pop("subcategory", None)
            
            # Если ИИ не смог извлечь название, ставим заглушку
            if not transaction_data.get("item", "").strip():
                if transaction_data.get("type") in ["Доход", "Приход"]:
                    transaction_data["item"] = "Поступление"
                else:
                    transaction_data["item"] = "Трата"
                    
            send_vk_message(user_id, f"⏳ Ищу '{transaction_data['item']}' в базах...")
            gs_response = send_to_google_sheets(transaction_data)
            
            if gs_response.get("status") == "SUCCESS":
                send_vk_message(user_id, "✅ Успешно записано!", get_main_keyboard())
                
            elif gs_response.get("status") == "SUCCESS_AUTO_ADDED":
                send_vk_message(user_id, f"✅ Записано!\nНашел в Глобальной базе: {gs_response.get('recognized_cat')} -> {gs_response.get('recognized_sub')}", get_main_keyboard())
                
            elif gs_response.get("status") == "UNKNOWN_ITEM":
                menu = gs_response.get("available_menu", {})
                menu_str = ""
                for c, subs in menu.items():
                    menu_str += f"{c}: {', '.join(subs)}\n"
                
                ai_cat, ai_sub = categorize_with_ai(transaction_data['item'], menu_str)
                
                if ai_cat in menu and ai_sub in menu[ai_cat]:
                    user_states[user_id] = {
                        "state": "confirm_category",
                        "payload": transaction_data,
                        "menu": menu,
                        "menu_str": menu_str,
                        "ai_cat": ai_cat,
                        "ai_sub": ai_sub,
                        "attempts": 1
                    }
                    send_vk_message(user_id, f"🤖 Думаю, '{transaction_data['item']}' относится к:\n📂 {ai_cat} -> {ai_sub}\n\nВсё верно?", get_yes_no_keyboard())
                else:
                    user_states[user_id] = {
                        "state": "provide_context",
                        "payload": transaction_data,
                        "menu": menu,
                        "menu_str": menu_str,
                        "attempts": 1
                    }
                    send_vk_message(user_id, f"🤔 Я пока не знаю статью '{transaction_data['item']}'.\nПодскажи буквально в двух словах, что это за трата/доход?", get_cancel_keyboard())
            else:
                send_vk_message(user_id, f"❌ Ошибка таблицы: {gs_response.get('message')}", get_main_keyboard())
                
        except json.JSONDecodeError:
            send_vk_message(user_id, "❌ Ошибка: ИИ вернул неправильный формат.", get_main_keyboard())
    else:
        if reply_text:
            send_vk_message(user_id, reply_text, get_main_keyboard())
        else:
            send_vk_message(user_id, "❌ Ошибка связи с ИИ.", get_main_keyboard())
            
    return True
