# -*- coding: utf-8 -*-
import re
import difflib

INCOME_KEYWORDS = [
    "доход", "приход", "поступление", "поступило", "поступили", "пополнил", "пополнение",
    "зарплата", "зп", "аванс", "премия", "подарили", "подарок мне",
    "вернули долг", "отдали долг", "кэшбэк", "проценты", "дивиденды",
    "выручка", "оплата от клиента", "оплата от заказчика", "зачисление",
    "самозанятость", "самозанятый", "гонорар", "подработка", "клиент",
    "перевели", "перевод мне"
]

SPOKEN_NUMBER_REPLACEMENTS = [
    (r'\b(питот|пятот|петот|пятьсот)\b', '500'),
    (r'\b(тыща|тысяча|косарь|штука)\b', '1000'),
    (r'\b(полторы\s*тысячи|полторы\s*тыщи|полтора\s*косаря)\b', '1500'),
    (r'\b(две\s*тысячи|две\s*тыщи)\b', '2000'),
    (r'\b(три\s*тысячи|три\s*тыщи)\b', '3000'),
    (r'\b(сто|сотка)\b', '100'),
    (r'\bдвести\b', '200'),
    (r'\bтриста\b', '300'),
    (r'\bчетыреста\b', '400'),
    (r'\bшестьсот\b', '600'),
    (r'\bсемьсот\b', '700'),
    (r'\bвосемьсот\b', '800'),
    (r'\bдевятьсот\b', '900'),
]

def normalize_spoken_numbers(text):
    """
    Нормализует разговорные числительные и оговорки Whisper в цифры
    (например: 'питот' -> '500', 'тыща' -> '1000').
    """
    res = text
    for pattern, repl in SPOKEN_NUMBER_REPLACEMENTS:
        res = re.sub(pattern, repl, res, flags=re.IGNORECASE)
    return res

def extract_recipient_and_clean_item(raw_text):
    """
    Интеллектуальный разбор текста операции:
    1. Отсекает служебные слова типа ('расход', 'доход', 'трата', 'оплата').
    2. Извлекает контекст/категорию из скобок или маркеров ('статья X', 'категория Y', 'в подкатегорию Z').
    3. Распознает составные конструкции ('на самозанятость поклейка обоев уголки' -> item='уголки', hint='самозанятость поклейка обоев').
    4. Отсекает адресатов/имена во всех падежах ('игрушка Марку' -> item='игрушка', comment='Марку').
    Возвращает: clean_item, extracted_comment, category_hint
    """
    clean_item = raw_text.strip()
    extracted_comment = ""
    category_hint = ""

    # 1. Отсекаем начальные служебные слова типа операции

    clean_item = re.sub(r'^(?:расход|доход|трата|трату|оплата|купил|оплатил)\s+', '', clean_item, flags=re.IGNORECASE).strip()

    # 2. Поиск подсказок категорий в круглых скобках: (поклейка обоев) или (самозанятость)
    m_paren = re.search(r'\(([^)]+)\)', clean_item)
    if m_paren:
        category_hint = m_paren.group(1).strip()
        clean_item = (clean_item[:m_paren.start()] + clean_item[m_paren.end():]).strip()

    # 3. Поиск явных синтаксических маркеров: 'статья X', 'категория Y', 'подкатегория Z'
    m_cat_marker = re.search(
        r'(?:,?\s*(?:в\s+)?(?:стать[яюи]|категори[яюи]|подкатегори[яюи])\s*:?\s*)([а-яёa-z0-9\s\-]+)$',
        clean_item,
        flags=re.IGNORECASE
    )
    if m_cat_marker:
        if not category_hint:
            category_hint = m_cat_marker.group(1).strip()
        clean_item = clean_item[:m_cat_marker.start()].strip()

    # 4. Поиск составных конструкций с предлогом в начале: 'на самозанятость поклейка обоев уголки'
    m_prep_start = re.match(r'^(?:на|для)\s+(.+?)\s+([а-яёa-z0-9\-]+)$', clean_item, flags=re.IGNORECASE)
    if m_prep_start:
        prep_body = m_prep_start.group(1).strip()
        actual_item = m_prep_start.group(2).strip()
        category_hint = prep_body
        clean_item = actual_item

    # 5. Поиск предложных конструкций в конце: 'уголки для ремонта', 'уголки на поклейку обоев'
    if not category_hint:
        m_prep_end = re.search(r'\s+(?:на|для)\s+([а-яёa-z0-9\s\-]+)$', clean_item, flags=re.IGNORECASE)
        if m_prep_end:
            prep_tail = m_prep_end.group(1).strip()
            is_person = re.match(
                r'^(?:марк[уаеом]|ром[еыуой]|кат[еиюей]|мам[еыуой]|пап[еыуой]|жен[еыуой]|муж[уаем]|сын[уаом]|дочк[еиюей]|дет[ям|ей|ьми])$',
                prep_tail,
                flags=re.IGNORECASE
            )
            if is_person:
                extracted_comment = m_prep_end.group(0).strip().capitalize()
            else:
                category_hint = prep_tail
                extracted_comment = prep_tail.capitalize()
            clean_item = clean_item[:m_prep_end.start()].strip()

    # 6. Поиск одиночных предлогов адресата: 'для Марка', 'на маму'
    if not extracted_comment:
        m_prep = re.search(r'\b(?:для|на)\s+([а-яёa-z0-9\-]+)\b', clean_item, flags=re.IGNORECASE)
        if m_prep:
            extracted_comment = m_prep.group(0).strip().capitalize()
            clean_item = (clean_item[:m_prep.start()] + clean_item[m_prep.end():]).strip()

    # 7. Поиск имен и родственников во всех падежах
    if not extracted_comment:
        m_name = re.search(
            r'\b('
            r'марк[уаеом]|ром[еыуой]|родиону?а?|'
            r'кат[еиюей]|екатерин[еыуой]|'
            r'мам[еыуой]|пап[еыуой]|жен[еыуой]|муж[уаем]|'
            r'сын[уаом]|дочк[еиюей]|дочер[иью]|'
            r'дет[ям|ей|ьми]|реб[её]нк[уаом]|'
            r'бабушк[еиюей]|дедушк[еиюей]|'
            r'кот[уаом]|собак[еиюей]|'
            r'друг[уаом]|брат[уаом]|сестр[еыуой]'
            r')\b',
            clean_item,
            flags=re.IGNORECASE
        )
        if m_name:
            matched_word = m_name.group(1).strip()
            extracted_comment = matched_word.capitalize()
            clean_item = (clean_item[:m_name.start()] + clean_item[m_name.end():]).strip()

    clean_item = re.sub(r'\s+', ' ', clean_item).strip(' ,;:-')
    return (clean_item if clean_item else raw_text), extracted_comment, category_hint

def detect_operation_type(user_text="", raw_type="Расход", item_name="", comment=""):
    """
    Определяет тип операции (Расход или Доход) по контексту текста, ключевым словам или явному типу.
    """
    check_str = f"{user_text} {raw_type} {item_name} {comment}".lower()
    for kw in INCOME_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', check_str) or kw in check_str:
            return "Доход", True
    if str(raw_type).strip().lower() in ["доход", "приход", "income"]:
        return "Доход", True
    return "Расход", False

def clean_fallback_item(user_text):
    """
    Очищает текст от сумм и общих стоп-слов для формирования резервного названия операции.
    """
    norm_text = normalize_spoken_numbers(user_text)
    text = re.sub(r'\d+([.,]\d+)?', '', norm_text).strip()
    stop_words = [
        "руб", "рублей", "р", "к", "k", "приход", "доход", "расход", "трата",
        "купил", "оплатил", "исправь", "измени", "категорию", "подкатегорию",
        "сумма", "на", "покажи", "последнюю", "операцию", "операции"
    ]
    words = [w for w in text.split() if w.lower() not in stop_words]
    clean = " ".join(words).strip()
    return clean if clean else "Операция"

def _try_fast_single_transaction_parse(user_text):
    """
    Детерминированный разбор простых фраз типа 'Шиномонтаж 2600', '1700 игрушка Марку',
    '250 расход на самозанятость поклейка обоев уголки' без вызова ИИ.
    Автоматически выделяет категорию/подсказку в category_hint и адресатов в comment.
    """
    norm_text = normalize_spoken_numbers(user_text.strip())
    match_end = re.search(r'^(.*?)\s+(\d+(?:[.,]\d+)?)\s*(?:руб|р)?$', norm_text, re.IGNORECASE)
    match_start = re.search(r'^(\d+(?:[.,]\d+)?)\s*(?:руб|р)?\s+(.*?)$', norm_text, re.IGNORECASE)

    raw_item = None
    raw_amount = None

    if match_end:
        raw_item = match_end.group(1).strip()
        raw_amount = match_end.group(2).replace(',', '.')
    elif match_start:
        raw_amount = match_start.group(1).replace(',', '.')
        raw_item = match_start.group(2).strip()

    if raw_item and raw_amount:
        try:
            amt = float(raw_amount)
            # Разрешаем разбор одной операции, исключая явные списки через точку с запятой или переносы
            if amt > 0 and len(raw_item) >= 2 and not any(ch in raw_item for ch in [';', '\n']):
                clean_title, comment, category_hint = extract_recipient_and_clean_item(raw_item)
                return {
                    "item": clean_title,
                    "raw_item": raw_item,
                    "amount": amt,
                    "comment": comment,
                    "category_hint": category_hint
                }
        except ValueError:
            pass
    return None

def _validate_ai_category_choice(menu_full, op_type, cat, sub):
    """
    Строгая валидация с интеллектуальным поиском:
    1. Проверяет пару cat -> sub в меню пользователя.
    2. Если cat не найдена, но sub или cat существует как подкатегория в другой родительской категории,
       автоматически подставляет правильную родительскую категорию.
    """
    type_menu = menu_full.get(op_type, {})
    cat_clean = str(cat or "").strip().lower()
    sub_clean = str(sub or "").strip().lower()

    # Поиск прямого совпадения категории
    matched_cat = next((c for c in type_menu if c.lower() == cat_clean), None)

    if not matched_cat:
        # Интеллектуальный поиск: возможно cat на самом деле является подкатегорией
        for real_cat, subs in type_menu.items():
            sub_names = list(subs.keys()) if isinstance(subs, dict) else subs
            for s in sub_names:
                if s.lower() == cat_clean or s.lower() == sub_clean:
                    matched_cat = real_cat
                    sub = s
                    break
            if matched_cat:
                break

    if not matched_cat:
        # Поиск по подкатегории
        for real_cat, subs in type_menu.items():
            sub_names = list(subs.keys()) if isinstance(subs, dict) else subs
            for s in sub_names:
                if s.lower() == sub_clean:
                    matched_cat = real_cat
                    sub = s
                    break
            if matched_cat:
                break

    if not matched_cat:
        return None, None

    subs = type_menu[matched_cat]
    sub_list = list(subs.keys()) if isinstance(subs, dict) else subs

    # Проверка и нормализация подкатегории внутри найденной категории
    matched_sub = next((s for s in sub_list if s.lower() == str(sub).lower().strip()), None)
    if matched_sub:
        return matched_cat, matched_sub

    # Если подкатегория не совпала в точности, ищем резервную в этой категории
    default_sub = next((s for s in sub_list if "другое" in s.lower()), None)
    if default_sub:
        return matched_cat, default_sub

    return matched_cat, (sub_list[0] if sub_list else "Разное")

def _find_best_matching_article_in_sub(menu_full, op_type, cat, sub, user_word):
    """
    Безопасный поиск статьи в подкатегории:
    - Сначала точное совпадение со статьей из базы.
    - Затем нечеткое совпадение с высоким порогом (>= 0.70).
    - Если в подкатегории есть статья с таким же названием, как подкатегория, выбирает её.
    - В крайнем случае выбирает 'Другое <подкатегория>' или базовую каноническую статью подкатегории.
    """
    clean_w = str(user_word or "").lower().strip()
    sub_articles = menu_full.get(op_type, {}).get(cat, {}).get(sub, [])
    if not sub_articles:
        return user_word.capitalize() if user_word else sub

    # 1. Точное совпадение
    for art in sub_articles:
        art_l = art.lower()
        if art_l == clean_w:
            return art

    # 2. Нечеткое совпадение по подстроке достаточной длины
    for art in sub_articles:
        art_l = art.lower()
        if (len(clean_w) >= 4 and clean_w in art_l) or (len(art_l) >= 4 and art_l in clean_w):
            return art

    # 3. Триграммное / difflib совпадение с порогом 0.70
    matches = difflib.get_close_matches(clean_w, [a.lower() for a in sub_articles], n=1, cutoff=0.70)
    if matches:
        for art in sub_articles:
            if art.lower() == matches[0]:
                return art

    # 4. Если точного совпадения нет — привязываем к существующей базовой статье подкатегории
    same_as_sub = next((a for a in sub_articles if a.lower() == sub.lower()), None)
    if same_as_sub:
        return same_as_sub

    # Ищем 'Другое ...'
    other_art = next((a for a in sub_articles if "другое" in a.lower()), None)
    if other_art:
        return other_art

    # Первая каноническая статья подкатегории
    return sub_articles[0]

def _match_category_tree(menu_full, op_type, text):
    """
    Прямой поиск совпадения строки с названием категории, подкатегории или статьи в меню.
    """
    clean = text.lower().strip()
    type_menu = menu_full.get(op_type, {})

    # 1. Поиск по категориям
    for cat, subs in type_menu.items():
        if cat.lower() == clean:
            sub_keys = list(subs.keys()) if isinstance(subs, dict) else (subs if subs else [])
            return cat, (sub_keys[0] if sub_keys else "Разное")

    # 2. Поиск по подкатегориям
    for cat, subs in type_menu.items():
        sub_keys = list(subs.keys()) if isinstance(subs, dict) else (subs if subs else [])
        for s in sub_keys:
            if s.lower() == clean:
                return cat, s

    # 3. Поиск по статьям
    for cat, subs in type_menu.items():
        if isinstance(subs, dict):
            for s, arts in subs.items():
                if isinstance(arts, list):
                    for a in arts:
                        if a.lower() == clean:
                            return cat, s

    return None, None

def resolve_category_from_hint_or_menu(menu_full, op_type, item, hint=""):
    """
    Интеллектуальное сопоставление товара и/или подсказки с деревом меню:
    1. Если передана подсказка hint, ищет её в дереве категорий/подкатегорий/статей.
    2. Если в hint указаны и категория, и подкатегория (например, 'самозанятость поклейка обоев'),
       точно находит нужный узел дерева.
    3. Возвращает (cat, sub, article) или (None, None, None).
    """
    if not menu_full or not hint:
        return None, None, None

    type_menu = menu_full.get(op_type, {})
    if not type_menu:
        return None, None, None

    h_clean = hint.lower().strip()

    # Проверяем пары "категория подкатегория"
    for c, subs in type_menu.items():
        sub_names = list(subs.keys()) if isinstance(subs, dict) else subs
        for s in sub_names:
            if (c.lower() in h_clean and s.lower() in h_clean) or s.lower() == h_clean:
                art = _find_best_matching_article_in_sub(menu_full, op_type, c, s, item)
                return c, s, art

    # Проверяем только категорию
    for c, subs in type_menu.items():
        if c.lower() == h_clean or c.lower() in h_clean:
            sub_names = list(subs.keys()) if isinstance(subs, dict) else subs
            target_sub = sub_names[0] if sub_names else "Разное"
            art = _find_best_matching_article_in_sub(menu_full, op_type, c, target_sub, item)
            return c, target_sub, art

    # Проверяем по статьям
    for c, subs in type_menu.items():
        if isinstance(subs, dict):
            for s, arts in subs.items():
                if isinstance(arts, list):
                    for a in arts:
                        if a.lower() == h_clean or a.lower() in h_clean:
                            return c, s, a

    return None, None, None
