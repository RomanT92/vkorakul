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
# КАРТА ПОРЯДКОВЫХ ЧИСЛИТЕЛЬНЫХ ДЛЯ ГОЛОСОВОГО УДАЛЕНИЯ
# ====================================================================
ORDINAL_WORDS_MAP = {
    "перв": 1, "один": 1,
    "втор": 2, "два": 2,
    "трет": 3, "три": 3,
    "четверт": 4, "четыр": 4,
    "пят": 5,
    "шест": 6,
    "сед": 7, "сем": 7,
    "восьм": 8, "восем": 8,
    "девят": 9,
    "десят": 10,
    "одиннадцат": 11,
    "двенадцат": 12,
    "тринадцат": 13,
    "четырнадцат": 14,
    "пятнадцат": 15,
    "шестнадцат": 16,
    "семнадцат": 17,
    "восемнадцат": 18,
    "девятнадцат": 19,
    "двадцат": 20,
    "последн": -1
}

def _parse_ordinal_token(token: str):
    """Преобразует порядковое слово или цифру в номер позиции (1-based)."""
    digits = re.sub(r'[^0-9]', '', token)
    if digits.isdigit() and int(digits) > 0:
        return int(digits)
    t_clean = token.lower().strip()
    for prefix, num in sorted(ORDINAL_WORDS_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if t_clean.startswith(prefix):
            return num
    return None

def _extract_delete_indices_or_names(text: str, items: list):
    """
    Извлекает список индексов (0-based) для удаления из фразы:
    'первое, четвертое и второе' -> [0, 3, 1]
    '1 и 3' -> [0, 2]
    """
    clean = re.sub(r'^(?:вычеркни|удали|убери|сотри|исключи)\s+', '', text, flags=re.IGNORECASE).strip()
    clean = re.sub(r'\s+из\s+покупок$', '', clean, flags=re.IGNORECASE).strip()

    tokens = [t.strip().strip('.,;!?') for t in re.split(r'[,;\s]+|\s+и\s+', clean) if t.strip()]
    matched_indices = []
    unmatched_tokens = []

    for tok in tokens:
        idx_num = _parse_ordinal_token(tok)
        if idx_num is not None:
            actual_idx = (len(items) - 1) if idx_num == -1 else (idx_num - 1)
            if 0 <= actual_idx < len(items) and actual_idx not in matched_indices:
                matched_indices.append(actual_idx)
        else:
            unmatched_tokens.append(tok.lower())

    # Если не нашли цифр/порядковых, ищем совпадения по названиям товаров
    if not matched_indices and unmatched_tokens:
        for idx, it in enumerate(items):
            it_name = it["item"].lower()
            for tok in unmatched_tokens:
                if len(tok) >= 3 and (tok in it_name or it_name in tok):
                    if idx not in matched_indices:
                        matched_indices.append(idx)
                    break

    return matched_indices

# ====================================================================
# CRUD ОПЕРАЦИИ С БАЗОЙ ДАННЫХ
# ====================================================================
def add_planned_items(user_id, items_data):
    """Добавляет список покупок в базу данных."""
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

def delete_items_by_ids(user_id, item_ids):
    """Удаляет список позиций по их ID без создания транзакций."""
    if not item_ids:
        return []
    _init_planned_db()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        uid = _resolve_internal_user_id(cur, user_id)
        cur.execute(
            "DELETE FROM planned_purchases WHERE id = ANY(%s) AND user_id = %s RETURNING item;",
            (item_ids, uid)
        )
        deleted_rows = cur.fetchall()
        conn.commit()
        return [r[0] for r in deleted_rows]
    except Exception as e:
        print(f"[PLANNED] Ошибка удаления позиций покупок: {e}")
        return []
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
# СИНТАКСИЧЕСКИЙ РАЗБОР ВВОДА ПОКУПОК
# ====================================================================
def _extract_planned_items_from_text(raw_text):
    """Разбирает фразу ввода покупок на отдельные позиции с опциональной суммой."""
    clean = re.sub(

        r'^(?:надо\s+|нужно\s+|не\s+забыть\s+|запиши\s+в\s+(?:список\s+)?покупок[:\s]*|в\s+список\s+покупок[:\s]*|список\s+покупок[:\s]*|купить|покупки[:\s]*)\s*',
        '',
        raw_text,
        flags=re.IGNORECASE
    ).strip()

    if not clean:
        return []

    parts = re.split(r'[,;]+|\s+и\s+', clean)
    items = []
    for p in parts:
        p_clean = p.strip().strip('.,;!?')
        if not p_clean:
            continue
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
    """Автономный перехватчик голосового и текстового управления списком покупок."""
    clean_text = re.sub(r'[^\w\s]', '', user_text_lower).strip()

    # 1. Запрос отображения списка покупок
    view_triggers = [
        "что купить", "список покупок", "покажи список покупок", "показать список покупок",
        "открой список покупок", "выведи список покупок", "мои покупки", "план покупок",
        "покупки", "покажи покупки", "открой покупки", "выведи покупки", "что нужно купить",
        "что надо купить", "глянуть покупки", "посмотреть покупки", "список того что купить"
    ]
    is_view_cmd = (
        clean_text in view_triggers
        or any(clean_text.startswith(tr) for tr in ["что купить", "список покупок", "покажи список покупок", "выведи список покупок", "показать список"])
        or ("список" in clean_text and "покуп" in clean_text)
    )
    if is_view_cmd:
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

        msg += "\n💡 Когда купишь, скажи:\n«Купил 1 за 250» или «Купил молоко 250».\n"
        msg += "💡 Для удаления: «Удали первое, четвертое и второе»."
        send_vk_message(user_id, msg, get_main_keyboard(user_id))
        return True

    # 2. Фиксация факта покупки («Купил молоко 250», «Купил 1 за 300», «Купил болгарку»)
    bought_m = re.match(r'^(?:купил|взял|оплатил)\s+(.+)$', user_text_lower)
    if bought_m:
        raw_cmd = bought_m.group(1).strip()
        items = get_active_planned_items(internal_uid)
        
        target_item = None
        actual_amount = None

        amt_match = re.search(r'(?:за\s+)?(\d+(?:[.,]\d+)?)\s*(?:руб|рублей|р)?$', raw_cmd)
        cmd_target = raw_cmd
        if amt_match:
            try:
                actual_amount = float(amt_match.group(1).replace(',', '.'))
                cmd_target = raw_cmd[:amt_match.start()].strip()
                cmd_target = re.sub(r'\s+за$', '', cmd_target).strip()
            except ValueError:
                pass

        if cmd_target.isdigit() and items:
            idx = int(cmd_target) - 1
            if 0 <= idx < len(items):
                target_item = items[idx]
        elif items:
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

            mark_item_bought_by_id(internal_uid, target_item["id"])
            search_res = smart_search_item(internal_uid, target_item["item"], op_type="Расход")
            if search_res.get("status") == "FOUND":
                cat = search_res.get("category")
                sub = search_res.get("subcategory")
                art = search_res.get("article")
            else:
                cat = "Быт"
                sub = "Покупки"
                art = target_item["item"].capitalize()

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

    # 3. Полная очистка списка
    if clean_text in ["очисти список покупок", "очисти покупки", "удали все покупки", "удали весь список покупок"]:
        count = clear_all_planned_items(internal_uid)
        send_vk_message(user_id, f"🗑 Список покупок очищен (удалено позиций: {count}).", get_main_keyboard(user_id))
        return True

    # 4. Удаление / вычеркивание одиночных или составных позиций голосом («Удали первое, четвертое и второе»)
    del_prefixes = ["вычеркни", "удали", "убери", "сотри", "исключи"]
    is_del_cmd = any(user_text_lower.startswith(pfx) for pfx in del_prefixes)
    if is_del_cmd:
        items = get_active_planned_items(internal_uid)
        if items:
            del_indices = _extract_delete_indices_or_names(user_text_lower, items)
            if del_indices:
                target_ids = [items[idx]["id"] for idx in del_indices]
                deleted_names = delete_items_by_ids(internal_uid, target_ids)
                left_count = len(items) - len(deleted_names)
                
                deleted_str = ", ".join([f"«{name}»" for name in deleted_names])
                left_msg = f"Осталось в списке: {left_count} шт." if left_count > 0 else "Список покупок теперь пуст!"
                send_vk_message(
                    user_id,
                    f"🗑 Удалено из списка покупок: {deleted_str}.\n{left_msg}",
                    get_main_keyboard(user_id)
                )
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
            msg += "\nПосмотреть весь список: «Что купить» или «Покажи список покупок»."
            send_vk_message(user_id, msg, get_main_keyboard(user_id))
            return True

    return False
