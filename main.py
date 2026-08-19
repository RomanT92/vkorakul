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

# ====================================================================
# 2. ПОДКЛЮЧЕНИЕ К СЕРВИСАМ
# ====================================================================
# Подключаемся к ВК от имени группы
vk_session = vk_api.VkApi(token=VK_TOKEN)
longpoll = VkLongPoll(vk_session)
vk = vk_session.get_api()

# Подключаемся к нейросети
ai_client = OpenAI(api_key=AI_TUNNEL_KEY, base_url=AI_BASE_URL)

# ====================================================================
# 3. ИНСТРУКЦИИ ДЛЯ НЕЙРОСЕТИ (ПРОМПТЫ)
# ====================================================================
# Промпт №1: Вытаскивает цифры и суть из сообщения (без выдумывания категорий)
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

# Промпт №2: Умный классификатор (выбирает категорию строго из меню)
PROMPT_CATEGORIZE = """
Ты — умный классификатор. Тебе дано название операции (и иногда пояснение от пользователя), а также СТРОГОЕ меню категорий.
Твоя задача — найти логичное совпадение в меню.
ПРАВИЛО 1: Если сомневаешься — возвращай "UNKNOWN".
ПРАВИЛО 2: Если это имя человека или сленг без пояснения — возвращай "UNKNOWN".
Формат ответа (только JSON):
{
  "category": "Выбранная категория",
  "subcategory": "Выбранная подкатегория"
}
"""

# ====================================================================
# 4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ====================================================================
def send_vk_message(user_id, text):
    """Отправляет текстовое сообщение пользователю в ВК"""
    vk.messages.send(user_id=user_id, message=text, random_id=0)

def send_to_google_sheets(payload):
    """Отправляет данные в Google Таблицу и возвращает ответ от нее"""
    try:
        response = requests.post(GOOGLE_SHEETS_URL, json=payload)
        try:
            return response.json()
        except Exception:
            # Если таблица упала с ошибкой и вернула HTML вместо JSON
            error_text = response.text[:300].replace('\n', ' ')
            return {"status": "ERROR", "message": f"Код {response.status_code}. Текст: {error_text}"}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

def categorize_with_ai(item, menu_str, context=""):
    """Просит ИИ выбрать категорию из меню (с учетом подсказки пользователя)"""
    prompt = f"Операция: {item}\n"
    if context:
        prompt += f"Пояснение пользователя: {context}\n"
    prompt += f"\nМеню:\n{menu_str}"
    
    try:
        response = ai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            temperature=0.0, # 0.0 отключает фантазию, делает ответы строгими
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
        print("Ошибка ИИ классификации:", e)
    return "UNKNOWN", "UNKNOWN"

print("Бот успешно запущен и слушает сообщения ВКонтакте...")

# Память бота (состояния пользователей: ждем ли мы от них ответа)
user_states = {}
MAX_ATTEMPTS = 5 # Сколько раз бот будет пытаться угадать по подсказкам

# ====================================================================
# 5. ГЛАВНЫЙ ЦИКЛ БОТА (БЕСКОНЕЧНОЕ ПРОСЛУШИВАНИЕ ВК)
# ====================================================================
for event in longpoll.listen():
    if event.type == VkEventType.MESSAGE_NEW and event.to_me:
        user_id = event.user_id
        user_text = event.text.strip()
        user_text_lower = user_text.lower()
        
        # ---------------------------------------------------------
        # СОСТОЯНИЕ 1: ЖДЕМ ПОДТВЕРЖДЕНИЯ (ИИ угадал, спрашивает Да/Нет)
        # ---------------------------------------------------------
        if user_id in user_states and user_states[user_id]["state"] == "confirm_category":
            if user_text_lower == "отмена":
                del user_states[user_id]
                send_vk_message(user_id, "❌ Операция отменена.")
                continue
                
            # Если пользователь подтвердил догадку ИИ
            if user_text_lower in ["да", "верно", "ага", "давай", "ок", "yes", "+"]:
                payload = user_states[user_id]["payload"]
                payload["category"] = user_states[user_id]["ai_cat"]
                payload["subcategory"] = user_states[user_id]["ai_sub"]
                
                send_vk_message(user_id, "⏳ Записываю...")
                gs_response = send_to_google_sheets(payload)
                if gs_response.get("status") == "SUCCESS":
                    send_vk_message(user_id, f"✅ Успешно записано и выучено!")
                else:
                    send_vk_message(user_id, f"❌ Ошибка таблицы: {gs_response.get('message')}")
                del user_states[user_id]
                
            # Если ИИ ошибся
            elif user_text_lower in ["нет", "неверно", "не", "no", "-"]:
                if user_states[user_id]["attempts"] < MAX_ATTEMPTS:
                    user_states[user_id]["state"] = "provide_context"
                    send_vk_message(user_id, f"Понял, ошибся 😔 (Попытка {user_states[user_id]['attempts']} из {MAX_ATTEMPTS})\nПодскажи другими словами, что это за операция?")
                else:
                    # Лимит исчерпан
                    user_states[user_id]["state"] = "manual_category"
                    menu = user_states[user_id]["menu"]
                    cats_list = "\n".join([f"• {k}" for k in menu.keys()])
                    msg = "🤷‍♂️ Я сдаюсь. Использованы все 5 попыток.\n\n"
                    msg += "Напиши, пожалуйста, точную категорию из списка через дефис (Категория - Подкатегория):\n\n"
                    msg += f"Доступные категории:\n{cats_list}"
                    send_vk_message(user_id, msg)
            else:
                send_vk_message(user_id, "Пожалуйста, ответь 'Да' или 'Нет' (или 'Отмена').")
            continue

        # ---------------------------------------------------------
        # СОСТОЯНИЕ 2: ЖДЕМ ПОДСКАЗКУ (Пользователь объясняет своими словами)
        # ---------------------------------------------------------
        if user_id in user_states and user_states[user_id]["state"] == "provide_context":
            if user_text_lower == "отмена":
                del user_states[user_id]
                send_vk_message(user_id, "❌ Операция отменена.")
                continue
                
            send_vk_message(user_id, "🧠 Думаю...")
            user_states[user_id]["attempts"] += 1 # Увеличиваем счетчик попыток
            
            payload = user_states[user_id]["payload"]
            menu = user_states[user_id]["menu"]
            menu_str = user_states[user_id]["menu_str"]
            
            # Снова просим ИИ угадать, но передаем ему подсказку пользователя
            ai_cat, ai_sub = categorize_with_ai(payload["item"], menu_str, context=user_text)
            
            if ai_cat in menu and ai_sub in menu[ai_cat]:
                # ИИ нашел вариант! Снова просим подтвердить
                user_states[user_id]["state"] = "confirm_category"
                user_states[user_id]["ai_cat"] = ai_cat
                user_states[user_id]["ai_sub"] = ai_sub
                send_vk_message(user_id, f"Ага! С учетом подсказки, думаю это:\n📂 {ai_cat} -> {ai_sub}\n\nВсё верно? (Да/Нет)")
            else:
                # ИИ снова не понял
                if user_states[user_id]["attempts"] < MAX_ATTEMPTS:
                    send_vk_message(user_id, f"Всё равно не могу сообразить 🤔 (Попытка {user_states[user_id]['attempts']} из {MAX_ATTEMPTS})\nПопробуй объяснить чуть подробнее или другими словами?")
                else:
                    user_states[user_id]["state"] = "manual_category"
                    cats_list = "\n".join([f"• {k}" for k in menu.keys()])
                    msg = "🤷‍♂️ Я сдаюсь. Использованы все 5 попыток.\n\n"
                    msg += "Напиши, пожалуйста, точную категорию из списка через дефис (Категория - Подкатегория):\n\n"
                    msg += f"Доступные категории:\n{cats_list}"
                    send_vk_message(user_id, msg)
            continue

        # ---------------------------------------------------------
        # СОСТОЯНИЕ 3: РУЧНОЙ ВВОД (Если ИИ так и не справился)
        # ---------------------------------------------------------
        if user_id in user_states and user_states[user_id]["state"] == "manual_category":
            if user_text_lower == "отмена":
                del user_states[user_id]
                send_vk_message(user_id, "❌ Операция отменена.")
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
                send_vk_message(user_id, "⚠️ Напиши через дефис. Пример: Транспорт - Такси\nИли напиши 'Отмена'.")
            continue

        # ---------------------------------------------------------
        # ОБЫЧНЫЙ РЕЖИМ: ПОЛЬЗОВАТЕЛЬ ПРИСЛАЛ НОВУЮ ТРАТУ/ДОХОД
        # ---------------------------------------------------------
        try:
            # 1. Извлекаем данные
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
                    
                    # БРОНЯ: удаляем категории, если ИИ их выдумал вопреки запрету
                    transaction_data.pop("category", None)
                    transaction_data.pop("subcategory", None)
                    
                    send_vk_message(user_id, f"⏳ Ищу '{transaction_data['item']}' в базах...")
                    
                    # 2. Ищем в Google Таблице
                    gs_response = send_to_google_sheets(transaction_data)
                    
                    if gs_response.get("status") == "SUCCESS":
                        send_vk_message(user_id, "✅ Успешно записано!")
                        
                    elif gs_response.get("status") == "SUCCESS_AUTO_ADDED":
                        send_vk_message(user_id, f"✅ Записано!\nНашел в Глобальной базе: {gs_response.get('recognized_cat')} -> {gs_response.get('recognized_sub')}")
                    
                    # 3. Слово не найдено. Подключаем классификатор
                    elif gs_response.get("status") == "UNKNOWN_ITEM":
                        menu = gs_response.get("available_menu", {})
                        menu_str = ""
                        for c, subs in menu.items():
                            menu_str += f"{c}: {', '.join(subs)}\n"
                            
                        # Просим ИИ угадать категорию
                        ai_cat, ai_sub = categorize_with_ai(transaction_data['item'], menu_str)
                        
                        if ai_cat in menu and ai_sub in menu[ai_cat]:
                            # ИИ угадал! Спрашиваем подтверждение
                            user_states[user_id] = {
                                "state": "confirm_category",
                                "payload": transaction_data,
                                "menu": menu,
                                "menu_str": menu_str,
                                "ai_cat": ai_cat,
                                "ai_sub": ai_sub,
                                "attempts": 1
                            }
                            send_vk_message(user_id, f"🤖 Думаю, '{transaction_data['item']}' относится к:\n📂 {ai_cat} -> {ai_sub}\n\nВсё верно? (Да/Нет)")
                        else:
                            # ИИ не смог угадать. Просим контекст.
                            user_states[user_id] = {
                                "state": "provide_context",
                                "payload": transaction_data,
                                "menu": menu,
                                "menu_str": menu_str,
                                "attempts": 1
                            }
                            send_vk_message(user_id, f"🤔 Я пока не знаю статью '{transaction_data['item']}'.\nПодскажи буквально в двух словах, что это за трата/доход?")
                    else:
                        send_vk_message(user_id, f"❌ Ошибка таблицы: {gs_response.get('message')}")
                        
                except json.JSONDecodeError:
                    send_vk_message(user_id, "❌ Ошибка: ИИ вернул неправильный формат.")
            else:
                # Если это не финансы, а просто общение
                send_vk_message(user_id, reply_text)
                
        except Exception as e:
            send_vk_message(user_id, "❌ Ошибка связи с ИИ.")
            print(f"Ошибка: {e}")
