# -*- coding: utf-8 -*-
import difflib
import re
from services import categorize_with_ai
from db import (
    smart_search_item,
    learn_user_word,
    update_transaction_category
)
from handlers_tx_parser import (
    _match_category_tree,
    _validate_ai_category_choice,
    _find_best_matching_article_in_sub
)

# Словарь типичных фонетических искажений Whisper и разговорных форм
VOICE_PHONETIC_FIXES = {
    "бокалье": "бакалея",
    "бокалея": "бакалея",
    "бакалье": "бакалея",
    "бакалее": "бакалея",
    "бакалею": "бакалея",
    "полфабрикаты": "полуфабрикаты",
    "полуфабрикатам": "полуфабрикаты",
    "фасфуд": "фастфуд",
    "фаст фуд": "фастфуд",
    "мясо рыба": "мясо и рыба",
    "рыба мясо": "мясо и рыба",
    "хоз товары": "хозтовары",
    "хозтовары": "хозтовары",
    "быт химия": "бытовая химия",
    "бытоваяхимия": "бытовая химия",
    "вкусняшки к пиву": "снеки",
    "закуски к пиву": "снеки",
    "к пиву": "снеки"
}

def _stem_word(w: str) -> str:
    """Обрезает падежные и грамматические окончания русских слов для устойчивого сравнения."""
    clean = re.sub(r'[^а-яa-z0-9]', '', w.lower())
    if len(clean) >= 6:
        return clean[:-2]
    elif len(clean) >= 4:
        return clean[:-1]
    return clean

def _simplify_str(s: str) -> str:
    """Удаляет пробелы, знаки препинания и союзы для строгого сопоставления составных имен."""
    clean = re.sub(r'[\s,.\-—–/]+', '', s.lower())
    clean = re.sub(r'\b(?:и|а|в|с)\b', '', clean)
    return clean

def _find_category_in_menu(menu_full, hint_text):
    """Полноценный трехуровневый поиск по меню категорий и подкатегорий с устойчивостью к падежам."""
    raw_clean = hint_text.lower().strip()
    clean = VOICE_PHONETIC_FIXES.get(raw_clean, raw_clean)
    clean_simple = _simplify_str(clean)
    clean_stem = _stem_word(clean)

    cat_candidates = []
    sub_candidates = []

    for m_type in ["Расход", "Доход"]:
        type_cats = menu_full.get(m_type, {})
        for cat_name, subs in type_cats.items():
            sub_keys = list(subs.keys()) if isinstance(subs, dict) else (subs if subs else [])
            cat_simple = _simplify_str(cat_name)
            cat_words_stems = [_stem_word(w) for w in re.split(r'[\s,.\-/]+', cat_name.lower()) if len(w) >= 3]

            # 1. ТОЧНОЕ СОВПАДЕНИЕ
            if cat_name.lower() == clean or cat_simple == clean_simple:
                matching_sub = next((s for s in sub_keys if s.lower() == clean or _simplify_str(s) == clean_simple), (sub_keys[0] if sub_keys else "Разное"))
                return True, m_type, cat_name, matching_sub

            for s_name in sub_keys:
                if s_name.lower() == clean or _simplify_str(s_name) == clean_simple:
                    return True, m_type, cat_name, s_name

            # 2. ПОИСК ПО КОРНЯМ СЛОВ (ПАДЕЖИ РУССКОГО ЯЗЫКА: бакалее -> бакалея)
            if len(clean_stem) >= 4:
                for s_name in sub_keys:
                    s_words_stems = [_stem_word(w) for w in re.split(r'[\s,.\-/]+', s_name.lower()) if len(w) >= 3]
                    if any(clean_stem == sw or (len(clean_stem) >= 5 and clean_stem in sw) for sw in s_words_stems):
                        return True, m_type, cat_name, s_name

                if any(clean_stem == cw or (len(clean_stem) >= 5 and clean_stem in cw) for cw in cat_words_stems):
                    matching_sub = sub_keys[0] if sub_keys else "Разное"
                    return True, m_type, cat_name, matching_sub

            # 3. ЧАСТИЧНОЕ ВХОЖДЕНИЕ
            if len(clean) >= 3:
                if clean in cat_name.lower() or cat_name.lower() in clean or (clean_simple and clean_simple in cat_simple):
                    matching_sub = sub_keys[0] if sub_keys else "Разное"
                    return True, m_type, cat_name, matching_sub
                for s_name in sub_keys:
                    s_simple = _simplify_str(s_name)
                    if clean in s_name.lower() or s_name.lower() in clean or (clean_simple and (clean_simple in s_simple or s_simple in clean_simple)):
                        return True, m_type, cat_name, s_name

            cat_candidates.append((cat_name.lower(), m_type, cat_name, sub_keys))
            for s_name in sub_keys:
                sub_candidates.append((s_name.lower(), m_type, cat_name, s_name))

    # 4. НЕЧЕТКИЙ ПОИСК (FUZZY MATCHING) С АДАПТИВНЫМ ПОРОГОМ
    all_sub_names = [item[0] for item in sub_candidates]
    cutoff_val = 0.55 if len(clean) >= 6 else 0.65
    matches_sub = difflib.get_close_matches(clean, all_sub_names, n=1, cutoff=cutoff_val)
    if matches_sub:
        matched_str = matches_sub[0]
        for item in sub_candidates:
            if item[0] == matched_str:
                return True, item[1], item[2], item[3]

    all_cat_names = [item[0] for item in cat_candidates]
    matches_cat = difflib.get_close_matches(clean, all_cat_names, n=1, cutoff=cutoff_val)
    if matches_cat:
        matched_str = matches_cat[0]
        for item in cat_candidates:
            if item[0] == matched_str:
                sub_keys = item[3]
                matching_sub = sub_keys[0] if sub_keys else "Разное"
                return True, item[1], item[2], matching_sub

    return False, None, None, None

def _apply_category_to_item(internal_uid, it, hint_text, menu_full, state):
    """
    Определяет правильную пару Категория -> Подкатегория -> Статья по подсказке пользователя.
    Если названа только категория, подкатегория подбирается ИИ под конкретный товар, а не берется первая попавшаяся.
    """
    current_art_name = it.get("article") or it.get("original_item") or it.get("item") or "Операция"
    op_type = it.get("type", "Расход")
    found_cat, found_sub = None, None
    m_type = op_type
    target_art = current_art_name
    hint_clean = hint_text.strip()
    hint_clean = VOICE_PHONETIC_FIXES.get(hint_clean.lower(), hint_clean)

    # 0. ПРОВЕРКА РАСЩЕПЛЕНИЯ СВЯЗКИ «Категория, Подкатегория» / «Категория -> Подкатегория»
    compound_delims = [r'\s*->\s*', r'\s*,\s*', r'\s*-\s*', r'\s*/\s*']
    for d_pattern in compound_delims:
        parts = re.split(d_pattern, hint_clean)
        if len(parts) >= 2:
            p_cat = parts[0].strip()
            p_sub = parts[1].strip()
            if len(p_cat) >= 2 and len(p_sub) >= 2:
                for check_type in [op_type, "Расход", "Доход"]:
                    type_cats = menu_full.get(check_type, {})
                    for c_name, subs in type_cats.items():
                        if p_cat.lower() in c_name.lower() or c_name.lower() in p_cat.lower():
                            sub_keys = list(subs.keys()) if isinstance(subs, dict) else (subs if subs else [])
                            for s_name in sub_keys:
                                if p_sub.lower() in s_name.lower() or s_name.lower() in p_sub.lower():
                                    found_cat = c_name
                                    found_sub = s_name
                                    m_type = check_type
                                    target_art = _find_best_matching_article_in_sub(menu_full, m_type, found_cat, found_sub, current_art_name)
                                    break
                            if found_cat:
                                break
                    if found_cat:
                        break
        if found_cat:
            break

    # 1. ПРОВЕРКА: ПОЛЬЗОВАТЕЛЬ НАЗВАЛ КАТЕГОРИЮ ВЕРХНЕГО УРОВНЯ
    if not found_cat:
        for check_type in [op_type, "Расход", "Доход"]:
            type_cats = menu_full.get(check_type, {})
            for c_name, subs in type_cats.items():
                if hint_clean.lower() == c_name.lower() or (len(hint_clean) >= 3 and hint_clean.lower() in c_name.lower()):
                    found_cat = c_name
                    m_type = check_type
                    sub_keys = list(subs.keys()) if isinstance(subs, dict) else (subs if subs else [])

                    # Подбираем подкатегорию под товар через ИИ строго внутри этой категории
                    scoped_menu_str = f"[{m_type}]\n{c_name}: {', '.join(sub_keys)}"
                    ai_c, ai_s = categorize_with_ai(current_art_name, scoped_menu_str, context=hint_clean)
                    if ai_s in sub_keys:
                        found_sub = ai_s
                    else:
                        c_tree, s_tree = _match_category_tree({m_type: {c_name: subs}}, m_type, current_art_name)
                        found_sub = s_tree if s_tree else (sub_keys[0] if sub_keys else "Разное")

                    target_art = _find_best_matching_article_in_sub(menu_full, m_type, found_cat, found_sub, current_art_name)
                    break
            if found_cat:
                break

    # 2. ПОИСК В БАЗЕ ДАННЫХ (СИНОНИМЫ И ЭТАЛОН)
    if not found_cat:
        db_match = smart_search_item(internal_uid, hint_clean, op_type=op_type)
        if db_match.get("status") != "FOUND":
            alt_type = "Доход" if op_type == "Расход" else "Расход"
            alt_db = smart_search_item(internal_uid, hint_clean, op_type=alt_type)
            if alt_db.get("status") == "FOUND":
                db_match = alt_db
                m_type = alt_type
            else:
                db_match = smart_search_item(internal_uid, hint_clean, op_type=None)

        if db_match.get("status") == "FOUND":
            m_type = db_match.get("type", op_type)
            found_cat = db_match["category"]
            found_sub = db_match["subcategory"]
            target_art = db_match.get("article") or _find_best_matching_article_in_sub(menu_full, m_type, found_cat, found_sub, current_art_name)
        else:
            # 3. ПОИСК ПО ДЕРЕВУ МЕНЮ
            is_match, menu_m_type, c_name, s_name = _find_category_in_menu(menu_full, hint_clean)
            if is_match:
                m_type = menu_m_type
                found_cat = c_name
                found_sub = s_name
                target_art = _find_best_matching_article_in_sub(menu_full, m_type, found_cat, found_sub, current_art_name)
            else:
                # 4. РЕЗЕРВ ЧЕРЕЗ ИИ
                type_menu = menu_full.get(op_type, {})
                menu_str = f"[{op_type}]\n" + "\n".join([f"{c}: {', '.join(subs.keys() if isinstance(subs, dict) else subs)}" for c, subs in type_menu.items()])
                ai_c, ai_s = categorize_with_ai(current_art_name, menu_str, context=hint_clean)
                v_c, v_s = _validate_ai_category_choice(menu_full, op_type, ai_c, ai_s)
                found_cat = v_c or "Разное"
                found_sub = v_s or "Требует проверки"
                target_art = _find_best_matching_article_in_sub(menu_full, op_type, found_cat, found_sub, current_art_name)

    # Сохраняем результат
    if state == "history_view" and "id" in it:
        update_transaction_category(internal_uid, it["id"], found_cat, found_sub, target_art, op_type=m_type)
        it["category"] = found_cat
        it["subcategory"] = found_sub
        it["article"] = target_art
        it["type"] = m_type
    else:
        it["category"] = found_cat
        it["subcategory"] = found_sub
        it["article"] = target_art
        if m_type:
            it["type"] = m_type
        it["is_known"] = (found_sub != "Требует проверки" and found_cat != "Разное")

    if found_cat != "Разное" and found_sub != "Требует проверки":
        learn_user_word(internal_uid, m_type, found_cat, found_sub, target_art, current_art_name)
        learn_user_word(internal_uid, m_type, found_cat, found_sub, target_art, hint_clean)

    return found_cat, found_sub
