# -*- coding: utf-8 -*-
from keyboards import (
    get_main_keyboard,
    get_yes_no_keyboard,
    get_cancel_keyboard,
    type_keyboard,
    get_numbered_keyboard
)
from services import send_vk_message, categorize_with_ai
from db import (
    save_transaction,
    learn_user_word,
    smart_search_item,
    get_full_menu
)
from handlers_queue_batch import _validate_ai_category, _find_matching_article

def handle_learning_flow(user_id, internal_uid, user_text, user_text_lower, state, user_states, MAX_ATTEMPTS):
    """Интерактивный цикл подтверждения, сбора подсказок и ручной выбор дерева."""

    # 1. ПОДТВЕРЖДЕНИЕ "ДА / НЕТ"
    if state == "confirm_category":
        payload = user_states[user_id]["payload"]
        cat = user_states[user_id]["ai_cat"]
        sub = user_states[user_id]["ai_sub"]
        item_name = payload["item"]
        amount = float(payload.get("amount", 0))
        op_type = payload.get("type", "Расход")
        comment = payload.get("comment", "")
        canon_art = user_states[user_id].get("canonical_art") or item_name.capitalize()

        if any(t in user_text_lower for t in ["сделать отдельной статьей", "сделать отдельной статьёй", "отдельной статьей", "отдельная статья"]):
            send_vk_message(user_id, "⏳ Создаю новую статью и записываю операцию...")
            save_transaction(
                user_id=internal_uid,
                op_type=op_type,
                category=cat,
                subcategory=sub,
                article=item_name.capitalize(),
                amount=amount,
                comment=comment,
                original_text=item_name,
                status='verified'
            )
            learn_user_word(
                user_id=internal_uid,
                op_type=op_type,
                category=cat,
                subcategory=sub,
                article=item_name.capitalize(),
                synonym=item_name
            )
            send_vk_message(user_id, f"✅ Создана новая статья «{item_name.capitalize()}» в подкатегории «{sub}»!\nОперация записана.", get_main_keyboard(user_id))
            del user_states[user_id]
            return True

        if any(w in user_text_lower for w in ["да", "верно", "ага", "давай", "ок", "yes", "+"]):
            send_vk_message(user_id, "⏳ Запоминаю и записываю в базу...")
            save_transaction(
                user_id=internal_uid,
                op_type=op_type,
                category=cat,
                subcategory=sub,
                article=canon_art,
                amount=amount,
                comment=comment,
                original_text=item_name,
                status='verified'
            )
            learn_user_word(
                user_id=internal_uid,
                op_type=op_type,
                category=cat,
                subcategory=sub,
                article=canon_art,
                synonym=item_name
            )
            syn_msg = f"«{item_name}» привязано как синоним к статье «{canon_art}»" if canon_art.lower() != item_name.lower() else f"Статья: «{canon_art}»"
            send_vk_message(
                user_id,
                f"✅ Успешно записано!\n📂 {cat} -> {sub}\n{syn_msg}",
                get_main_keyboard(user_id)
            )
            del user_states[user_id]
            return True

        elif any(w in user_text_lower for w in ["нет", "неверно", "не", "no", "-"]):
            if user_states[user_id]["attempts"] < MAX_ATTEMPTS:
                user_states[user_id]["state"] = "provide_context"
                user_states[user_id]["context_history"] = ""
                send_vk_message(
                    user_id,
                    f"Понял, ошибся 😔 (Попытка {user_states[user_id]['attempts']} из {MAX_ATTEMPTS})\n"
                    f"Подскажи другими словами, к чему относится «{item_name}»?",
                    get_cancel_keyboard(show_back=True)
                )
            else:
                user_states[user_id]["state"] = "tx_manual_type"
                send_vk_message(user_id, "🤷‍♂️ Я сдаюсь. Давайте выберем вручную!\n\nЭто Расход или Доход?", type_keyboard(show_back=True))
            return True
        else:
            send_vk_message(user_id, "Пожалуйста, ответьте «✅ Да», «❌ Нет» или нажмите «📄 Сделать отдельной статьёй».", get_yes_no_keyboard(show_back=True, show_promote_article=True))
            return True

    # 2. ПОДСКАЗКА ОТ ПОЛЬЗОВАТЕЛЯ
    if state == "provide_context":
        user_states[user_id]["attempts"] += 1
        payload = user_states[user_id]["payload"]
        if "доход" in user_text_lower or "приход" in user_text_lower:
            payload["type"] = "Доход"
        elif "расход" in user_text_lower or "трата" in user_text_lower:
            payload["type"] = "Расход"

        op_type = payload.get("type", "Расход")
        check_res = smart_search_item(internal_uid, user_text, op_type=op_type)
        if check_res.get("status") != "FOUND":
            check_res = smart_search_item(internal_uid, user_text, op_type=None)

        if check_res.get("status") == "FOUND":
            user_states[user_id]["state"] = "confirm_category"
            user_states[user_id]["ai_cat"] = check_res.get("category")
            user_states[user_id]["ai_sub"] = check_res.get("subcategory")
            user_states[user_id]["canonical_art"] = check_res.get("article", payload["item"])
            if check_res.get("type"):
                payload["type"] = check_res["type"]
            send_vk_message(
                user_id,
                f"Ага! «{user_text}» — это статья «{check_res.get('article')}»:\n"
                f"📂 {check_res.get('category')} -> {check_res.get('subcategory')}\n\n"
                f"Привязать «{payload['item']}» как синоним?",
                get_yes_no_keyboard(show_back=True, show_promote_article=True)
            )
            return True

        send_vk_message(user_id, "🧠 Думаю...")
        menu_full = get_full_menu(internal_uid)
        type_menu = menu_full.get(op_type, {})
        menu_str = f"[{op_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])

        raw_c, raw_s = categorize_with_ai(payload["item"], menu_str, context=user_text)
        v_c, v_s = _validate_ai_category(menu_full, op_type, raw_c, raw_s)

        if v_c and v_s and v_s != "Требует проверки":
            canon_art = _find_matching_article(menu_full, op_type, v_c, v_s, payload["item"])
            user_states[user_id]["state"] = "confirm_category"
            user_states[user_id]["ai_cat"] = v_c
            user_states[user_id]["ai_sub"] = v_s
            user_states[user_id]["canonical_art"] = canon_art

            if canon_art.lower() != payload["item"].lower():
                prompt_msg = f"Ага! «{payload['item']}» относится к:\n📂 {v_c} -> {v_s} (статья: «{canon_art}»)\n\nПривязать как синоним к «{canon_art}»?"
            else:
                prompt_msg = f"Ага! «{payload['item']}» относится к:\n📂 {v_c} -> {v_s}\n\nСоздать статью «{payload['item'].capitalize()}»?"

            send_vk_message(user_id, prompt_msg, get_yes_no_keyboard(show_back=True, show_promote_article=(canon_art.lower() != payload["item"].lower())))
        else:
            if user_states[user_id]["attempts"] < MAX_ATTEMPTS:
                send_vk_message(user_id, f"Всё равно не могу сообразить 🤔 (Попытка {user_states[user_id]['attempts']} из {MAX_ATTEMPTS})\nПопробуй назвать точную категорию из твоего меню?", get_cancel_keyboard(show_back=True))
            else:
                user_states[user_id]["state"] = "tx_manual_type"
                send_vk_message(user_id, "🤷‍♂️ Я сдаюсь. Давайте выберем вручную!\n\nЭто Расход или Доход?", type_keyboard(show_back=True))
        return True

    # 3. ИНТЕРАКТИВНЫЙ РУЧНОЙ ВЫБОР
    if state == "tx_manual_type":
        if "доход" in user_text_lower or "расход" in user_text_lower:
            op_type = "Доход" if "доход" in user_text_lower else "Расход"
            user_states[user_id]["payload"]["type"] = op_type
            menu_full = get_full_menu(internal_uid)
            type_menu = menu_full.get(op_type, {})
            cats = sorted(list(type_menu.keys()))
            if not cats:
                send_vk_message(user_id, f"Категорий типа '{op_type}' пока нет.", get_main_keyboard(user_id))
                del user_states[user_id]
                return True
            user_states[user_id]["type_menu"] = type_menu
            user_states[user_id]["cats"] = cats
            user_states[user_id]["state"] = "tx_manual_cat"
            msg = f"Выберите КАТЕГОРИЮ ({op_type}):\n\n"
            for i, c in enumerate(cats):
                msg += f"{i+1}. {c}\n"
            send_vk_message(user_id, msg, get_numbered_keyboard(len(cats), show_back=True))
            return True
        else:
            send_vk_message(user_id, "Пожалуйста, выберите «📉 Расход» или «📈 Доход» кнопками внизу.", type_keyboard(show_back=True))
            return True

    if state == "tx_manual_cat":
        if user_text.isdigit():
            idx = int(user_text) - 1
            cats = user_states[user_id].get("cats", [])
            if 0 <= idx < len(cats):
                sel_cat = cats[idx]
                user_states[user_id]["sel_cat"] = sel_cat
                type_menu = user_states[user_id].get("type_menu", {})
                raw_subs = type_menu.get(sel_cat, [])
                subs = sorted(list(raw_subs.keys() if isinstance(raw_subs, dict) else raw_subs))
                if not subs:
                    subs = ["Другое"]
                user_states[user_id]["subs"] = subs
                user_states[user_id]["state"] = "tx_manual_sub"
                msg = f"Категория: {sel_cat}\nВыберите ПОДКАТЕГОРИЮ:\n\n"
                for i, s in enumerate(subs):
                    msg += f"{i+1}. {s}\n"
                send_vk_message(user_id, msg, get_numbered_keyboard(len(subs), show_back=True))
                return True

    if state == "tx_manual_sub":
        if user_text.isdigit():
            idx = int(user_text) - 1
            subs = user_states[user_id].get("subs", [])
            if 0 <= idx < len(subs):
                sel_sub = subs[idx]
                payload = user_states[user_id]["payload"]
                item_name = payload["item"]
                amount = float(payload.get("amount", 0))
                op_type = payload.get("type", "Расход")
                comment = payload.get("comment", "")
                sel_cat = user_states[user_id]["sel_cat"]

                send_vk_message(user_id, "⏳ Обучаюсь и записываю в базу...")
                menu_full = get_full_menu(internal_uid)
                canon_art = _find_matching_article(menu_full, op_type, sel_cat, sel_sub, item_name)

                save_transaction(
                    user_id=internal_uid,
                    op_type=op_type,
                    category=sel_cat,
                    subcategory=sel_sub,
                    article=canon_art,
                    amount=amount,
                    comment=comment,
                    original_text=item_name,
                    status='verified'
                )
                learn_user_word(
                    user_id=internal_uid,
                    op_type=op_type,
                    category=sel_cat,
                    subcategory=sel_sub,
                    article=canon_art,
                    synonym=item_name
                )
                syn_msg = f"«{item_name}» запомнено как синоним к статье «{canon_art}»" if canon_art.lower() != item_name.lower() else f"Создана статья «{canon_art}»"
                send_vk_message(user_id, f"✅ Успешно!\n📂 {sel_cat} -> {sel_sub}\n{syn_msg}", get_main_keyboard(user_id))
                del user_states[user_id]
                return True

    return False
