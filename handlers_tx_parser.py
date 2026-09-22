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
    text = re.sub(r'\d+([.,]\d+)?', '', user_text).strip()
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
    Детерминированный разбор простых фраз типа 'Шиномонтаж 2600', 'такси 450' без вызова ИИ.
    """
    text = user_text.strip()
    match_end = re.search(r'^(.*?)\s+(\d+(?:[.,]\d+)?)\s*(?:руб|р)?$', text, re.IGNORECASE)
    match_start = re.search(r'^(\d+(?:[.,]\d+)?)\s*(?:руб|р)?\s+(.*?)$', text, re.IGNORECASE)

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
            if amt > 0 and len(raw_item) >= 2 and not any(ch in raw_item for ch in [',', ';', '\n']):
                return {"item": raw_item, "amount": amt}
        except ValueError:
            pass
    return None

def _validate_ai_category_choice(menu_full, op_type, cat, sub):
    """
    Строгая валидация: существует ли предложенная категория и подкатегория в структуре пользователя.
    """
    type_menu = menu_full.get(op_type, {})
    if cat not in type_menu:
        matched_cat = next((c for c in type_menu if c.lower() == str(cat).lower().strip()), None)
        if not matched_cat:
            return None, None
        cat = matched_cat

    subs = type_menu[cat]
    sub_list = list(subs.keys()) if isinstance(subs, dict) else subs
    
    if sub not in sub_list:
        matched_sub = next((s for s in sub_list if s.lower() == str(sub).lower().strip()), None)
        if matched_sub:
            return cat, matched_sub
        default_sub = next((s for s in sub_list if "другое" in s.lower()), None)
        if default_sub:
            return cat, default_sub
        return cat, (sub_list[0] if sub_list else "Разное")

    return cat, sub

def _find_best_matching_article_in_sub(menu_full, op_type, cat, sub, user_word):
    """
    Безопасный поиск статьи в подкатегории без привязки случайных чужих слов.
    """
    clean_w = user_word.lower().strip()
    sub_articles = menu_full.get(op_type, {}).get(cat, {}).get(sub, [])
    if not sub_articles:
        return user_word.capitalize()

    for art in sub_articles:
        art_l = art.lower()
        if art_l == clean_w or (len(clean_w) >= 4 and clean_w in art_l) or (len(art_l) >= 4 and art_l in clean_w):
            return art

    matches = difflib.get_close_matches(clean_w, [a.lower() for a in sub_articles], n=1, cutoff=0.72)
    if matches:
        for art in sub_articles:
            if art.lower() == matches[0]:
                return art

    return user_word.capitalize()

def _match_category_tree(menu_full, op_type, text):
    """
    Прямой поиск совпадения строки с названием категории или подкатегории в меню.
    """
    clean = text.lower().strip()
    type_menu = menu_full.get(op_type, {})
    for cat, subs in type_menu.items():
        if cat.lower() == clean:
            sub_keys = list(subs.keys()) if isinstance(subs, dict) else (subs if subs else [])
            return cat, (sub_keys[0] if sub_keys else "Разное")
        sub_keys = list(subs.keys()) if isinstance(subs, dict) else (subs if subs else [])
        for s in sub_keys:
            if s.lower() == clean:
                return cat, s
    return None, None
