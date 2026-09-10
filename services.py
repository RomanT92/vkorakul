Вот полный, не сокращённый код файла **`services.py`**:

В нём:

1.  Исправлены функции `_safe_to_int` и `_clean_amount` для надёжного извлечения чисел и очистки мусора (валюты `₽`, неразрывные пробелы `\xa0`, запятые).
2.  Автоматическое определение кодировок (`windows-1251`, `utf-8-sig`, `cp1251`) и разделителей (`;`, `,`, `\t`) для банков РФ.
3.  Поддержка как плоских выписок (включая две колонки «Списание/Пополнение»), так и матричных календарей.
4.  Защита от лимита ВК на длину сообщений (разбивка длинных текстов на части).
5.  Парсер голосовых команд для управления списками (`parse_voice_list_command_with_ai`).
6.  Все промпты импортируются строго из `config.py`.

<!-- end list -->

```` python
# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import base64
import re

# ====================================================================
# АВТОУСТАНОВКА БИБЛИОТЕК (Хак для Bothost)
# ====================================================================
try:
    import pandas as pd
except ImportError:
    print("Библиотеки не найдены. Запускаю автоустановку...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pandas", "openpyxl"])
    print("Установка завершена! Перезапускаю скрипт, чтобы применить изменения...")
    os.execv(sys.executable, [sys.executable] + sys.argv)

import vk_api
from vk_api.longpoll import VkLongPoll
from openai import OpenAI
import requests
import json
import tempfile

# Импортируем настройки и системные промпты строго из config.py
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
    """
    Отправляет сообщение пользователю ВКонтакте.
    Защищает от лимита 4096 символов (разбивает сообщение на части),
    чтобы бот не падал при запросе большой истории операций.
    """
    try:
        max_len = 3800
        if len(text) > max_len:
            parts = [text[i:i+max_len] for i in range(0, len(text), max_len)]
            for idx, part in enumerate(parts):
                kb = keyboard if idx == len(parts) - 1 else None
                post = {'user_id': user_id, 'message': part, 'random_id': 0}
                if kb is not None:
                    post['keyboard'] = kb.get_keyboard()
                vk.messages.send(**post)
            return

        post = {'user_id': user_id, 'message': text, 'random_id': 0}
        if keyboard is not None:
            post['keyboard'] = keyboard.get_keyboard()
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
    """Распознает голосовые/текстовые команды управления элементами списков."""
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
        if text.startswith("```json"):
            text = text[7:-3].strip()
        elif text.startswith("```"):
            text = text[3:-3].strip()
        return json.loads(text)
    except Exception as e:
        print(f"Ошибка парсинга голосовой команды списка: {e}")
        return {"action": "unknown"}

def categorize_with_ai(item, menu_str, context=""):
    """Просит ИИ подобрать категорию из меню с учетом контекста."""
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
        if text.startswith("{") and text.endswith("}"):
            data = json.loads(text)
            return data.get("category", "UNKNOWN"), data.get("subcategory", "UNKNOWN")
    except Exception as e:
        print(f"Ошибка AI при категоризации: {e}")
    return "UNKNOWN", "UNKNOWN"

def extract_transaction_with_ai(user_text):
    """Парсит финансовые операции, команды истории/удаления или общается."""
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

def transcribe_audio_with_ai(audio_url):
    """Скачивает голосовое сообщение из ВК и переводит его в текст."""
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
    """Извлекает общий итог и магазин из чека (GPT-4o Vision)."""
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
                        {"type": "image_url", "image_url": {"url": base64_uri}}
                    ]
                }
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Ошибка AI при чтении итога чека: {e}")
        return None

def extract_receipt_items_with_ai(image_url, menu_str):
    """Извлекает все товары из чека и распределяет их по меню."""
    try:
        base64_uri = get_image_base64_uri(image_url)
        if not base64_uri:
            return None

        prompt = PROMPT_RECEIPT_ITEMS.replace("{menu_str}", menu_str)
        response = ai_client.chat.completions.create(
            model="gpt-4o",
            temperature=0.0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": base64_uri}}
                    ]
                }
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Ошибка AI при чтении позиций чека: {e}")
        return None

def categorize_batch_with_ai(items_list, menu_str):
    """Отправляет список операций в ИИ для массовой категоризации."""
    prompt = f"Меню:\n{menu_str}\n\nОперации:\n"
    for item in items_list:
        prompt += f"- {item['original_item']} ({item['amount']} руб.)\n"

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
        if text.startswith("```json"):
            text = text[7:-3].strip()
        elif text.startswith("```"):
            text = text[3:-3].strip()
        if text.startswith("[") and text.endswith("]"):
            return json.loads(text)
    except Exception as e:
        print(f"Ошибка AI при пакетной категоризации: {e}")
    return []

# ====================================================================
# УМНЫЙ ПАРСИНГ ВЫПИСОК (CSV / XLSX / XLS)
# ====================================================================
def _safe_to_int(val, default=None):
    """Преобразует число или букву колонки (A, B, C...) в целочисленный индекс 0, 1, 2..."""
    if val is None:
        return default
    if isinstance(val, int):
        return val
    s = str(val).strip()
    if s.isdigit():
        return int(s)
    if len(s) == 1 and s.isalpha():
        return ord(s.upper()) - ord('A')
    return default

def _clean_amount(raw_val):
    """Очищает строку от значков валют, пробелов и преобразует в float."""
    if raw_val is None:
        return 0.0
    s = str(raw_val).replace(" ", "").replace("\xa0", "").replace("'", "").replace(",", ".")
    match = re.search(r'[-+]?\d+(\.\d+)?', s)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return 0.0
    return 0.0

def parse_bank_file_with_ai(file_url, file_ext):
    """
    Скачивает файл выписки, определяет кодировку и структуру (flat/matrix),
    извлекая операции в формате [[date, op_type, amount, desc], ...].
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
        response = requests.get(file_url, headers=headers, timeout=35)
        if response.status_code != 200:
            return {"status": "ERROR", "message": f"Не удалось скачать файл от ВК (HTTP {response.status_code})"}

        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            temp_file.write(response.content)
            temp_file_path = temp_file.name

        dfs = {}
        if file_ext == ".csv":
            # Пробуем определить кодировку для банков РФ
            loaded_df = None
            for enc in ["utf-8-sig", "windows-1251", "utf-8", "cp1251"]:
                for sep in [";", ",", "\t"]:
                    try:
                        test_df = pd.read_csv(temp_file_path, header=None, dtype=str, encoding=enc, sep=sep)
                        if test_df.shape[1] > 1 and len(test_df) > 0:
                            loaded_df = test_df
                            break
                    except Exception:
                        continue
                if loaded_df is not None:
                    break
            
            if loaded_df is None:
                loaded_df = pd.read_csv(temp_file_path, header=None, dtype=str, errors='replace')
            dfs = {"CSV": loaded_df}
        else:
            # Excel (.xlsx / .xls)
            dfs = pd.read_excel(temp_file_path, sheet_name=None, header=None, dtype=str)

        os.remove(temp_file_path)

        parsed_operations = []

        for sheet_name, df in dfs.items():
            if df is None or df.empty or len(df) < 2:
                continue

            sample_df = df.head(60).fillna("")
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
                if mapping_text.startswith("```json"):
                    mapping_text = mapping_text[7:-3].strip()
                elif mapping_text.startswith("```"):
                    mapping_text = mapping_text[3:-3].strip()

                mapping = json.loads(mapping_text)
                file_type = mapping.get("file_type")

                if file_type not in ["flat", "matrix"]:
                    print(f"Пропускаю вкладку '{sheet_name}' (тип: {file_type})")
                    continue

                # =========================================================
                # ТИП 1: ПЛОСКАЯ БАНКОВСКАЯ ВЫПИСКА
                # =========================================================
                if file_type == "flat":
                    header_idx = _safe_to_int(mapping.get("header_row_index"), 0)
                    date_col = _safe_to_int(mapping.get("date_col_idx"), 0)
                    desc_col = _safe_to_int(mapping.get("desc_col_idx"), 1)
                    amount_col = _safe_to_int(mapping.get("amount_col_idx"), None)
                    expense_col = _safe_to_int(mapping.get("expense_col_idx"), None)
                    income_col = _safe_to_int(mapping.get("income_col_idx"), None)
                    is_signed = mapping.get("is_amount_signed", False)

                    for i in range(header_idx + 1, len(df)):
                        row = df.iloc[i].fillna("")
                        try:
                            date_val = str(row[date_col]).strip() if date_col < len(row) else ""
                            desc_val = str(row[desc_col]).strip() if desc_col < len(row) else ""

                            if not date_val or not desc_val or date_val.lower() in ["nan", "none", "nat", "дата", "период"]:
                                continue

                            amount_val = 0.0
                            op_type = "Расход"

                            # Две отдельные колонки (Расход и Доход)
                            if expense_col is not None and income_col is not None:
                                exp_val = _clean_amount(row[expense_col]) if expense_col < len(row) else 0.0
                                inc_val = _clean_amount(row[income_col]) if income_col < len(row) else 0.0

                                if inc_val > 0:
                                    amount_val = inc_val
                                    op_type = "Доход"
                                elif exp_val != 0:
                                    amount_val = abs(exp_val)
                                    op_type = "Расход"
                            # Одна колонка сумм
                            elif amount_col is not None and amount_col < len(row):
                                raw_amt = _clean_amount(row[amount_col])
                                if is_signed:
                                    if raw_amt > 0:
                                        op_type = "Доход"
                                        amount_val = raw_amt
                                    else:
                                        op_type = "Расход"
                                        amount_val = abs(raw_amt)
                                else:
                                    amount_val = abs(raw_amt)

                            if amount_val <= 0:
                                continue

                            parsed_operations.append([date_val, op_type, amount_val, desc_val])
                        except Exception:
                            continue

                # =========================================================
                # ТИП 2: СЛОЖНАЯ МАТРИЦА (ТАБЛИЦА-КАЛЕНДАРЬ)
                # =========================================================
                elif file_type == "matrix":
                    header_idx = _safe_to_int(mapping.get("header_row_index"), 0)
                    cat_col = _safe_to_int(mapping.get("category_col_idx"), 0)
                    start_col = _safe_to_int(mapping.get("date_start_col_idx"), 1)
                    days_row = df.iloc[header_idx].fillna("")

                    stop_words = [
                        "план", "факт", "баланс", "итого", "максимум", "минимум", "средне",
                        "почему", "часов", "осталось", "неделя", "месяц", "доходы-расходы",
                        "резерв", "корректировка", "капитал", "долг", "всего", "отклонение"
                    ]

                    for i in range(header_idx + 1, len(df)):
                        row = df.iloc[i].fillna("")
                        cat_name = str(row[cat_col]).strip() if cat_col < len(row) else ""

                        if not cat_name or cat_name.lower() in ["nan", "none"]:
                            continue
                        if any(word in cat_name.lower() for word in stop_words):
                            continue

                        for col_idx in range(start_col, len(df.columns)):
                            day_val = str(days_row[col_idx]).strip()
                            amt = _clean_amount(row[col_idx])
                            if amt <= 0:
                                continue

                            parsed_operations.append([f"{day_val} число ({sheet_name})", "Расход", abs(amt), cat_name])

            except Exception as sheet_err:
                print(f"Ошибка анализа листа {sheet_name}: {sheet_err}")
                continue

        if not parsed_operations:
            return {
                "status": "ERROR",
                "message": "Не удалось найти финансовые операции в файле. Убедитесь, что файл содержит колонки с датой, суммой и назначением платежа."
            }

        if len(parsed_operations) > 50000:
            return {
                "status": "ERROR",
                "message": f"Найдено слишком много строк ({len(parsed_operations)}). Лимит системы — 50 000 за раз."
            }

        return {"status": "SUCCESS", "operations": parsed_operations}
    except Exception as e:
        print(f"Критическая ошибка парсинга: {e}")
        return {"status": "ERROR", "message": str(e)}

````
