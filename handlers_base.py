# -*- coding: utf-8 -*-
from keyboards import get_main_keyboard, get_crud_keyboard, get_cancel_keyboard
from services import send_vk_message, send_to_google_sheets
from db import migrate_dictionary_from_gs, get_new_unharvested_words

def handle_base_commands(user_id, user_text_lower, state, user_states):
    """
    Обработчик базовой навигации, команд отмены, помощи и импорта статистики.
    """
    # =========================================================
    # СЛУЖЕБНЫЕ КОМАНДЫ АДМИНИСТРАТОРА
    # =========================================================
    if user_text_lower == "миграция базы":
        send_vk_message(user_id, "⏳ Начинаю скачивание Глобальной базы из Google Sheets... Это займет пару секунд.")
        res = send_to_google_sheets({"action": "export_global_dict"})
        if res.get("status") == "SUCCESS":
            send_vk_message(user_id, "✅ Данные получены. Распаковываю синонимы и загружаю в PostgreSQL...")
            count = migrate_dictionary_from_gs(res)
            send_vk_message(user_id, f"🎉 Миграция успешно завершена! В базу загружено {count} синонимов.", get_main_keyboard(user_id))
        else:
            send_vk_message(user_id, f"❌ Ошибка при скачивании базы: {res.get('message', 'Неизвестная ошибка')}")
        return True

    if user_text_lower == "сбор новых слов":
        send_vk_message(user_id, "⏳ Сканирую базы пользователей на наличие новых слов...")
        new_words = get_new_unharvested_words()
        if not new_words:
            send_vk_message(user_id, "🎉 Новых слов не найдено. Все пользовательские слова уже есть в Глобальной базе!", get_main_keyboard(user_id))
            return True

        send_vk_message(user_id, f"Найдено {len(new_words)} новых слов. Выгружаю в Google Таблицу...")
        res = send_to_google_sheets({
            "action": "append_harvested_words",
            "rows": new_words
        })
        if res.get("status") == "SUCCESS":
            send_vk_message(
                user_id,
                f"✅ Успешно выгружено {len(new_words)} строк в лист 'Глобальная База Синонимов'!\n\n"
                f"Зайдите в таблицу, отметьте нужные галочками и отправьте команду «миграция базы».",
                get_main_keyboard(user_id)
            )
        else:
            send_vk_message(user_id, f"❌ Ошибка выгрузки в Google Таблицу: {res.get('message')}", get_main_keyboard(user_id))
        return True

    # =========================================================
    # ПОЛНЫЙ СБРОС (ОТМЕНА)
    # =========================================================
    if "отмена" in user_text_lower:
        if user_id in user_states:
            del user_states[user_id]
        send_vk_message(user_id, "Действие отменено. Главное меню.", get_main_keyboard(user_id))
        return True

    # =========================================================
    # ПОМОЩЬ / СТАРТ
    # =========================================================
    if any(cmd in user_text_lower for cmd in ["помощь", "начать", "start"]):
        if user_id in user_states:
            del user_states[user_id]
        help_text = (
            "🤖 Привет! Я твой финансовый Оракул.\n\n"
            "Просто напиши или надиктуй мне трату или доход, например:\n"
            "👉 Такси 500\n"
            "👉 Зарплата 50000\n"
            "👉 Кофе 250, бензин 2000, в магните 1400\n\n"
            "💡 Чтобы загрузить прошлые выписки банков — нажмите «📊 Импорт статистики прошлого»!\n"
            "Используйте кнопки меню для управления структурой и разбора трат."
        )
        send_vk_message(user_id, help_text, get_main_keyboard(user_id))
        return True

    # =========================================================
    # НАЗАД ИЗ РАЗНЫХ МЕНЮ
    # =========================================================
    if "назад" in user_text_lower:
        if state == "wait_import_file":
            del user_states[user_id]
            send_vk_message(user_id, "Главное меню.", get_main_keyboard(user_id))
            return True
        elif state in ["wait_entity_create", "wait_entity_rename", "wait_del_move_action"]:
            user_states[user_id] = {"state": "menu_crud"}
            send_vk_message(user_id, "Управление структурой. Что хотите сделать?", get_crud_keyboard())
            return True
        elif state in ["menu_crud", ""]:
            if user_id in user_states:
                del user_states[user_id]
            send_vk_message(user_id, "Главное меню.", get_main_keyboard(user_id))
            return True

    # =========================================================
    # ЗАПУСК «ИМПОРТ СТАТИСТИКИ ПРОШЛОГО»
    # =========================================================
    if "импорт статистики прошлого" in user_text_lower:
        user_states[user_id] = {"state": "wait_import_file"}
        import_instruction = (
            "📊 **Импорт статистики прошлого**\n\n"
            "Отправьте мне файл вашей банковской выписки или таблицу с историей трат.\n\n"
            "📄 **Поддерживаемые форматы:**\n"
            "• .CSV (выписки из Сбера, Т-Банка, Альфы, ВТБ)\n"
            "• .XLSX / .XLS (Excel-таблицы любого банка или личные шаблоны)\n\n"
            "💡 **Как получить выписку в банке:**\n"
            "Зайдите в мобильное приложение банка ➔ выберите карту ➔ «Выписка по счету» ➔ период (месяц/год) ➔ формат CSV или Excel ➔ отправьте файл сюда в чат.\n\n"
            "⚡ *ИИ самостоятельно определит даты, суммы, получателей и распределит всё по категориям!*"
        )
        send_vk_message(user_id, import_instruction, get_cancel_keyboard(show_back=True))
        return True

    # =========================================================
    # ВХОД В УПРАВЛЕНИЕ СТРУКТУРОЙ
    # =========================================================
    if "категории и статьи" in user_text_lower and state == "":
        user_states[user_id] = {"state": "menu_crud"}
        send_vk_message(user_id, "Управление структурой. Что хотите сделать?", get_crud_keyboard())
        return True

    if state == "menu_crud":
        from keyboards import get_entity_keyboard, get_del_move_keyboard
        if "создать" in user_text_lower:
            user_states[user_id]["state"] = "wait_entity_create"
            send_vk_message(user_id, "Что именно вы хотите создать?", get_entity_keyboard())
            return True
        elif "переименовать" in user_text_lower:
            user_states[user_id]["state"] = "wait_entity_rename"
            send_vk_message(user_id, "Что именно вы хотите переименовать?", get_entity_keyboard())
            return True
        elif "удалить" in user_text_lower or "перенести" in user_text_lower:
            user_states[user_id]["state"] = "wait_del_move_action"
            send_vk_message(user_id, "Что вы хотите сделать?", get_del_move_keyboard())
            return True

    return False

