# -*- coding: utf-8 -*-
from keyboards import get_main_keyboard, get_crud_keyboard
from services import send_vk_message, send_to_google_sheets
from db import migrate_dictionary_from_gs

def handle_base_commands(user_id, user_text_lower, state, user_states):
    
    # --- СЕКРЕТНАЯ КОМАНДА ДЛЯ ПЕРЕНОСА БАЗЫ В POSTGRESQL ---
    if user_text_lower == "миграция базы":
        send_vk_message(user_id, "⏳ Начинаю скачивание Глобальной базы из Google Sheets... Это займет пару секунд.")
        # Просим Гугл Таблицу отдать нам весь словарь
        res = send_to_google_sheets({"action": "export_global_dict"})
        if res.get("status") == "SUCCESS":
            send_vk_message(user_id, "✅ Данные получены. Распаковываю синонимы и загружаю в PostgreSQL...")
            # Запускаем функцию миграции из db.py
            count = migrate_dictionary_from_gs(res.get("data", []))
            send_vk_message(user_id, f"🎉 Миграция успешно завершена! В базу загружено {count} синонимов.", get_main_keyboard())
        else:
            send_vk_message(user_id, "❌ Ошибка при скачивании базы.")
        return True
    # ---------------------------------------------------------

    if user_text_lower in ["помощь", "начать", "start", "отмена", "назад"]:
        if user_text_lower in ["помощь", "начать", "start"]:
            if user_id in user_states:
                del user_states[user_id]
            help_text = "🤖 Привет! Я твой финансовый Оракул.\n\nПросто напиши мне трату или доход, например:\n👉 Такси 500\n👉 Зарплата 50000\n\nИспользуй кнопки меню для управления структурой!"
            send_vk_message(user_id, help_text, get_main_keyboard())
            return True

        if user_text_lower == "назад":
            if state in ["wait_entity_create", "wait_entity_rename", "wait_del_move_action"]:
                user_states[user_id] = {"state": "menu_crud"}
                send_vk_message(user_id, "Управление структурой. Что хотите сделать?", get_crud_keyboard())
                return True
            elif state == "menu_crud":
                if user_id in user_states:
                    del user_states[user_id]
                send_vk_message(user_id, "Главное меню.", get_main_keyboard())
                return True

        if user_id in user_states:
            del user_states[user_id]
        send_vk_message(user_id, "Действие отменено. Главное меню.", get_main_keyboard())
        return True

    if user_text_lower == "категории и статьи":
        user_states[user_id] = {"state": "menu_crud"}
        send_vk_message(user_id, "Управление структурой. Что хотите сделать?", get_crud_keyboard())
        return True

    if state == "menu_crud":
        from keyboards import get_entity_keyboard, get_del_move_keyboard
        if user_text_lower == "создать":
            user_states[user_id]["state"] = "wait_entity_create"
            send_vk_message(user_id, "Что именно вы хотите создать?", get_entity_keyboard())
            return True
        elif user_text_lower == "переименовать":
            user_states[user_id]["state"] = "wait_entity_rename"
            send_vk_message(user_id, "Что именно вы хотите переименовать?", get_entity_keyboard())
            return True
        elif user_text_lower == "удалить / перенести":
            user_states[user_id]["state"] = "wait_del_move_action"
            send_vk_message(user_id, "Что вы хотите сделать?", get_del_move_keyboard())
            return True

    return False
