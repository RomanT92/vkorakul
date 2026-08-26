# -*- coding: utf-8 -*-
import vk_api
from vk_api.longpoll import VkLongPoll
from openai import OpenAI
import requests
import json
import tempfile
import os

# Импортируем настройки и промпты из нашего файла конфигурации (config.py)
from config import (
    VK_TOKEN, AI_TUNNEL_KEY, GOOGLE_SHEETS_URL, AI_BASE_URL, 
    PROMPT_CATEGORIZE, PROMPT_EXTRACT, PROMPT_RECEIPT_TOTAL, PROMPT_RECEIPT_ITEMS,
    PROMPT_BATCH_CATEGORIZE
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
