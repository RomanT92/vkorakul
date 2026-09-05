# -*- coding: utf-8 -*-
import json
import re
import difflib
from keyboards import (
    get_main_keyboard,
    get_yes_no_keyboard,
    get_cancel_keyboard,
    type_keyboard,
    get_numbered_keyboard
)
from services import send_vk_message, extract_transaction_with_ai, categorize_with_ai
from db import (
    get_or_create_user,
    smart_search_item,
    save_transaction,
    get_full_menu,
    db_rename_category,
    db_rename_subcategory,
    db_rename_article,
    db_delete_entity,
    db_move_entity
)

def find_entity_in_menu(menu, target_name):
    """Поиск сущности любого уровня (категория, подкатегория, статья) по названию."""
    target = target_name.lower().strip()
    all_entities = []
    for c_type in ["Расход", "Доход"]:
        type_menu = menu.get(c_type, {})
        for cat, subs in type_menu.items():
            all_entities.append({"level": "category", "type": c_type, "cat": cat, "sub": "", "art": "", "name": cat.lower().strip()})
            subs_items = subs.items() if isinstance(subs, dict) else [(s, []) for s in subs]
            for sub, arts in subs_items:
                all_entities.append({"level": "subcategory", "type": c_type, "cat": cat, "sub": sub, "art": "", "name": sub.lower().strip()})
                for art in arts:
                    all_entities.append({"level": "article", "type": c_type, "cat": cat, "sub": sub, "art": art, "name": art.lower().strip()})
    
    results = [ent for ent in all_entities if ent["name"] == target]
    if not results:
        names = [ent["name"] for ent in all_entities]
        matches = difflib.get_close_matches(target, names, n=1, cutoff=0.7)
        if matches:
            best_match = matches[0]
            results = [ent for ent in all_entities if ent["name"] == best_match]
    return results

def clean_fallback_item(user_text):
    """Вырезает из текста пользователя сумму и служебные слова, оставляя реальное название."""
    text = re.sub(r'\d+([.,]\d+)?', '', user_text).strip()
    stop_words = ["руб", "рублей", "р", "к", "k", "приход", "доход", "расход", "трата", "купил", "оплатил"]
    words = [w for w in text.split() if w.lower() not in stop_words]
    clean = " ".join(words).strip()
    return clean if clean else "Трата"

def handle_transaction(user_id, user_text, state, user_states):
    if state != "":
        return False

    user_text_lower = user_text.lower()
    internal_uid = get_or_create_user(user_id)

    reply_text = extract_transaction_with_ai(user_text)

    if reply_text and reply_text.startswith("{") and reply_text.endswith("}"):
        try:
            parsed_data = json.loads(reply_text)
            action = parsed_data.get("action")

            # =========================================================
            # ТЕКСТОВОЕ УПРАВЛЕНИЕ СТРУКТУРОЙ (CRUD) ЧЕРЕЗ ИИ
            # =========================================================
            if action in ["smart_rename", "smart_delete", "smart_move"]:
                target_name = parsed_data.get("old_name") if action == "smart_rename" else parsed_data.get("item", "")
                send_vk_message(user_id, f"⏳ Ищу '{target_name}' в структуре...")
                menu = get_full_menu(internal_uid)
                results = find_entity_in_menu(menu, target_name)
                
                if not results:
                    send_vk_message(user_id, f"❌ Не нашел '{target_name}' в базе. Попробуйте через кнопки меню.", get_main_keyboard())
                    return True
                elif len(results) > 1:
                    send_vk_message(user_id, f"⚠️ Найдено несколько совпадений для '{target_name}'. Воспользуйтесь кнопками меню для выбора.", get_main_keyboard())
                    return True

                r = results[0]
                found_name = r["cat"] if r["level"] == "category" else (r["sub"] if r["level"] == "subcategory" else r["art"])

                if action == "smart_rename":
                    new_name = parsed_data.get("new_name", "")
                    if r["level"] == "category":
                        db_rename_category(internal_uid, r["type"], r["cat"], new_name)
                    elif r["level"] == "subcategory":
                        db_rename_subcategory(internal_uid, r["type"], r["cat"], r["sub"], new_name)
                    else:
                        db_rename_article(internal_uid, r["type"], r["cat"], r["sub"], r["art"], new_name)
                    send_vk_message(user_id, f"✅ Успешно переименовано в '{new_name}'!", get_main_keyboard())

                elif action == "smart_delete":
                    level_ru = {"category": "КАТЕГОРИЮ", "subcategory": "ПОДКАТЕГОРИЮ", "article": "СТАТЬЮ"}[r["level"]]
                    user_states[user_id] = {
                        "state": "delete_confirm",
                        "del_level": r["level"],
                        "c_type": r["type"],
                        "sel_cat": r["cat"],
                        "sel_sub": r["sub"],
                        "sel_art": r["art"]
                    }
                    send_vk_message(user_id, f"⚠️ Вы уверены, что хотите удалить {level_ru} '{found_name}'?", get_yes_no_keyboard())

                elif action == "smart_move":
                    if r["level"] == "category":
                        send_vk_message(user_id, "❌ Категорию нельзя перенести. Только подкатегорию или статью.", get_main_keyboard())
                        return True
                    
                    cats = sorted(list(menu.get(r["type"], {}).keys()))
                    if r["level"] == "article":
                        user_states[user_id] = {
                            "state": "move_target_cat",
                            "move_level": "article",
                            "c_type": r["type"],
                            "sel_cat": r["cat"],
                            "sel_sub": r["sub"],
                            "sel_art": r["art"],
                            "cats": cats
                        }
                        msg = f"В какую КАТЕГОРИЮ перенести статью '{found_name}'?\n\n"
                        for i, c in enumerate(cats):
                            msg += f"{i+1}. {c}\n"
                        send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))

                    elif r["level"] == "subcategory":
                        user_states[user_id] = {
                            "state": "move_target_parent",
                            "move_level": "subcategory",
                            "c_type": r["type"],
                            "sel_cat": r["cat"],
                            "sel_sub": r["sub"],
                            "cats": cats
                        }
                        msg = f"В какую КАТЕГОРИЮ перенести подкатегорию '{found_name}'?\n\n"
                        for i, c in enumerate(cats):
                            msg += f"{i+1}. {c}\n"
                        send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
                return True

            if action == "start_interactive":
                op = parsed_data.get("operation")
                item = parsed_data.get("item", "")
                if op == "create_article":
                    user_states[user_id] = {"state": "create_art_type", "pending_name": item}
                    send_vk_message(user_id, f"Создаем статью {f'«{item}»' if item else ''}.\nЭто статья Расходов или Доходов?", type_keyboard())
                    return True
                elif op == "create_subcategory":
                    user_states[user_id] = {"state": "create_sub_type", "pending_name": item}
                    send_vk_message(user_id, f"Создаем подкатегорию {f'«{item}»' if item else ''}.\nЭто подкатегория Расходов или Доходов?", type_keyboard())
                    return True
                elif op == "create_category":
                    user_states[user_id] = {"state": "create_cat_type", "pending_name": item}
                    send_vk_message(user_id, f"Создаем категорию {f'«{item}»' if item else ''}.\nЭто категория Расходов или Доходов?", type_keyboard())
                    return True

            # =========================================================
            # ОБРАБОТКА ОБЫЧНЫХ ОПЕРАЦИЙ (ТРАТЫ / ДОХОДЫ)
            # =========================================================
            parsed_data.pop("category", None)
            parsed_data.pop("subcategory", None)

            # Проверяем явные триггеры от пользователя
            income_triggers = ["приход", "доход", "зарплата", "аванс", "премия", "подарили", "поступление"]
            expense_triggers = ["расход", "трата", "купил", "оплатил"]
            
            user_explicit_type = None
            if any(word in user_text_lower for word in income_triggers) and not any(word in user_text_lower for word in expense_triggers):
                user_explicit_type = "Доход"
            elif any(word in user_text_lower for word in expense_triggers):
                user_explicit_type = "Расход"

            ai_guessed_type = parsed_data.get("type", "Расход")
            if ai_guessed_type not in ["Расход", "Доход"]:
                ai_guessed_type = "Расход"

            # Не затираем исходное слово пользователя на "Поступление"
            current_item = parsed_data.get("item", "").strip()
            if not current_item or current_item.lower() in ["приход", "доход", "расход", "трата", "поступление"]:
                current_item = clean_fallback_item(user_text)
                parsed_data["item"] = current_item

            amount = float(parsed_data.get("amount", 0))
            comment = parsed_data.get("comment", "")

            send_vk_message(user_id, f"⚡ Ищу '{current_item}' в базе...")

            # 1. Сначала ищем по типу, который предположил ИИ или указал юзер
            search_res = smart_search_item(internal_uid, current_item, op_type=user_explicit_type or ai_guessed_type)

            # 2. Если по угаданному типу не нашлось и юзер явно не писал "доход/расход" — ищем без привязки к типу!
            if search_res["status"] != "FOUND" and not user_explicit_type:
                search_res = smart_search_item(internal_uid, current_item, op_type=None)

            if search_res["status"] == "FOUND":
                op_type = search_res["type"]
                parsed_data["type"] = op_type
                save_transaction(
                    user_id=internal_uid,
                    op_type=op_type,
                    category=search_res["category"],
                    subcategory=search_res["subcategory"],
                    article=search_res["article"],
                    amount=amount,
                    comment=comment,
                    original_text=current_item,
                    status='verified'
                )
                send_vk_message(user_id, f"✅ Успешно записано! ({op_type})\n📂 {search_res['category']} -> {search_res['subcategory']}", get_main_keyboard())
            else:
                op_type = user_explicit_type or ai_guessed_type
                parsed_data["type"] = op_type
                menu_full = get_full_menu(internal_uid)
                type_menu = menu_full.get(op_type, {})
                menu_str = f"[{op_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])
                
                ai_cat, ai_sub = categorize_with_ai(current_item, menu_str)

                valid_cat = ai_cat in type_menu and ai_sub in (type_menu[ai_cat].keys() if isinstance(type_menu[ai_cat], dict) else type_menu[ai_cat])

                if valid_cat and ai_sub != "Требует проверки":
                    user_states[user_id] = {
                        "state": "confirm_category",
                        "payload": parsed_data,
                        "menu": menu_full,
                        "menu_str": menu_str,
                        "ai_cat": ai_cat,
                        "ai_sub": ai_sub,
                        "attempts": 1
                    }
                    send_vk_message(user_id, f"🤖 Думаю, '{current_item}' ({op_type}) относится к:\n📂 {ai_cat} -> {ai_sub}\n\nВсё верно?", get_yes_no_keyboard())
                else:
                    user_states[user_id] = {
                        "state": "provide_context",
                        "payload": parsed_data,
                        "menu": menu_full,
                        "menu_str": menu_str,
                        "attempts": 1
                    }
                    send_vk_message(user_id, f"🤔 Я пока не знаю статью '{current_item}'.\nПодскажи в двух словах, к чему это относится (или напиши правильную категорию):", get_cancel_keyboard())
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
