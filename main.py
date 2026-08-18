# -*- coding: utf-8 -*-
# Импортируем нужные библиотеки
import vk_api # Для работы с ВКонтакте
from vk_api.longpoll import VkLongPoll, VkEventType # Для прослушивания новых сообщений
from openai import OpenAI # Для работы с ИИ (AITunnel использует библиотеку OpenAI)
import requests # Для отправки запросов в Google Таблицу
import json # Для работы с форматом данных JSON

# ==========================================
# НАСТРОЙКИ (ВСТАВЬТЕ СВОИ ДАННЫЕ)
# ==========================================
VK_TOKEN = "vk1.a.Mvn90TUedTR7oGAliJvvGbsUvaxnmfjz8SRM7lvuJLbvfsfHK7kMfOB5YPIPSnEzNBqimGJhEyg1ap078WsZ75jXc4Uc1Bj3J1AnGHq_Ot0ZpeznNiYE2N5HUxNbv_5GjXrSZBzPc1GJ0cgj4PAyl6QlqHxjDzsPpAJZVNCsLQjLLaJTRtJmp-eg-t5zx_A0NFiWnQu-styq0N7A8api_w"
AI_TUNNEL_KEY = "sk-aitunnel-uR0sN0BlJhJNKC1IyNGLVFMvRw5Pv1Xw"
AI_BASE_URL = "https://api.aitunnel.ru/v1/" # Óòî÷íèòå URL â êàáèíåòå AITunnel
GOOGLE_SHEETS_URL = "https://script.google.com/macros/s/AKfycbyeFzUu2-u1N0bJBg9sL4olZOQnoUOciceXxEB9jGzfcrfZD07IYo-LyIP03nx-yAtV/exec"

# ==========================================
# 2. ПОДКЛЮЧЕНИЕ К СЕРВИСАМ
# ==========================================
# Авторизуемся ВКонтакте
vk_session = vk_api.VkApi(token=VK_TOKEN)
longpoll = VkLongPoll(vk_session)
vk = vk_session.get_api()

# Авторизуемся в нейросети через AITunnel
ai_client = OpenAI(api_key=AI_TUNNEL_KEY, base_url=AI_BASE_URL)

# ==========================================
# 3. ИНСТРУКЦИИ ДЛЯ НЕЙРОСЕТИ (ПРОМПТЫ)
# ==========================================
PROMPT_EXTRACT = """
Ты — строгий финансовый робот. Пользователь пишет траты или доходы.
Извлеки данные и верни СТРОГО в формате JSON.
{
  "item": "Название покупки (1-2 слова)",
  "amount": 1500,
  "type": "Расход" (или "Доход"),
  "comment": "комментарий"
}
ПРАВИЛО: НИКОГДА не добавляй поля "category" или "subcategory".
"""

# ЖЕСТКИЙ ПРОМПТ ДЛЯ КЛАССИФИКАТОРА
PROMPT_CATEGORIZE = """
Ты — безэмоциональный робот-классификатор. Тебе дано название операции и СТРОГОЕ меню.
Твоя задача — найти 100% логичное совпадение в меню.
ПРАВИЛО 1: Если ты сомневаешься хотя бы на 1%, СРАЗУ возвращай "UNKNOWN".
ПРАВИЛО 2: НЕ ПЫТАЙСЯ УГАДАТЬ. Если это имя человека, непонятный набор букв или сленг — возвращай "UNKNOWN".
Формат ответа (только JSON):
{
  "category": "Выбранная категория",
  "subcategory": "Выбранная подкатегория"
}
Или если не уверен:
{
  "category": "UNKNOWN",
  "subcategory": "UNKNOWN"
}
"""

def send_vk_message(user_id, text):
    vk.messages.send(user_id=user_id, message=text, random_id=0)

def send_to_google_sheets(payload):
    try:
        response = requests.post(GOOGLE_SHEETS_URL, json=payload)
        return response.json()
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

print("Бот успешно запущен и слушает сообщения ВКонтакте...")

user_states = {}

for event in longpoll.listen():
    if event.type == VkEventType.MESSAGE_NEW and event.to_me:
        user_id = event.user_id
        user_text = event.text
        
        # --- РЕЖИМ РУЧНОГО ОБУЧЕНИЯ ---
        if user_id in user_states and user_states[user_id]["state"] == "waiting_for_category":
            if user_text.lower() == "отмена":
                del user_states[user_id]
                send_vk_message(user_id, "❌ Добавление отменено.")
                continue

            parts = user_text.split("-")
            if len(parts) >= 2:
                cat = parts[0].strip()
                sub = parts[1].strip()
                
                payload = user_states[user_id]["payload"]
                payload["category"] = cat
                payload["subcategory"] = sub
                
                send_vk_message(user_id, "⏳ Обучаюсь и записываю...")
                gs_response = send_to_google_sheets(payload)
                
                if gs_response.get("status") == "SUCCESS":
                    send_vk_message(user_id, f"✅ Успешно! Я запомнил, что '{payload['item']}' — это {cat} -> {sub}.")
                else:
                    send_vk_message(user_id, f"❌ Ошибка: {gs_response.get('message')}")
                
                del user_states[user_id]
            else:
                send_vk_message(user_id, "⚠️ Пожалуйста, напиши через дефис. Пример: Транспорт - Такси\nИли напиши 'Отмена'.")
            continue

        # --- ОБЫЧНЫЙ РЕЖИМ ---
        try:
            # ДОБАВЛЕН temperature=0.0 (Отключает фантазию ИИ)
            ai_extract = ai_client.chat.completions.create(
                model="gpt-3.5-turbo", 
                temperature=0.0,
                messages=[
                    {"role": "system", "content": PROMPT_EXTRACT},
                    {"role": "user", "content": user_text}
                ]
            )
            reply_text = ai_extract.choices[0].message.content.strip()
            
            if reply_text.startswith("{") and reply_text.endswith("}"):
                try:
                    transaction_data = json.loads(reply_text)
                    transaction_data.pop("category", None)
                    transaction_data.pop("subcategory", None)
                    
                    send_vk_message(user_id, f"⏳ Ищу '{transaction_data['item']}' в базах...")
                    gs_response = send_to_google_sheets(transaction_data)
                    
                    if gs_response.get("status") == "SUCCESS":
                        send_vk_message(user_id, "✅ Успешно записано!")
                    elif gs_response.get("status") == "SUCCESS_AUTO_ADDED":
                        send_vk_message(user_id, f"✅ Записано!\nНашел в Глобальной базе: {gs_response.get('recognized_cat')} -> {gs_response.get('recognized_sub')}")
                    
                    elif gs_response.get("status") == "UNKNOWN_ITEM":
                        menu = gs_response.get("available_menu", {})
                        menu_str = ""
                        for c, subs in menu.items():
                            menu_str += f"{c}: {', '.join(subs)}\n"
                            
                        send_vk_message(user_id, "🧠 Слово новое. Думаю, куда его отнести...")
                        
                        # ДОБАВЛЕН temperature=0.0 (Отключает фантазию классификатора)
                        ai_cat_response = ai_client.chat.completions.create(
                            model="gpt-3.5-turbo",
                            temperature=0.0,
                            messages=[
                                {"role": "system", "content": PROMPT_CATEGORIZE},
                                {"role": "user", "content": f"Операция: {transaction_data['item']}\n\nМеню:\n{menu_str}"}
                            ]
                        )
                        
                        ai_cat_text = ai_cat_response.choices[0].message.content.strip()
                        ai_success = False
                        
                        if ai_cat_text.startswith("{") and ai_cat_text.endswith("}"):
                            cat_json = json.loads(ai_cat_text)
                            ai_cat = cat_json.get("category", "UNKNOWN")
                            ai_sub = cat_json.get("subcategory", "UNKNOWN")
                            
                            if ai_cat in menu and ai_sub in menu[ai_cat]:
                                transaction_data["category"] = ai_cat
                                transaction_data["subcategory"] = ai_sub
                                
                                gs_res_2 = send_to_google_sheets(transaction_data)
                                if gs_res_2.get("status") == "SUCCESS":
                                    send_vk_message(user_id, f"🤖 ИИ автоматически отнес '{transaction_data['item']}' к '{ai_cat} -> {ai_sub}'.\nЗаписано и выучено!")
                                    ai_success = True
                        
                        if not ai_success:
                            cats_list = "\n".join([f"• {k}" for k in menu.keys()])
                            user_states[user_id] = {
                                "state": "waiting_for_category",
                                "payload": transaction_data
                            }
                            
                            msg = f"🤷‍♂️ Я и ИИ не уверены, куда отнести '{transaction_data['item']}'.\n\n"
                            msg += "Помоги мне! Напиши ответ в формате:\nКатегория - Подкатегория\n\n"
                            msg += f"Доступные категории:\n{cats_list}"
                            
                            send_vk_message(user_id, msg)
                    else:
                        send_vk_message(user_id, f"❌ Ошибка таблицы: {gs_response.get('message')}")
                        
                except json.JSONDecodeError:
                    send_vk_message(user_id, "❌ Ошибка: ИИ вернул неправильный формат.")
            else:
                send_vk_message(user_id, reply_text)
                
        except Exception as e:
            send_vk_message(user_id, "❌ Ошибка связи с ИИ.")
            print(f"Ошибка: {e}")
