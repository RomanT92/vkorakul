# -*- coding: utf-8 -*-
import json
import re
import requests
from io import BytesIO
import vk_api
from vk_api.longpoll import VkLongPoll
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

# ====================================================================
# ИНИЦИАЛИЗАЦИЯ VK API (ДЛЯ main.py)
# ====================================================================
vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()
longpoll = VkLongPoll(vk_session)

def send_vk_message(user_id, message, keyboard=None):
    """Отправка сообщения пользователю ВКонтакте."""
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
    """Единая точка вызова моделей ИИ через AI Tunnel."""
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

# ====================================================================
# ИЗВЛЕЧЕНИЕ ОПЕРАЦИЙ (ДЛЯ handlers_transaction.py)
# ====================================================================
def extract_operations_with_ai(user_text):
    """Извлечение операций из текста пользователя."""
    messages = [
        {"role": "system", "content": PROMPT_EXTRACT},
        {"role": "user", "content": user_text}
    ]
    return _call_llm(messages, model="gpt-4o", temperature=0.0)

# Прямой алиас имени для handlers_transaction.py
extract_transaction_with_ai = extract_operations_with_ai

# ====================================================================
# РАЗБОР КОМАНД К СПИСКУ (ДЛЯ handlers_voice_commands.py)
# ====================================================================
def parse_list_command_with_ai(user_text):
    """Разбор голосовой/текстовой команды к списку операций."""
    messages = [
        {"role": "system", "content": PROMPT_LIST_COMMAND},
        {"role": "user", "content": user_text}
    ]
    return _call_llm(messages, model="gpt-4o-mini", temperature=0.0)

# Прямой алиас имени для handlers_voice_commands.py
parse_voice_list_command_with_ai = parse_list_command_with_ai

# ====================================================================
# КЛАССИФИКАЦИЯ (ДЛЯ handlers_receipt.py и handlers_transaction.py)
# ====================================================================
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

# ====================================================================
# ПАКЕТНАЯ КЛАССИФИКАЦИЯ (ДЛЯ handlers_queue.py)
# ====================================================================
def categorize_batch_with_ai(batch, menu_str):
    """Пакетная классификация списка операций из очереди разбора."""
    items_names = [it.get("original_item", "") for it in batch]
    cat_prompt = PROMPT_BATCH_CATEGORIZE.format(
        menu_str=menu_str,
        items_json=json.dumps(items_names, ensure_ascii=False)
    )
    messages = [
        {"role": "system", "content": cat_prompt},
        {"role": "user", "content": "Классифицируй товары по меню."}
    ]
    raw = _call_llm(messages, model="gpt-4o-mini", temperature=0.0)
    results = []
    try:
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        clean = match.group(0) if match else raw
        arr = json.loads(clean)
        for idx, item in enumerate(batch):
            c_info = arr[idx] if idx < len(arr) else {}
            results.append({
                "original_item": item.get("original_item", ""),
                "category": c_info.get("category", "Разное"),
                "subcategory": c_info.get("subcategory", "Требует проверки")
            })
    except Exception as e:
        print(f"Ошибка categorize_batch_with_ai: {e}")
        for item in batch:
            results.append({
                "original_item": item.get("original_item", ""),
                "category": "Разное",
                "subcategory": "Требует проверки"
            })
    return results

# ====================================================================
# РАБОТА С ЧЕКАМИ (ДЛЯ handlers_receipt.py)
# ====================================================================
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

def extract_receipt_items_pipeline(photo_url, menu_str):
    """Двухэтапный конвейер разбора чека (OCR -> Текстовая классификация)."""
    # 1 этап: Чистое чтение позиций и сумм (GPT-4o Vision)
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
        print(f"Ошибка парсинга JSON OCR: {e}")
        return []

    if not raw_items:
        return []

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

    # 2 этап: Быстрая текстовая категоризация по меню
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

# ====================================================================
# ГОЛОСОВЫЕ СООБЩЕНИЯ (ДЛЯ main.py)
# ====================================================================
def transcribe_audio_with_ai(audio_url):
    """Распознавание голосовых сообщений через Whisper API."""
    try:
        resp_audio = requests.get(audio_url, timeout=30)
        if resp_audio.status_code != 200:
            return ""

        headers = {
            "Authorization": f"Bearer {AI_TUNNEL_KEY}"
        }
        files = {
            "file": ("audio.ogg", resp_audio.content, "audio/ogg")
        }
        data = {
            "model": "whisper-1",
            "language": "ru"
        }

        resp = requests.post(f"{AI_BASE_URL}audio/transcriptions", headers=headers, files=files, data=data, timeout=60)
        if resp.status_code == 200:
            return resp.json().get("text", "").strip()
        return ""
    except Exception as e:
        print(f"Ошибка транскрибации аудио: {e}")
        return ""

# ====================================================================
# ИМПОРТ ВЫПИСОК (ДЛЯ main.py)
# ====================================================================
def parse_bank_file_with_ai(doc_url, doc_ext):
    """Парсинг банковской выписки (CSV/XLSX)."""
    try:
        import pandas as pd
        resp = requests.get(doc_url, timeout=30)
        if resp.status_code != 200:
            return {"status": "ERROR", "message": "Не удалось скачать файл"}

        file_bytes = resp.content

        if doc_ext == '.csv':
            try:
                df = pd.read_csv(BytesIO(file_bytes), encoding='utf-8')
            except Exception:
                df = pd.read_csv(BytesIO(file_bytes), encoding='cp1251', sep=None, engine='python')
        else:
            df = pd.read_excel(BytesIO(file_bytes))

        if df.empty:
            return {"status": "ERROR", "message": "Файл пуст"}

        sample_str = df.head(10).to_string()
        messages = [
            {"role": "system", "content": PROMPT_FILE_MAPPING},
            {"role": "user", "content": f"Анализируй структуру выписки:\n{sample_str}"}
        ]
        raw_mapping = _call_llm(messages, model="gpt-4o-mini", temperature=0.0)

        match = re.search(r'\{.*\}', raw_mapping, re.DOTALL)
        mapping = json.loads(match.group(0)) if match else {}

        operations = []
        if mapping.get("file_type") == "flat":
            date_col = mapping.get("date_col_idx", 0)
            desc_col = mapping.get("desc_col_idx", 1)
            amt_col = mapping.get("amount_col_idx", 2)

            for idx, row in df.iterrows():
                try:
                    d_val = str(row.iloc[date_col]).strip()
                    desc_val = str(row.iloc[desc_col]).strip()
                    raw_amt = str(row.iloc[amt_col]).replace(',', '.').strip()
                    amt_val = abs(float(re.sub(r'[^\d.]', '', raw_amt)))
                    if amt_val > 0 and desc_val:
                        operations.append([d_val, "Расход", amt_val, desc_val])
                except Exception:
                    continue

        return {"status": "SUCCESS", "operations": operations}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}
