# -*- coding: utf-8 -*-
import re

ORDINAL_MAP = {
    "одиннадцат": 11, "двенадцат": 12, "тринадцат": 13,
    "четырнадцат": 14, "пятнадцат": 15, "шестнадцат": 16,
    "семнадцат": 17, "восемнадцат": 18, "девятнадцат": 19,
    "двадцат": 20, "тридцат": 30, "сороков": 40, "пятидесят": 50,
    "во-перв": 1, "перв": 1, "один": 1,
    "во-втор": 2, "втор": 2, "два": 2,
    "в-трет": 3, "трет": 3, "три": 3,
    "четверт": 4, "четыр": 4,
    "пят": 5, "шест": 6, "сед": 7, "сем": 7,
    "восьм": 8, "девят": 9, "десят": 10,
    "последн": -1
}

# Сортировка ключей от длинных к коротким гарантирует, что "семнадцат" проверяется раньше "сем"
SORTED_ORDINALS = sorted(ORDINAL_MAP.items(), key=lambda x: len(x[0]), reverse=True)

def _parse_token_to_number(token: str):
    """Извлекает числовое значение из токена: цифры (17, 17-е, №17) или порядковые слова."""
    clean_num = re.sub(r'[^0-9]', '', token)
    if clean_num.isdigit():
        val = int(clean_num)
        if val > 0:
            return val

    t_lower = re.sub(r'[^a-zA-Zа-яА-Я0-9ёЁ\-]', '', token.lower().strip())
    for prefix, num in SORTED_ORDINALS:
        if t_lower.startswith(prefix):
            return num
    return None

def _try_fast_deterministic_single_clause(clause_text, items_len):
    """
    Разбор одной клаузы (например: 'семнадцатое это готовая еда' или 'первое измени название болгарка') за 1 мс.
    """
    clean = clause_text.strip()
    target_idx = None
    matched_token = None

    tokens = clean.split()
    for token in tokens:
        num = _parse_token_to_number(token)
        if num is not None:
            target_idx = (items_len - 1) if num == -1 else (num - 1)
            matched_token = token
            break

    if target_idx is None or not (0 <= target_idx < items_len):
        return None

    # 1. Создание новой / отдельной статьи для конкретной операции
    new_art_m = re.search(

        r'(?:перенеси|перенести|создай|создать|сделай|сделать|запиши|добавь|выдели)?\s*(?:в|на)?\s*(?:нов(?:ую|ая|ой)|отдельн(?:ую|ая|ой)|сво(?:ю|я|ей))?\s*стать(?:ю|я|е)\s*(?:под\s*названием|с\s*названием|это|как)?\s*(.+)$',
        clean,
        flags=re.IGNORECASE
    )
    if not new_art_m:
        new_art_m = re.search(
            r'(?:это|назови)?\s*(.+?)\s*(?:в|на)?\s*(?:нов(?:ую|ая|ой)|отдельн(?:ую|ая|ой)|сво(?:ю|я|ей))\s*стать(?:ю|я|е)$',
            clean,
            flags=re.IGNORECASE
        )
    if not new_art_m:
        new_art_m = re.search(
            r'(?:создай|создать|сделай|сделать|выдели|запиши)\s*(?:в|на)?\s*стать(?:ю|я|е)\s*(?:под\s*названием|с\s*названием|это|как)?\s*(.+)$',
            clean,
            flags=re.IGNORECASE
        )
    if new_art_m:
        val_art = new_art_m.group(1).strip()
        val_art = re.sub(r'^(?:в|на|под\s*названием|это|как)\s+', '', val_art, flags=re.IGNORECASE).strip().strip('.,;!')
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

    # 3. Переименование названия товара (включая "измени название", "поменяй название", "название на X")
    rename_m = re.search(
        r'(?:назови|переименуй|исправь название|измени название|поменяй название|смени название|название)\s*(?:как|в|на|это)?\s+(.+)$',
        clean,
        flags=re.IGNORECASE
    )
    if rename_m:
        val = rename_m.group(1).strip()
        val = re.sub(r'^(?:как|в|на|это)\s+', '', val, flags=re.IGNORECASE).strip().strip('.,;!')
        if val and not any(sw in val for sw in ["удали", "отмена", "назад", "сумм", "категори"]):
            return {"action": "rename_item", "index": target_idx, "name": val}

    # 4. Удаление
    if any(w in clean for w in ["удали", "стереть", "убрать", "вычеркни"]):
        return {"action": "delete", "index": target_idx}

    # 5. Изменение категории / статьи
    # 5.1. Явные команды с ключевыми словами
    cat_m = re.search(r'(?:категорию|категория|подкатегорию|подкатегория)\s*(?:это|в|на|как)?\s+(.+)$', clean, flags=re.IGNORECASE)
    if not cat_m:
        cat_m = re.search(r'(?:измени|поменяй|поставь|смени|перенеси)\s*(?:на|в|как)\s+(.+)$', clean, flags=re.IGNORECASE)

    # 5.2. Естественные разговорные формы («семнадцатое это подарочная карта», «первое это фастфуд», «для первой фастфуд»)
    if not cat_m and matched_token:
        rest = re.sub(r'^(?:а\s+|и\s+|у\s+|для\s+|по\s+)?' + re.escape(matched_token) + r'[:\s\-]+', '', clean, flags=re.IGNORECASE).strip()
        rest = re.sub(r'^(?:это|в|на|как)\s+', '', rest, flags=re.IGNORECASE).strip()
        if rest:
            cat_m = re.search(r'^(.+)$', rest)

    if cat_m:
        hint = cat_m.group(1).strip()
        hint = re.sub(r'^(?:на|в|как|категорию|подкатегорию|это)\s+', '', hint, flags=re.IGNORECASE).strip().strip('.,;!')
        stop_words = ["удали", "готово", "сохрани", "отмена", "назад", "сумма", "руб", "стать", "созда", "сдела", "отдельн", "название", "переименуй"]
        if hint and not any(sw in hint for sw in stop_words):
            return {"action": "set_category", "index": target_idx, "hint": hint}

    return None

def _parse_compound_voice_command(user_text_lower, items_len):
    """
    Разбивает составную фразу на несколько клауз.
    Запятые и союзы делят строку ТОЛЬКО если далее следует порядковое числительное следующей операции.
    """
    clean_text = re.sub(r'[!?«»"\'\-]+', ' ', user_text_lower).strip().rstrip('.,')
    ordinal_lookahead = (
        r'(?=(?:у\s+|для\s+|по\s+)?'
        r'(?:во-перв|перв|во-втор|втор|в-трет|трет|четверт|пят|шест|сед|сем|восьм|девят|десят|'
        r'одиннадцат|двенадцат|тринадцат|четырнадцат|пятнадцат|шестнадцат|семнадцат|восемнадцат|девятнадцат|двадцат|\d+))'
    )

    raw_clauses = re.split(
        r'[,.]*\s+(?:а|и)\s+' + ordinal_lookahead + r'|[,.]+\s*' + ordinal_lookahead,
        clean_text
    )

    actions = []
    for cl in raw_clauses:
        cl_clean = cl.strip()
        if not cl_clean:
            continue
        parsed = _try_fast_deterministic_single_clause(cl_clean, items_len)
        if parsed:
            actions.append(parsed)

    return actions
