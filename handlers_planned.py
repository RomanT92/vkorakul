# -*- coding: utf-8 -*-
import re
from db.connection import get_db_connection
from db.transactions import (
    smart_search_item,
    save_transaction,
    _resolve_internal_user_id
)
from services import send_vk_message
from keyboards import get_main_keyboard

# ====================================================================
# АВТОНОМНАЯ ИНИЦИАЛИЗАЦИЯ ТАБЛИЦЫ В БАЗЕ ДАННЫХ
# ====================================================================
_DB_INITIALIZED = False

def _init_planned_db():
    """Создает таблицу запланированных покупок при первом запуске, если она отсутствует."""
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS planned_purchases (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                item VARCHAR(255) NOT NULL,
                expected_amount NUMERIC(12, 2) DEFAULT NULL,
                comment TEXT DEFAULT '',
                is_bought BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_planned_purchases_user 
            ON planned_purchases (user_id, is_bought);
        """)
        conn.commit()
        _DB_INITIALIZED = True
    except Exception as e:
        print(f"[PLANNED] Ошибка инициализации таблицы planned_purchases: {e}")
    finally:
        cur.close()
        conn.close()

# ====================================================================
# CRUD ОПЕРАЦИИ С БАЗОЙ ДАННЫХ
# ====================================================================
def add_planned_items(user_id, items_data):
    """
    Добавляет список покупок в базу данных.
    items_data: список словарей [{"item": str, "amount": float|None}]
    """
    _init_planned_db()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        query = """
            INSERT INTO planned_purchases (user_id, item, expected_amount)
            VALUES (%s, %s, %s);
        """
        for it in items_data:
            cur.execute(query, (uid, it["item"].strip(), it.get("amount")))
        conn.commit()
        return True
    except Exception as e:
        print(f"[PLANNED] Ошибка добавления запланированных покупок: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def get_active_planned_items(user_id):
    """Возвращает список еще не купленных товаров пользователя."""
    _init_planned_db()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        cur.execute("""
            SELECT id, item, expected_amount, created_at
            FROM planned_purchases
            WHERE user_id = %s AND is_bought = FALSE
            ORDER BY id ASC;
        """, (uid,))
        rows = cur.fetchall()
        result = []
        for r in rows:
            result.append({
                "id": r[0],
                "item": r[1],
                "expected_amount": float(r[2]) if r[2] is not None else None,
                "created_at": r[3]
            })
        return result
    except Exception as e:
        print(f"[PLANNED] Ошибка чтения списка покупок: {e}")
        return []
    finally:
        cur.close()
        conn.close()

def mark_item_bought_by_id(user_id, item_id):
    """Помечает позицию по ID как купленную."""
    _init_planned_db()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        cur.execute("""
            UPDATE planned_purchases
            SET is_bought = TRUE
            WHERE id = %s AND user_id = %s AND is_bought = FALSE
            RETURNING item, expected_amount;
        """, (item_id, uid))
        row = cur.fetchone()
        conn.commit()
        if row:
            return {"item": row[0], "expected_amount": float(row[1]) if row[1] is not None else None}
        return None
    except Exception as e:
        print(f"[PLANNED] Ошибка отметки покупки: {e}")
        return None
    finally:
        cur.close()
        conn.close()

def delete_item_by_id(user_id, item_id):
    """Удаляет позицию из списка без создания транзакции."""
    _init_planned_db()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        cur.execute("DELETE FROM planned_purchases WHERE id = %s AND user_id = %s RETURNING item;", (item_id, uid))
        row = cur.fetchone()
        conn.commit()
        return row[0] if row else None
    except Exception as e:
        print(f"[PLANNED] Ошибка удаления из списка покупок: {e}")
        return None
    finally:
        cur.close()
        conn.close()

def clear_all_planned_items(user_id):
    """Очищает весь некупленный список покупок пользователя."""
    _init_planned_db()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        cur.execute("DELETE FROM planned_purchases WHERE user_id = %s AND is_bought = FALSE;", (uid,))
        deleted_count = cur.rowcount
        conn.commit()
        return deleted_count
    except Exception as e:
        print(f"[PLANNED] Ошибка полной очистки покупок: {e}")
        return 0
    finally:
        cur.close()
        conn.close()

# ====================================================================
# СИНТАКСИЧЕСКИЙ РАЗБОР ГОЛОСОВЫХ И ТЕКСТОВЫХ ФРАЗ
# ====================================================================
def _extract_planned_items_from_text(raw_text):
    """
    Разбирает фразу ввода покупок на отдельные позиции с опциональной суммой.
    Примеры:
    - 'купить молоко, хлеб и сыр' -> [молоко, хлеб, сыр]
    - 'надо купить болгарку за 4500 и диски 300' -> [болгарка (4500), диски (300)]
    """
    clean = re.sub(

        r'^(?:надо\s+|нужно\s+|не\s+забыть\s+|запиши\s+в\s+(?:список\s+)?покупок[:\s]*|в\s+список\s+покупок[:\s]*|список\s+покупок[:\s]*|купить|покупки[:\s]*)\s*',
        '',
        raw_text,
        flags=re.IGNORECASE
    ).strip()

    if not clean:
        return []

    # Разделяем по запятым и союзу 'и'
    parts = re.split(r'[,;]+|\s+и\s+', clean)
    items = []
    for p in parts:
        p_clean = p.strip().strip('.,;!?')
        if not p_clean:
            continue
        # Поиск суммы в конце строки: 'болгарку за 4500', 'куртка 12000 руб'
        amt_m = re.search(r'(?:за\s+)?(\d+(?:[.,]\d+)?)\s*(?:руб|рублей|р)?$', p_clean, flags=re.IGNORECASE)
        amount = None
        item_title = p_clean
        if amt_m:
            try:
                amount = float(amt_m.group(1).replace(',', '.'))
                item_title = p_clean[:amt_m.start()].strip()
                item_title = re.sub(r'\s+за$', '', item_title, flags=re.IGNORECASE).strip()
            except ValueError:
                pass
        
        if item_title:
            items.append({"item": item_title.capitalize(), "amount": amount})
    return items

# ====================================================================
# ЕДИНЫЙ ВХОДНОЙ ДИСПЕТЧЕР МОДУЛЯ ПОКУПОК
# ====================================================================
def handle_planned_purchases(user_id, internal_uid, user_text, user_text_lower, state, user_states):
    """
    Автономный перехватчик списка покупок.
    Возвращает True, если запрос обработан этим модулем, иначе False.
    """
    # 1. Запрос отображения списка покупок
    view_triggers = [
        "что купить", "список покупок", "список покупок.", "мои покупки",
        "план покупок", "покупки", "покажи покупки", "открой покупки"
    ]
    if user_text_lower in view_triggers or user_text_lower.startswith("что купить"):
        items = get_active_planned_items(internal_uid)
        if not items:
            send_vk_message(
                user_id,
                "🛒 Твой список покупок пуст!\n\n"
                "Чтобы добавить, просто скажи или напиши:\n"
                "👉 «Купить молоко, хлеб и кофе»\n"
                "👉 «Надо купить болгарку за 4500»",
                get_main_keyboard(user_id)
            )
            return True

        msg = "🛒 СПИСОК ПОКУПОК:\n\n"
        total_sum = 0.0
        has_sums = False
        for idx, it in enumerate(items, start=1):
            amt_str = ""
            if it["expected_amount"] is not None:
                amt_str = f" (~{it['expected_amount']:g} ₽)"
                total_sum += it["expected_amount"]
                has_sums = True
            msg += f"{idx}. {it['item']}{amt_str}\n"

        if has_sums and total_sum > 0:
            msg += f"\n💰 Ожидаемая сумма: ~{total_sum:g} ₽\n"

        msg += "\n💡 Когда купишь, скажи:\n«Купил 1 за 250» или «Купил молоко 250»."
        send_vk_message(user_id, msg, get_main_keyboard(user_id))
        return True

    # 2. Фиксация факта покупки («Купил молоко 250», «Купил 1 за 300», «Купил болгарку»)
    bought_m = re.match(r'^(?:купил|взял|оплатил)\s+(.+)$', user_text_lower)
    if bought_m:
        raw_cmd = bought_m.group(1).strip()
        items = get_active_planned_items(internal_uid)
        
        target_item = None
        actual_amount = None

        # Проверяем сумму в конце команды
        amt_match = re.search(r'(?:за\s+)?(\d+(?:[.,]\d+)?)\s*(?:руб|рублей|р)?$', raw_cmd)
        cmd_target = raw_cmd
        if amt_match:
            try:
                actual_amount = float(amt_match.group(1).replace(',', '.'))
                cmd_target = raw_cmd[:amt_match.start()].strip()
                cmd_target = re.sub(r'\s+за$', '', cmd_target).strip()
            except ValueError:
                pass

        # Проверка по номеру строки: "купил 1", "купил 1 за 250"
        if cmd_target.isdigit() and items:
            idx = int(cmd_target) - 1
            if 0 <= idx < len(items):
                target_item = items[idx]
        elif items:
            # Поиск по совпадению названия
            for it in items:
                if it["item"].lower() in cmd_target or cmd_target in it["item"].lower():
                    target_item = it
                    break

        if target_item:
            final_amount = actual_amount if actual_amount is not None else target_item.get("expected_amount")
            if final_amount is None or final_amount <= 0:
                send_vk_message(
                    user_id,
                    f"На какую сумму купили «{target_item['item']}»?\n"
                    f"Напишите или скажите, например: «Купил {target_item['item']} 350».",
                    get_main_keyboard(user_id)
                )
                return True

            # 1. Помечаем как купленное в списке
            mark_item_bought_by_id(internal_uid, target_item["id"])

            # 2. Подбираем категорию и статью через smart_search_item
            search_res = smart_search_item(internal_uid, target_item["item"], op_type="Расход")
            if search_res.get("status") == "FOUND":
                cat = search_res.get("category")
                sub = search_res.get("subcategory")
                art = search_res.get("article")
            else:
                cat = "Быт"
                sub = "Покупки"
                art = target_item["item"].capitalize()

            # 3. Сохраняем в реальные транзакции
            save_transaction(
                user_id=internal_uid,
                op_type="Расход",
                category=cat,
                subcategory=sub,
                article=art,
                amount=final_amount,
                comment="Из списка покупок",
                original_text=target_item["item"],
                status='verified'
            )

            send_vk_message(
                user_id,
                f"✅ Куплено: {target_item['item']} — {final_amount:g} ₽\n"
                f"📂 Записано в {cat} -> {sub} (статья: {art})\n"
                f"Вычеркнуто из списка покупок! 🎉",
                get_main_keyboard(user_id)
            )
            return True

    # 3. Простое удаление / вычеркивание без создания расхода
    del_m = re.match(r'^(?:вычеркни|удали|убери|сотри)\s+(.+?)(?:\s+из\s+покупок)?$', user_text_lower)
    if del_m:
        raw_target = del_m.group(1).strip()
        items = get_active_planned_items(internal_uid)
        target_to_del = None
        if raw_target.isdigit() and items:
            idx = int(raw_target) - 1
            if 0 <= idx < len(items):
                target_to_del = items[idx]
        elif items:
            for it in items:
                if it["item"].lower() in raw_target or raw_target in it["item"].lower():
                    target_to_del = it
                    break

        if target_to_del:
            delete_item_by_id(internal_uid, target_to_del["id"])
            send_vk_message(user_id, f"🗑 «{target_to_del['item']}» удалено из списка покупок.", get_main_keyboard(user_id))
            return True

    # 4. Полная очистка списка
    if user_text_lower in ["очисти список покупок", "очисти покупки", "удали все покупки"]:
        count = clear_all_planned_items(internal_uid)
        send_vk_message(user_id, f"🗑 Список покупок очищен (удалено позиций: {count}).", get_main_keyboard(user_id))
        return True

    # 5. Добавление новых запланированных покупок голосом или текстом
    add_triggers = [
        "купить", "надо купить", "нужно купить", "не забыть купить",
        "запиши в покупки", "запиши в список покупок", "в список покупок"
    ]
    is_add_cmd = any(user_text_lower.startswith(tr) for tr in add_triggers)
    if is_add_cmd:
        parsed_items = _extract_planned_items_from_text(user_text)
        if parsed_items:
            add_planned_items(internal_uid, parsed_items)
            msg = "🛒 Добавлено в список покупок:\n"
            for it in parsed_items:
                amt_str = f" (~{it['amount']:g} ₽)" if it.get("amount") else ""
                msg += f"• {it['item']}{amt_str}\n"
            msg += "\nПосмотреть весь список: «Что купить»."
            send_vk_message(user_id, msg, get_main_keyboard(user_id))
            return True

    return False
