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
# Промпт №1: ИИ читает сообщение пользователя и достает только суть (цифры и название)
PROMPT_EXTRACT = """
Ты — умный финансовый ассистент. Пользователь пишет тебе свои траты или доходы.
Твоя задача — извлечь данные и вернуть их СТРОГО в формате JSON.
Формат JSON:
{
  "item": "Название покупки/операции (коротко, 1-2 слова)",
  "amount": 1500,
  "type": "Расход" (или "Доход"),
  "comment": "комментарий"
}
СТРОГОЕ ПРАВИЛО: НИКОГДА не добавляй поля "category" или "subcategory".
"""

# Промпт №2: ИИ пытается угадать категорию из нашего готового меню
PROMPT_CATEGORIZE = """
Ты — строгий классификатор. Тебе дано название операции и СТРОГОЕ меню доступных категорий и подкатегорий.
Твоя задача — выбрать наиболее подходящую Категорию и Подкатегорию ИЗ ПРЕДОСТАВЛЕННОГО МЕНЮ.
Если ни одна не подходит, или ты сомневаешься, верни "UNKNOWN".
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

# ==========================================
# 4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def send_vk_message(user_id, text):
    """Отправляет текстовое сообщение пользователю в ВК"""
    vk.messages.send(user_id=user_id, message=text, random_id=0)

def send_to_google_sheets(payload):
    """Отправляет данные в Google Таблицу и возвращает ответ от нее"""
    try:
        response = requests.post(GOOGLE_SHEETS_URL, json=payload)
        return response.json()
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

print("Бот успешно запущен и слушает сообщения ВКонтакте...")

# Словарь для запоминания пользователей, которые сейчас находятся в режиме "Обучения"
user_states = {}

# ==========================================
# 5. ГЛАВНЫЙ ЦИКЛ БОТА (БЕСКОНЕЧНОЕ ПРОСЛУШИВАНИЕ)
# ==========================================
for event in longpoll.listen():
    # Если пришло новое сообщение и оно адресовано боту
    if event.type == VkEventType.MESSAGE_NEW and event.to_me:
        user_id = event.user_id
        user_text = event.text
        
        # ---------------------------------------------------------
        # БЛОК А: РЕЖИМ РУЧНОГО ОБУЧЕНИЯ (Ждем ответ от человека)
        # ---------------------------------------------------------
        # Если бот ранее спросил пользователя "Куда это записать?"
        if user_id in user_states and user_states[user_id]["state"] == "waiting_for_category":
            # Пользователь может передумать
            if user_text.lower() == "отмена":
                del user_states[user_id]
                send_vk_message(user_id, "❌ Добавление отменено.")
                continue

            # Разделяем текст по дефису (ожидаем "Категория - Подкатегория")
            parts = user_text.split("-")
            if len(parts) >= 2:
                cat = parts[0].strip()
                sub = parts[1].strip()
                
                # Достаем операцию из памяти бота и добавляем в нее выбранные категории
                payload = user_states[user_id]["payload"]
                payload["category"] = cat
                payload["subcategory"] = sub
                
                send_vk_message(user_id, "⏳ Обучаюсь и записываю...")
                
                # Отправляем в Таблицу (сценарий обучения)
                gs_response = send_to_google_sheets(payload)
                
                if gs_response.get("status") == "SUCCESS":
                    send_vk_message(user_id, f"✅ Успешно! Я запомнил, что '{payload['item']}' — это {cat} -> {sub}.")
                else:
                    send_vk_message(user_id, f"❌ Ошибка: {gs_response.get('message')}")
                
                # Удаляем пользователя из режима обучения
                del user_states[user_id]
            else:
                send_vk_message(user_id, "⚠️ Пожалуйста, напиши через дефис. Пример: Транспорт - Такси\nИли напиши 'Отмена'.")
            continue

        # ---------------------------------------------------------
        # БЛОК Б: ОБЫЧНЫЙ РЕЖИМ (Обработка новой траты/дохода)
        # ---------------------------------------------------------
        try:
            # ШАГ 1: Просим ИИ достать суть из текста
            ai_extract = ai_client.chat.completions.create(
                model="gpt-3.5-turbo", # Если AITunnel поддерживает gpt-4o-mini, лучше использовать его (он умнее и дешевле)
                messages=[
                    {"role": "system", "content": PROMPT_EXTRACT},
                    {"role": "user", "content": user_text}
                ]
            )
            reply_text = ai_extract.choices[0].message.content.strip()
            
            # Проверяем, вернул ли ИИ JSON (значит он распознал финансы)
            if reply_text.startswith("{") and reply_text.endswith("}"):
                try:
                    transaction_data = json.loads(reply_text)
                    # БРОНЯ: Удаляем категории, если ИИ их выдумал вопреки запрету
                    transaction_data.pop("category", None)
                    transaction_data.pop("subcategory", None)
                    
                    send_vk_message(user_id, f"⏳ Ищу '{transaction_data['item']}' в базах...")
                    
                    # ШАГ 2: Отправляем запрос в Таблицу для поиска по базам
                    gs_response = send_to_google_sheets(transaction_data)
                    
                    # Таблица нашла точное совпадение в Личной базе
                    if gs_response.get("status") == "SUCCESS":
                        send_vk_message(user_id, "✅ Успешно записано!")
                        
                    # Таблица нашла совпадение в Глобальной базе и скопировала себе
                    elif gs_response.get("status") == "SUCCESS_AUTO_ADDED":
                        send_vk_message(user_id, f"✅ Записано!\nНашел в Глобальной базе: {gs_response.get('recognized_cat')} -> {gs_response.get('recognized_sub')}")
                    
                    # ШАГ 3: Таблица не знает слово. Подключаем ИИ-классификатор!
                    elif gs_response.get("status") == "UNKNOWN_ITEM":
                        menu = gs_response.get("available_menu", {})
                        
                        # Формируем красивое текстовое меню для ИИ
                        menu_str = ""
                        for c, subs in menu.items():
                            menu_str += f"{c}: {', '.join(subs)}\n"
                            
                        send_vk_message(user_id, "🧠 Слово новое. Думаю, куда его отнести...")
                        
                        # Просим ИИ выбрать категорию из меню
                        ai_cat_response = ai_client.chat.completions.create(
                            model="gpt-3.5-turbo",
                            messages=[
                                {"role": "system", "content": PROMPT_CATEGORIZE},
                                {"role": "user", "content": f"Операция: {transaction_data['item']}\n\nМеню:\n{menu_str}"}
                            ]
                        )
                        
                        ai_cat_text = ai_cat_response.choices[0].message.content.strip()
                        ai_success = False
                        
                        # Если ИИ сделал выбор
                        if ai_cat_text.startswith("{") and ai_cat_text.endswith("}"):
                            cat_json = json.loads(ai_cat_text)
                            ai_cat = cat_json.get("category", "UNKNOWN")
                            ai_sub = cat_json.get("subcategory", "UNKNOWN")
                            
                            # ЖЕСТКАЯ ПРОВЕРКА: ИИ не соврал, и такие категории реально есть в меню
                            if ai_cat in menu and ai_sub in menu[ai_cat]:
                                transaction_data["category"] = ai_cat
                                transaction_data["subcategory"] = ai_sub
                                
                                # Отправляем готовое решение в таблицу для записи и обучения
                                gs_res_2 = send_to_google_sheets(transaction_data)
                                if gs_res_2.get("status") == "SUCCESS":
                                    send_vk_message(user_id, f"🤖 ИИ автоматически отнес '{transaction_data['item']}' к '{ai_cat} -> {ai_sub}'.\nЗаписано и выучено!")
                                    ai_success = True
                        
                        # ШАГ 4: Если ИИ не справился (вернул UNKNOWN или выдумал категорию)
                        if not ai_success:
                            # Показываем меню человеку
                            cats_list = "\n".join([f"• {k}" for k in menu.keys()])
                            
                            # Переводим пользователя в режим обучения
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
                # Если ИИ решил, что это не финансы, а просто разговор (вернул обычный текст)
                send_vk_message(user_id, reply_text)
                
        except Exception as e:
            send_vk_message(user_id, "❌ Ошибка связи с ИИ.")
            print(f"Ошибка: {e}")
