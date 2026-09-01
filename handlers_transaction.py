# -*- coding: utf-8 -*-
import json
from keyboards import get_main_keyboard, get_yes_no_keyboard, get_cancel_keyboard
from services import send_vk_message, extract_transaction_with_ai, categorize_with_ai
from db import get_or_create_user, smart_search_item, save_transaction, get_full_menu

def handle_transaction(user_id, user_text, state, user_states):
    if state != "":
        return False

    user_text_lower = user_text.lower()
    # 1. Просим ИИ извлечь сумму и название
    reply_text = extract_transaction_with_ai(user_text)

    if reply_text and reply_text.startswith("{") and reply_text.endswith("}"):
        try:
            parsed_data = json.loads(reply_text)
            action = parsed_data.get("action")
            
            # ВРЕМЕННАЯ ЗАГЛУШКА ДЛЯ CRUD (пока мы не перенесли их в БД)
            if action in ["smart_rename", "smart_delete", "smart_move", "start_interactive"]:
                send_vk_message(user_id, "⚙️ Управление структурой сейчас переезжает на новую сверхбыструю базу данных. Эта функция заработает чуть позже!", get_main_keyboard())
                return True

            parsed_data.pop("category", None)
            parsed_data.pop("subcategory", None)

            # Логика определения типа (Доход/Расход)
            income_triggers = ["приход", "доход", "зарплата", "аванс", "премия", "подарили", "поступление"]
            expense_triggers = ["расход", "трата", "купил", "оплатил"]
            
            if any(word in user_text_lower for word in income_triggers) and not any(word in user_text_lower for word in expense_triggers):
                parsed_data["type"] = "Доход"
            elif any(word in user_text_lower for word in expense_triggers):
                parsed_data["type"] = "Расход"
            else:
                parsed_data["type"] = parsed_data.get("type", "Расход")

            current_item = parsed_data.get("item", "").strip()
            if not current_item or current_item.lower() in ["приход", "доход", "расход", "трата"]:
                current_item = "Поступление" if parsed_data["type"] in ["Доход", "Приход"] else "Трата"
            parsed_data["item"] = current_item
            
            amount = float(parsed_data.get("amount", 0))
            comment = parsed_data.get("comment", "")

            send_vk_message(user_id, f"⚡ Ищу '{current_item}' в новой базе PostgreSQL...")

            # --- МАГИЯ POSTGRESQL ---
            # Получаем внутренний ID пользователя в базе
            internal_uid = get_or_create_user(user_id)
            # Ищем слово в БД с опечатками
            search_res = smart_search_item(internal_uid, current_item, parsed_data["type"])

            if search_res["status"] == "FOUND":
                # Слово найдено! Сохраняем транзакцию за миллисекунды
                save_transaction(
                    user_id=internal_uid,
                    op_type=parsed_data["type"],
                    category=search_res["category"],
                    subcategory=search_res["subcategory"],
                    article=search_res["article"],
                    amount=amount,
                    comment=comment,
                    original_text=current_item,
                    status='verified'
                )
                send_vk_message(user_id, f"✅ Успешно записано!\n📂 {search_res['category']} -> {search_res['subcategory']}", get_main_keyboard())
            else:
                # Слово не найдено, просим ИИ угадать
                menu = get_full_menu(internal_uid)
                menu_str = "\n".join([f"{c}: {', '.join(subs)}" for c, subs in menu.get(parsed_data["type"], {}).items()])
                
                ai_cat, ai_sub = categorize_with_ai(current_item, menu_str)
                
                if ai_cat in menu.get(parsed_data["type"], {}) and ai_sub in menu[parsed_data["type"]][ai_cat]:
                    user_states[user_id] = {
                        "state": "confirm_category", 
                        "payload": parsed_data, 
                        "menu": menu, 
                        "menu_str": menu_str, 
                        "ai_cat": ai_cat, 
                        "ai_sub": ai_sub, 
                        "attempts": 1
                    }
                    send_vk_message(user_id, f"🤖 Думаю, '{current_item}' относится к:\n📂 {ai_cat} -> {ai_sub}\n\nВсё верно?", get_yes_no_keyboard())
                else:
                    user_states[user_id] = {
                        "state": "provide_context", 
                        "payload": parsed_data, 
                        "menu": menu, 
                        "menu_str": menu_str, 
                        "attempts": 1
                    }
                    send_vk_message(user_id, f"🤔 Я пока не знаю статью '{current_item}'.\nПодскажи буквально в двух словах, что это за трата/доход?", get_cancel_keyboard())

        except json.JSONDecodeError:
            send_vk_message(user_id, "❌ Ошибка: ИИ вернул неправильный формат.", get_main_keyboard())
        except Exception as e:
            send_vk_message(user_id, f"❌ Ошибка базы данных: {e}", get_main_keyboard())
    else:
        if reply_text:
            send_vk_message(user_id, reply_text, get_main_keyboard())
        else:
            send_vk_message(user_id, "❌ Ошибка связи с ИИ.", get_main_keyboard())
    
    return True
