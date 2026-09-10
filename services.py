# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import base64

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

from config import (
    VK_TOKEN,
    AI_TUNNEL_KEY,
    GOOGLE_SHEETS_URL,
    AI_BASE_URL,
    PROMPT_CATEGORIZE,
    PROMPT_EXTRACT,
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
    """
    Скачивает изображение из ВК через Python и кодирует в Base64.
    Это защищает от блокировки со стороны VK CDN серверами OpenAI.
    """
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
# ФУНКЦИИ СВЯЗИ
# ====================================================================
def send_vk_message(user_id, text, keyboard=None):
    """Отправляет сообщение пользователю ВКонтакте."""
    try:
        post = {'user_id': user_id, 'message': text, 'random_id': 0}
        if keyboard is not None:
            post['keyboard'] = keyboard.get_keyboard()
        vk.messages.send(**post)
    except Exception as e:
        print(f"Ошибка отправки с клавиатурой: {e}")
        try:
            vk.messages.send(user_id=user_id, message=text, random_id=0)
        except:
            pass

def send_to_google_sheets(payload):
    """Отправляет JSON-данные в Google Таблицу и возвращает ответ."""
    try:
        response = requests.post(GOOGLE_SHEETS_URL, json=payload, timeout=20)
        return response.json()
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

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
    """Универсальная функция: парсит транзакцию или отвечает как собеседник."""
    try:
        response = ai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            temperature=0.3,
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
    """Извлекает только общий итог и магазин из чека (GPT-4o Vision)."""
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
    """Отправляет список операций в ИИ для массовой категоризации (разбор завалов)."""
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

def parse_bank_file_with_ai(file_url, file_ext):
    """
    Скачивает файл, перебирает ВСЕ вкладки, анализирует структуру через ИИ
    и вытаскивает все операции со всех подходящих листов.
    """
    try:
        response = requests.get(file_url, timeout=30)
        if response.status_code != 200:
            return {"status": "ERROR", "message": "Не удалось скачать файл от ВК"}

        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            temp_file.write(response.content)
            temp_file_path = temp_file.name

        if file_ext == ".csv":
            dfs = {"CSV": pd.read_csv(temp_file_path, header=None, dtype=str)}
        else:
            dfs = pd.read_excel(temp_file_path, sheet_name=None, header=None, dtype=str)

        os.remove(temp_file_path)

        parsed_operations = []

        for sheet_name, df in dfs.items():
            if df.empty:
                continue

            sample_df = df.head(150).fillna("")
            csv_sample = sample_df.to_csv(index=False, sep=";")

            try:
                ai_response = ai_client.chat.completions.create(
                    model="gpt-4o",
                    temperature=0.0,
                    messages=[
                        {"role": "system", "content": PROMPT_FILE_MAPPING},
                        {"role": "user", "content": f"Вкладка: {sheet_name}\nДанные:\n{csv_sample}"}
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
                    continue

                if file_type == "flat":
                    header_idx = mapping.get("header_row_index", 0)
                    date_col = mapping.get("date_col_idx")
                    amount_col = mapping.get("amount_col_idx")
                    desc_col = mapping.get("desc_col_idx")
                    is_signed = mapping.get("is_amount_signed", False)

                    for i in range(header_idx + 1, len(df)):
                        row = df.iloc[i].fillna("")
                        try:
                            date_val = str(row[date_col]).strip()
                            desc_val = str(row[desc_col]).strip()
                            amount_str = str(row[amount_col]).replace(" ", "").replace("\xa0", "").replace(",", ".")

                            if not amount_str or not desc_val or not date_val or date_val.lower() in ["nan", "none", "nat"]:
                                continue

                            amount_val = float(amount_str)
                            if amount_val == 0:
                                continue

                            op_type = "Расход"
                            if is_signed:
                                if amount_val > 0:
                                    op_type = "Доход"
                                amount_val = abs(amount_val)

                            parsed_operations.append([date_val, op_type, amount_val, desc_val])
                        except:
                            continue

                elif file_type == "matrix":
                    header_idx = mapping.get("header_row_index", 0)
                    cat_col = mapping.get("category_col_idx")
                    start_col = mapping.get("date_start_col_idx")
                    days_row = df.iloc[header_idx].fillna("")

                    stop_words = [
                        "план", "факт", "баланс", "итого", "максимум", "минимум", "средне",
                        "почему", "часов", "осталось", "неделя", "месяц", "доходы-расходы",
                        "резерв", "корректировка", "капитал", "долг", "всего", "отклонение",
                        "в долг", "из резерва"
                    ]

                    for i in range(header_idx + 1, len(df)):
                        row = df.iloc[i].fillna("")
                        category_name = str(row[cat_col]).strip()

                        if not category_name or category_name.lower() in ["nan", "none"]:
                            continue
                        if any(word in category_name.lower() for word in stop_words):
                            continue

                        for col_idx in range(start_col, len(df.columns)):
                            day_val = str(days_row[col_idx]).strip()
                            amount_str = str(row[col_idx]).replace(" ", "").replace("\xa0", "").replace(",", ".")

                            if not amount_str or amount_str.lower() in ["0", "0.0", "none", "nan"]:
                                continue
                            if not day_val or day_val.lower() in ["nan", "none", "nat"]:
                                continue

                            try:
                                amount_val = float(amount_str)
                                if amount_val == 0:
                                    continue
                                parsed_operations.append([f"{day_val} число ({sheet_name})", "Расход", abs(amount_val), category_name])
                            except:
                                continue
            except Exception as e:
                print(f"Ошибка при анализе вкладки '{sheet_name}': {e}")
                continue

        if len(parsed_operations) > 50000:
            return {
                "status": "ERROR",
                "message": f"Найдено слишком много цифр ({len(parsed_operations)}). Лимит системы - 50 000 за один раз."
            }

        return {"status": "SUCCESS", "operations": parsed_operations}
    except Exception as e:
        print(f"Ошибка парсинга файла: {e}")
        return {"status": "ERROR", "message": str(e)}

PROMPT_LIST_COMMAND = """
Ты — анализатор команд управления списком операций.
Пользователь смотрит на нумерованный список трат/доходов и даёт команду (голосом или текстом).

Твоя задача — извлечь параметры команды в JSON:

1. УДАЛЕНИЕ:
- "удали первую, третью и пятую" -> {"action": "delete", "indices": [1, 3, 5]}
- "убери вторую" -> {"action": "delete", "indices": [2]}
- "удали 1 4 6" -> {"action": "delete", "indices": [1, 4, 6]}

2. ИЗМЕНЕНИЕ СУММЫ:
- "измени сумму у четвертой на 250" -> {"action": "edit_amount", "index": 4, "amount": 250}
- "у второй поставь 1500 рублей" -> {"action": "edit_amount", "index": 2, "amount": 1500}

3. ИЗМЕНЕНИЕ КАТЕГОРИИ:
- "измени категорию у второй на рестораны" -> {"action": "edit_category", "index": 2, "category_hint": "рестораны"}
- "четвертая это такси" -> {"action": "edit_category", "index": 4, "category_hint": "такси"}
- "третья это спорт" -> {"action": "edit_category", "index": 3, "category_hint": "спорт"}

Если команда не относится к управлению элементами списка — верни {"action": "unknown"}.
Ответь СТРОГО JSON без маркдауна.
"""

def parse_voice_list_command_with_ai(user_text):
    """Распознает команды изменения/удаления элементов списка из голосового текста."""
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
        print(f"Ошибка парсинга голосовой команды: {e}")
        return {"action": "unknown"}
