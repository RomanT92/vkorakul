# -*- coding: utf-8 -*-
from vk_api.longpoll import VkEventType

# Импортируем сервисы для работы с ВК и ИИ
from services import (
    longpoll, vk, send_vk_message, transcribe_audio_with_ai
)

# Импортируем наши обработчики (Handlers)
from handlers_base import handle_base_commands
from handlers_structure import handle_structure
from handlers_queue import handle_queue_and_learning
from handlers_transaction import handle_transaction

# ====================================================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ====================================================================
# Память бота (хранит состояния пользователей в оперативной памяти)
user_states = {}

# Максимальное количество попыток запросить подсказку у пользователя
MAX_ATTEMPTS = 3  

# ====================================================================
# ГЛАВНЫЙ ЦИКЛ БОТА
# ====================================================================
print("Бот успешно запущен и слушает сообщения ВКонтакте...")

for event in longpoll.listen():
    if event.type == VkEventType.MESSAGE_NEW and event.to_me:
        user_id = event.user_id
        user_text = event.text.strip()
        
        # ==============================================================
        # ПЕРЕХВАТ ГОЛОСОВОГО СООБЩЕНИЯ
        # ==============================================================
        # Если текста нет, но есть вложение типа 'audiomsg' (голосовое сообщение)
        if not user_text and event.attachments and event.attachments.get('attach1_type') == 'audiomsg':
            send_vk_message(user_id, "🎧 Слушаю голосовое сообщение...")
            
            try:
                # Получаем полную информацию о сообщении через API ВК
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
                        # Подменяем пустой текст на распознанный текст от ИИ!
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

        # Если после всех проверок сообщение всё ещё пустое 
        # (например, прислали стикер, геопозицию или картинку без текста)
        if not user_text:
            continue

        # Переводим текст в нижний регистр для удобства проверок базовых команд (назад, отмена)
        user_text_lower = user_text.lower()
        
        # Получаем текущее состояние пользователя (если его нет, будет пустая строка "")
        state = user_states.get(user_id, {}).get("state", "")

        # ==============================================================
        # МАРШРУТИЗАЦИЯ (STATE MACHINE)
        # ==============================================================
        # Бот по очереди передает сообщение в разные обработчики.
        # Если обработчик вернул True, значит он взял сообщение на себя, 
        # и мы делаем continue (переходим к ожиданию следующего сообщения).

        # 1. Базовые команды (отмена, назад, помощь, переходы из главного меню)
        if handle_base_commands(user_id, user_text_lower, state, user_states):
            continue

        # 2. Ветка управления структурой (Создать, Переименовать, Удалить, Перенести)
        if handle_structure(user_id, user_text, user_text_lower, state, user_states):
            continue

        # 3. Ветка разбора завалов и интерактивного обучения ИИ
        if handle_queue_and_learning(user_id, user_text, user_text_lower, state, user_states, MAX_ATTEMPTS):
            continue

        # 4. Обычный режим (парсинг новой транзакции, умные команды структуры или просто общение)
        if handle_transaction(user_id, user_text, state, user_states):
            continue

        # 5. Глобальная защита от падения 
        # Сработает только если у пользователя есть активный стейт (например, он в меню удаления),
        # но он ввел что-то, что ни один обработчик не смог распознать.
        send_vk_message(user_id, "⚠️ Неверный ввод. Пожалуйста, выберите вариант из меню.\nДля выхода нажмите «Отмена».")
