# -*- coding: utf-8 -*-
import json
from keyboards import (
    get_main_keyboard, get_yes_no_keyboard, get_cancel_keyboard,
    type_keyboard, get_entity_keyboard, get_del_move_keyboard
)
from services import (
    send_vk_message, send_to_google_sheets, 
    extract_transaction_with_ai, categorize_with_ai
)

def handle_transaction(user_id, user_text, state, user_states):
    if state != "":
        return False
        
    reply_text = extract_transaction_with_ai(user_text)
    
    if reply_text and reply_text.startswith("{") and reply_text.endswith("}"):
        try:
            parsed_data = json.loads(reply_text)
            
            # ==============================================================
            # РЕЖИМ 2: ИНТЕРАКТИВНОЕ УПРАВЛЕНИЕ СТРУКТУРОЙ
            # ==============================================================
            if parsed_data.get("action") == "start_interactive":
                op = parsed_data.get("operation")
                item = parsed_data.get("item", "")
                
                if op == "create_article":
                    user_states[user_id] = {"state": "create_art_type", "pending_name": item}
                    send_vk_message(user_id, f"Ок, создаем статью {f'«{item}»' if item else ''}.\nЭто будет статья Расходов или Доходов?", type_keyboard())
                    return True
                elif op == "create_subcategory":
                    user_states[user_id] = {"state": "create_sub_type", "pending_name": item}
                    send_vk_message(user_id, f"Ок, создаем подкатегорию {f'«{item}»' if item else ''}.\nЭто будет подкатегория Расходов или Доходов?", type_keyboard())
                    return True
                elif op == "create_category":
                    user_states[user_id] = {"state": "create_cat_type", "pending_name": item}
                    send_vk_message(user_id, f"Ок, создаем категорию {f'«{item}»' if item else ''}.\nЭто будет категория Расходов или Доходов?", type_keyboard())
                    return True
                elif op == "rename":
                    user_states[user_id] = {"state": "wait_entity_rename"}
                    send_vk_message(user_id, "Что именно вы хотите переименовать?", get_entity_keyboard())
                    return True
                elif op in ["delete", "move"]:
                    user_states[user_id] = {"state": "wait_del_move_action"}
                    send_vk_message(user_id, "Что вы хотите сделать?", get_del_move_keyboard())
                    return True

            # Резерв на случай, если ИИ всё же выдаст прямую команду
            elif "action" in parsed_data:
                send_vk_message(user_id, "⏳ Выполняю команду по изменению структуры...")
                gs_response = send_to_google_sheets(parsed_data)
                msg = gs_response.get("message", "✅ Структура успешно обновлена!") if gs_response.get("status") == "SUCCESS" else f"❌ Ошибка таблицы: {gs_response.get('message')}"
                send_vk_message(user_id, msg, get_main_keyboard())
                return True
            
            # ==============================================================
            # РЕЖИМ 1: ОБЫЧНАЯ ТРАТА ИЛИ ДОХОД
            # ==============================================================
            parsed_data.pop("category", None)
            parsed_data.pop("subcategory", None)
            
            if not parsed_data.get("item", "").strip():
                parsed_data["item"] = "Поступление" if parsed_data.get("type") in ["Доход", "Приход"] else "Трата"
                    
            send_vk_message(user_id, f"⏳ Ищу '{parsed_data['item']}' в базах...")
            gs_response = send_to_google_sheets(parsed_data)
            
            if gs_response.get("status") == "SUCCESS":
                send_vk_message(user_id, "✅ Успешно записано!", get_main_keyboard())
            elif gs_response.get("status") == "SUCCESS_AUTO_ADDED":
                send_vk_message(user_id, f"✅ Записано!\nНашел в Глобальной базе: {gs_response.get('recognized_cat')} -> {gs_response.get('recognized_sub')}", get_main_keyboard())
            elif gs_response.get("status") == "UNKNOWN_ITEM":
                menu = gs_response.get("available_menu", {})
                menu_str = "\n".join([f"{c}: {', '.join(subs)}" for c, subs in menu.items()])
                ai_cat, ai_sub = categorize_with_ai(parsed_data['item'], menu_str)
                
                if ai_cat in menu and ai_sub in menu[ai_cat]:
                    user_states[user_id] = {"state": "confirm_category", "payload": parsed_data, "menu": menu, "menu_str": menu_str, "ai_cat": ai_cat, "ai_sub": ai_sub, "attempts": 1}
                    send_vk_message(user_id, f"🤖 Думаю, '{parsed_data['item']}' относится к:\n📂 {ai_cat} -> {ai_sub}\n\nВсё верно?", get_yes_no_keyboard())
                else:
                    user_states[user_id] = {"state": "provide_context", "payload": parsed_data, "menu": menu, "menu_str": menu_str, "attempts": 1}
                    send_vk_message(user_id, f"🤔 Я пока не знаю статью '{parsed_data['item']}'.\nПодскажи буквально в двух словах, что это за трата/доход?", get_cancel_keyboard())
            else:
                send_vk_message(user_id, f"❌ Ошибка таблицы: {gs_response.get('message')}", get_main_keyboard())
                
        except json.JSONDecodeError:
            send_vk_message(user_id, "❌ Ошибка: ИИ вернул неправильный формат.", get_main_keyboard())
            
    # ==============================================================
    # РЕЖИМ 3: ПРОСТОЕ ОБЩЕНИЕ
    # ==============================================================
    else:
        if reply_text:
            send_vk_message(user_id, reply_text, get_main_keyboard())
        else:
            send_vk_message(user_id, "❌ Ошибка связи с ИИ.", get_main_keyboard())
            
    return True
