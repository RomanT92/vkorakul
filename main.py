# -*- coding: utf-8 -*-
from vk_api.longpoll import VkEventType

# Импортируем сервисы для работы с ВК и ИИ
from services import (
    longpoll, vk, send_vk_message, transcribe_audio_with_ai
)

# Импортируем наши обработчики (Handlers), по которым мы разбили логику
from handlers_base import handle_base_commands
from handlers_structure import handle_structure
from handlers_queue import handle_queue_and_learning
from handlers_transaction import handle_transaction

# ====================================================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ====================================================================
# Память бота (хранит состояния пользователей в оперативной памяти)
# Формат: {user_id: {"state": "имя_стейта", "другие_данные": ...}}
user_states = {}

# Максимальное количество попыток запросить подсказку у пользователя
MAX_ATTEMPTS = 3  

# ====================================================================
# ГЛАВНЫЙ ЦИКЛ БОТА
# ====================================================================
print("Бот успешно запущен и слушает сообщения ВКонтакте...")

# Бесконечный цикл, который слушает сервер ВКонтакте на предмет новых событий
for event in longpoll.listen():
    # Проверяем, что событие — это новое сообщение, и оно адресовано нашему боту
    if event.type == VkEventType.MESSAGE_NEW and event.to_me:
        user_id = event.user_id
        user_text = event.text.strip()
        
        # ==============================================================
        # 1. ПЕРЕХВАТ ГОЛОСОВОГО СООБЩЕНИЯ
        # ==============================================================
        # Если текста нет, но есть хоть какие-то вложения (event.attachments — это словарь)
        if not user_text and event.attachments:
            # Ищем маркер голосового сообщения по всем значениям в словаре вложений.
            # ВК может прислать 'audiomsg' или 'audio_message' под разными ключами.
            is_voice = any(val in ['audiomsg', 'audio_message'] for val in event.attachments.values())
            
            if is_voice:
                send_vk_message(user_id, "🎧 Слушаю голосовое сообщение...")
                
                try:
                    # Получаем полную информацию о сообщении через API ВК (нам нужна ссылка на файл)
                    msg_data = vk.messages.getById(message_ids=event.message_id)['items'][0]
                    attachments = msg_data.get('attachments', [])
                    
                    audio_url = None
                    for att in attachments:
                        if att['type'] == 'audio_message':
                            audio_url = att['audio_message']['link_ogg']
                            break
                    
                    if audio_url:
                        # Отправляем ссылку на аудиофайл в нейросеть (Whisper) на распознавание
                        transcribed_text = transcribe_audio_with_ai(audio_url)
                        
                        if transcribed_text:
                            # МАГИЯ: Подменяем пустой текст на распознанный текст от ИИ!
                            # Теперь бот думает, что пользователь просто напечатал этот текст.
                            user_text = transcribed_text
                            send_vk_message(user_id, f"📝 Распознано: «{user_text}»")
                        else:
                            send_vk_message(user_id, "❌ Не удалось распознать речь. Попробуйте текстом.")
                            continue
                    else:
                        send_vk_message(user_id, "❌ Не удалось получить аудиофайл от ВК.")
                        continue
                except Exception as e:
                    print(f"Ошибка при обработке голосового: {e}")
                    send_vk_message(user_id, "❌ Произошла ошибка при загрузке голосового сообщения.")
                    continue

        # ==============================================================
        # 2. ФИЛЬТР ПУСТЫХ СООБЩЕНИЙ
        # ==============================================================
        # Если после всех проверок сообщение всё ещё пустое 
        # (например, прислали стикер, геопозицию, фото без подписи или документ)
        if not user_text:
            continue

        # Переводим текст в нижний регистр для удобства проверок базовых команд (назад, отмена)
        user_text_lower = user_text.lower()
        
        # Получаем текущее состояние пользователя (если его нет, будет пустая строка "")
        state = user_states.get(user_id, {}).get("state", "")

        # ==============================================================
        # 3. МАРШРУТИЗАЦИЯ (STATE MACHINE / РОУТЕР)
        # ==============================================================
        # Бот по очереди передает сообщение в разные обработчики (модули).
        # Если обработчик вернул True, значит он распознал команду и взял её на себя.
        # В таком случае срабатывает 'continue', и мы ждем следующее сообщение от ВК.

        # Шаг А: Базовые команды (отмена, назад, помощь, переходы из главного меню)
        if handle_base_commands(user_id, user_text_lower, state, user_states):
            continue

        # Шаг Б: Ветка управления структурой (Создать, Переименовать, Удалить, Перенести через меню)
        if handle_structure(user_id, user_text, user_text_lower, state, user_states):
            continue

        # Шаг В: Ветка разбора завалов и интерактивного обучения ИИ (вопросы "Верно?")
        if handle_queue_and_learning(user_id, user_text, user_text_lower, state, user_states, MAX_ATTEMPTS):
            continue

        # Шаг Г: Обычный режим 
        # (парсинг новой транзакции, умные команды изменения структуры текстом или просто общение с ИИ)
        if handle_transaction(user_id, user_text, state, user_states):
            continue

        # ==============================================================
        # 4. ГЛОБАЛЬНАЯ ЗАЩИТА ОТ ОШИБОК
        # ==============================================================
        # Сработает только если у пользователя ЕСТЬ активный стейт (например, он в меню удаления),
        # но он ввел что-то, что ни один из обработчиков выше не смог распознать (например, текст вместо цифры).
        send_vk_message(user_id, "⚠️ Неверный ввод. Пожалуйста, выберите вариант из меню.\nДля выхода нажмите «Отмена».")
