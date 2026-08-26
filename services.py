# -*- coding: utf-8 -*-
import vk_api
from vk_api.longpoll import VkLongPoll
from openai import OpenAI
import requests
import json

# Импортируем настройки и промпты из нашего файла конфигурации
from config import (
    VK_TOKEN, AI_TUNNEL_KEY, GOOGLE_SHEETS_URL, AI_BASE_URL, 
    PROMPT_CATEGORIZE, PROMPT_EXTRACT
)

# ====================================================================
# ИНИЦИАЛИЗАЦИЯ КЛИЕНТОВ (ВК и ИИ)
# ====================================================================
# Подключаемся к ВКонтакте
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
            # Защита от сбоев: если ВК ругается на клавиатуру, 
            # пробуем отправить хотя бы просто текст, чтобы бот не молчал.
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
            # Это позволяет ему понимать сленг, ассоциации и сложные объяснения из подсказок.
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
    """
    Просит ИИ извлечь сумму, очищенное название и тип из свободного текста.
    Используется самым первым, когда пользователь только написал сообщение.
    """
    try:
        response = ai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            # temperature=0.0 делает ИИ строгим роботом. 
            # Здесь нам нужна 100% точность, чтобы он не придумал лишних цифр 
            # и правильно очистил строку от мусора.
            temperature=0.0, 
            messages=[
                {"role": "system", "content": PROMPT_EXTRACT},
                {"role": "user", "content": user_text}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Ошибка AI при извлечении: {e}")
        return None
