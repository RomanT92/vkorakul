# -*- coding: utf-8 -*-
# ====================================================================
# ИМПОРТ БИБЛИОТЕК
# ====================================================================
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
from openai import OpenAI
import requests
import json

# ====================================================================
# 1. НАСТРОЙКИ (КЛЮЧИ ДОСТУПА)
# ====================================================================
VK_TOKEN = "vk1.a.Mvn90TUedTR7oGAliJvvGbsUvaxnmfjz8SRM7lvuJLbvfsfHK7kMfOB5YPIPSnEzNBqimGJhEyg1ap078WsZ75jXc4Uc1Bj3J1AnGHq_Ot0ZpeznNiYE2N5HUxNbv_5GjXrSZBzPc1GJ0cgj4PAyl6QlqHxjDzsPpAJZVNCsLQjLLaJTRtJmp-eg-t5zx_A0NFiWnQu-styq0N7A8api_w"
AI_TUNNEL_KEY = "sk-aitunnel-uR0sN0BlJhJNKC1IyNGLVFMvRw5Pv1Xw"
GOOGLE_SHEETS_URL = "https://script.google.com/macros/s/AKfycbyeFzUu2-u1N0bJBg9sL4olZOQnoUOciceXxEB9jGzfcrfZD07IYo-LyIP03nx-yAtV/exec"
AI_BASE_URL = "https://api.aitunnel.ru/v1/"

# ИЗМЕНЕНИЕ: Жестко фиксируем версию API ВК для поддержки кнопок
vk_session = vk_api.VkApi(token=VK_TOKEN, api_version='5.131')
longpoll = VkLongPoll(vk_session)
vk = vk_session.get_api()
ai_client = OpenAI(api_key=AI_TUNNEL_KEY, base_url=AI_BASE_URL)

# ====================================================================
# 2. ПРОМПТЫ (ИНСТРУКЦИИ ДЛЯ НЕЙРОСЕТИ)
# ====================================================================
PROMPT_EXTRACT = """
Ты — строгий финансовый робот. Пользователь пишет траты (расходы) или поступления (доходы/приходы). 
Извлеки данные и верни СТРОГО в формате JSON.
{
  "item": "Название покупки или источник дохода",
  "amount": 1500,
  "type": "Расход" (или "Доход"),
  "comment": "остальные слова или пояснения"
}

ПРАВИЛА ДЛЯ ПОЛЯ "type":
1. По умолчанию всё считается как "Расход".
2. НО если в тексте есть слова: зарплата, аванс, премия, кэшбек, возврат, подарили, доход, приход, поступление, перевод мне, от (кого-то) — СТАВЬ "Доход"!

ПРАВИЛА ДЛЯ ПОЛЯ "item":
1. Уважай реальные слова и ИМЕНА! Если слово существует в языке или это имя (например: "Кате", "Маше", "такси", "Петру"), оставляй его ТОЧНО так. НЕ исправляй "Кате" на "Кафе"!
2. Исправляй ТОЛЬКО абсолютно очевидные опечатки несуществующих слов (например, "квфе" -> "кафе", "малако" -> "молоко").
3. НЕ пиши слова 'приход', 'расход' или 'доход' в название! Оставь поле пустым (""), если кроме суммы и слова "доход" ничего нет.
4. НИКОГДА не добавляй поля "category" или "subcategory".
"""

PROMPT_CATEGORIZE = """
Ты — умный финансовый классификатор. Тебе дано название операции и ПОДСКАЗКА от пользователя (синоним, объяснение или известное слово).
Твоя задача — опираясь на подсказку, найти наиболее подходящую категорию и подкатегорию ИСКЛЮЧИТЕЛЬНО из предоставленного меню.

ПРАВИЛА:
1. Если пользователь дал подсказку (например, "огурцы"), пойми, к какой категории из меню она относится (например, "Продукты - Овощи фрукты").
2. Ты ДОЛЖЕН использовать только те Категории и Подкатегории, которые есть в тексте Меню. Никакой отсебятины!
3. Копируй названия Категории и Подкатегории символ в символ.
4. Если совершенно непонятно — возвращай "UNKNOWN".

Формат ответа (только JSON):
{
  "category": "Точное название категории из меню",
  "subcategory": "Точное название подкатегории из меню"
}
"""

# ====================================================================
# 3. ГЕНЕРАТОРЫ КЛАВИАТУР (КНОПОК)
# ====================================================================
def get_main_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Разобрать завалы', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Создать категорию', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('Помощь', color=VkKeyboardColor.SECONDARY)
    return keyboard

def get_yes_no_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Да', color=VkKeyboardColor.POSITIVE)
    keyboard.add_button('Нет', color=VkKeyboardColor.NEGATIVE)
    keyboard.add_line()
    keyboard.add_button('Отмена', color=VkKeyboardColor.SECONDARY)
    return keyboard

def type_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Расход', color=VkKeyboardColor.NEGATIVE)
    keyboard.add_button('Доход', color=VkKeyboardColor.POSITIVE)
    keyboard.add_line()
    keyboard.add_button('Отмена', color=VkKeyboardColor.SECONDARY)
    return keyboard

def get_cancel_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard

# ====================================================================
# 4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ====================================================================
def send_vk_message(user_id, text, keyboard=None):
    """
    ИЗМЕНЕНИЕ: Бронебойная отправка сообщений. 
    Если ВК запрещает клавиатуру, бот не падает, а отправляет текст без неё.
    """
    try:
        post = {'user_id': user_id, 'message': text, 'random_id': 0}
        if keyboard is not None:
            post['keyboard'] = keyboard.get_keyboard()
        vk.messages.send(**post)
    except Exception as e:
        print(f"Ошибка отправки сообщения (возможно из-за кнопок): {e}")
        try:
            # Пробуем отправить просто текст, если клавиатура вызвала ошибку
            vk.messages.send(user_id=user_id, message=text, random_id=0)
        except Exception as e2:
            print(f"Критическая ошибка отправки: {e2}")

def send_to_google_sheets(payload):
    try:
        response = requests.post(GOOGLE_SHEETS_URL, json=payload)
        try:
            return response.json()
        except Exception:
            error_text = response.text[:300].replace('\n', ' ')
            return {"status": "ERROR", "message": f"Код {response.status_code}. Текст: {error_text}"}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

def categorize_with_ai(item, menu_str, context=""):
    prompt = f"Операция: {item}\n"
    if context:
        prompt += f"Подсказка пользователя: {context}\n"
    prompt += f"\nМеню:\n{menu_str}"
    try:
        response = ai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            temperature=0.0,
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

def process_next_in_queue(user_id):
    state_data = user_states[user_id]
    queue = state_data["queue"]
    
    if not queue:
        send_vk_message(user_id, "🎉 Ура! Все завалы разобраны! Журнал чист.", get_main_keyboard())
        del user_states[user_id]
        return
        
    current = queue[0]
    menu = state_data["menu"]
    menu_str = "\n".join([f"{c}: {', '.join(subs)}" for c, subs in menu.items()])
    
    send_vk_message(user_id, f"Осталось разобрать: {len(queue)} шт.\n🧠 Анализирую: '{current['original_item']}'...")
    ai_cat, ai_sub = categorize_with_ai(current['original_item'], menu_str)
    
    state_data["state"] = "queue_confirm"
    state_data["ai_cat"] = ai_cat
    state_data["ai_sub"] = ai_sub
    state_data["attempts"] = 0
    
    msg = f"📅 Дата: {current['date'][:10]}\n💰 Сумма: {current['amount']}\n🛒 Операция: {current['original_item']}\n\n🤖 ИИ думает, это:\n📂 {ai_cat} -> {ai_sub}\n\nВерно?"
    send_vk_message(user_id, msg, get_yes_no_keyboard())

print("Бот успешно запущен и слушает сообщения ВКонтакте...")

user_states = {}
MAX_ATTEMPTS = 5

# ====================================================================
# 5. ГЛАВНЫЙ ЦИКЛ БОТА
# ====================================================================
for event in longpoll.listen():
    if event.type == VkEventType.MESSAGE_NEW and event.to_me:
        user_id = event.user_id
        user_text = event.text.strip()
        user_text_lower = user_text.lower()

        if user_text_lower in ["помощь", "начать", "start"]:
            help_text = "🤖 Привет! Я твой финансовый Оракул.\n\n" \
                        "Просто напиши мне трату или доход, например:\n" \
                        "👉 Такси 500\n" \
                        "👉 Зарплата 50000\n" \
                        "👉 Продукты 1500 Пятерочка\n\n" \
                        "Используй кнопки ниже для удобства!"
            send_vk_message(user_id, help_text, get_main_keyboard())
            continue

        # =========================================================
        # БЛОК Г: РАЗБОР ИМПОРТА (ЗАВАЛОВ)
        # =========================================================
        if user_text_lower in ["разобрать", "разобрать импорт", "разобрать завалы"]:
            send_vk_message(user_id, "⏳ Запрашиваю список нераспознанных операций из Таблицы...")
            res = send_to_google_sheets({"action": "get_unverified"})
            
            if res.get("status") == "SUCCESS":
                unverified = res.get("data", [])
                if not unverified:
                    send_vk_message(user_id, "🎉 Всё чисто! Нераспознанных операций нет.", get_main_keyboard())
                else:
                    user_states[user_id] = {"state": "queue_process", "queue": unverified, "menu": res.get("available_menu", {})}
                    process_next_in_queue(user_id)
            else:
                send_vk_message(user_id, f"❌ Ошибка: {res.get('message')}", get_main_keyboard())
            continue

        if user_id in user_states and user_states[user_id].get("state") == "queue_confirm":
            if user_text_lower == "отмена":
                del user_states[user_id]
                send_vk_message(user_id, "❌ Разбор завалов остановлен.", get_main_keyboard())
                continue
                
            if user_text_lower in ["да", "верно", "ага", "давай", "ок", "yes", "+"]:
                current = user_states[user_id]["queue"][0]
                payload = {
                    "action": "resolve_unverified",
                    "original_item": current["original_item"],
                    "amount": current["amount"],
                    "type": current["type"],
                    "category": user_states[user_id]["ai_cat"],
                    "subcategory": user_states[user_id]["ai_sub"]
                }
                send_vk_message(user_id, "⏳ Записываю и обучаюсь...")
                send_to_google_sheets(payload)
                user_states[user_id]["queue"].pop(0)
                process_next_in_queue(user_id)
                continue
            elif user_text_lower in ["нет", "неверно", "не", "no", "-"]:
                user_states[user_id]["state"] = "queue_hint"
                send_vk_message(user_id, "Понял, ошибся. Подскажи другими словами, что это за операция?", get_cancel_keyboard())
                continue
            else:
                send_vk_message(user_id, "Пожалуйста, ответь 'Да' или 'Нет' (или 'Отмена').", get_yes_no_keyboard())
                continue

        if user_id in user_states and user_states[user_id].get("state") == "queue_hint":
            if user_text_lower == "отмена":
                del user_states[user_id]
                send_vk_message(user_id, "❌ Разбор завалов остановлен.", get_main_keyboard())
                continue
                
            send_vk_message(user_id, "🧠 Думаю...")
            current = user_states[user_id]["queue"][0]
            menu = user_states[user_id]["menu"]
            menu_str = "\n".join([f"{c}: {', '.join(subs)}" for c, subs in menu.items()])
            
            check_payload = {"action": "check_item", "item": user_text, "type": current.get("type", "Расход")}
            check_res = send_to_google_sheets(check_payload)
            
            if check_res.get("status") == "FOUND":
                user_states[user_id]["state"] = "queue_confirm"
                user_states[user_id]["ai_cat"] = check_res.get("cat")
                user_states[user_id]["ai_sub"] = check_res.get("sub")
                send_vk_message(user_id, f"Ага! Слово '{user_text}' мне знакомо.\n📂 {check_res.get('cat')} -> {check_res.get('sub')}\n\nВсё верно?", get_yes_no_keyboard())
                continue

            ai_cat, ai_sub = categorize_with_ai(current["original_item"], menu_str, context=user_text)
            if ai_cat in menu and ai_sub in menu[ai_cat]:
                user_states[user_id]["state"] = "queue_confirm"
                user_states[user_id]["ai_cat"] = ai_cat
                user_states[user_id]["ai_sub"] = ai_sub
                send_vk_message(user_id, f"Ага! С учетом подсказки, думаю это:\n📂 {ai_cat} -> {ai_sub}\n\nВсё верно?", get_yes_no_keyboard())
                continue
            else:
                user_states[user_id]["state"] = "queue_manual"
                cats_list = "\n".join([f"• {k}" for k in menu.keys()])
                send_vk_message(user_id, "🤷‍♂️ Я сдаюсь. Напиши точную категорию из списка через дефис:\n\n" + cats_list, get_cancel_keyboard())
                continue

        if user_id in user_states and user_states[user_id].get("state") == "queue_manual":
            if user_text_lower == "отмена":
                del user_states[user_id]
                send_vk_message(user_id, "❌ Разбор завалов остановлен.", get_main_keyboard())
                continue
                
            parts = user_text.split("-")
            if len(parts) >= 2:
                current = user_states[user_id]["queue"][0]
                payload = {
                    "action": "resolve_unverified",
                    "original_item": current["original_item"],
                    "amount": current["amount"],
                    "type": current["type"],
                    "category": parts[0].strip(),
                    "subcategory": parts[1].strip()
                }
                send_vk_message(user_id, "⏳ Записываю и обучаюсь...")
                send_to_google_sheets(payload)
                user_states[user_id]["queue"].pop(0)
                process_next_in_queue(user_id)
                continue
            else:
                send_vk_message(user_id, "⚠️ Напиши через дефис. Пример: Транспорт - Такси", get_cancel_keyboard())
                continue


        # =========================================================
        # БЛОК А: ИНТЕРАКТИВНОЕ СОЗДАНИЕ НОВОЙ КАТЕГОРИИ
        # =========================================================
        if user_id in user_states and user_states[user_id].get("state") == "create_cat_name":
            if user_text_lower == "отмена":
                del user_states[user_id]
                send_vk_message(user_id, "❌ Создание категории отменено.", get_main_keyboard())
                continue
                
            parts = user_text.split("-")
            if len(parts) >= 2:
                cat = parts[0].strip()
                sub = parts[1].strip()
                user_states[user_id]["new_cat"] = cat
                user_states[user_id]["new_sub"] = sub
                user_states[user_id]["state"] = "create_cat_type"
                send_vk_message(user_id, f"Отлично: 📂 {cat} -> {sub}.\n\nЭто будет категория для Расходов или Доходов?", type_keyboard())
            else:
                send_vk_message(user_id, "⚠️ Обязательно используй дефис. Пример: Хобби - Рыбалка", get_cancel_keyboard())
            continue

        if user_id in user_states and user_states[user_id].get("state") == "create_cat_type":
            if user_text_lower == "отмена":
                del user_states[user_id]
                send_vk_message(user_id, "❌ Создание категории отменено.", get_main_keyboard())
                continue
                
            cat_type = "Доход" if "доход" in user_text_lower or "приход" in user_text_lower else "Расход"
                
            payload = {
                "action": "add_subcategory",
                "category": user_states[user_id]["new_cat"],
                "subcategory": user_states[user_id]["new_sub"],
                "type": cat_type
            }
            
            send_vk_message(user_id, "⏳ Создаю структуру...")
            gs_response = send_to_google_sheets(payload)
            
            if gs_response.get("status") == "SUCCESS":
                send_vk_message(user_id, f"✅ Успешно! Категория '{payload['category']} -> {payload['subcategory']}' ({cat_type}) создана.\nТеперь можешь записывать в неё операции.", get_main_keyboard())
            else:
                send_vk_message(user_id, f"❌ Ошибка таблицы: {gs_response.get('message')}", get_main_keyboard())
                
            del user_states[user_id]
            continue

        if user_text_lower.startswith("создать категорию") or user_text_lower.startswith("новая категория"):
            clean_text = user_text_lower.replace("создать категорию", "").replace("новая категория", "").strip()
            
            if clean_text and "-" in clean_text:
                prefix_len = len("создать категорию") if user_text_lower.startswith("создать категорию") else len("новая категория")
                content = user_text[prefix_len:].strip()
                parts = content.split("-")
                
                cat = parts[0].strip()
                sub = parts[1].strip()
                user_states[user_id] = {
                    "state": "create_cat_type",
                    "new_cat": cat,
                    "new_sub": sub
                }
                send_vk_message(user_id, f"Отлично: 📂 {cat} -> {sub}.\n\nЭто будет категория для Расходов или Доходов?", type_keyboard())
                continue
            
            user_states[user_id] = {"state": "create_cat_name"}
            send_vk_message(user_id, "Создаем новую категорию! 📂\n\nНапиши название Категории и Подкатегории через дефис.\nПример: Хобби - Рыбалка", get_cancel_keyboard())
            continue


        # =========================================================
        # БЛОК Б: ОБУЧЕНИЕ И ПОДСКАЗКИ (ОДИНОЧНЫЕ ОПЕРАЦИИ)
        # =========================================================
        if user_id in user_states and user_states[user_id].get("state") == "confirm_category":
            if user_text_lower == "отмена":
                del user_states[user_id]
                send_vk_message(user_id, "❌ Операция отменена.", get_main_keyboard())
                continue
                
            if user_text_lower in ["да", "верно", "ага", "давай", "ок", "yes", "+"]:
                payload = user_states[user_id]["payload"]
                payload["category"] = user_states[user_id]["ai_cat"]
                payload["subcategory"] = user_states[user_id]["ai_sub"]
                
                send_vk_message(user_id, "⏳ Записываю...")
                gs_response = send_to_google_sheets(payload)
                
                if gs_response.get("status") == "SUCCESS":
                    send_vk_message(user_id, f"✅ Успешно записано и выучено!", get_main_keyboard())
                else:
                    send_vk_message(user_id, f"❌ Ошибка таблицы: {gs_response.get('message')}", get_main_keyboard())
                del user_states[user_id]
                continue
                
            elif user_text_lower in ["нет", "неверно", "не", "no", "-"]:
                if user_states[user_id]["attempts"] < MAX_ATTEMPTS:
                    user_states[user_id]["state"] = "provide_context"
                    send_vk_message(user_id, f"Понял, ошибся 😔 (Попытка {user_states[user_id]['attempts']} из {MAX_ATTEMPTS})\nПодскажи другими словами, что это за операция?", get_cancel_keyboard())
                else:
                    user_states[user_id]["state"] = "manual_category"
                    menu = user_states[user_id]["menu"]
                    cats_list = "\n".join([f"• {k}" for k in menu.keys()])
                    msg = "🤷‍♂️ Я сдаюсь. Использованы все 5 попыток.\n\nНапиши, пожалуйста, точную категорию из списка через дефис:\n\n" + cats_list
                    send_vk_message(user_id, msg, get_cancel_keyboard())
                continue
            else:
                send_vk_message(user_id, "Пожалуйста, используй кнопки 'Да', 'Нет' или 'Отмена'.", get_yes_no_keyboard())
                continue

        if user_id in user_states and user_states[user_id].get("state") == "provide_context":
            if user_text_lower == "отмена":
                del user_states[user_id]
                send_vk_message(user_id, "❌ Операция отменена.", get_main_keyboard())
                continue
                
            send_vk_message(user_id, "🧠 Думаю...")
            user_states[user_id]["attempts"] += 1
            payload = user_states[user_id]["payload"]
            menu = user_states[user_id]["menu"]
            menu_str = "\n".join([f"{c}: {', '.join(subs)}" for c, subs in menu.items()])
            
            check_payload = {"action": "check_item", "item": user_text, "type": payload.get("type", "Расход")}
            check_res = send_to_google_sheets(check_payload)
            
            if check_res.get("status") == "FOUND":
                ai_cat = check_res.get("cat")
                ai_sub = check_res.get("sub")
                user_states[user_id]["state"] = "confirm_category"
                user_states[user_id]["ai_cat"] = ai_cat
                user_states[user_id]["ai_sub"] = ai_sub
                send_vk_message(user_id, f"Ага! Слово '{user_text}' мне знакомо. Значит исходная операция относится к:\n📂 {ai_cat} -> {ai_sub}\n\nВсё верно?", get_yes_no_keyboard())
                continue

            ai_cat, ai_sub = categorize_with_ai(payload["item"], menu_str, context=user_text)
            
            if ai_cat in menu and ai_sub in menu[ai_cat]:
                user_states[user_id]["state"] = "confirm_category"
                user_states[user_id]["ai_cat"] = ai_cat
                user_states[user_id]["ai_sub"] = ai_sub
                send_vk_message(user_id, f"Ага! С учетом подсказки, думаю это:\n📂 {ai_cat} -> {ai_sub}\n\nВсё верно?", get_yes_no_keyboard())
                continue
            else:
                if user_states[user_id]["attempts"] < MAX_ATTEMPTS:
                    send_vk_message(user_id, f"Всё равно не могу сообразить 🤔 (Попытка {user_states[user_id]['attempts']} из {MAX_ATTEMPTS})\nПопробуй объяснить чуть подробнее или другими словами?", get_cancel_keyboard())
                else:
                    user_states[user_id]["state"] = "manual_category"
                    cats_list = "\n".join([f"• {k}" for k in menu.keys()])
                    send_vk_message(user_id, "🤷‍♂️ Я сдаюсь. Напиши точную категорию из списка через дефис:\n\n" + cats_list, get_cancel_keyboard())
                continue

        if user_id in user_states and user_states[user_id].get("state") == "manual_category":
            if user_text_lower == "отмена":
                del user_states[user_id]
                send_vk_message(user_id, "❌ Операция отменена.", get_main_keyboard())
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
                    send_vk_message(user_id, f"✅ Успешно! Я запомнил, что '{payload['item']}' — это {cat} -> {sub}.", get_main_keyboard())
                else:
                    send_vk_message(user_id, f"❌ Ошибка: {gs_response.get('message')}", get_main_keyboard())
                del user_states[user_id]
                continue
            else:
                send_vk_message(user_id, "⚠️ Напиши через дефис. Пример: Транспорт - Такси", get_cancel_keyboard())
                continue

        # =========================================================
        # БЛОК В: ОБЫЧНЫЙ РЕЖИМ (Обработка новой одиночной операции)
        # =========================================================
        try:
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
                    
                    if not transaction_data.get("item", "").strip():
                        if transaction_data.get("type") in ["Доход", "Приход"]:
                            transaction_data["item"] = "Поступление"
                        else:
                            transaction_data["item"] = "Трата"
                    
                    send_vk_message(user_id, f"⏳ Ищу '{transaction_data['item']}' в базах...")
                    
                    gs_response = send_to_google_sheets(transaction_data)
                    
                    if gs_response.get("status") == "SUCCESS":
                        send_vk_message(user_id, "✅ Успешно записано!", get_main_keyboard())
                    elif gs_response.get("status") == "SUCCESS_AUTO_ADDED":
                        send_vk_message(user_id, f"✅ Записано!\nНашел в Глобальной базе: {gs_response.get('recognized_cat')} -> {gs_response.get('recognized_sub')}", get_main_keyboard())
                    elif gs_response.get("status") == "UNKNOWN_ITEM":
                        menu = gs_response.get("available_menu", {})
                        menu_str = ""
                        for c, subs in menu.items():
                            menu_str += f"{c}: {', '.join(subs)}\n"
                            
                        ai_cat, ai_sub = categorize_with_ai(transaction_data['item'], menu_str)
                        
                        if ai_cat in menu and ai_sub in menu[ai_cat]:
                            user_states[user_id] = {
                                "state": "confirm_category",
                                "payload": transaction_data,
                                "menu": menu,
                                "menu_str": menu_str,
                                "ai_cat": ai_cat,
                                "ai_sub": ai_sub,
                                "attempts": 1
                            }
                            send_vk_message(user_id, f"🤖 Думаю, '{transaction_data['item']}' относится к:\n📂 {ai_cat} -> {ai_sub}\n\nВсё верно?", get_yes_no_keyboard())
                        else:
                            user_states[user_id] = {
                                "state": "provide_context",
                                "payload": transaction_data,
                                "menu": menu,
                                "menu_str": menu_str,
                                "attempts": 1
                            }
                            send_vk_message(user_id, f"🤔 Я пока не знаю статью '{transaction_data['item']}'.\nПодскажи буквально в двух словах, что это за трата/доход?", get_cancel_keyboard())
                    else:
                        send_vk_message(user_id, f"❌ Ошибка таблицы: {gs_response.get('message')}", get_main_keyboard())
                except json.JSONDecodeError:
                    send_vk_message(user_id, "❌ Ошибка: ИИ вернул неправильный формат.", get_main_keyboard())
            else:
                # Обычное текстовое общение - просто выводим базовую клавиатуру
                send_vk_message(user_id, reply_text, get_main_keyboard())
                
        except Exception as e:
            send_vk_message(user_id, "❌ Ошибка связи с ИИ.", get_main_keyboard())
            print(f"Ошибка: {e}")
