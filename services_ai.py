# -*- coding: utf-8 -*-
import os
import base64
import re
import io
import json
import tempfile
import requests
from openai import OpenAI

from config import (
    AI_TUNNEL_KEY,
    AI_BASE_URL,
    PROMPT_CATEGORIZE,
    PROMPT_EXTRACT,
    PROMPT_LIST_COMMAND,
    PROMPT_RECEIPT_TOTAL,
    PROMPT_RECEIPT_ITEMS,
    PROMPT_BATCH_CATEGORIZE
)

# ====================================================================
# ИНИЦИАЛИЗАЦИЯ ИИ КЛИЕНТА (OPENAI / AITUNNEL)
# ====================================================================
ai_client = OpenAI(api_key=AI_TUNNEL_KEY, base_url=AI_BASE_URL)

def _clean_json_from_markdown(text: str) -> str:
    """Очищает ответ нейросети от markdown-блоков ```json ... ``` и пробелов."""
    if not text:
        return ""
    cleaned = text.strip()
    # Удаляем открывающий блок ```json или ```
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.IGNORECASE)
    # Удаляем закрывающий блок ```
    cleaned = re.sub(r'\s*```$', '', cleaned)
    return cleaned.strip()

# ====================================================================
# ОБРАБОТКА ИЗОБРАЖЕНИЙ (КАЧЕСТВЕННЫЙ РЕСАЙЗ ДЛЯ ЧЕКОВ РФ)
# ====================================================================
def get_image_base64_uri(image_url):
    """
    Скачивает изображение из ВК. Сохраняет высокое разрешение по ширине
    (до 1600px по ширине и до 4200px по высоте), предотвращая искажение мелкого
    шрифта на длинных кассовых чеках, и кодирует в Base64.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        res = requests.get(image_url, headers=headers, timeout=25)
        if res.status_code != 200:
            print(f"[RECEIPT] Ошибка загрузки фото из ВК: HTTP {res.status_code}")
            return None

        # Умное масштабирование для кассовых чеков (не сплющивать ширину!)
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(res.content))
            w, h = img.size
            max_w = 1600
            max_h = 4200
            scale = min(max_w / float(w), max_h / float(h), 1.0)
            if scale < 1.0:
                new_w = int(w * scale)
                new_h = int(h * scale)
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            if img.mode != "RGB":
                img = img.convert("RGB")

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=88, optimize=True)
            b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")
            return f"data:image/jpeg;base64,{b64_data}"
        except Exception as e_pil:
            print(f"[RECEIPT] Pillow сжатие пропущено ({e_pil}), отправляем оригинал")
            b64_data = base64.b64encode(res.content).decode("utf-8")
            return f"data:image/jpeg;base64,{b64_data}"

    except Exception as e:
        print(f"[RECEIPT] Исключение при скачивании фото: {e}")
        return None

# ====================================================================
# ФУНКЦИИ ГОЛОСОВОГО И ТЕКСТОВОГО УПРАВЛЕНИЯ СПИСКАМИ
# ====================================================================
def parse_voice_list_command_with_ai(user_text):
    """
    Парсит составные голосовые команды к спискам операций.
    Использует gemini-2.5-flash как приоритетную быструю модель
    с автоматическим каскадным переходом (fallback) на gpt-4o-mini и gpt-3.5-turbo при сбоях шлюза.
    """
    models_to_try = ["gemini-2.5-flash", "gpt-4o-mini", "gpt-3.5-turbo"]
    for model_name in models_to_try:
        try:
            response = ai_client.chat.completions.create(
                model=model_name,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": PROMPT_LIST_COMMAND},
                    {"role": "user", "content": user_text}
                ],
                timeout=20
            )
            text = response.choices[0].message.content.strip()
            cleaned = _clean_json_from_markdown(text)
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return json.loads(cleaned)
        except Exception as e:
            print(f"Ошибка парсинга голосовой команды списка ({model_name}): {type(e).__name__}: {e}")
            continue
    return {"action": "unknown"}

parse_list_command_with_ai = parse_voice_list_command_with_ai

# ====================================================================
# КЛАССИФИКАЦИЯ ТРАНЗАКЦИЙ И АКТИВНЫЙ ДИАЛОГ
# ====================================================================
def categorize_with_ai(item, menu_str, context=""):
    """
    Классификация транзакции по эталонному меню с каскадом моделей (gemini-2.5-flash -> gpt-4o-mini -> gpt-3.5-turbo).
    """
    prompt = f"Операция: {item}\n"
    if context:
        prompt += f"Подсказка пользователя: {context}\n"
    prompt += f"\nМеню:\n{menu_str}"

    models_to_try = ["gemini-2.5-flash", "gpt-4o-mini", "gpt-3.5-turbo"]
    for model_name in models_to_try:
        try:
            response = ai_client.chat.completions.create(
                model=model_name,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": PROMPT_CATEGORIZE},
                    {"role": "user", "content": prompt}
                ],
                timeout=20
            )
            text = response.choices[0].message.content.strip()
            cleaned = _clean_json_from_markdown(text)
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                return data.get("category", "UNKNOWN"), data.get("subcategory", "UNKNOWN")
        except Exception as e:
            print(f"Ошибка AI при категоризации ({model_name}): {type(e).__name__}: {e}")
            continue
    return "UNKNOWN", "UNKNOWN"

def extract_transaction_with_ai(user_text):
    """
    Извлечение транзакций и свободный диалог с поддержкой каскада моделей.
    """
    models_to_try = ["gpt-3.5-turbo", "gpt-4o-mini", "gemini-2.5-flash"]
    for model_name in models_to_try:
        try:
            response = ai_client.chat.completions.create(
                model=model_name,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": PROMPT_EXTRACT},
                    {"role": "user", "content": user_text}
                ],
                timeout=20
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Ошибка AI при извлечении/общении ({model_name}): {type(e).__name__}: {e}")
            continue
    return None

extract_operations_with_ai = extract_transaction_with_ai

def transcribe_audio_with_ai(audio_url):
    """Распознавание голосовых сообщений через Whisper."""
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

# ====================================================================
# МУЛЬТИМОДАЛЬНОЕ СКАНИРОВАНИЕ ЧЕКОВ (VISION OCR)
# ====================================================================
def extract_receipt_total_with_ai(image_url):
    """
    Извлекает только итог чека и название магазина через мультимодальную модель.
    Поддерживает сохранение детализации, каскад моделей и прямой URL.
    """
    base64_uri = get_image_base64_uri(image_url)

    image_payloads = []
    if base64_uri:
        image_payloads.append({"type": "image_url", "image_url": {"url": base64_uri, "detail": "high"}})
    if image_url and str(image_url).startswith("http"):
        image_payloads.append({"type": "image_url", "image_url": {"url": image_url, "detail": "high"}})

    if not image_payloads:
        print("[RECEIPT] Не удалось подготовить фото чека для анализа итога.")
        return None

    models_to_try = [
        "gemini-2.5-flash",
        "claude-3-5-sonnet",
        "gpt-4o",
        "gpt-4o-mini"
    ]

    for img_item in image_payloads:
        for model_name in models_to_try:
            try:
                response = ai_client.chat.completions.create(
                    model=model_name,
                    temperature=0.0,
                    max_tokens=2048,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": PROMPT_RECEIPT_TOTAL},
                                img_item
                            ]
                        }
                    ],
                    timeout=45
                )
                res_text = response.choices[0].message.content
                if res_text and res_text.strip():
                    return res_text.strip()
            except Exception as e:
                print(f"[RECEIPT] Ошибка {model_name} при чтении итога чека: {e}")
                continue

    return None

def extract_receipt_items_with_ai(image_url):
    """
    Извлекает все товары из чека построчно через Vision-модель в высоком разрешении.
    Использует detail='high', каскад лучших Vision-моделей (Gemini 2.5 Flash / Claude 3.5 Sonnet / GPT-4o) и max_tokens=4096.
    """
    base64_uri = get_image_base64_uri(image_url)

    image_payloads = []
    if base64_uri:
        image_payloads.append({"type": "image_url", "image_url": {"url": base64_uri, "detail": "high"}})
    if image_url and str(image_url).startswith("http"):
        image_payloads.append({"type": "image_url", "image_url": {"url": image_url, "detail": "high"}})

    if not image_payloads:
        print("[RECEIPT] Не удалось подготовить фото чека для построчного разбора.")
        return None

    models_to_try = [
        "gemini-2.5-flash",
        "claude-3-5-sonnet",
        "gpt-4o",
        "gpt-4o-mini"
    ]

    for img_item in image_payloads:
        for model_name in models_to_try:
            try:
                response = ai_client.chat.completions.create(
                    model=model_name,
                    temperature=0.0,
                    max_tokens=4096,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": PROMPT_RECEIPT_ITEMS},
                                img_item
                            ]
                        }
                    ],
                    timeout=60
                )
                res_text = response.choices[0].message.content
                if res_text and res_text.strip():
                    return res_text.strip()
            except Exception as e:
                print(f"[RECEIPT] Ошибка {model_name} при чтении позиций чека: {e}")
                continue

    return None

def normalize_receipt_items_with_ai(raw_items_list):
    """
    Нормализация сырых строк чеков в базовые существительные с каскадом моделей.
    """
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
    prompt += '\nВерни СТРОГО JSON-объект в формате: {"Сырое название": "Очищенное существительное"}'

    models_to_try = ["gemini-2.5-flash", "gpt-4o-mini", "gpt-3.5-turbo"]
    for model_name in models_to_try:
        try:
            response = ai_client.chat.completions.create(
                model=model_name,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": "Ты нормализатор товаров в базовые существительные. Отвечай только валидным JSON."},
                    {"role": "user", "content": prompt}
                ],
                timeout=25
            )
            text = response.choices[0].message.content.strip()
            cleaned = _clean_json_from_markdown(text)
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return json.loads(cleaned)
        except Exception as e:
            print(f"Ошибка нормализации брендов ({model_name}): {type(e).__name__}: {e}")
            continue
    return {}

def categorize_batch_with_ai(items_list, menu_str):
    """
    Пакетная классификация списка товаров по эталонному меню.
    Использует каскад моделей (gemini-2.5-flash, gpt-4o-mini) для идеального соблюдения JSON и точного маппинга.
    """
    prompt = f"Меню:\n{menu_str}\n\nОперации:\n"
    for item in items_list:
        orig = item.get('original_item') or item.get('item', '')
        amt = item.get('amount', 0)
        prompt += f"- {orig} ({amt} руб.)\n"

    models_to_try = ["gemini-2.5-flash", "gpt-4o-mini"]
    for model_name in models_to_try:
        try:
            response = ai_client.chat.completions.create(
                model=model_name,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": PROMPT_BATCH_CATEGORIZE},
                    {"role": "user", "content": prompt}
                ],
                timeout=30
            )
            text = response.choices[0].message.content.strip()
            cleaned = _clean_json_from_markdown(text)
            match = re.search(r'\[.*\]', cleaned, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return json.loads(cleaned)
        except Exception as e:
            print(f"Ошибка AI при пакетной категоризации ({model_name}): {type(e).__name__}: {e}")
            continue
    return []
