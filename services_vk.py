# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import requests

# ====================================================================
# АВТОУСТАНОВКА БИБЛИОТЕК (Хак для Bothost)
# ====================================================================
try:
    import pandas as pd
    from PIL import Image
except ImportError:
    print("Библиотеки не найдены. Запускаю автоустановку...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pandas", "openpyxl", "pillow"])
    print("Установка завершена! Перезапускаю скрипт...")
    os.execv(sys.executable, [sys.executable] + sys.argv)

import vk_api
from vk_api.longpoll import VkLongPoll
from config import VK_TOKEN, GOOGLE_SHEETS_URL

# ====================================================================
# ИНИЦИАЛИЗАЦИЯ КЛИЕНТА ВК
# ====================================================================
vk_session = vk_api.VkApi(token=VK_TOKEN, api_version='5.131')
longpoll = VkLongPoll(vk_session)
vk = vk_session.get_api()

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
# АВТОМАТИЧЕСКАЯ ТЕЛЕМЕТРИЯ И WATCHDOG (АДМИНКА + ТАБЛИЦА)
# ====================================================================
def send_heartbeat():
    """
    Отправляет ежеминутный сигнал активности:
    1. В локальную FastAPI веб-админку на порт 3000 (/api/heartbeat) мгновенно.
    2. В Google Таблицу (если указан GOOGLE_SHEETS_URL) с изолированным перехватом.
    """
    local_port = int(os.environ.get("PORT", 3000))
    local_url = f"http://127.0.0.1:{local_port}/api/heartbeat"
    local_result = {"status": "SUCCESS"}

    # 1. Отправка в локальную админку (быстрый таймаут 1.5с)
    try:
        resp = requests.post(local_url, json={"bot_version": "6.5.0"}, timeout=1.5)
        if resp.status_code == 200:
            local_result = resp.json()
    except Exception:
        pass

    # 2. Дублирование в Google Таблицу (с защитой от зависания цикла бота)
    if GOOGLE_SHEETS_URL:
        try:
            response = requests.post(GOOGLE_SHEETS_URL, json={"action": "heartbeat"}, timeout=5)
            return response.json()
        except Exception as e:
            print(f"[WATCHDOG] Ошибка отправки сигнала активности в таблицу: {e}")
            return {"status": "ERROR", "message": str(e)}

    return local_result

def report_module_health(module_num: int, status: str = "В строю", error_details: str = ""):
    """
    Отправляет статус модуля (№1-27):
    1. В локальную FastAPI веб-админку (/api/module_status).
    2. В Google Таблицу (если указан GOOGLE_SHEETS_URL).
    """
    local_port = int(os.environ.get("PORT", 3000))
    local_url = f"http://127.0.0.1:{local_port}/api/module_status"
    err_str = str(error_details)[:300] if error_details else ""

    # 1. Отправка в локальную админку (быстрый таймаут 1.5с)
    try:
        requests.post(
            local_url,
            json={
                "module_num": module_num,
                "status": status,
                "error_details": err_str
            },
            timeout=1.5
        )
    except Exception:
        pass

    # 2. Дублирование в Google Таблицу
    if GOOGLE_SHEETS_URL:
        payload = {
            "action": "update_module_status",
            "module_num": module_num,
            "status": status,
            "error": err_str
        }
        try:
            response = requests.post(GOOGLE_SHEETS_URL, json=payload, timeout=5)
            return response.json()
        except Exception as e:
            print(f"Ошибка отправки статуса модуля №{module_num} в таблицу: {e}")
            return {"status": "ERROR"}

    return {"status": "SUCCESS"}
