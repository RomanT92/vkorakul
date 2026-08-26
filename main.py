# -*- coding: utf-8 -*-
from vk_api.longpoll import VkEventType

# Импортируем сервисы для работы с ВК и ИИ
from services import (
    longpoll, vk, send_vk_message, transcribe_audio_with_ai
)

# Импортируем клавиатуру для выбора режима чека
from keyboards import get_receipt_mode_keyboard

# Импортируем наши обработчики (Handlers), по которым мы разбили логику
from handlers_base import handle_base_commands
from handlers_structure import handle_structure
from handlers_queue import handle_queue_and_learning
from handlers_receipt import handle_receipt
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
        # 1. ПЕРЕХВАТ ГОЛОСОВОГО СООБЩЕНИЯ
        # ==============================================================
        if not user_text and event.attachments:
            # Ищем маркер голосового сообщения по всем значениям в словаре вложений
            is_voice = any(val in ['audiomsg', 'audio_message'] for val in event.attachments.values())
            
            if is_voice:
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

        # ==============================================================
        # 1.5 ПЕРЕХВАТ ФОТОГРАФИИ (ЧЕКА)
        # ==============================================================
        if not user_text and event.attachments:
            # Проверяем, есть ли среди вложений фотография
            is_photo = any(val == 'photo' for val in event.attachments.values())
            
            if is_photo:
                try:
                    msg_data = vk.messages.getById(message_ids=event.message_id)['items'][0]
                    attachments = msg_data.get('attachments', [])
                    photo_url = None
                    
                    for att in attachments:
                        if att['type'] == 'photo':
                            # Берем фотографию в максимальном разрешении (последнюю в списке sizes)
                            sizes = att['photo']['sizes']
                            largest_photo = sorted(sizes, key=lambda x: x['width'])[-1]
                            photo_url = largest_photo['url']
                            break
                    
                    if photo_url:
                        # Сохраняем ссылку на фото в память и переводим пользователя в режим выбора
                        user_states[user_id] = {"state": "receipt_mode_select", "photo_url": photo_url}
                        send_vk_message(user_id, "👀 Вижу чек. Как его записать?", get_receipt_mode_keyboard())
                    else:
                        send_vk_message(user_id, "❌ Не удалось получить ссылку на фото.")
                except Exception as e:
                    print(f"Ошибка при обработке фото: {e}")
                    send_vk_message(user_id, "❌ Произошла ошибка при загрузке фотографии.")
                continue

        # ==============================================================
        # 2. ФИЛЬТР ПУСТЫХ СООБЩЕНИЙ
        # ==============================================================
        # Если после всех проверок сообщение всё ещё пустое (например, прислали стикер)
        if not user_text:
            continue

        user_text_lower = user_text.lower()
        state = user_states.get(user_id, {}).get("state", "")

        # ==============================================================
        # 3. МАРШРУТИЗАЦИЯ (STATE MACHINE / РОУТЕР)
        # ==============================================================
        # Бот по очереди передает сообщение в разные обработчики.
        # Если обработчик вернул True, значит он распознал команду и взял её на себя.

        # Шаг А: Базовые команды (отмена, назад, помощь, переходы из главного меню)
        if handle_base_commands(user_id, user_text_lower, state, user_states):
            continue

        # Шаг Б: Ветка управления структурой (Создать, Переименовать, Удалить, Перенести через меню)
        if handle_structure(user_id, user_text, user_text_lower, state, user_states):
            continue

        # Шаг В: Ветка разбора завалов и интерактивного обучения ИИ
        if handle_queue_and_learning(user_id, user_text, user_text_lower, state, user_states, MAX_ATTEMPTS):
            continue

        # Шаг Г: Ветка обработки чеков (выбор режима, ревью позиций, исправление)
        if handle_receipt(user_id, user_text, user_text_lower, state, user_states):
            continue

        # Шаг Д: Обычный режим (парсинг транзакции, умные команды структуры или общение)
        if handle_transaction(user_id, user_text, state, user_states):
            continue

        # ==============================================================
        # 4. ГЛОБАЛЬНАЯ ЗАЩИТА ОТ ОШИБОК
        # ==============================================================
        # Сработает только если у пользователя ЕСТЬ активный стейт, 
        # но он ввел что-то, что ни один из обработчиков не смог распознать.
        send_vk_message(user_id, "⚠️ Неверный ввод. Пожалуйста, выберите вариант из меню.\nДля выхода нажмите «Отмена».")
