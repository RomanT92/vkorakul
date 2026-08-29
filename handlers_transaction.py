# -*- coding: utf-8 -*-
import json
import difflib
from keyboards import (
    get_main_keyboard, get_yes_no_keyboard, get_cancel_keyboard,
    type_keyboard, get_entity_keyboard, get_del_move_keyboard, get_numbered_keyboard
)
from services import (
    send_vk_message, send_to_google_sheets, 
    extract_transaction_with_ai, categorize_with_ai
)

def find_entity_in_menu(menu, target_name):
    target = target_name.lower().strip()
    all_entities = []
    
    for c_type in ["Расход", "Доход"]:
        type_menu = menu.get(c_type, {})
        for cat, subs in type_menu.items():
            all_entities.append({"level": "category", "type": c_type, "cat": cat, "sub": "", "art": "", "name": cat.lower().strip()})
            for sub, arts in subs.items():
                all_entities.append({"level": "subcategory", "type": c_type, "cat": cat, "sub": sub, "art": "", "name": sub.lower().strip()})
                for art in arts:
                    all_entities.append({"level": "article", "type": c_type, "cat": cat, "sub": sub, "art": art, "name": art.lower().strip()})
    
    results = []
    for ent in all_entities:
        if ent["name"] == target:
            results.append(ent)
            
    if not results:
        names = [ent["name"] for ent in all_entities]
        matches = difflib.get_close_matches(target, names, n=1, cutoff=0.7)
        if matches:
            best_match = matches[0]
            for ent in all_entities:
                if ent["name"] == best_match:
                    results.append(ent)
                    
    return results

def handle_transaction(user_id, user_text, state, user_states):
    if state != "":
        return False
        
    user_text_lower = user_text.lower()
    reply_text = extract_transaction_with_ai(user_text)
    
    if reply_text and reply_text.startswith("{") and reply_text.endswith("}"):
        try:
            parsed_data = json.loads(reply_text)
            action = parsed_data.get("action")
            
            # ==============================================================
            # РЕЖИМ 2.1: УМНЫЙ ПОИСК (ПЕРЕИМЕНОВАТЬ, УДАЛИТЬ, ПЕРЕНЕСТИ)
            # ==============================================================
            if action in ["smart_rename", "smart_delete", "smart_move"]:
                target_name = parsed_data.get("old_name") if action == "smart_rename" else parsed_data.get("item", "")
                send_vk_message(user_id, f"⏳ Ищу '{target_name}' в структуре...")
                
                res = send_to_google_sheets({"action": "get_full_menu"})
                if res.get("status") == "SUCCESS":
                    menu = res.get("menu", {})
                    results = find_entity_in_menu(menu, target_name)
                    
                    if len(results) == 0:
                        send_vk_message(user_id, f"❌ Не нашел '{target_name}' в базе. Попробуйте через кнопки меню.", get_main_keyboard())
                        return True
                    elif len(results) > 1:
                        send_vk_message(user_id, f"⚠️ Нашел несколько совпадений для '{target_name}'. Пожалуйста, воспользуйтесь кнопками меню для точности.", get_main_keyboard())
                        return True
                        
                    r = results[0]
                    found_name = r["cat"] if r["level"] == "category" else (r["sub"] if r["level"] == "subcategory" else r["art"])
                    
                    if action == "smart_rename":
                        new_name = parsed_data.get("new_name", "")
                        if r["level"] == "category":
                            payload = {"action": "rename_category", "type": r["type"], "old_cat": r["cat"], "new_cat": new_name}
                        elif r["level"] == "subcategory":
                            payload = {"action": "rename_subcategory", "type": r["type"], "cat": r["cat"], "old_sub": r["sub"], "new_sub": new_name}
                        else:
                            payload = {"action": "rename_article", "type": r["type"], "cat": r["cat"], "sub": r["sub"], "old_art": r["art"], "new_art": new_name}
                        
                        send_vk_message(user_id, f"⏳ Переименовываю {r['level']} '{found_name}' в '{new_name}'...")
                        gs_res = send_to_google_sheets(payload)
                        msg = "✅ Успешно переименовано!" if gs_res.get("status") == "SUCCESS" else f"❌ Ошибка: {gs_res.get('message')}"
                        send_vk_message(user_id, msg, get_main_keyboard())
                    
                    elif action == "smart_delete":
                        level_ru = {"category": "КАТЕГОРИЮ", "subcategory": "ПОДКАТЕГОРИЮ", "article": "СТАТЬЮ"}[r["level"]]
                        user_states[user_id] = {
                            "state": "delete_confirm", "del_level": r["level"], "c_type": r["type"],
                            "sel_cat": r["cat"], "sel_sub": r["sub"], "sel_art": r["art"]
                        }
                        send_vk_message(user_id, f"⚠️ Вы уверены, что хотите удалить {level_ru} '{found_name}'?", get_yes_no_keyboard())
                    
                    elif action == "smart_move":
                        if r["level"] == "category":
                            send_vk_message(user_id, "❌ Категорию нельзя перенести. Только подкатегорию или статью.", get_main_keyboard())
                            return True
                            
                        cats = list(menu.get(r["type"], {}).keys())
                        cats.sort()
                        
                        if r["level"] == "article":
                            user_states[user_id] = {
                                "state": "move_target_cat", "move_level": "article", "c_type": r["type"],
                                "sel_cat": r["cat"], "sel_sub": r["sub"], "sel_art": r["art"],
                                "cats": cats, "menu": menu.get(r["type"], {})
                            }
                            msg = f"В какую КАТЕГОРИЮ перенести статью '{found_name}'?\n\n"
                            for i, c in enumerate(cats):
                                msg += f"{i+1}. {c}\n"
                            send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
                            
                        elif r["level"] == "subcategory":
                            user_states[user_id] = {
                                "state": "move_target_parent", "move_level": "subcategory", "c_type": r["type"],
                                "sel_cat": r["cat"], "sel_sub": r["sub"], "cats": cats
                            }
                            msg = f"В какую КАТЕГОРИЮ перенести подкатегорию '{found_name}'?\n\n"
                            for i, c in enumerate(cats):
                                msg += f"{i+1}. {c}\n"
                            send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
                return True

            # ==============================================================
            # РЕЖИМ 2.2: ИНТЕРАКТИВНОЕ СОЗДАНИЕ
            # ==============================================================
            if action == "start_interactive":
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

            # ==============================================================
            # РЕЖИМ 1: ОБЫЧНАЯ ТРАТА ИЛИ ДОХОД
            # ==============================================================
            parsed_data.pop("category", None)
            parsed_data.pop("subcategory", None)
            
            income_triggers = ["приход", "доход", "зарплата", "аванс", "премия", "подарили", "поступление"]
            expense_triggers = ["расход", "трата", "купил", "оплатил"]
            
            if any(word in user_text_lower for word in income_triggers) and not any(word in user_text_lower for word in expense_triggers):
                parsed_data["type"] = "Доход"
            elif any(word in user_text_lower for word in expense_triggers):
                parsed_data["type"] = "Расход"

            current_item = parsed_data.get("item", "").strip().lower()
            if not current_item or current_item in ["приход", "доход", "расход", "трата"]:
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
