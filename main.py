# -*- coding: utf-8 -*-
from vk_api.longpoll import VkEventType

# Импортируем сервисы для работы с ВК и ИИ
from services import (
    longpoll, vk, send_vk_message, transcribe_audio_with_ai, 
    parse_bank_file_with_ai, send_to_google_sheets 
)

# Импортируем клавиатуры
from keyboards import get_receipt_mode_keyboard, get_main_keyboard

# Импортируем наши обработчики (Handlers), по которым мы разбили логику
from handlers_base import handle_base_commands
from handlers_structure import handle_structure
from handlers_queue import handle_queue_and_learning
from handlers_receipt import handle_receipt
from handlers_transaction import handle_transaction

# ====================================================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ====================================================================
user_states = {}
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
            is_voice = any(val in ['audiomsg', 'audio_message'] for val in event.attachments.values())
            
            if is_voice:
                send_vk_message(user_id, "🎧 Слушаю голосовое сообщение...")
                try:
                    msg_data = vk.messages.getById(message_ids=event.message_id)['items'][0]
                    attachments = msg_data.get('attachments', [])
                    
                    audio_url = None
                    for att in attachments:
                        if att['type'] == 'audio_message':
                            audio_url = att['audio_message']['link_ogg']
                            break
                    
                    if audio_url:
                        transcribed_text = transcribe_audio_with_ai(audio_url)
                        if transcribed_text:
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
            is_photo = any(val == 'photo' for val in event.attachments.values())
            
            if is_photo:
                try:
                    msg_data = vk.messages.getById(message_ids=event.message_id)['items'][0]
                    attachments = msg_data.get('attachments', [])
                    photo_url = None
                    
                    for att in attachments:
                        if att['type'] == 'photo':
                            sizes = att['photo']['sizes']
                            largest_photo = sorted(sizes, key=lambda x: x['width'])[-1]
                            photo_url = largest_photo['url']
                            break
                    
                    if photo_url:
                        user_states[user_id] = {"state": "receipt_mode_select", "photo_url": photo_url}
                        send_vk_message(user_id, "👀 Вижу чек. Как его записать?", get_receipt_mode_keyboard())
                    else:
                        send_vk_message(user_id, "❌ Не удалось получить ссылку на фото.")
                except Exception as e:
                    print(f"Ошибка при обработке фото: {e}")
                    send_vk_message(user_id, "❌ Произошла ошибка при загрузке фотографии.")
                continue

        # ==============================================================
        # 1.6 ПЕРЕХВАТ ДОКУМЕНТА (БАНКОВСКОЙ ВЫПИСКИ ИЛИ МАТРИЦЫ)
        # ==============================================================
        if not user_text and event.attachments:
            is_doc = any(val == 'doc' for val in event.attachments.values())
            
            if is_doc:
                send_vk_message(user_id, "📁 Вижу файл. Изучаю его структуру...")
                try:
                    msg_data = vk.messages.getById(message_ids=event.message_id)['items'][0]
                    attachments = msg_data.get('attachments', [])
                    
                    doc_url = None
                    doc_ext = None
                    
                    for att in attachments:
                        if att['type'] == 'doc':
                            doc = att['doc']
                            ext = doc.get('ext', '').lower()
                            if ext in ['csv', 'xlsx', 'xls']:
                                doc_url = doc['url']
                                doc_ext = f".{ext}"
                                break
                    
                    if doc_url:
                        parse_result = parse_bank_file_with_ai(doc_url, doc_ext)
                        
                        if parse_result.get("status") == "SUCCESS":
                            operations = parse_result.get("operations", [])
                            send_vk_message(user_id, f"✅ Структура понятна! Извлек {len(operations)} операций.\n⏳ Отправляю их в таблицу частями...")
                            
                            # ОТПРАВКА ЧАСТЯМИ (ЧАНКАМИ)
                            # Режем огромный массив на пачки по 500 строк, чтобы Google не завис
                            chunk_size = 500
                            for i in range(0, len(operations), chunk_size):
                                chunk = operations[i:i + chunk_size]
                                send_to_google_sheets({
                                    "action": "append_import_rows",
                                    "rows": chunk
                                })
                            
                            send_vk_message(user_id, "⏳ Данные загружены. Запускаю умный анализ и поиск совпадений...")
                            
                            # Когда всё загружено, даем команду таблице на переваривание
                            gs_res = send_to_google_sheets({
                                "action": "run_import_and_get_unverified",
                                "rows": [] # Строки уже загружены, просто запускаем алгоритм
                            })
                            
                            if gs_res.get("status") == "SUCCESS":
                                unverified = gs_res.get("data", [])
                                if not unverified:
                                    send_vk_message(user_id, "🎉 Импорт завершен! Все операции автоматически раскиданы по категориям. Завалов нет.", get_main_keyboard())
                                else:
                                    from handlers_queue import _process_next_batch
                                    user_states[user_id] = {
                                        "state": "queue_process", 
                                        "queue": unverified, 
                                        "menu": gs_res.get("available_menu", {})
                                    }
                                    _process_next_batch(user_id, user_states)
                            else:
                                send_vk_message(user_id, f"❌ Ошибка таблицы при импорте: {gs_res.get('message')}")
                        else:
                            send_vk_message(user_id, f"❌ Не удалось разобрать файл: {parse_result.get('message')}")
                    else:
                        send_vk_message(user_id, "⚠️ Пожалуйста, отправьте файл в формате .CSV или .XLSX")
                except Exception as e:
                    print(f"Ошибка при обработке документа: {e}")
                    send_vk_message(user_id, "❌ Произошла ошибка при загрузке файла.")
                continue

        # ==============================================================
        # 2. ФИЛЬТР ПУСТЫХ СООБЩЕНИЙ
        # ==============================================================
        if not user_text:
            continue

        user_text_lower = user_text.lower()
        state = user_states.get(user_id, {}).get("state", "")

        # ==============================================================
        # 3. МАРШРУТИЗАЦИЯ (STATE MACHINE / РОУТЕР)
        # ==============================================================
        if handle_base_commands(user_id, user_text_lower, state, user_states):
            continue

        if handle_structure(user_id, user_text, user_text_lower, state, user_states):
            continue

        if handle_queue_and_learning(user_id, user_text, user_text_lower, state, user_states, MAX_ATTEMPTS):
            continue

        if handle_receipt(user_id, user_text, user_text_lower, state, user_states):
            continue

        if handle_transaction(user_id, user_text, state, user_states):
            continue

        send_vk_message(user_id, "⚠️ Неверный ввод. Пожалуйста, выберите вариант из меню.\nДля выхода нажмите «Отмена».")
