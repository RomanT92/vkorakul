# -*- coding: utf-8 -*-
from vk_api.longpoll import VkEventType
from services import (
    longpoll, vk, send_vk_message,
    transcribe_audio_with_ai, parse_bank_file_with_ai
)
from keyboards import get_receipt_mode_keyboard, get_main_keyboard
from handlers_base import handle_base_commands
from handlers_structure import handle_structure
from handlers_queue import handle_queue_and_learning, _process_next_batch
from handlers_receipt import handle_receipt
from handlers_transaction import handle_transaction
from db import (
    get_or_create_user, import_parsed_operations,
    get_unverified_transactions, get_full_menu
)

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
        internal_uid = get_or_create_user(user_id)

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
        # 1.6 ПЕРЕХВАТ ДОКУМЕНТА (CSV ИЛИ XLSX ВЫПИСКИ)
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
                            send_vk_message(user_id, f"✅ Извлек {len(operations)} операций.\n⚡ Анализирую и сохраняю в базу данных...")
                            stats = import_parsed_operations(internal_uid, operations)
                            send_vk_message(
                                user_id,
                                f"📊 Результат загрузки:\n"
                                f"• Всего операций: {stats['total']}\n"
                                f"• Автоматически распределено: {stats['verified']}\n"
                                f"• Требует проверки: {stats['needs_review']}"
                            )
                            if stats['needs_review'] == 0:
                                send_vk_message(user_id, "🎉 Все операции успешно распределены! Завалов нет.", get_main_keyboard(user_id))
                            else:
                                unverified_raw = get_unverified_transactions(user_id)
                                unique_items = {}
                                for row in unverified_raw:
                                    key = f"{row['type']}_{row['original_item']}"
                                    if key not in unique_items:
                                        unique_items[key] = {
                                            "type": row["type"],
                                            "original_item": row["original_item"],
                                            "count": 1,
                                            "amount": row["amount"]
                                        }
                                    else:
                                        unique_items[key]["count"] += 1
                                
                                full_menu = get_full_menu(internal_uid)
                                combined_menu = {}
                                for t in ["Расход", "Доход"]:
                                    for c, s in full_menu.get(t, {}).items():
                                        combined_menu[c] = list(s.keys()) if isinstance(s, dict) else s
                                
                                user_states[user_id] = {
                                    "state": "queue_process",
                                    "queue": list(unique_items.values()),
                                    "menu": combined_menu
                                }
                                _process_next_batch(user_id, user_states)
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

        send_vk_message(user_id, "⚠️ Неверный ввод. Пожалуйста, выберите вариант из меню.\nДля выхода нажмите «Отмена».", get_main_keyboard(user_id))
