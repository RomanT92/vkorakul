# -*- coding: utf-8 -*-
import json
import re
import difflib
from keyboards import (
    get_main_keyboard,
    get_yes_no_keyboard,
    get_cancel_keyboard,
    type_keyboard,
    get_numbered_keyboard,
    get_multi_tx_review_keyboard
)
from services import send_vk_message, extract_transaction_with_ai, categorize_with_ai
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

def _clean_json_string(text):
    """Очищает строку от маркдауна ```json ... ``` если ИИ его добавил"""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:-3].strip()
    elif text.startswith("```"):
        text = text[3:-3].strip()
    return text

def _show_multi_tx_items(user_id, items, show_apply_all=False):
    """Выводит красивый пронумерованный список распознанных операций."""
    msg = f"📋 Распознанные операции (всего {len(items)}):\n\n"
    for i, item in enumerate(items):
        item_name = item.get("item", "Операция")
        amount = item.get("amount", 0)
        op_type = item.get("type", "Расход")
        cat = item.get("category", "?")
        sub = item.get("subcategory", "?")
        comm = f" ({item['comment']})" if item.get("comment") else ""

        type_icon = "📉" if op_type == "Расход" else "📈"
        msg += f"{i+1}. {item_name} — {amount} руб. {type_icon}{comm}\n"
        msg += f"   📂 {cat} -> {sub}\n\n"

    msg += "Если всё верно, жмите «✅ Готово».\n"
    if show_apply_all:
        msg += "Нажмите «⚡ Применить для всех оставшихся», чтобы продублировать категорию.\n"
    msg += "Если хотите изменить категорию статьи — отправьте её НОМЕР."

    send_vk_message(user_id, msg, get_multi_tx_review_keyboard(len(items), show_apply_all=show_apply_all, show_back=True))

def handle_transaction(user_id, user_text, state, user_states):
    user_text_lower = user_text.lower()
    internal_uid = get_or_create_user(user_id)

    # =========================================================
    # ОБРАБОТКА «НАЗАД» В МАССОВОМ ВВОДЕ ОПЕРАЦИЙ
    # =========================================================
    if "назад" in user_text_lower:
        if state == "multi_tx_edit_hint":
            user_states[user_id]["state"] = "multi_tx_review"
            _show_multi_tx_items(user_id, user_states[user_id]["items"], show_apply_all=False)
            return True
        elif state == "multi_tx_review":
            del user_states[user_id]
            send_vk_message(user_id, "Главное меню.", get_main_keyboard(user_id))
            return True

    # =========================================================
    # ЭТАП 2: РЕВЬЮ СПИСКА ОПЕРАЦИЙ (ГОТОВО, НОМЕР, ПРИМЕНИТЬ ДЛЯ ВСЕХ)
    # =========================================================
    if state == "multi_tx_review":
        state_data = user_states[user_id]
        items = state_data["items"]

        if "готово" in user_text_lower:
            send_vk_message(user_id, "⏳ Сохраняю операции в базу данных...", get_cancel_keyboard(show_back=False))
            saved_count = 0
            needs_review_count = 0

            for item in items:
                cat = item.get("category", "Разное")
                sub = item.get("subcategory", "Требует проверки")
                art = item.get("item", "Трата")
                amount = float(item.get("amount", 0))
                op_type = item.get("type", "Расход")
                comment = item.get("comment", "")

                if cat == "Разное" or sub == "Требует проверки":
                    op_status = 'needs_review'
                    needs_review_count += 1
                else:
                    op_status = 'verified'

                ok = save_transaction(
                    user_id=internal_uid,
                    op_type=op_type,
                    category=cat,
                    subcategory=sub,
                    article=art,
                    amount=amount,
                    comment=comment,
                    original_text=art,
                    status=op_status
                )
                if ok:
                    saved_count += 1

                if op_status == 'verified':
                    learn_user_word(internal_uid, op_type, cat, sub, art, art)

            report_msg = f"🎉 Успешно сохранено {saved_count} операций!\nЖурнал обновлен."
            if needs_review_count > 0:
                report_msg += f"\n\n⚠️ {needs_review_count} позиций требуют проверки. Вы можете распределить их кнопкой «📥 Разобрать операции»."

            send_vk_message(user_id, report_msg, get_main_keyboard(user_id))
            del user_states[user_id]
            return True

        elif any(w in user_text_lower for w in ["применить для всех", "применить ко всем"]):
            last_cat = state_data.get("last_category")
            last_sub = state_data.get("last_subcategory")
            start_idx = state_data.get("last_edit_idx", 0) + 1

            if not last_cat or not last_sub:
                send_vk_message(user_id, "⚠️ Сначала измените какую-нибудь одну операцию из списка.")
                return True

            applied = 0
            for i in range(start_idx, len(items)):
                items[i]["category"] = last_cat
                items[i]["subcategory"] = last_sub
                applied += 1

            if applied == 0:
                for it in items:
                    it["category"] = last_cat
                    it["subcategory"] = last_sub
                applied = len(items)

            send_vk_message(user_id, f"⚡ Категория «{last_cat} -> {last_sub}» применена к {applied} операциям!")
            _show_multi_tx_items(user_id, items, show_apply_all=True)
            return True

        elif user_text.isdigit():
            idx = int(user_text) - 1
            if 0 <= idx < len(items):
                state_data["edit_idx"] = idx
                state_data["state"] = "multi_tx_edit_hint"
                sel_item = items[idx]
                send_vk_message(
                    user_id,
                    f"✏️ Исправляем: «{sel_item.get('item')}» ({sel_item.get('amount')} руб.)\n"
                    f"Напишите правильную категорию или точное название статьи (например: «Детский сад» или «Образование»):",
                    get_cancel_keyboard(show_back=True)
                )
                return True

    # =========================================================
    # ЭТАП 2.1: ОБРАБОТКА ПОДСКАЗКИ К КОНКРЕТНОМУ ПУНКТУ СПИСКА (ПОИСК В БД ПЕРВЫМ!)
    # =========================================================
    if state == "multi_tx_edit_hint":
        state_data = user_states[user_id]
        idx = state_data["edit_idx"]
        items = state_data["items"]
        sel_item = items[idx]
        op_type = sel_item.get("type", "Расход")

        # 1. Поиск по базе данных
        db_match = smart_search_item(internal_uid, user_text, op_type=op_type)
        if db_match["status"] != "FOUND":
            db_match = smart_search_item(internal_uid, user_text, op_type=None)

        if db_match["status"] == "FOUND":
            ai_cat = db_match["category"]
            ai_sub = db_match["subcategory"]
            if db_match.get("type"):
                sel_item["type"] = db_match["type"]
        else:
            # 2. Проверка точного совпадения по дереву категорий
            menu_full = get_full_menu(internal_uid)
            u_clean = user_text.lower().strip()
            found_in_tree = False

            for m_type in ["Расход", "Доход"]:
                type_cats = menu_full.get(m_type, {})
                for m_cat, m_subs in type_cats.items():
                    if m_cat.lower() == u_clean:
                        ai_cat = m_cat
                        sub_keys = list(m_subs.keys()) if isinstance(m_subs, dict) else (m_subs if m_subs else [])
                        ai_sub = sub_keys[0] if sub_keys else "Разное"
                        sel_item["type"] = m_type
                        found_in_tree = True
                        break
                    sub_keys = list(m_subs.keys()) if isinstance(m_subs, dict) else (m_subs if m_subs else [])
                    for s_name in sub_keys:
                        if s_name.lower() == u_clean:
                            ai_cat = m_cat
                            ai_sub = s_name
                            sel_item["type"] = m_type
                            found_in_tree = True
                            break
                    if found_in_tree:
                        break
                if found_in_tree:
                    break

            # 3. Резервный поиск через нейросеть
            if not found_in_tree:
                send_vk_message(user_id, "🧠 Подбираю категорию с помощью ИИ...", get_cancel_keyboard(show_back=True))
                menu_full = state_data["menu"]
                type_menu = menu_full.get(op_type, {})
                menu_str = f"[{op_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])
                ai_cat, ai_sub = categorize_with_ai(sel_item.get("item"), menu_str, context=user_text)

        sel_item["category"] = ai_cat
        sel_item["subcategory"] = ai_sub

        state_data["last_category"] = ai_cat
        state_data["last_subcategory"] = ai_sub
        state_data["last_edit_idx"] = idx

        state_data["state"] = "multi_tx_review"
        _show_multi_tx_items(user_id, items, show_apply_all=True)
        return True

    if state != "":
        return False

    # =========================================================
    # ЭТАП 1: ПЕРВИЧНЫЙ АНАЛИЗ ВВОДА (ГОЛОС ИЛИ ТЕКСТ) ЧЕРЕЗ ИИ
    # =========================================================
    reply_text = extract_transaction_with_ai(user_text)
    if not reply_text:
        return False

    clean_text = _clean_json_string(reply_text)

    if clean_text.startswith("{") and clean_text.endswith("}"):
        try:
            parsed_data = json.loads(clean_text)
            action = parsed_data.get("action")

            if action in ["smart_rename", "smart_delete", "smart_move"]:
                target_name = parsed_data.get("old_name") if action == "smart_rename" else parsed_data.get("item", "")
                send_vk_message(user_id, f"⏳ Ищу '{target_name}' в структуре...")
                menu = get_full_menu(internal_uid)
                results = find_entity_in_menu(menu, target_name)
                
                if not results:
                    send_vk_message(user_id, f"❌ Не нашел '{target_name}' в базе. Попробуйте через кнопки меню.", get_main_keyboard(user_id))
                    return True
                elif len(results) > 1:
                    send_vk_message(user_id, f"⚠️ Найдено несколько совпадений для '{target_name}'. Воспользуйтесь кнопками меню для выбора.", get_main_keyboard(user_id))
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
                    send_vk_message(user_id, f"✅ Успешно переименовано в '{new_name}'!", get_main_keyboard(user_id))

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
                    send_vk_message(user_id, f"⚠️ Вы уверены, что хотите удалить {level_ru} '{found_name}'?", get_yes_no_keyboard(show_back=True))

                elif action == "smart_move":
                    if r["level"] == "category":
                        send_vk_message(user_id, "❌ Категорию нельзя перенести. Только подкатегорию или статью.", get_main_keyboard(user_id))
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
                        send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))

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
                        send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))
                return True

            if action == "start_interactive":
                op = parsed_data.get("operation")
                item = parsed_data.get("item", "")
                if op == "create_article":
                    user_states[user_id] = {"state": "create_art_type", "pending_name": item}
                    send_vk_message(user_id, f"Создаем статью {f'«{item}»' if item else ''}.\nЭто статья Расходов или Доходов?", type_keyboard(show_back=True))
                    return True
                elif op == "create_subcategory":
                    user_states[user_id] = {"state": "create_sub_type", "pending_name": item}
                    send_vk_message(user_id, f"Создаем подкатегорию {f'«{item}»' if item else ''}.\nЭто подкатегория Расходов или Доходов?", type_keyboard(show_back=True))
                    return True
                elif op == "create_category":
                    user_states[user_id] = {"state": "create_cat_type", "pending_name": item}
                    send_vk_message(user_id, f"Создаем категорию {f'«{item}»' if item else ''}.\nЭто категория Расходов или Доходов?", type_keyboard(show_back=True))
                    return True

            raw_ops = parsed_data.get("operations", [])
            if not raw_ops and "item" in parsed_data:
                raw_ops = [parsed_data]

            if not raw_ops:
                return False

            menu_full = get_full_menu(internal_uid)
            processed_items = []
            all_known = True

            send_vk_message(user_id, f"⚡ Распознаю {len(raw_ops)} операций и сопоставляю с базой...")

            for op in raw_ops:
                current_item = op.get("item", "").strip()
                if not current_item or current_item.lower() in ["приход", "доход", "расход", "трата", "поступление"]:
                    current_item = clean_fallback_item(user_text)

                amount = float(op.get("amount", 0))
                op_type = op.get("type", "Расход")
                if op_type not in ["Расход", "Доход"]:
                    op_type = "Расход"
                comment = op.get("comment", "").strip()

                # 1. Поиск по чистому наименованию
                search_res = smart_search_item(internal_uid, current_item, op_type=op_type)
                if search_res["status"] != "FOUND":
                    search_res = smart_search_item(internal_uid, current_item, op_type=None)

                # 2. Комбинированная проверка с комментарием (защита от разделения составных слов ИИ)
                if search_res["status"] != "FOUND" and comment:
                    full_phrase = f"{current_item} {comment}".strip()
                    phrase_res = smart_search_item(internal_uid, full_phrase, op_type=op_type)
                    if phrase_res["status"] != "FOUND":
                        phrase_res = smart_search_item(internal_uid, full_phrase, op_type=None)
                    if phrase_res["status"] == "FOUND":
                        search_res = phrase_res
                        current_item = full_phrase
                        comment = ""

                if search_res["status"] == "FOUND":
                    processed_items.append({
                        "item": current_item,
                        "amount": amount,
                        "type": search_res["type"],
                        "category": search_res["category"],
                        "subcategory": search_res["subcategory"],
                        "comment": comment,
                        "is_known": True
                    })
                else:
                    all_known = False
                    type_menu = menu_full.get(op_type, {})
                    menu_str = f"[{op_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])
                    ai_cat, ai_sub = categorize_with_ai(current_item, menu_str)

                    valid_cat = ai_cat in type_menu and ai_sub in (type_menu[ai_cat].keys() if isinstance(type_menu[ai_cat], dict) else type_menu[ai_cat])

                    if valid_cat and ai_sub != "Требует проверки":
                        cat_res, sub_res = ai_cat, ai_sub
                    else:
                        cat_res, sub_res = "Разное", "Требует проверки"

                    processed_items.append({
                        "item": current_item,
                        "amount": amount,
                        "type": op_type,
                        "category": cat_res,
                        "subcategory": sub_res,
                        "comment": comment,
                        "is_known": False
                    })

            # СЦЕНАРИЙ А: 1 операция и она известна в базе -> мгновенная запись
            if len(processed_items) == 1 and all_known:
                single = processed_items[0]
                save_transaction(
                    user_id=internal_uid,
                    op_type=single["type"],
                    category=single["category"],
                    subcategory=single["subcategory"],
                    article=single["item"],
                    amount=single["amount"],
                    comment=single["comment"],
                    original_text=single["item"],
                    status='verified'
                )
                send_vk_message(
                    user_id,
                    f"✅ Успешно записано! ({single['type']})\n📂 {single['category']} -> {single['subcategory']}\n💰 {single['amount']} руб.",
                    get_main_keyboard(user_id)
                )
                return True

            # СЦЕНАРИЙ Б: Несколько операций или новая статья -> интерактивное ревью
            user_states[user_id] = {
                "state": "multi_tx_review",
                "items": processed_items,
                "menu": menu_full
            }
            _show_multi_tx_items(user_id, processed_items, show_apply_all=False)
            return True

        except json.JSONDecodeError:
            send_vk_message(user_id, "❌ Ошибка: ИИ вернул некорректный формат ответа.", get_main_keyboard(user_id))
        except Exception as e:
            send_vk_message(user_id, f"❌ Ошибка базы данных: {e}", get_main_keyboard(user_id))
    else:
        if reply_text:
            send_vk_message(user_id, reply_text, get_main_keyboard(user_id))
            return True

    return False
