# -*- coding: utf-8 -*-
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
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
1. Уважай реальные слова и ИМЕНА! НЕ исправляй "Кате" на "Кафе"!
2. Исправляй ТОЛЬКО абсолютно очевидные опечатки (например, "квфе" -> "кафе").
3. НЕ пиши слова 'приход', 'расход' или 'доход' в название! Оставь поле пустым (""), если кроме суммы и слова "доход" ничего нет.
4. НИКОГДА не добавляй поля "category" или "subcategory".
"""

PROMPT_CATEGORIZE = """
Ты — умный финансовый классификатор. Тебе дано название операции и ПОДСКАЗКА от пользователя.
Твоя задача — опираясь на подсказку, найти наиболее подходящую категорию и подкатегорию ИСКЛЮЧИТЕЛЬНО из предоставленного меню.
Формат ответа (только JSON):
{
  "category": "Точное название категории из меню",
  "subcategory": "Точное название подкатегории из меню"
}
"""

# ====================================================================
# 3. ГЕНЕРАТОРЫ КЛАВИАТУР (МНОГОУРОВНЕВОЕ МЕНЮ)
# ====================================================================
def get_main_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Разобрать завалы', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Категории и статьи', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('Помощь', color=VkKeyboardColor.SECONDARY)
    return keyboard

def get_crud_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Создать', color=VkKeyboardColor.POSITIVE)
    keyboard.add_button('Переименовать', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Удалить / перенести', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('Назад', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_del_move_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Удалить', color=VkKeyboardColor.NEGATIVE)
    keyboard.add_button('Перенести', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Назад', color=VkKeyboardColor.SECONDARY)
    return keyboard

def get_entity_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Категорию', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('Подкатегорию', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Статью', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Назад', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_move_entity_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Подкатегорию', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('Статью', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Назад', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_numbered_keyboard(count):
    keyboard = VkKeyboard(one_time=False)
    limit = min(count, 36)
    for i in range(1, limit + 1):
        keyboard.add_button(str(i), color=VkKeyboardColor.SECONDARY)
        if i % 4 == 0 and i != limit:
            keyboard.add_line()
    keyboard.add_line()
    keyboard.add_button('Отмена', color=VkKeyboardColor.NEGATIVE)
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
    try:
        post = {'user_id': user_id, 'message': text, 'random_id': 0}
        if keyboard is not None:
            post['keyboard'] = keyboard.get_keyboard()
        vk.messages.send(**post)
    except Exception as e:
        print(f"Ошибка отправки: {e}")
        try:
            vk.messages.send(user_id=user_id, message=text, random_id=0)
        except:
            pass

def send_to_google_sheets(payload):
    try:
        response = requests.post(GOOGLE_SHEETS_URL, json=payload)
        return response.json()
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
        pass
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

        # ---------------------------------------------------------
        # ЦЕНТРАЛИЗОВАННАЯ ОБРАБОТКА "НАЗАД", "ОТМЕНА" И БАЗОВЫХ КОМАНД
        # ---------------------------------------------------------
        if user_text_lower in ["помощь", "начать", "start", "отмена", "назад"]:
            state = user_states.get(user_id, {}).get("state", "")
            
            if user_text_lower in ["помощь", "начать", "start"]:
                if user_id in user_states: del user_states[user_id]
                help_text = "🤖 Привет! Я твой финансовый Оракул.\n\nПросто напиши мне трату или доход, например:\n👉 Такси 500\n👉 Зарплата 50000\n\nИспользуй кнопки меню для управления структурой!"
                send_vk_message(user_id, help_text, get_main_keyboard())
                continue
                
            if user_text_lower == "назад":
                if state in ["wait_entity_create", "wait_entity_rename", "wait_del_move_action"]:
                    user_states[user_id] = {"state": "menu_crud"}
                    send_vk_message(user_id, "Управление структурой. Что хотите сделать?", get_crud_keyboard())
                    continue
                elif state == "menu_crud":
                    if user_id in user_states: del user_states[user_id]
                    send_vk_message(user_id, "Главное меню.", get_main_keyboard())
                    continue
            
            # Глобальная отмена
            if user_id in user_states: del user_states[user_id]
            send_vk_message(user_id, "Действие отменено. Главное меню.", get_main_keyboard())
            continue

        # ---------------------------------------------------------
        # НАВИГАЦИЯ ПО МНОГОУРОВНЕВОМУ МЕНЮ
        # ---------------------------------------------------------
        if user_text_lower == "категории и статьи":
            user_states[user_id] = {"state": "menu_crud"}
            send_vk_message(user_id, "Управление структурой. Что хотите сделать?", get_crud_keyboard())
            continue

        state = user_states.get(user_id, {}).get("state", "")

        # Уровень 2: Выбор действия
        if state == "menu_crud":
            if user_text_lower == "создать":
                user_states[user_id]["state"] = "wait_entity_create"
                send_vk_message(user_id, "Что именно вы хотите создать?", get_entity_keyboard())
                continue
            elif user_text_lower == "переименовать":
                user_states[user_id]["state"] = "wait_entity_rename"
                send_vk_message(user_id, "Что именно вы хотите переименовать?", get_entity_keyboard())
                continue
            elif user_text_lower == "удалить / перенести":
                user_states[user_id]["state"] = "wait_del_move_action"
                send_vk_message(user_id, "Что вы хотите сделать?", get_del_move_keyboard())
                continue

        # ---------------------------------------------------------
        # ВЕТКА: УДАЛИТЬ ИЛИ ПЕРЕНЕСТИ
        # ---------------------------------------------------------
        if state == "wait_del_move_action":
            if user_text_lower == "удалить":
                user_states[user_id]["state"] = "delete_select_level"
                send_vk_message(user_id, "Что именно удалить?", get_entity_keyboard())
                continue
            elif user_text_lower == "перенести":
                user_states[user_id]["state"] = "move_select_level"
                send_vk_message(user_id, "Что именно перенести?", get_move_entity_keyboard())
                continue

        # --- УДАЛЕНИЕ ---
        if state == "delete_select_level":
            if user_text_lower in ["категорию", "подкатегорию", "статью"]:
                level_map = {"категорию": "category", "подкатегорию": "subcategory", "статью": "article"}
                user_states[user_id]["del_level"] = level_map[user_text_lower]
                user_states[user_id]["state"] = "delete_select_type"
                send_vk_message(user_id, "В Расходах или Доходах?", type_keyboard())
            continue

        if state == "delete_select_type":
            c_type = "Доход" if "доход" in user_text_lower else "Расход"
            send_vk_message(user_id, "⏳ Загружаю структуру...")
            res = send_to_google_sheets({"action": "get_full_menu"})
            if res.get("status") == "SUCCESS":
                menu = res.get("menu", {}).get(c_type, {})
                cats = list(menu.keys())
                cats.sort()
                user_states[user_id]["menu"] = menu
                user_states[user_id]["c_type"] = c_type
                user_states[user_id]["cats"] = cats
                user_states[user_id]["state"] = "delete_select_cat"
                msg = f"Выберите категорию ({c_type}):\n\n"
                for i, c in enumerate(cats): msg += f"{i+1}. {c}\n"
                send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
            continue

        if state == "delete_select_cat":
            if user_text.isdigit():
                idx = int(user_text) - 1
                cats = user_states[user_id]["cats"]
                if 0 <= idx < len(cats):
                    sel_cat = cats[idx]
                    user_states[user_id]["sel_cat"] = sel_cat
                    level = user_states[user_id]["del_level"]
                    
                    if level == "category":
                        user_states[user_id]["state"] = "delete_confirm"
                        send_vk_message(user_id, f"⚠️ Вы уверены, что хотите удалить КАТЕГОРИЮ '{sel_cat}' со всеми подкатегориями и статьями?\n\n(Она удалится из вашей личной таблицы, но останется в Глобальной)", get_yes_no_keyboard())
                    else:
                        subs = list(user_states[user_id]["menu"].get(sel_cat, {}).keys())
                        subs.sort()
                        user_states[user_id]["subs"] = subs
                        user_states[user_id]["state"] = "delete_select_sub"
                        msg = f"Выберите подкатегорию в '{sel_cat}':\n\n"
                        for i, s in enumerate(subs): msg += f"{i+1}. {s}\n"
                        send_vk_message(user_id, msg, get_numbered_keyboard(len(subs)))
            continue

        if state == "delete_select_sub":
            if user_text.isdigit():
                idx = int(user_text) - 1
                subs = user_states[user_id]["subs"]
                if 0 <= idx < len(subs):
                    sel_sub = subs[idx]
                    user_states[user_id]["sel_sub"] = sel_sub
                    level = user_states[user_id]["del_level"]
                    
                    if level == "subcategory":
                        user_states[user_id]["state"] = "delete_confirm"
                        send_vk_message(user_id, f"⚠️ Вы уверены, что хотите удалить ПОДКАТЕГОРИЮ '{sel_sub}' со всеми её статьями?", get_yes_no_keyboard())
                    else:
                        arts = user_states[user_id]["menu"][user_states[user_id]["sel_cat"]].get(sel_sub, [])
                        arts.sort()
                        user_states[user_id]["arts"] = arts
                        user_states[user_id]["state"] = "delete_select_art"
                        msg = f"Выберите статью в '{sel_sub}':\n\n"
                        for i, a in enumerate(arts): msg += f"{i+1}. {a}\n"
                        send_vk_message(user_id, msg, get_numbered_keyboard(len(arts)))
            continue

        if state == "delete_select_art":
            if user_text.isdigit():
                idx = int(user_text) - 1
                arts = user_states[user_id]["arts"]
                if 0 <= idx < len(arts):
                    sel_art = arts[idx]
                    user_states[user_id]["sel_art"] = sel_art
                    user_states[user_id]["state"] = "delete_confirm"
                    send_vk_message(user_id, f"⚠️ Вы уверены, что хотите удалить СТАТЬЮ '{sel_art}'?", get_yes_no_keyboard())
            continue

        if state == "delete_confirm":
            if user_text_lower in ["да", "верно", "ага", "yes", "+"]:
                payload = {
                    "action": "delete_entity",
                    "level": user_states[user_id]["del_level"],
                    "type": user_states[user_id]["c_type"],
                    "cat": user_states[user_id].get("sel_cat", ""),
                    "sub": user_states[user_id].get("sel_sub", ""),
                    "art": user_states[user_id].get("sel_art", "")
                }
                send_vk_message(user_id, "⏳ Удаляю...")
                send_to_google_sheets(payload)
                send_vk_message(user_id, "✅ Успешно удалено!", get_main_keyboard())
                del user_states[user_id]
            elif user_text_lower in ["нет", "неверно", "не", "no", "-"]:
                send_vk_message(user_id, "Удаление отменено.", get_main_keyboard())
                del user_states[user_id]
            continue

        # --- ПЕРЕНОС ---
        if state == "move_select_level":
            if user_text_lower in ["подкатегорию", "статью"]:
                level_map = {"подкатегорию": "subcategory", "статью": "article"}
                user_states[user_id]["move_level"] = level_map[user_text_lower]
                user_states[user_id]["state"] = "move_select_type"
                send_vk_message(user_id, "В Расходах или Доходах?", type_keyboard())
            continue

        if state == "move_select_type":
            c_type = "Доход" if "доход" in user_text_lower else "Расход"
            send_vk_message(user_id, "⏳ Загружаю структуру...")
            res = send_to_google_sheets({"action": "get_full_menu"})
            if res.get("status") == "SUCCESS":
                menu = res.get("menu", {}).get(c_type, {})
                cats = list(menu.keys())
                cats.sort()
                user_states[user_id]["menu"] = menu
                user_states[user_id]["c_type"] = c_type
                user_states[user_id]["cats"] = cats
                user_states[user_id]["state"] = "move_select_cat"
                msg = f"Выберите категорию ({c_type}):\n\n"
                for i, c in enumerate(cats): msg += f"{i+1}. {c}\n"
                send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
            continue

        if state == "move_select_cat":
            if user_text.isdigit():
                idx = int(user_text) - 1
                cats = user_states[user_id]["cats"]
                if 0 <= idx < len(cats):
                    sel_cat = cats[idx]
                    user_states[user_id]["sel_cat"] = sel_cat
                    subs = list(user_states[user_id]["menu"].get(sel_cat, {}).keys())
                    subs.sort()
                    user_states[user_id]["subs"] = subs
                    user_states[user_id]["state"] = "move_select_sub"
                    msg = f"Выберите подкатегорию в '{sel_cat}':\n\n"
                    for i, s in enumerate(subs): msg += f"{i+1}. {s}\n"
                    send_vk_message(user_id, msg, get_numbered_keyboard(len(subs)))
            continue

        if state == "move_select_sub":
            if user_text.isdigit():
                idx = int(user_text) - 1
                subs = user_states[user_id]["subs"]
                if 0 <= idx < len(subs):
                    sel_sub = subs[idx]
                    user_states[user_id]["sel_sub"] = sel_sub
                    level = user_states[user_id]["move_level"]
                    
                    if level == "subcategory":
                        user_states[user_id]["state"] = "move_target_parent"
                        cats = user_states[user_id]["cats"]
                        msg = f"В какую категорию перенести '{sel_sub}'?\n\n"
                        for i, c in enumerate(cats): msg += f"{i+1}. {c}\n"
                        send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
                    else:
                        arts = user_states[user_id]["menu"][user_states[user_id]["sel_cat"]].get(sel_sub, [])
                        arts.sort()
                        user_states[user_id]["arts"] = arts
                        user_states[user_id]["state"] = "move_select_art"
                        msg = f"Выберите статью в '{sel_sub}':\n\n"
                        for i, a in enumerate(arts): msg += f"{i+1}. {a}\n"
                        send_vk_message(user_id, msg, get_numbered_keyboard(len(arts)))
            continue

        if state == "move_select_art":
            if user_text.isdigit():
                idx = int(user_text) - 1
                arts = user_states[user_id]["arts"]
                if 0 <= idx < len(arts):
                    sel_art = arts[idx]
                    user_states[user_id]["sel_art"] = sel_art
                    user_states[user_id]["state"] = "move_target_parent"
                    subs = user_states[user_id]["subs"]
                    msg = f"В какую подкатегорию перенести статью '{sel_art}'?\n\n"
                    for i, s in enumerate(subs): msg += f"{i+1}. {s}\n"
                    send_vk_message(user_id, msg, get_numbered_keyboard(len(subs)))
            continue

        if state == "move_target_parent":
            if user_text.isdigit():
                level = user_states[user_id]["move_level"]
                targets = user_states[user_id]["cats"] if level == "subcategory" else user_states[user_id]["subs"]
                idx = int(user_text) - 1
                if 0 <= idx < len(targets):
                    new_parent = targets[idx]
                    payload = {
                        "action": "move_entity",
                        "level": level,
                        "type": user_states[user_id]["c_type"],
                        "cat": user_states[user_id]["sel_cat"],
                        "sub": user_states[user_id]["sel_sub"],
                        "art": user_states[user_id].get("sel_art", ""),
                        "new_parent": new_parent
                    }
                    send_vk_message(user_id, "⏳ Переношу...")
                    send_to_google_sheets(payload)
                    send_vk_message(user_id, "✅ Успешно перенесено!", get_main_keyboard())
                    del user_states[user_id]
            continue


        # ---------------------------------------------------------
        # ВЕТКА: СОЗДАТЬ
        # ---------------------------------------------------------
        if state == "wait_entity_create":
            if user_text_lower == "категорию":
                user_states[user_id] = {"state": "create_cat_type"}
                send_vk_message(user_id, "Это будет категория Расходов или Доходов?", type_keyboard())
                continue
            elif user_text_lower == "подкатегорию":
                user_states[user_id] = {"state": "create_sub_type"}
                send_vk_message(user_id, "Это будет подкатегория Расходов или Доходов?", type_keyboard())
                continue
            elif user_text_lower == "статью":
                user_states[user_id] = {"state": "create_art_type"}
                send_vk_message(user_id, "Это будет статья Расходов или Доходов?", type_keyboard())
                continue

        if state == "create_cat_type":
            c_type = "Доход" if "доход" in user_text_lower else "Расход"
            user_states[user_id]["c_type"] = c_type
            user_states[user_id]["state"] = "create_cat_name"
            send_vk_message(user_id, f"Выбран тип: {c_type}.\n\nВведите название НОВОЙ КАТЕГОРИИ:", get_cancel_keyboard())
            continue

        if state == "create_cat_name":
            user_states[user_id]["new_cat"] = user_text
            user_states[user_id]["state"] = "create_cat_subname"
            send_vk_message(user_id, f"Категория: {user_text}.\n\nТеперь введите название ПЕРВОЙ ПОДКАТЕГОРИИ для неё:", get_cancel_keyboard())
            continue

        if state == "create_cat_subname":
            new_sub = user_text
            c_type = user_states[user_id]["c_type"]
            new_cat = user_states[user_id]["new_cat"]
            payload = {"action": "add_subcategory", "type": c_type, "category": new_cat, "subcategory": new_sub}
            send_vk_message(user_id, "⏳ Создаю категорию и подкатегорию...")
            send_to_google_sheets(payload)
            send_vk_message(user_id, f"✅ Успешно! Создана категория '{new_cat} -> {new_sub}'.\nСтатьи-заглушки добавлены автоматически.", get_main_keyboard())
            del user_states[user_id]
            continue

        if state == "create_sub_type":
            c_type = "Доход" if "доход" in user_text_lower else "Расход"
            send_vk_message(user_id, "⏳ Загружаю список категорий...")
            res = send_to_google_sheets({"action": "get_full_menu"})
            if res.get("status") == "SUCCESS":
                menu = res.get("menu", {}).get(c_type, {})
                cats = list(menu.keys())
                cats.sort()
                if not cats:
                    send_vk_message(user_id, f"Категорий типа '{c_type}' пока нет. Сначала создайте категорию.", get_main_keyboard())
                    del user_states[user_id]
                    continue
                msg = f"Выберите категорию ({c_type}), в которую добавим подкатегорию:\n\n"
                for i, c in enumerate(cats):
                    msg += f"{i+1}. {c}\n"
                user_states[user_id] = {"state": "create_sub_catselect", "c_type": c_type, "cats": cats, "menu": menu}
                send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
            continue

        if state == "create_sub_catselect":
            if user_text.isdigit():
                idx = int(user_text) - 1
                cats = user_states[user_id].get("cats", [])
                if 0 <= idx < len(cats):
                    sel_cat = cats[idx]
                    user_states[user_id]["sel_cat"] = sel_cat
                    user_states[user_id]["state"] = "create_sub_name"
                    send_vk_message(user_id, f"Категория: {sel_cat}.\n\nВведите название НОВОЙ ПОДКАТЕГОРИИ:", get_cancel_keyboard())
            continue

        if state == "create_sub_name":
            new_sub = user_text
            c_type = user_states[user_id]["c_type"]
            sel_cat = user_states[user_id]["sel_cat"]
            payload = {"action": "add_subcategory", "type": c_type, "category": sel_cat, "subcategory": new_sub}
            send_vk_message(user_id, "⏳ Создаю подкатегорию...")
            send_to_google_sheets(payload)
            send_vk_message(user_id, f"✅ Успешно! Добавлена подкатегория '{sel_cat} -> {new_sub}'.\nСтатья-заглушка добавлена автоматически.", get_main_keyboard())
            del user_states[user_id]
            continue

        if state == "create_art_type":
            c_type = "Доход" if "доход" in user_text_lower else "Расход"
            send_vk_message(user_id, "⏳ Загружаю список категорий...")
            res = send_to_google_sheets({"action": "get_full_menu"})
            if res.get("status") == "SUCCESS":
                menu = res.get("menu", {}).get(c_type, {})
                cats = list(menu.keys())
                cats.sort()
                msg = f"Выберите категорию ({c_type}):\n\n"
                for i, c in enumerate(cats):
                    msg += f"{i+1}. {c}\n"
                user_states[user_id] = {"state": "create_art_catselect", "c_type": c_type, "cats": cats, "menu": res.get("menu", {})}
                send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
            continue

        if state == "create_art_catselect":
            if user_text.isdigit():
                idx = int(user_text) - 1
                cats = user_states[user_id].get("cats", [])
                if 0 <= idx < len(cats):
                    sel_cat = cats[idx]
                    c_type = user_states[user_id].get("c_type", "Расход")
                    
                    # --- ИСПРАВЛЕННЫЙ БЛОК БЕЗОПАСНОГО ИЗВЛЕЧЕНИЯ ---
                    full_menu = user_states[user_id].get("menu", {})
                    type_menu = full_menu.get(c_type, {}) if isinstance(full_menu, dict) else {}
                    subs_dict = type_menu.get(sel_cat, {}) if isinstance(type_menu, dict) else {}
                    
                    if isinstance(subs_dict, dict):
                        subs = list(subs_dict.keys())
                    else:
                        subs = []
                        
                    subs.sort()
                    
                    if not subs:
                        send_vk_message(user_id, f"В категории '{sel_cat}' пока нет подкатегорий. Сначала создайте её.", get_main_keyboard())
                        del user_states[user_id]
                        continue
                    # ------------------------------------------------

                    msg = f"Выберите подкатегорию в '{sel_cat}':\n\n"
                    for i, s in enumerate(subs):
                        msg += f"{i+1}. {s}\n"
                    user_states[user_id]["state"] = "create_art_subselect"
                    user_states[user_id]["sel_cat"] = sel_cat
                    user_states[user_id]["subs"] = subs
                    send_vk_message(user_id, msg, get_numbered_keyboard(len(subs)))
            continue

        if state == "create_art_subselect":
            if user_text.isdigit():
                idx = int(user_text) - 1
                subs = user_states[user_id].get("subs", [])
                if 0 <= idx < len(subs):
                    sel_sub = subs[idx]
                    user_states[user_id]["state"] = "create_art_name"
                    user_states[user_id]["sel_sub"] = sel_sub
                    send_vk_message(user_id, f"Отлично: {user_states[user_id]['sel_cat']} -> {sel_sub}.\n\nВведите название НОВОЙ СТАТЬИ:", get_cancel_keyboard())
            continue

        if state == "create_art_name":
            art_name = user_text
            payload = {
                "action": "add_article",
                "type": user_states[user_id]["c_type"],
                "category": user_states[user_id]["sel_cat"],
                "subcategory": user_states[user_id]["sel_sub"],
                "item": art_name
            }
            send_vk_message(user_id, "⏳ Добавляю статью в базу...")
            send_to_google_sheets(payload)
            send_vk_message(user_id, f"✅ Статья '{art_name}' успешно создана!", get_main_keyboard())
            del user_states[user_id]
            continue
        # ---------------------------------------------------------
        # ВЕТКА: ПЕРЕИМЕНОВАТЬ
        # ---------------------------------------------------------
        if state == "wait_entity_rename":
            if user_text_lower == "категорию":
                send_vk_message(user_id, "⏳ Загружаю список категорий...")
                res = send_to_google_sheets({"action": "get_full_menu"})
                if res.get("status") == "SUCCESS":
                    menu = res.get("menu", {})
                    cats = list(set(list(menu.get("Расход", {}).keys()) + list(menu.get("Доход", {}).keys())))
                    cats.sort()
                    if not cats:
                        send_vk_message(user_id, "Категорий пока нет.", get_main_keyboard())
                        continue
                    msg = "Какую категорию переименовать?\n\n"
                    for i, c in enumerate(cats): msg += f"{i+1}. {c}\n"
                    user_states[user_id] = {"state": "rename_cat_select", "cats": cats, "menu": menu}
                    send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
                continue
                
            elif user_text_lower == "подкатегорию":
                send_vk_message(user_id, "⏳ Загружаю список...")
                res = send_to_google_sheets({"action": "get_full_menu"})
                if res.get("status") == "SUCCESS":
                    menu = res.get("menu", {})
                    cats = list(set(list(menu.get("Расход", {}).keys()) + list(menu.get("Доход", {}).keys())))
                    cats.sort()
                    msg = "В какой категории находится подкатегория?\n\n"
                    for i, c in enumerate(cats): msg += f"{i+1}. {c}\n"
                    user_states[user_id] = {"state": "rename_sub_select_cat", "cats": cats, "menu": menu}
                    send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
                continue
                
            elif user_text_lower == "статью":
                send_vk_message(user_id, "⏳ Загружаю меню...")
                res = send_to_google_sheets({"action": "get_full_menu"})
                if res.get("status") == "SUCCESS":
                    user_states[user_id] = {"state": "rename_art_type", "menu": res.get("menu", {})}
                    send_vk_message(user_id, "Статья находится в Расходах или Доходах?", type_keyboard())
                continue

        if state == "rename_cat_select":
            if user_text.isdigit():
                idx = int(user_text) - 1
                cats = user_states[user_id]["cats"]
                if 0 <= idx < len(cats):
                    old_cat = cats[idx]
                    user_states[user_id]["state"] = "rename_cat_type"
                    user_states[user_id]["old_cat"] = old_cat
                    send_vk_message(user_id, f"Введите новое название для категории '{old_cat}':", get_cancel_keyboard())
                    continue

        if state == "rename_cat_type":
            new_cat = user_text
            old_cat = user_states[user_id]["old_cat"]
            send_vk_message(user_id, f"⏳ Переименовываю '{old_cat}' в '{new_cat}' во всех базах...")
            send_to_google_sheets({"action": "rename_category", "old_cat": old_cat, "new_cat": new_cat, "type": "Расход"})
            send_to_google_sheets({"action": "rename_category", "old_cat": old_cat, "new_cat": new_cat, "type": "Доход"})
            send_vk_message(user_id, "✅ Категория успешно переименована!", get_main_keyboard())
            del user_states[user_id]
            continue

        if state == "rename_sub_select_cat":
            if user_text.isdigit():
                idx = int(user_text) - 1
                cats = user_states[user_id]["cats"]
                if 0 <= idx < len(cats):
                    sel_cat = cats[idx]
                    menu = user_states[user_id]["menu"]
                    subs_exp = list(menu.get("Расход", {}).get(sel_cat, {}).keys())
                    subs_inc = list(menu.get("Доход", {}).get(sel_cat, {}).keys())
                    subs = list(set(subs_exp + subs_inc))
                    subs.sort()
                    if not subs:
                        send_vk_message(user_id, f"В категории '{sel_cat}' нет подкатегорий.", get_main_keyboard())
                        del user_states[user_id]
                        continue
                    msg = f"Какую подкатегорию в '{sel_cat}' переименовать?\n\n"
                    for i, s in enumerate(subs): msg += f"{i+1}. {s}\n"
                    user_states[user_id]["state"] = "rename_sub_select_sub"
                    user_states[user_id]["sel_cat"] = sel_cat
                    user_states[user_id]["subs"] = subs
                    send_vk_message(user_id, msg, get_numbered_keyboard(len(subs)))
                    continue

        if state == "rename_sub_select_sub":
            if user_text.isdigit():
                idx = int(user_text) - 1
                subs = user_states[user_id]["subs"]
                if 0 <= idx < len(subs):
                    old_sub = subs[idx]
                    user_states[user_id]["state"] = "rename_sub_type"
                    user_states[user_id]["old_sub"] = old_sub
                    send_vk_message(user_id, f"Введите новое название для '{old_sub}':", get_cancel_keyboard())
                    continue

        if state == "rename_sub_type":
            new_sub = user_text
            sel_cat = user_states[user_id]["sel_cat"]
            old_sub = user_states[user_id]["old_sub"]
            send_vk_message(user_id, f"⏳ Переименовываю '{old_sub}' в '{new_sub}'...")
            send_to_google_sheets({"action": "rename_subcategory", "cat": sel_cat, "old_sub": old_sub, "new_sub": new_sub, "type": "Расход"})
            send_to_google_sheets({"action": "rename_subcategory", "cat": sel_cat, "old_sub": old_sub, "new_sub": new_sub, "type": "Доход"})
            send_vk_message(user_id, "✅ Подкатегория успешно переименована!", get_main_keyboard())
            del user_states[user_id]
            continue

        if state == "rename_art_type":
            c_type = "Доход" if "доход" in user_text_lower else "Расход"
            menu = user_states[user_id]["menu"].get(c_type, {})
            cats = list(menu.keys())
            cats.sort()
            msg = f"Выберите категорию ({c_type}):\n\n"
            for i, c in enumerate(cats): msg += f"{i+1}. {c}\n"
            user_states[user_id]["state"] = "rename_art_cat"
            user_states[user_id]["c_type"] = c_type
            user_states[user_id]["cats"] = cats
            send_vk_message(user_id, msg, get_numbered_keyboard(len(cats)))
            continue

        if state == "rename_art_cat":
            if user_text.isdigit():
                idx = int(user_text) - 1
                cats = user_states[user_id]["cats"]
                if 0 <= idx < len(cats):
                    sel_cat = cats[idx]
                    c_type = user_states[user_id]["c_type"]
                    subs_dict = user_states[user_id]["menu"][c_type].get(sel_cat, {})
                    subs = list(subs_dict.keys())
                    subs.sort()
                    msg = f"Выберите подкатегорию в '{sel_cat}':\n\n"
                    for i, s in enumerate(subs): msg += f"{i+1}. {s}\n"
                    user_states[user_id]["state"] = "rename_art_sub"
                    user_states[user_id]["sel_cat"] = sel_cat
                    user_states[user_id]["subs"] = subs
                    send_vk_message(user_id, msg, get_numbered_keyboard(len(subs)))
                    continue

        if state == "rename_art_sub":
            if user_text.isdigit():
                idx = int(user_text) - 1
                subs = user_states[user_id]["subs"]
                if 0 <= idx < len(subs):
                    sel_sub = subs[idx]
                    c_type = user_states[user_id]["c_type"]
                    sel_cat = user_states[user_id]["sel_cat"]
                    arts = user_states[user_id]["menu"][c_type][sel_cat].get(sel_sub, [])
                    arts.sort()
                    if not arts:
                        send_vk_message(user_id, "В этой подкатегории нет статей.", get_main_keyboard())
                        del user_states[user_id]
                        continue
                    msg = f"Какую статью переименовать?\n\n"
                    for i, a in enumerate(arts): msg += f"{i+1}. {a}\n"
                    user_states[user_id]["state"] = "rename_art_select"
                    user_states[user_id]["sel_sub"] = sel_sub
                    user_states[user_id]["arts"] = arts
                    send_vk_message(user_id, msg, get_numbered_keyboard(len(arts)))
                    continue

        if state == "rename_art_select":
            if user_text.isdigit():
                idx = int(user_text) - 1
                arts = user_states[user_id]["arts"]
                if 0 <= idx < len(arts):
                    old_art = arts[idx]
                    user_states[user_id]["state"] = "rename_art_newname"
                    user_states[user_id]["old_art"] = old_art
                    send_vk_message(user_id, f"Введите новое название для статьи '{old_art}':", get_cancel_keyboard())
                    continue

        if state == "rename_art_newname":
            new_art = user_text
            payload = {
                "action": "rename_article",
                "type": user_states[user_id]["c_type"],
                "cat": user_states[user_id]["sel_cat"],
                "sub": user_states[user_id]["sel_sub"],
                "old_art": user_states[user_id]["old_art"],
                "new_art": new_art
            }
            send_vk_message(user_id, f"⏳ Переименовываю статью...")
            send_to_google_sheets(payload)
            send_vk_message(user_id, "✅ Статья успешно переименована!", get_main_keyboard())
            del user_states[user_id]
            continue

        # =========================================================
        # РАЗБОР ИМПОРТА (ЗАВАЛОВ)
        # =========================================================
        if user_text_lower in ["разобрать завалы", "разобрать"]:
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

        if state == "queue_confirm":
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
                send_vk_message(user_id, "Пожалуйста, ответь 'Да' или 'Нет'.", get_yes_no_keyboard())
                continue

        if state == "queue_hint":
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

        if state == "queue_manual":
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
        # ОБУЧЕНИЕ ОДИНОЧНОЙ ОПЕРАЦИИ (ДА/НЕТ, ПОДСКАЗКИ)
        # =========================================================
        if state == "confirm_category":
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
                    send_vk_message(user_id, "🤷‍♂️ Я сдаюсь. Напиши точную категорию из списка через дефис:\n\n" + cats_list, get_cancel_keyboard())
                continue
            else:
                send_vk_message(user_id, "Пожалуйста, ответь 'Да' или 'Нет'.", get_yes_no_keyboard())
                continue

        if state == "provide_context":
            send_vk_message(user_id, "🧠 Думаю...")
            user_states[user_id]["attempts"] += 1
            payload = user_states[user_id]["payload"]
            menu = user_states[user_id]["menu"]
            menu_str = "\n".join([f"{c}: {', '.join(subs)}" for c, subs in menu.items()])
            
            check_payload = {"action": "check_item", "item": user_text, "type": payload.get("type", "Расход")}
            check_res = send_to_google_sheets(check_payload)
            if check_res.get("status") == "FOUND":
                user_states[user_id]["state"] = "confirm_category"
                user_states[user_id]["ai_cat"] = check_res.get("cat")
                user_states[user_id]["ai_sub"] = check_res.get("sub")
                send_vk_message(user_id, f"Ага! Слово '{user_text}' мне знакомо.\n📂 {check_res.get('cat')} -> {check_res.get('sub')}\n\nВсё верно?", get_yes_no_keyboard())
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
                    send_vk_message(user_id, f"Всё равно не могу сообразить 🤔 (Попытка {user_states[user_id]['attempts']} из {MAX_ATTEMPTS})\nПопробуй объяснить чуть подробнее?", get_cancel_keyboard())
                else:
                    user_states[user_id]["state"] = "manual_category"
                    cats_list = "\n".join([f"• {k}" for k in menu.keys()])
                    send_vk_message(user_id, "🤷‍♂️ Я сдаюсь. Напиши точную категорию из списка через дефис:\n\n" + cats_list, get_cancel_keyboard())
                continue

        if state == "manual_category":
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
        # ОБЫЧНЫЙ РЕЖИМ (Обработка новой одиночной операции)
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
                        for c, subs in menu.items(): menu_str += f"{c}: {', '.join(subs)}\n"
                            
                        ai_cat, ai_sub = categorize_with_ai(transaction_data['item'], menu_str)
                        if ai_cat in menu and ai_sub in menu[ai_cat]:
                            user_states[user_id] = {
                                "state": "confirm_category", "payload": transaction_data, "menu": menu,
                                "menu_str": menu_str, "ai_cat": ai_cat, "ai_sub": ai_sub, "attempts": 1
                            }
                            send_vk_message(user_id, f"🤖 Думаю, '{transaction_data['item']}' относится к:\n📂 {ai_cat} -> {ai_sub}\n\nВсё верно?", get_yes_no_keyboard())
                        else:
                            user_states[user_id] = {
                                "state": "provide_context", "payload": transaction_data, "menu": menu,
                                "menu_str": menu_str, "attempts": 1
                            }
                            send_vk_message(user_id, f"🤔 Я пока не знаю статью '{transaction_data['item']}'.\nПодскажи буквально в двух словах, что это за трата/доход?", get_cancel_keyboard())
                    else:
                        send_vk_message(user_id, f"❌ Ошибка таблицы: {gs_response.get('message')}", get_main_keyboard())
                except json.JSONDecodeError:
                    send_vk_message(user_id, "❌ Ошибка: ИИ вернул неправильный формат.", get_main_keyboard())
            else:
                send_vk_message(user_id, reply_text, get_main_keyboard())
                
        except Exception as e:
            send_vk_message(user_id, "❌ Ошибка связи с ИИ.", get_main_keyboard())
            print(f"Ошибка: {e}") 
