# -*- coding: utf-8 -*-
import vk_api
from vk_api.longpoll import VkLongPoll
from openai import OpenAI
import requests
import json
import tempfile
import os
import pandas as pd

# Импортируем настройки и промпты из нашего файла конфигурации (config.py)
from config import (
    VK_TOKEN, AI_TUNNEL_KEY, GOOGLE_SHEETS_URL, AI_BASE_URL, 
    PROMPT_CATEGORIZE, PROMPT_EXTRACT, PROMPT_RECEIPT_TOTAL, PROMPT_RECEIPT_ITEMS,
    PROMPT_BATCH_CATEGORIZE, PROMPT_FILE_MAPPING # <-- Добавили это
)

# ====================================================================
# ИНИЦИАЛИЗАЦИЯ КЛИЕНТОВ (ВК и ИИ)
# ====================================================================
# Подключаемся к ВКонтакте, жестко фиксируя версию API для поддержки кнопок
vk_session = vk_api.VkApi(token=VK_TOKEN, api_version='5.131')
longpoll = VkLongPoll(vk_session)
vk = vk_session.get_api()

# Подключаемся к нейросети через шлюз AITunnel
ai_client = OpenAI(api_key=AI_TUNNEL_KEY, base_url=AI_BASE_URL)

# ====================================================================
# ФУНКЦИИ СВЯЗИ
# ====================================================================

def send_vk_message(user_id, text, keyboard=None):
    """
    Отправляет сообщение пользователю ВКонтакте.
    Если передана клавиатура, прикрепляет её к сообщению.
    """
    try:
        post = {'user_id': user_id, 'message': text, 'random_id': 0}
        if keyboard is not None:
            post['keyboard'] = keyboard.get_keyboard()
        vk.messages.send(**post)
    except Exception as e:
        print(f"Ошибка отправки с клавиатурой: {e}")
        try:
            # Защита от сбоев: если ВК ругается на формат клавиатуры 
            # (например, если кнопок слишком много), 
            # пробуем отправить просто текст, чтобы бот не молчал.
            vk.messages.send(user_id=user_id, message=text, random_id=0)
        except:
            pass

def send_to_google_sheets(payload):
    """
    Отправляет JSON-данные в твою Google Таблицу (в Apps Script) 
    и возвращает ответ от таблицы в виде словаря.
    """
    try:
        response = requests.post(GOOGLE_SHEETS_URL, json=payload)
        return response.json()
    except Exception as e:
        # Если таблица недоступна или скрипт упал, возвращаем ошибку, 
        # чтобы бот мог сообщить об этом пользователю.
        return {"status": "ERROR", "message": str(e)}

def categorize_with_ai(item, menu_str, context=""):
    """
    Просит ИИ подобрать категорию из меню с учетом контекста.
    Используется при разборе завалов и когда бот просит подсказку.
    """
    prompt = f"Операция: {item}\n"
    if context:
        prompt += f"Подсказка пользователя: {context}\n"
    prompt += f"\nМеню:\n{menu_str}"
    
    try:
        response = ai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            # temperature=0.2 дает ИИ немного "фантазии" и гибкости ума. 
            # Это позволяет ему понимать сленг, ассоциации и сложные объяснения из подсказок,
            # но при этом не выдумывать несуществующие категории.
            temperature=0.2, 
            messages=[
                {"role": "system", "content": PROMPT_CATEGORIZE},
                {"role": "user", "content": prompt}
            ]
        )
        text = response.choices[0].message.content.strip()
        
        # Проверяем, что ИИ действительно вернул JSON
        if text.startswith("{") and text.endswith("}"):
            data = json.loads(text)
            return data.get("category", "UNKNOWN"), data.get("subcategory", "UNKNOWN")
    except Exception as e:
        print(f"Ошибка AI при категоризации: {e}")
    
    return "UNKNOWN", "UNKNOWN"

def extract_transaction_with_ai(user_text):
    """
    Универсальная функция для обычного режима.
    Просит ИИ извлечь сумму и очищенное название (вернет JSON), 
    ЛИБО просто ответить на вопрос пользователя обычным текстом (режим собеседника).
    """
    try:
        response = ai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            # temperature=0.3 — идеальный баланс! 
            # ИИ будет достаточно точным, чтобы правильно собрать JSON с цифрами,
            # но при этом достаточно "живым", чтобы интересно отвечать на вопросы как собеседник.
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
    """
    Скачивает голосовое сообщение из ВК и переводит его в текст 
    с помощью модели Whisper (OpenAI).
    """
    try:
        # 1. Скачиваем аудиофайл по ссылке от ВК
        response = requests.get(audio_url)
        if response.status_code != 200:
            return None
        
        # 2. Сохраняем его во временный файл на сервере
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_audio:
            temp_audio.write(response.content)
            temp_audio_path = temp_audio.name

        # 3. Отправляем аудиофайл в нейросеть на распознавание
        with open(temp_audio_path, "rb") as audio_file:
            transcript = ai_client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file
            )
        
        # 4. Удаляем временный файл, чтобы не засорять память сервера
        os.remove(temp_audio_path)
        
        # Возвращаем распознанный текст
        return transcript.text.strip()
        
    except Exception as e:
        print(f"Ошибка распознавания голоса: {e}")
        return None

def extract_receipt_total_with_ai(image_url):
    """Извлекает только общий итог и магазин из чека"""
    try:
        response = ai_client.chat.completions.create(
            model="gpt-4o", 
            temperature=0.0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT_RECEIPT_TOTAL},
                        {"type": "image_url", "image_url": {"url": image_url}}
                    ]
                }
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Ошибка AI при чтении итога чека: {e}")
        return None

def extract_receipt_items_with_ai(image_url, menu_str):
    """Извлекает все товары из чека и распределяет их по переданному меню"""
    prompt = PROMPT_RECEIPT_ITEMS.replace("{menu_str}", menu_str)
    try:
        response = ai_client.chat.completions.create(
            model="gpt-4o", 
            temperature=0.0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}}
                    ]
                }
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Ошибка AI при чтении позиций чека: {e}")
        return None

def categorize_batch_with_ai(items_list, menu_str):
    """Отправляет список операций в ИИ для массовой категоризации"""
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
        
        # Очищаем от маркдауна, если ИИ его добавил
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
    Скачивает файл, анализирует структуру через ИИ и вытаскивает все операции.
    Поддерживает как плоские выписки, так и сложные матрицы.
    """
    try:
        # 1. Скачиваем файл
        response = requests.get(file_url)
        if response.status_code != 200:
            return {"status": "ERROR", "message": "Не удалось скачать файл от ВК"}

        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            temp_file.write(response.content)
            temp_file_path = temp_file.name

        # 2. Читаем файл как сырые данные (без заголовков)
        if file_ext == ".csv":
            df = pd.read_csv(temp_file_path, header=None, dtype=str)
        else:
            df = pd.read_excel(temp_file_path, header=None, dtype=str)
        
        os.remove(temp_file_path)

        # 3. Берем первые 150 строк, переводим в текст (CSV) и отправляем ИИ
        sample_df = df.head(150).fillna("")
        csv_sample = sample_df.to_csv(index=False, sep=";")

        ai_response = ai_client.chat.completions.create(
            model="gpt-4o", # Используем мощную модель для анализа структуры
            temperature=0.0,
            messages=[
                {"role": "system", "content": PROMPT_FILE_MAPPING},
                {"role": "user", "content": f"Файл:\n{csv_sample}"}
            ]
        )
        
        mapping_text = ai_response.choices[0].message.content.strip()
        if mapping_text.startswith("```json"):
            mapping_text = mapping_text[7:-3].strip()
        elif mapping_text.startswith("```"):
            mapping_text = mapping_text[3:-3].strip()
            
        mapping = json.loads(mapping_text)
        file_type = mapping.get("file_type")
        
        parsed_operations = []
        
        # =========================================================
        # ТИП 1: ПЛОСКАЯ БАНКОВСКАЯ ВЫПИСКА
        # =========================================================
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
                    # Убираем пробелы из сумм (например 1 500,00 -> 1500.00)
                    amount_str = str(row[amount_col]).replace(" ", "").replace("\xa0", "").replace(",", ".")
                    
                    if not amount_str or not desc_val:
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
                    
        # =========================================================
        # ТИП 2: СЛОЖНАЯ МАТРИЦА (ТВОЙ ШАБЛОН)
        # =========================================================
        elif file_type == "matrix":
            header_idx = mapping.get("header_row_index", 0)
            cat_col = mapping.get("category_col_idx")
            start_col = mapping.get("date_start_col_idx")
            
            days_row = df.iloc[header_idx].fillna("")
            
            for i in range(header_idx + 1, len(df)):
                row = df.iloc[i].fillna("")
                category_name = str(row[cat_col]).strip()
                if not category_name:
                    continue
                    
                # Идем по всем колонкам с датами (с 1 по 31 число)
                for col_idx in range(start_col, len(df.columns)):
                    day_val = str(days_row[col_idx]).strip()
                    amount_str = str(row[col_idx]).replace(" ", "").replace("\xa0", "").replace(",", ".")
                    
                    if not amount_str or amount_str.lower() in ["0", "0.0", "none", "nan"]:
                        continue
                        
                    try:
                        amount_val = float(amount_str)
                        if amount_val == 0:
                            continue
                            
                        # Матрица распаковывается в плоский список!
                        parsed_operations.append([f"{day_val} число", "Расход", abs(amount_val), category_name])
                    except:
                        continue

        return {"status": "SUCCESS", "operations": parsed_operations}
        
    except Exception as e:
        print(f"Ошибка парсинга файла: {e}")
        return {"status": "ERROR", "message": str(e)}
