import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
from openai import OpenAI
import requests
import json

# ==========================================
# НАСТРОЙКИ (ВСТАВЬТЕ СВОИ ДАННЫЕ)
# ==========================================
VK_TOKEN = "vk1.a.Mvn90TUedTR7oGAliJvvGbsUvaxnmfjz8SRM7lvuJLbvfsfHK7kMfOB5YPIPSnEzNBqimGJhEyg1ap078WsZ75jXc4Uc1Bj3J1AnGHq_Ot0ZpeznNiYE2N5HUxNbv_5GjXrSZBzPc1GJ0cgj4PAyl6QlqHxjDzsPpAJZVNCsLQjLLaJTRtJmp-eg-t5zx_A0NFiWnQu-styq0N7A8api_w"
AI_TUNNEL_KEY = "sk-aitunnel-uR0sN0BlJhJNKC1IyNGLVFMvRw5Pv1Xw"
AI_BASE_URL = "https://api.aitunnel.ru/v1/" # Óòî÷íèòå URL â êàáèíåòå AITunnel
GOOGLE_SHEETS_URL = "https://script.google.com/macros/s/AKfycbyeFzUu2-u1N0bJBg9sL4olZOQnoUOciceXxEB9jGzfcrfZD07IYo-LyIP03nx-yAtV/exec"

# ==========================================
# ИНИЦИАЛИЗАЦИЯ
# ==========================================
# Подключаемся к ВК
vk_session = vk_api.VkApi(token=VK_TOKEN)
longpoll = VkLongPoll(vk_session)
vk = vk_session.get_api()

# Подключаемся к ИИ через AITunnel
ai_client = OpenAI(api_key=AI_TUNNEL_KEY, base_url=AI_BASE_URL)

# Системный промпт: объясняем ИИ, как он должен отвечать
SYSTEM_PROMPT = """
Ты — умный финансовый ассистент. Пользователь пишет тебе свои траты или доходы.
Твоя задача — извлечь данные и вернуть их СТРОГО в формате JSON, без лишнего текста.
Формат JSON:
{
  "item": "Название покупки/операции",
  "amount": 1500,
  "type": "Расход" (или "Доход"),
  "comment": "любой комментарий пользователя"
}
Если пользователь просто общается, отвечай обычным текстом (не JSON).
"""

def send_vk_message(user_id, text):
    """Функция отправки сообщения в ВК"""
    vk.messages.send(user_id=user_id, message=text, random_id=0)

def send_to_google_sheets(payload):
    """Функция отправки данных в нашу таблицу"""
    try:
        response = requests.post(GOOGLE_SHEETS_URL, json=payload)
        return response.json()
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

print("Бот успешно запущен и слушает ВК...")

# ==========================================
# ГЛАВНЫЙ ЦИКЛ БОТА
# ==========================================
for event in longpoll.listen():
    if event.type == VkEventType.MESSAGE_NEW and event.to_me:
        user_id = event.user_id
        user_text = event.text
        
        # Отправляем ИИ сообщение пользователя
        try:
            ai_response = ai_client.chat.completions.create(
                model="gpt-3.5-turbo", # Или gpt-4o-mini, в зависимости от AITunnel
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_text}
                ]
            )
            reply_text = ai_response.choices[0].message.content.strip()
            
            # Проверяем, вернул ли ИИ JSON (похоже ли это на транзакцию)
            if reply_text.startswith("{") and reply_text.endswith("}"):
                try:
                    # Распаковываем JSON от ИИ
                    transaction_data = json.loads(reply_text)
                    
                    # Отправляем пользователю сообщение, что начали обработку
                    send_vk_message(user_id, f"Записываю: {transaction_data['item']} на {transaction_data['amount']} руб...")
                    
                    # Отправляем в Google Таблицу
                    gs_response = send_to_google_sheets(transaction_data)
                    
                    # Обрабатываем ответ от таблицы
                    if gs_response.get("status") == "SUCCESS":
                        send_vk_message(user_id, "Успешно записано в таблицу!")
                    elif gs_response.get("status") == "SUCCESS_AUTO_ADDED":
                        send_vk_message(user_id, f"Записано! Автоматически определил категорию: {gs_response.get('recognized_cat')} -> {gs_response.get('recognized_sub')}")
                    elif gs_response.get("status") == "UNKNOWN_ITEM":
                        # Если таблица не знает слово, отправляем меню пользователю
                        send_vk_message(user_id, "Я не знаю эту статью. Скажи в двух словах хотя бы примерно что это.")
                        # В будущем здесь можно добавить логику кнопок (Inline Keyboards) ВК
                    else:
                        send_vk_message(user_id, f"Ошибка таблицы: {gs_response.get('message')}")
                        
                except json.JSONDecodeError:
                    send_vk_message(user_id, "Ошибка: ИИ вернул неправильный формат данных.")
            else:
                # Если ИИ вернул обычный текст (просто общение)
                send_vk_message(user_id, reply_text)
                
        except Exception as e:
            send_vk_message(user_id, "Ошибка связи с ИИ.")
            print(f"Ошибка: {e}")
