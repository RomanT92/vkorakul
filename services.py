# -*- coding: utf-8 -*-
import requests
import json
import re
from config import (
    VK_TOKEN,
    AI_TUNNEL_KEY,
    GOOGLE_SHEETS_URL,
    AI_BASE_URL,
    PROMPT_EXTRACT,
    PROMPT_LIST_COMMAND,
    PROMPT_CATEGORIZE,
    PROMPT_RECEIPT_TOTAL,
    PROMPT_RECEIPT_OCR_ONLY,
    PROMPT_BATCH_CATEGORIZE,
    PROMPT_FILE_MAPPING
)

def send_vk_message(user_id, message, keyboard=None):
    """Отправка сообщения в чат ВКонтакте."""
    url = "https://api.vk.com/method/messages.send"
    data = {
        "user_id": user_id,
        "message": message,
        "random_id": 0,
        "access_token": VK_TOKEN,
        "v": "5.131"
    }
    if keyboard:
        data["keyboard"] = keyboard
    try:
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print(f"Ошибка отправки VK: {e}")

def send_to_google_sheets(payload):
    """Отправка вебхука в Google Apps Script."""
    try:
        resp = requests.post(GOOGLE_SHEETS_URL, json=payload, timeout=25)
        return resp.json()
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

def _call_llm(messages, model="gpt-4o", max_tokens=2500, temperature=0.1):
    """Единая точка вызова языковых моделей через AI Tunnel."""
    headers = {
        "Authorization": f"Bearer {AI_TUNNEL_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    try:
        resp = requests.post(f"{AI_BASE_URL}chat/completions", headers=headers, json=body, timeout=60)
        if resp.status_code == 200:
            res_json = resp.json()
            return res_json["choices"][0]["message"]["content"].strip()
        print(f"Ошибка LLM API ({resp.status_code}): {resp.text}")
        return ""
    except Exception as e:
        print(f"Исключение при вызове LLM: {e}")
        return ""

def extract_operations_with_ai(user_text):
    """Извлечение операций из текста пользователя."""
    messages = [
        {"role": "system", "content": PROMPT_EXTRACT},
        {"role": "user", "content": user_text}
    ]
    return _call_llm(messages, model="gpt-4o", temperature=0.0)

def parse_list_command_with_ai(user_text):
    """Разбор голосовой/текстовой команды к списку операций."""
    messages = [
        {"role": "system", "content": PROMPT_LIST_COMMAND},
        {"role": "user", "content": user_text}
    ]
    return _call_llm(messages, model="gpt-4o-mini", temperature=0.0)

def categorize_with_ai(item_name, menu_str, context=""):
    """Классификация одной операции по меню."""
    sys_prompt = PROMPT_CATEGORIZE + f"\n\nМЕНЮ КАТЕГОРИЙ:\n{menu_str}"
    user_prompt = f"Название: {item_name}"
    if context:
        user_prompt += f"\nПодсказка пользователя: {context}"

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt}
    ]
    raw = _call_llm(messages, model="gpt-4o-mini", temperature=0.0)
    try:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        clean = match.group(0) if match else raw
        d = json.loads(clean)
        return d.get("category", "Разное"), d.get("subcategory", "Требует проверки")
    except Exception:
        return "Разное", "Требует проверки"

def extract_receipt_total_with_ai(photo_url):
    """Быстрое чтение общего итога чека (магазин + итоговая сумма)."""
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT_RECEIPT_TOTAL},
                {"type": "image_url", "image_url": {"url": photo_url}}
            ]
        }
    ]
    return _call_llm(messages, model="gpt-4o", temperature=0.0)

# ====================================================================
# ДВУХЭТАПНЫЙ ПАЙПЛАЙН ЧТЕНИЯ ЧЕКА (OCR -> BATCH CATEGORIZE)
# ====================================================================
def extract_receipt_items_pipeline(photo_url, menu_str):
    """
    Двухэтапный разбор чека:
    Этап 1: GPT-4o Vision только считывает все позиции и точные цены (с правилом '=').
    Этап 2: Текстовая модель пакетно проставляет категории из menu_str.
    """
    # --- ЭТАП 1: Vision OCR ---
    ocr_messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT_RECEIPT_OCR_ONLY},
                {"type": "image_url", "image_url": {"url": photo_url}}
            ]
        }
    ]
    raw_ocr = _call_llm(ocr_messages, model="gpt-4o", temperature=0.0, max_tokens=3000)
    if not raw_ocr:
        return []

    try:
        match = re.search(r'\{.*\}', raw_ocr, re.DOTALL)
        clean_json = match.group(0) if match else raw_ocr
        data = json.loads(clean_json)
        raw_items = data.get("items", [])
    except Exception as e:
        print(f"Ошибка парсинга JSON OCR Этапа 1: {e}")
        return []

    if not raw_items:
        return []

    # Очищаем позиции и фильтруем стоп-слова
    items_for_cat = []
    stop_words = ["итог", "итогр", "всего к оплате", "сумма ндс", "скидка", "безналич", "карта", "сдача"]
    for it in raw_items:
        name = str(it.get("name", "")).strip()
        try:
            amt = abs(float(it.get("amount", 0)))
        except Exception:
            amt = 0.0

        if amt > 0 and name and not any(w in name.lower() for w in stop_words):
            items_for_cat.append({"item": name, "amount": amt})

    if not items_for_cat:
        return []

    # --- ЭТАП 2: Текстовая пакетная категоризация ---
    cat_prompt = PROMPT_BATCH_CATEGORIZE.format(
        menu_str=menu_str,
        items_json=json.dumps([x["item"] for x in items_for_cat], ensure_ascii=False)
    )
    cat_messages = [
        {"role": "system", "content": cat_prompt},
        {"role": "user", "content": "Классифицируй товары по предоставленному меню."}
    ]
    raw_cats = _call_llm(cat_messages, model="gpt-4o-mini", temperature=0.0)

    final_results = []
    try:
        match_arr = re.search(r'\[.*\]', raw_cats, re.DOTALL)
        clean_arr = match_arr.group(0) if match_arr else raw_cats
        cat_list = json.loads(clean_arr)
    except Exception:
        cat_list = []

    for idx, it in enumerate(items_for_cat):
        c_info = cat_list[idx] if idx < len(cat_list) else {}
        final_results.append({
            "item": it["item"],
            "amount": it["amount"],
            "category": c_info.get("category", "Разное"),
            "subcategory": c_info.get("subcategory", "Требует проверки")
        })

    return final_results
