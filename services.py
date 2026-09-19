# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import base64
import re
import io
import json
import tempfile
import requests

# ====================================================================
# АВТОУСТАНОВКА БИБЛИОТЕК (Хак для Bothost)
# ====================================================================
try:
    import pandas as pd
except ImportError:
    print("Библиотеки не найдены. Запускаю автоустановку...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pandas", "openpyxl"])
    print("Установка завершена! Перезапускаю скрипт...")
    os.execv(sys.executable, [sys.executable] + sys.argv)

import vk_api
from vk_api.longpoll import VkLongPoll
from openai import OpenAI
from config import (
    VK_TOKEN,
    AI_TUNNEL_KEY,
    GOOGLE_SHEETS_URL,
    AI_BASE_URL,
    PROMPT_CATEGORIZE,
    PROMPT_EXTRACT,
    PROMPT_LIST_COMMAND,
    PROMPT_RECEIPT_TOTAL,
    PROMPT_RECEIPT_ITEMS,
    PROMPT_BATCH_CATEGORIZE,
    PROMPT_FILE_MAPPING
)

# ====================================================================
# ИНИЦИАЛИЗАЦИЯ КЛИЕНТОВ (ВК и ИИ)
# ====================================================================
vk_session = vk_api.VkApi(token=VK_TOKEN, api_version='5.131')
longpoll = VkLongPoll(vk_session)
vk = vk_session.get_api()
ai_client = OpenAI(api_key=AI_TUNNEL_KEY, base_url=AI_BASE_URL)

# ====================================================================
# АВТОМАТИЧЕСКАЯ ТЕЛЕМЕТРИЯ В ТАБЛИЦУ «КОНТРОЛЬ ФУНКЦИОНАЛА»
# ====================================================================
def report_module_health(module_num: int, status: str = "В строю", error_details: str = ""):
    """
    Отправляет статус модуля (№1-19) на лист 'Контроль функционала'.
    status: 'В строю' или 'Требует внимания'.
    """
    payload = {
        "action": "update_module_status",
        "module_num": module_num,
        "status": status,
        "error": str(error_details)[:300] if error_details else ""
    }
    try:
        return send_to_google_sheets(payload)
    except Exception as e:
        print(f"Ошибка отправки статуса модуля №{module_num}: {e}")
        return {"status": "ERROR"}

# ====================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С ФОТО
# ====================================================================
def get_image_base64_uri(image_url):
    """Скачивает изображение из ВК через Python и кодирует в Base64."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        res = requests.get(image_url, headers=headers, timeout=25)
        if res.status_code == 200:
            b64_data = base64.b64encode(res.content).decode("utf-8")
            return f"data:image/jpeg;base64,{b64_data}"
        else:
            print(f"Ошибка загрузки фото из ВК: HTTP {res.status_code}")
            return None
    except Exception as e:
        print(f"Исключение при скачивании фото: {e}")
        return None

# ====================================================================
# ФУНКЦИИ СВЯЗИ С ВК (С ЗАЩИТОЙ ОТ ЗАВИСАНИЯ И ДЛИННЫХ ТЕКСТОВ)
# ====================================================================
def send_vk_message(user_id, text, keyboard=None):
    try:
        max_len = 3800
        kb_val = None
        if keyboard is not None:
            kb_val = keyboard.get_keyboard() if hasattr(keyboard, 'get_keyboard') else keyboard

        if len(text) > max_len:
            parts = [text[i:i+max_len] for i in range(0, len(text), max_len)]
            for idx, part in enumerate(parts):
                post = {'user_id': user_id, 'message': part, 'random_id': 0}
                if idx == len(parts) - 1 and kb_val is not None:
                    post['keyboard'] = kb_val
                vk.messages.send(**post)
            return

        post = {'user_id': user_id, 'message': text, 'random_id': 0}
        if kb_val is not None:
            post['keyboard'] = kb_val
        vk.messages.send(**post)
    except Exception as e:
        print(f"Ошибка отправки сообщения ВК с клавиатурой: {e}")
        try:
            vk.messages.send(user_id=user_id, message=text[:3800], random_id=0)
        except Exception as e2:
            print(f"Критическая ошибка отправки: {e2}")

def send_to_google_sheets(payload):
    """Отправляет JSON-данные в Google Таблицу и возвращает ответ."""
    try:
        response = requests.post(GOOGLE_SHEETS_URL, json=payload, timeout=20)
        return response.json()
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

# ====================================================================
# ФУНКЦИИ ОБРАБОТКИ ЧЕРЕЗ ИИ
# ====================================================================
def parse_voice_list_command_with_ai(user_text):
    try:
        response = ai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            temperature=0.0,
            messages=[
                {"role": "system", "content": PROMPT_LIST_COMMAND},
                {"role": "user", "content": user_text}
            ]
        )
        text = response.choices[0].message.content.strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(text)
    except Exception as e:
        print(f"Ошибка парсинга голосовой команды списка: {e}")
        return {"action": "unknown"}

parse_list_command_with_ai = parse_voice_list_command_with_ai

def categorize_with_ai(item, menu_str, context=""):
    prompt = f"Операция: {item}\n"
    if context:
        prompt += f"Подсказка пользователя: {context}\n"
    prompt += f"\nМеню:\n{menu_str}"

    try:
        response = ai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            temperature=0.2,
            messages=[
                {"role": "system", "content": PROMPT_CATEGORIZE},
                {"role": "user", "content": prompt}
            ]
        )
        text = response.choices[0].message.content.strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            return data.get("category", "UNKNOWN"), data.get("subcategory", "UNKNOWN")
    except Exception as e:
        print(f"Ошибка AI при категоризации: {e}")
    return "UNKNOWN", "UNKNOWN"

def extract_transaction_with_ai(user_text):
    try:
        response = ai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            temperature=0.2,
            messages=[
                {"role": "system", "content": PROMPT_EXTRACT},
                {"role": "user", "content": user_text}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Ошибка AI при извлечении/общении: {e}")
        return None

extract_operations_with_ai = extract_transaction_with_ai

def transcribe_audio_with_ai(audio_url):
    try:
        response = requests.get(audio_url, timeout=20)
        if response.status_code != 200:
            return None

        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_audio:
            temp_audio.write(response.content)
            temp_audio_path = temp_audio.name

        with open(temp_audio_path, "rb") as audio_file:
            transcript = ai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )

        os.remove(temp_audio_path)
        return transcript.text.strip()
    except Exception as e:
        print(f"Ошибка распознавания голоса: {e}")
        return None

def extract_receipt_total_with_ai(image_url):
    try:
        base64_uri = get_image_base64_uri(image_url)
        if not base64_uri:
            return None

        response = ai_client.chat.completions.create(
            model="gpt-4o",
            temperature=0.0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT_RECEIPT_TOTAL},
                        {"type": "image_url", "image_url": {"url": base64_uri, "detail": "high"}}
                    ]
                }
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Ошибка AI при чтении итога чека: {e}")
        return None

def extract_receipt_items_with_ai(image_url):
    try:
        base64_uri = get_image_base64_uri(image_url)
        if not base64_uri:
            return None

        response = ai_client.chat.completions.create(
            model="gpt-4o",
            temperature=0.0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT_RECEIPT_ITEMS},
                        {"type": "image_url", "image_url": {"url": base64_uri, "detail": "high"}}
                    ]
                }
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Ошибка AI при чтении позиций чека: {e}")
        return None

def normalize_receipt_items_with_ai(raw_items_list):
    prompt = (
        "Преврати сырые строки чеков СТРОГО в базовое существительное товара.\n"
        "УДАЛИ ВСЕ БРЕНДЫ, ВКУСЫ, СОРТА И МАГАЗИНЫ!\n"
        "Примеры:\n"
        "- Пакет Лента -> Пакет\n"
        "- Салфетки влажные Little -> Салфетки влажные\n"
        "- Колбаса Останкино -> Колбаса\n"
        "- Зубная щетка Colgate -> Зубная щетка\n"
        "- Бекон Черкизово -> Бекон\n"
        "- Яйцо куриное -> Яйца\n"
        "- Напиток Святой источник -> Вода\n"
        "- Шоколад Milka Oreo -> Шоколад\n"
        "- Молоко Домик в деревне -> Молоко\n\n"
        "Вот список для очистки:\n"
    )
    for it in raw_items_list:
        prompt += f"- {it}\n"
    
    prompt += "\nВерни СТРОГО JSON-объект в формате: {\"Сырое название\": \"Очищенное существительное\"}"
    
    try:
        response = ai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            temperature=0.0,
            messages=[
                {"role": "system", "content": "Ты нормализатор товаров в базовые существительные. Отвечай только валидным JSON."},
                {"role": "user", "content": prompt}
            ]
        )
        text = response.choices[0].message.content.strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(text)
    except Exception as e:
        print(f"Ошибка нормализации брендов: {e}")
        return {}

def categorize_batch_with_ai(items_list, menu_str):
    prompt = f"Меню:\n{menu_str}\n\nОперации:\n"
    for item in items_list:
        orig = item.get('original_item') or item.get('item', '')
        amt = item.get('amount', 0)
        prompt += f"- {orig} ({amt} руб.)\n"

    try:
        response = ai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            temperature=0.2,
            messages=[
                {"role": "system", "content": PROMPT_BATCH_CATEGORIZE},
                {"role": "user", "content": prompt}
            ]
        )
        text = response.choices[0].message.content.strip()
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(text)
    except Exception as e:
        print(f"Ошибка AI при пакетной категоризации: {e}")
        return []

# ====================================================================
# УМНЫЙ ПАРСИНГ ВЫПИСОК (БАНКИ РФ + ПАНДАС + ИИ)
# ====================================================================
def _clean_amount(raw_val):
    if raw_val is None:
        return 0.0
    s = str(raw_val).strip()
    if not s or s.lower() in ["nan", "none", "null", ""]:
        return 0.0
    is_negative = ('-' in s) or ('CR' in s.upper())
    clean_s = re.sub(r'[^\d.,]', '', s)
    if not clean_s:
        return 0.0
    if '.' in clean_s and ',' in clean_s:
        if clean_s.rfind(',') > clean_s.rfind('.'):
            clean_s = clean_s.replace('.', '').replace(',', '.')
        else:
            clean_s = clean_s.replace(',', '')
    elif ',' in clean_s:
        clean_s = clean_s.replace(',', '.')
    try:
        val = float(clean_s)
        return -val if is_negative else val
    except ValueError:
        return 0.0

def _detect_bank_columns(df):
    date_keywords = ["дата операции", "дата платежа", "дата проводки", "дата", "date"]
    amount_keywords = ["сумма операции", "сумма платежа", "сумма в валюте счета", "сумма", "amount"]
    expense_keywords = ["сумма списания", "списание", "расход", "дебет", "debit", "снятие"]
    income_keywords = ["сумма зачисления", "зачисление", "пополнение", "приход", "доход", "кредит", "credit"]
    desc_keywords = ["описание операции", "назначение платежа", "детали платежа", "контрагент", "описание", "получатель", "категория", "merchant", "description"]

    max_scan_rows = min(25, len(df))
    for r_idx in range(max_scan_rows):
        row_cells = [str(cell).lower().strip() for cell in df.iloc[r_idx].values]
        found_date = None
        found_amount = None
        found_expense = None
        found_income = None
        found_desc = None

        for c_idx, cell in enumerate(row_cells):
            if not cell:
                continue
            if found_date is None and any(kw in cell for kw in date_keywords):
                found_date = c_idx
                continue
            if found_expense is None and any(kw in cell for kw in expense_keywords):
                found_expense = c_idx
                continue
            if found_income is None and any(kw in cell for kw in income_keywords):
                found_income = c_idx
                continue
            if found_amount is None and any(kw in cell for kw in amount_keywords):
                found_amount = c_idx
                continue
            if found_desc is None and any(kw in cell for kw in desc_keywords):
                found_desc = c_idx
                continue

        has_amount = (found_amount is not None) or (found_expense is not None and found_income is not None)
        if found_date is not None and has_amount and found_desc is not None:
            return {
                "header_row": r_idx,
                "date_col": found_date,
                "desc_col": found_desc,
                "amount_col": found_amount,
                "expense_col": found_expense,
                "income_col": found_income
            }
    return None

def parse_bank_file_with_ai(file_url, file_ext):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(file_url, headers=headers, timeout=35)
        if response.status_code != 200:
            return {"status": "ERROR", "message": f"Не удалось скачать файл от ВК (HTTP {response.status_code})"}

        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            temp_file.write(response.content)
            temp_file_path = temp_file.name

        dfs = {}
        if file_ext == ".csv":
            loaded_df = None
            for enc in ["utf-8-sig", "windows-1251", "utf-8", "cp1251"]:
                for sep in [";", ",", "\t"]:
                    try:
                        test_df = pd.read_csv(temp_file_path, header=None, dtype=str, encoding=enc, sep=sep, on_bad_lines='skip')
                        if test_df.shape[1] > 1 and len(test_df) > 0:
                            loaded_df = test_df
                            break
                    except Exception:
                        continue
                if loaded_df is not None:
                    break
            if loaded_df is None:
                loaded_df = pd.read_csv(temp_file_path, header=None, dtype=str, errors='replace')
            dfs = {"Выписка": loaded_df}
        else:
            try:
                dfs = pd.read_excel(temp_file_path, sheet_name=None, header=None, dtype=str)
            except Exception:
                dfs = pd.read_excel(temp_file_path, sheet_name=None, header=None, dtype=str, engine='openpyxl')

        os.remove(temp_file_path)

        parsed_operations = []
        for sheet_name, df in dfs.items():
            if df is None or df.empty or len(df) < 2:
                continue

            auto_meta = _detect_bank_columns(df)
            if auto_meta is not None:
                h_idx = auto_meta["header_row"]
                d_col = auto_meta["date_col"]
                desc_col = auto_meta["desc_col"]
                amt_col = auto_meta["amount_col"]
                exp_col = auto_meta["expense_col"]
                inc_col = auto_meta["income_col"]

                for i in range(h_idx + 1, len(df)):
                    row = df.iloc[i].values
                    if d_col >= len(row) or desc_col >= len(row):
                        continue
                    date_val = str(row[d_col]).strip()
                    desc_val = str(row[desc_col]).strip()
                    if not date_val or not desc_val or date_val.lower() in ["nan", "none", "nat", "дата"]:
                        continue

                    final_amount = 0.0
                    op_type = "Расход"

                    if exp_col is not None and inc_col is not None:
                        exp_amt = abs(_clean_amount(row[exp_col])) if exp_col < len(row) else 0.0
                        inc_amt = abs(_clean_amount(row[inc_col])) if inc_col < len(row) else 0.0
                        if inc_amt > 0:
                            final_amount = inc_amt
                            op_type = "Доход"
                        elif exp_amt > 0:
                            final_amount = exp_amt
                            op_type = "Расход"
                    elif amt_col is not None and amt_col < len(row):
                        raw_amt = _clean_amount(row[amt_col])
                        if raw_amt > 0:
                            final_amount = raw_amt
                            op_type = "Доход" if any(w in desc_val.lower() for w in ["зарплата", "пополнение", "перевод от", "аванс"]) else "Расход"
                        elif raw_amt < 0:
                            final_amount = abs(raw_amt)
                            op_type = "Расход"

                    if final_amount > 0:
                        parsed_operations.append([date_val, op_type, final_amount, desc_val])

                if len(parsed_operations) > 0:
                    continue

            # Резервный анализ через GPT-4o
            sample_df = df.head(50).fillna("")
            csv_sample = sample_df.to_csv(index=False, sep=";")
            try:
                ai_response = ai_client.chat.completions.create(
                    model="gpt-4o",
                    temperature=0.0,
                    messages=[
                        {"role": "system", "content": PROMPT_FILE_MAPPING},
                        {"role": "user", "content": f"Вкладка: {sheet_name}\nСтроки файла:\n{csv_sample}"}
                    ]
                )
                mapping_text = ai_response.choices[0].message.content.strip()
                match = re.search(r'\{.*\}', mapping_text, re.DOTALL)
                if not match:
                    continue
                mapping = json.loads(match.group(0))
                file_type = mapping.get("file_type")

                if file_type == "flat":
                    h_idx = int(mapping.get("header_row_index") or 0)
                    d_col = int(mapping.get("date_col_idx") or 0)
                    desc_col = int(mapping.get("desc_col_idx") or 1)
                    amt_col = mapping.get("amount_col_idx")
                    amt_col = int(amt_col) if amt_col is not None else None
                    is_signed = mapping.get("is_amount_signed", False)

                    for i in range(h_idx + 1, len(df)):
                        row = df.iloc[i].values
                        if d_col >= len(row) or desc_col >= len(row):
                            continue
                        date_val = str(row[d_col]).strip()
                        desc_val = str(row[desc_col]).strip()
                        if not date_val or not desc_val or date_val.lower() in ["nan", "none", "nat"]:
                            continue
                        if amt_col is not None and amt_col < len(row):
                            val = _clean_amount(row[amt_col])
                            op_type = "Доход" if (is_signed and val > 0) else "Расход"
                            final_amt = abs(val)
                            if final_amt > 0:
                                parsed_operations.append([date_val, op_type, final_amt, desc_val])

                elif file_type == "matrix":
                    h_idx = int(mapping.get("header_row_index") or 0)
                    cat_col = int(mapping.get("category_col_idx") or 0)
                    start_col = int(mapping.get("date_start_col_idx") or 1)
                    days_row = df.iloc[h_idx].values
                    stop_words = ["план", "факт", "баланс", "итого", "максимум", "минимум", "средне", "осталось", "резерв", "долг"]

                    for i in range(h_idx + 1, len(df)):
                        row = df.iloc[i].values
                        if cat_col >= len(row):
                            continue
                        cat_name = str(row[cat_col]).strip()
                        if not cat_name or cat_name.lower() in ["nan", "none"]:
                            continue
                        if any(w in cat_name.lower() for w in stop_words):
                            continue
                        for col_idx in range(start_col, len(row)):
                            day_val = str(days_row[col_idx]).strip() if col_idx < len(days_row) else ""
                            amt = abs(_clean_amount(row[col_idx]))
                            if amt > 0 and day_val and day_val.lower() not in ["nan", "none"]:
                                parsed_operations.append([f"{day_val} число ({sheet_name})", "Расход", amt, cat_name])
            except Exception as e_sheet:
                print(f"Ошибка ИИ-маппинга листа {sheet_name}: {e_sheet}")
                continue

        if not parsed_operations:
            return {"status": "ERROR", "message": "Не удалось найти финансовые операции в файле."}

        return {"status": "SUCCESS", "operations": parsed_operations}
    except Exception as e:
        print(f"Критическая ошибка парсинга: {e}")
        return {"status": "ERROR", "message": str(e)}
