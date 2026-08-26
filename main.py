# -*- coding: utf-8 -*-
from vk_api.longpoll import VkEventType
from services import longpoll, send_vk_message

# Импортируем наши обработчики (Handlers)
from handlers_base import handle_base_commands
from handlers_structure import handle_structure
from handlers_queue import handle_queue_and_learning
from handlers_transaction import handle_transaction

# Память бота (хранит состояния пользователей)
user_states = {}
MAX_ATTEMPTS = 3

print("Бот успешно запущен и слушает сообщения ВКонтакте...")

for event in longpoll.listen():
    if event.type == VkEventType.MESSAGE_NEW and event.to_me:
        user_id = event.user_id
        user_text = event.text.strip()
        user_text_lower = user_text.lower()
        
        # Получаем текущее состояние пользователя (если его нет, будет пустая строка "")
        state = user_states.get(user_id, {}).get("state", "")

        # 1. Базовые команды (отмена, назад, помощь, переходы из главного меню)
        if handle_base_commands(user_id, user_text_lower, state, user_states):
            continue

        # 2. Ветка управления структурой (Создать, Переименовать, Удалить, Перенести)
        if handle_structure(user_id, user_text, user_text_lower, state, user_states):
            continue

        # 3. Ветка разбора завалов и интерактивного обучения ИИ
        if handle_queue_and_learning(user_id, user_text, user_text_lower, state, user_states, MAX_ATTEMPTS):
            continue

        # 4. Обычный режим (парсинг новой транзакции через нейросеть)
        if handle_transaction(user_id, user_text, state, user_states):
            continue

        # 5. Глобальная защита от падения (если стейт завис или ввели дичь)
        send_vk_message(user_id, "⚠️ Неверный ввод. Пожалуйста, выберите вариант из меню.\nДля выхода нажмите «Отмена».")
