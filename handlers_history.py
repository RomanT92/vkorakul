# -*- coding: utf-8 -*-
import re
from datetime import datetime
from keyboards import (
    get_main_keyboard,
    get_numbered_keyboard,
    get_tx_action_keyboard,
    get_cancel_keyboard
)
from services import send_vk_message, categorize_with_ai
from db import (
    get_user_history,
    delete_transaction_by_id,
    delete_all_user_transactions,
    get_last_transaction,
    update_transaction_amount,
    update_transaction_category,
    get_full_menu,
    promote_synonym_to_article,
    learn_user_word
)
from handlers_tx_parser import _validate_ai_category_choice, _find_best_matching_article_in_sub

def _format_history_response(user_id, hist_data, title="📜 История ваших последних операций:"):
    items = hist_data.get("items", [])
    if not items:
        send_vk_message(user_id, "За выбранный период операций не найдено.", get_main_keyboard(user_id))
        return

    msg = f"{title}\n\n"
    for i, it in enumerate(items, 1):
        dt = it["date"].strftime("%d.%m %H:%M") if hasattr(it["date"], "strftime") else str(it["date"])[:16]
        type_icon = "📉" if it["type"] == "Расход" else "📈"
        comm = f" ({it['comment']})" if it.get("comment") else ""
        msg += f"{i}. {dt} | {it['article']} — {it['amount']:g} ₽ {type_icon}{comm}\n"
        msg += f"   📂 {it['category']} -> {it['subcategory']}\n\n"

    msg += f"Всего расходов: {hist_data.get('total_expense', 0):g} ₽\n"
    msg += f"Всего доходов: {hist_data.get('total_income', 0):g} ₽\n\n"
    msg += "💡 Чтобы изменить или удалить операцию — отправьте её НОМЕР из списка."

    send_vk_message(user_id, msg, get_numbered_keyboard(len(items), show_back=True))

def apply_edit_to_last_transaction(user_id, internal_uid, new_category_hint=None, new_amount=None, new_item_name=None, new_type=None, new_article_name=None):
    """
    Применяет точечное исправление к последней финансовой транзакции пользователя.
    """
    last_tx = get_last_transaction(internal_uid)
    if not last_tx:
        send_vk_message(user_id, "⚠️ У вас пока нет записанных операций для редактирования.", get_main_keyboard(user_id))
        return True

    tx_id = last_tx["id"]
    changes = []

    # 1. Смена суммы
    if new_amount is not None and float(new_amount) > 0:
        if update_transaction_amount(internal_uid, tx_id, float(new_amount)):
            changes.append(f"• Сумма: {float(new_amount):g} руб.")

    # 2. Создание новой статьи на лету и перенос транзакции
    if new_article_name:
        raw_art = new_article_name.strip()
        clean_new_art = raw_art[0].upper() + raw_art[1:] if raw_art else "Новая статья"
        cat = last_tx["category"]
        sub = last_tx["subcategory"]
        op_t = new_type or last_tx["type"]
        
        promote_synonym_to_article(internal_uid, op_t, cat, sub, clean_new_art)
        learn_user_word(internal_uid, op_t, cat, sub, clean_new_art, clean_new_art.lower())
        update_transaction_category(internal_uid, tx_id, cat, sub, article=clean_new_art, op_type=op_t)
        changes.append(f"• Перенесено в новую статью: «{clean_new_art}» (📂 {cat} -> {sub})")

    # 3. Смена категории / подкатегории / статьи
    elif new_category_hint:
        menu_full = get_full_menu(internal_uid)
        op_t = new_type or last_tx["type"]
        type_menu = menu_full.get(op_t, {})
        menu_str = f"[{op_t}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])

        raw_c, raw_s = categorize_with_ai(last_tx["original_text"] or last_tx["article"], menu_str, context=new_category_hint)
        v_c, v_s = _validate_ai_category_choice(menu_full, op_t, raw_c, raw_s)

        if v_c and v_s and v_s != "Требует проверки":
            matched_art = _find_best_matching_article_in_sub(menu_full, op_t, v_c, v_s, new_category_hint)
            if update_transaction_category(internal_uid, tx_id, v_c, v_s, article=matched_art, op_type=op_t):
                learn_user_word(internal_uid, op_t, v_c, v_s, matched_art, (last_tx["original_text"] or last_tx["article"]).lower())
                changes.append(f"• Категория: {v_c} -> {v_s} (статья: «{matched_art}»)")
        else:
            send_vk_message(
                user_id,
                f"⚠️ Не удалось подобрать категорию по подсказке «{new_category_hint}».\nОперация оставлена без изменений.",
                get_main_keyboard(user_id)
            )
            return True

    if changes:
        orig_name = last_tx.get('original_text') or last_tx.get('article')
        msg = f"✅ Последняя операция («{orig_name}») успешно обновлена!\n\n" + "\n".join(changes)
        send_vk_message(user_id, msg, get_main_keyboard(user_id))
        return True

    return False

def handle_history_and_edits(user_id, internal_uid, user_text, user_text_lower, state, user_states):
    """
    Диспетчер истории операций и редактирования конкретных финансовых транзакций.
    СТРОГОЕ ПРАВИЛО: НЕ перехватывает команды списка покупок и структуры каталога!
    """
    # ==============================================================
    # 0. ЗАЩИТА: ЕСЛИ ЭТО СПИСОК ПОКУПОК ИЛИ СТРУКТУРА -> ПРОПУСКАЕМ!
    # ==============================================================
    # 0.1 Список покупок отдаем строго в handlers_planned.py
    if any(pk in user_text_lower for pk in ["список покупок", "план покупок", "что купить", "купить", "покупки"]):
        # Исключение: если явно запрошена история прошлых покупок
        if not any(past_kw in user_text_lower for past_kw in ["последние покупки", "прошлые покупки", "история покупок"]):
            return False

    # 0.2 Управление структурой
    structure_entity_words = ["статью", "статья", "статье", "подкатегорию", "подкатегория", "подкатегории", "категорию", "категория", "категории"]
    if any(re.search(r'\b' + re.escape(w) + r'\b', user_text_lower) for w in structure_entity_words):
        if not any(tx_kw in user_text_lower for tx_kw in ["последн", "предпоследн", "этой операци", "эту операци", "данной операци"]):
            return False

    # ==============================================================
    # 1. ПРАВКА ПОСЛЕДНЕЙ ОПЕРАЦИИ (СТРОГО ПРИ НАЛИЧИИ СЛОВА "ПОСЛЕДН...")
    # ==============================================================
    is_last_tx_command = any(w in user_text_lower for w in ["последн", "предпоследн"])
    
    if is_last_tx_command:
        # 1.1 Создание новой статьи для последней операции

        new_art_m = re.search(r'(?:перенеси|создай|сделай)?\s*(?:в|на)?\s*нов(?:ую|ая|ой)\s*стать(?:ю|я|е)\s*(.+)$', user_text_lower)
        if new_art_m:
            val_art = new_art_m.group(1).strip()
            val_art = re.sub(r'^(?:под\s*названием|с\s*названием|это|как)\s+', '', val_art).strip()
            if val_art:
                return apply_edit_to_last_transaction(user_id, internal_uid, new_article_name=val_art)

        # 1.2 Изменение суммы последней операции
        amt_match = re.search(r'(?:сумму|сумма|на сумму|поставь сумму)\s*(?:на|в|равна)?\s*(\d+(?:[.,]\d+)?)$', user_text_lower)
        if amt_match:
            try:
                new_amt = float(amt_match.group(1).replace(',', '.'))
                return apply_edit_to_last_transaction(user_id, internal_uid, new_amount=new_amt)
            except ValueError:
                pass

        # 1.3 Перенос последней операции в другую категорию
        cat_match = re.search(r'(?:перенеси|поменяй категорию|смени категорию|категорию|в категорию|в подкатегорию)\s*(?:на|в|как)?\s+(.+)$', user_text_lower)
        if cat_match:
            hint = cat_match.group(1).strip()
            hint = re.sub(r'^(?:на|в|как|категорию|подкатегорию)\s+', '', hint).strip()
            if hint and not any(sw in hint for sw in ["удали", "отмена", "назад", "сумма"]):
                return apply_edit_to_last_transaction(user_id, internal_uid, new_category_hint=hint)

        # 1.4 Удаление последней операции
        if any(w in user_text_lower for w in ["удали последнюю", "отмени последнюю", "убери последнюю"]):
            last_tx = get_last_transaction(internal_uid)
            if not last_tx:
                send_vk_message(user_id, "⚠️ У вас пока нет операций для удаления.", get_main_keyboard(user_id))
                return True
            if delete_transaction_by_id(internal_uid, last_tx["id"]):
                send_vk_message(
                    user_id,
                    f"🗑 Последняя операция («{last_tx['original_text'] or last_tx['article']}» — {last_tx['amount']:g} ₽) успешно удалена!",
                    get_main_keyboard(user_id)
                )
            else:
                send_vk_message(user_id, "❌ Не удалось удалить операцию.", get_main_keyboard(user_id))
            return True

    # ==============================================================
    # 2. ПРОСМОТР ИСТОРИИ ПРОШЛЫХ ОПЕРАЦИЙ (ВЫПИСКИ)
    # ==============================================================
    history_triggers = [
        "история", "мои траты", "выписка", "покажи операции", "список операций",
        "история операций", "последние операции", "последние покупки", "выведи последние покупки",
        "выведи последние операции", "покажи последние траты", "мои расходы", "история трат"
    ]
    is_history_cmd = (
        user_text_lower in history_triggers
        or any(user_text_lower.startswith(tr) for tr in ["покажи историю", "показать историю", "покажи последние операции", "выведи последние"])
    )
    if is_history_cmd:
        hist = get_user_history(internal_uid, limit=10)
        user_states[user_id] = {"state": "history_view", "history_items": hist.get("items", [])}
        _format_history_response(user_id, hist, "📜 Ваши последние 10 операций:")
        return True

    # ==============================================================
    # 3. ИНТЕРАКТИВНОЕ РЕДАКТИРОВАНИЕ ОПЕРАЦИИ ИЗ СПИСКА
    # ==============================================================
    if state == "history_view":
        if any(w in user_text_lower for w in ["отмена", "назад"]):
            del user_states[user_id]
            send_vk_message(user_id, "Главное меню.", get_main_keyboard(user_id))
            return True

        if user_text.isdigit():
            idx = int(user_text) - 1
            items = user_states[user_id].get("history_items", [])
            if 0 <= idx < len(items):
                sel_item = items[idx]
                user_states[user_id]["state"] = "tx_action_select"
                user_states[user_id]["selected_tx"] = sel_item
                msg = (
                    f"Выбрана операция:\n"
                    f"📌 {sel_item['article']} — {sel_item['amount']:g} ₽\n"
                    f"📂 {sel_item['category']} -> {sel_item['subcategory']}\n\n"
                    f"Что вы хотите сделать?"
                )
                send_vk_message(user_id, msg, get_tx_action_keyboard())
                return True

    if state == "tx_action_select":
        sel_item = user_states[user_id].get("selected_tx")
        if not sel_item:
            del user_states[user_id]
            return False

        if "изменить сумму" in user_text_lower:
            user_states[user_id]["state"] = "tx_edit_amount_input"
            send_vk_message(user_id, f"Введите новую сумму для «{sel_item['article']}»:", get_cancel_keyboard(show_back=True))
            return True

        elif "изменить категорию" in user_text_lower:
            user_states[user_id]["state"] = "tx_edit_cat_input"
            send_vk_message(user_id, f"Напишите новую категорию, подкатегорию или статью для «{sel_item['article']}»:", get_cancel_keyboard(show_back=True))
            return True

        elif "удалить операцию" in user_text_lower:
            if delete_transaction_by_id(internal_uid, sel_item["id"]):
                send_vk_message(user_id, f"🗑 Операция «{sel_item['article']}» ({sel_item['amount']:g} ₽) удалена!", get_main_keyboard(user_id))
            else:
                send_vk_message(user_id, "❌ Не удалось удалить операцию.", get_main_keyboard(user_id))
            del user_states[user_id]
            return True

    if state == "tx_edit_amount_input":
        sel_item = user_states[user_id].get("selected_tx")
        num_clean = re.sub(r'[^0-9.,]', '', user_text).replace(',', '.')
        try:
            val = float(num_clean)
            if val > 0 and update_transaction_amount(internal_uid, sel_item["id"], val):
                send_vk_message(user_id, f"✅ Сумма успешно изменена на {val:g} ₽!", get_main_keyboard(user_id))
                del user_states[user_id]
                return True
        except ValueError:
            pass
        send_vk_message(user_id, "⚠️ Пожалуйста, введите корректное число (сумму):", get_cancel_keyboard(show_back=True))
        return True

    if state == "tx_edit_cat_input":
        sel_item = user_states[user_id].get("selected_tx")
        menu_full = get_full_menu(internal_uid)
        op_t = sel_item["type"]
        type_menu = menu_full.get(op_t, {})
        menu_str = f"[{op_t}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])

        raw_c, raw_s = categorize_with_ai(sel_item["article"], menu_str, context=user_text)
        v_c, v_s = _validate_ai_category_choice(menu_full, op_t, raw_c, raw_s)

        if v_c and v_s and v_s != "Требует проверки":
            matched_art = _find_best_matching_article_in_sub(menu_full, op_t, v_c, v_s, user_text)
            update_transaction_category(internal_uid, sel_item["id"], v_c, v_s, article=matched_art, op_type=op_t)
            send_vk_message(user_id, f"✅ Категория изменена на:\n📂 {v_c} -> {v_s} (статья: «{matched_art}»)", get_main_keyboard(user_id))
            del user_states[user_id]
            return True
        else:
            send_vk_message(user_id, "⚠️ Не удалось сопоставить с каталогом. Попробуйте еще раз:", get_cancel_keyboard(show_back=True))
            return True

    return False
