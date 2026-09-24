# -*- coding: utf-8 -*-
import re

ORDINAL_MAP = {
    "во-перв": 1, "перв": 1, "один": 1, "1": 1,
    "во-втор": 2, "втор": 2, "два": 2, "2": 2,
    "в-трет": 3, "трет": 3, "три": 3, "3": 3,
    "четверт": 4, "четыр": 4, "4": 4,
    "пят": 5, "5": 5,
    "шест": 6, "6": 6,
    "сед": 7, "сем": 7, "7": 7,
    "восьм": 8, "8": 8,
    "девят": 9, "9": 9,
    "десят": 10, "10": 10,
    "одиннадцат": 11, "11": 11,
    "двенадцат": 12, "12": 12,
    "тринадцат": 13, "13": 13,
    "четырнадцат": 14, "14": 14,
    "пятнадцат": 15, "15": 15,
    "последн": -1
}

def _try_fast_deterministic_single_clause(clause_text, items_len):
    """
    Разбор одной клаузы (например: 'первое это фастфуд' или 'во-первых создай новую статью Лепёшки') за 1 мс.
    """
    clean = clause_text.strip()
    target_idx = None
    matched_token = None
    for token in clean.split():
        for prefix, num in ORDINAL_MAP.items():
            if token.startswith(prefix):
                target_idx = (items_len - 1) if num == -1 else (num - 1)
                matched_token = token
                break
        if target_idx is not None:
            break

    if target_idx is None or not (0 <= target_idx < items_len):
        return None

    # 1. Создание новой статьи для конкретной операции (включая формы «во-первых, создай новую статью X»)

    new_art_m = re.search(r'(?:перенеси|перенести|создай|создать|сделай|сделать|запиши|добавь)?\s*(?:в|на)?\s*нов(?:ую|ая|ой)\s*стать(?:ю|я|е)\s*(?:под\s*названием|с\s*названием|это|как)?\s*(.+)$', clean, flags=re.IGNORECASE)
    if not new_art_m:
        new_art_m = re.search(r'(?:это|назови)?\s*(.+?)\s*(?:в|на)?\s*нов(?:ую|ая|ой)\s*стать(?:ю|я|е)$', clean, flags=re.IGNORECASE)
    if new_art_m:
        val_art = new_art_m.group(1).strip()
        val_art = re.sub(r'^(?:в|на|под\s*названием|это|как)\s+', '', val_art, flags=re.IGNORECASE).strip()
        val_art = re.sub(r'\bна\s+стенн', 'настенн', val_art, flags=re.IGNORECASE).strip()
        if val_art and not any(sw in val_art for sw in ["удали", "отмена", "назад", "сумм"]):
            return {"action": "create_article", "index": target_idx, "name": val_art}

    # 2. Изменение суммы
    amt_m = re.search(r'(?:сумму|сумма|поменяй сумму|измени сумму|поставь сумму)\s*(?:на|в|равна)?\s*(\d+(?:[.,]\d+)?)$', clean)
    if not amt_m:
        amt_m = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:руб|рублей|р)?$', clean)
    if amt_m and ("сумм" in clean or "на" in clean):
        try:
            return {"action": "edit_amount", "index": target_idx, "amount": float(amt_m.group(1).replace(',', '.'))}
        except ValueError:
            pass

    # 3. Переименование названия товара
    rename_m = re.search(r'(?:назови|переименуй|исправь название|название)\s*(?:как|в|на)?\s+(.+)$', clean)
    if rename_m:
        val = rename_m.group(1).strip()
        val = re.sub(r'^(?:как|в|на)\s+', '', val).strip()
        return {"action": "rename_item", "index": target_idx, "name": val}

    # 4. Удаление
    if any(w in clean for w in ["удали", "стереть", "убрать", "вычеркни"]):
        return {"action": "delete", "index": target_idx}

    # 5. Изменение категории / статьи
    # 5.1. Явные команды с ключевыми словами (исключая «новую статью», которая уже обработана в шаге 1)
    cat_m = re.search(r'(?:категорию|категория|подкатегорию|подкатегория)\s*(?:это|в|на|как)?\s+(.+)$', clean)
    if not cat_m:
        cat_m = re.search(r'(?:измени|поменяй|поставь|смени|перенеси)\s*(?:на|в|как)\s+(.+)$', clean)
    
    # 5.2. Естественные разговорные формы («первое это фастфуд», «второе мясо рыба», «а третье это бокалье», «1 - еда»)
    if not cat_m and matched_token:
        rest = re.sub(r'^(?:а\s+|и\s+|у\s+)?' + re.escape(matched_token) + r'[:\s\-]+', '', clean).strip()
        rest = re.sub(r'^(?:это|в|на|как)\s+', '', rest).strip()
        if rest:
            cat_m = re.search(r'^(.+)$', rest)

    if cat_m:
        hint = cat_m.group(1).strip()
        hint = re.sub(r'^(?:на|в|как|категорию|подкатегорию|это)\s+', '', hint).strip()
        stop_words = ["удали", "готово", "сохрани", "отмена", "назад", "сумма", "руб"]
        if hint and not any(sw in hint for sw in stop_words):
            return {"action": "set_category", "index": target_idx, "hint": hint}

    return None

def _parse_compound_voice_command(user_text_lower, items_len):
    """
    Разбивает составную фразу на несколько клауз по знакам препинания и союзам.
    Пример: 'Первое это фастфуд, второе это мясо рыба, а третье это бакалея'
    """
    clean_text = re.sub(r'[!?«»"\'\-]+', ' ', user_text_lower).strip()
    raw_clauses = re.split(r'[,.]+|\s+(?:а|и)\s+(?=(?:у\s+)?(?:во-перв|перв|во-втор|втор|в-трет|трет|четверт|пят|шест|сед|сем|восьм|девят|десят|\d+))', clean_text)

    actions = []
    for cl in raw_clauses:
        cl_clean = cl.strip()
        if not cl_clean:
            continue
        parsed = _try_fast_deterministic_single_clause(cl_clean, items_len)
        if parsed:
            actions.append(parsed)

    return actions
