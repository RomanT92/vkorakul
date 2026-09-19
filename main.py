# -*- coding: utf-8 -*-
import threading
import time
from db import (
    get_full_menu,
    get_or_create_user,
    get_unverified_transactions,
    import_parsed_operations,
)
from handlers_base import handle_base_commands
from handlers_queue import _process_next_batch, handle_queue_and_learning
from handlers_receipt import handle_receipt
from handlers_structure import handle_structure
from handlers_transaction import handle_transaction
from handlers_voice_commands import handle_list_voice_commands
from keyboards import get_main_keyboard, get_receipt_mode_keyboard
from services import (
    longpoll,
    parse_bank_file_with_ai,
    send_vk_message,
    transcribe_audio_with_ai,
    report_module_health,
    vk,
)
from vk_api.longpoll import VkEventType

# ====================================================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ====================================================================
user_states = {}
MAX_ATTEMPTS = 3
TEST_INTERVAL_HOURS = 4  # Интервал автотестов (раз в 4 часа)

# ====================================================================
# АВТОНОМНЫЙ СТОРОЖЕВОЙ ПОТОК (АВТОТЕСТ ПРИ СТАРТЕ И КАЖДЫЕ 4 ЧАСА)
# ====================================================================
def background_health_monitor():
    """
    Фоновый демон:
    1. Запускает полный аудит 19 модулей СРАЗУ при старте бота.
    2. Повторяет полный прогон каждые 4 часа в фоновом режиме.
    """
    time.sleep(3)  # Короткая пауза, чтобы LongPoll успел инициализироваться
    while True:
        try:
            print(f"\n[АВТОТЕСТ] Запуск планового сквозного аудита 19 модулей...")
            from test_runner import run_all_self_tests
            passed, failed, errors = run_all_self_tests()
            print(f"[АВТОТЕСТ] Завершен: {passed}/19 в строю, {failed} сбоев. Следующий запуск через {TEST_INTERVAL_HOURS} ч.\n")
        except Exception as e:
            print(f"[АВТОТЕСТ] Ошибка выполнения фонового теста: {e}")
        
        # Ожидание 4 часа (4 * 3600 сек)
        time.sleep(TEST_INTERVAL_HOURS * 3600)

# Запуск фонового демона
monitor_thread = threading.Thread(target=background_health_monitor, daemon=True)
monitor_thread.start()

# ====================================================================
# ГЛАВНЫЙ ЦИКЛ БОТА
# ====================================================================
print("Бот успешно запущен и слушает сообщения ВКонтакте...")

for event in longpoll.listen():
    if event.type == VkEventType.MESSAGE_NEW and event.to_me:
        user_id = event.user_id
        user_text = event.text.strip()
        
        try:
            internal_uid = get_or_create_user(user_id)
            report_module_health(1, "В строю")
        except Exception as e_user:
            report_module_health(1, "Требует внимания", str(e_user))
            continue

        # ==============================================================
        # 1. ПЕРЕХВАТ ГОЛОСОВОГО СООБЩЕНИЯ (МОДУЛЬ №3)
        # ==============================================================
        if not user_text and event.attachments:
            is_voice = any(
                val in ['audiomsg', 'audio_message'] for val in event.attachments.values()
            )
            if is_voice:
                send_vk_message(user_id, '🎧 Слушаю голосовое сообщение...')
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
                            send_vk_message(user_id, f'📝 Распознано: «{user_text}»')
                            report_module_health(3, "В строю")
                        else:
                            report_module_health(3, "Требует внимания", "Whisper вернул пустой текст")
                            send_vk_message(user_id, '❌ Не удалось распознать речь. Попробуйте текстом.')
                            continue
                    else:
                        report_module_health(3, "Требует внимания", "Не найдена ссылка на .ogg от VK")
                        send_vk_message(user_id, '❌ Не удалось получить аудиофайл от ВК.')
                        continue
                except Exception as e:
                    report_module_health(3, "Требует внимания", str(e))
                    print(f'Ошибка при обработке голосового: {e}')
                    send_vk_message(user_id, '❌ Произошла ошибка при загрузке голосового сообщения.')
                    continue

        # ==============================================================
        # 1.5 ПЕРЕХВАТ ФОТОГРАФИИ ЧЕКА (МОДУЛЬ №10)
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
                        user_states[user_id] = {
                            'state': 'receipt_mode_select',
                            'photo_url': photo_url,
                        }
                        send_vk_message(user_id, '👀 Вижу чек. Как его записать?', get_receipt_mode_keyboard())
                        report_module_health(10, "В строю")
                    else:
                        report_module_health(10, "Требует внимания", "Не удалось извлечь URL фотографии чека")
                        send_vk_message(user_id, '❌ Не удалось получить ссылку на фото.')
                except Exception as e:
                    report_module_health(10, "Требует внимания", str(e))
                    print(f'Ошибка при обработке фото: {e}')
                    send_vk_message(user_id, '❌ Произошла ошибка при загрузке фотографии.')
                continue

        # ==============================================================
        # 1.6 ПЕРЕХВАТ ВЫПИСОК CSV / XLSX / XLS (МОДУЛЬ №15)
        # ==============================================================
        if not user_text and event.attachments:
            is_doc = any(val == 'doc' for val in event.attachments.values())
            if is_doc:
                send_vk_message(user_id, '📁 Вижу файл выписки. Изучаю его структуру...')
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
                                doc_ext = f'.{ext}'
                                break
                    if doc_url:
                        parse_result = parse_bank_file_with_ai(doc_url, doc_ext)
                        if parse_result.get('status') == 'SUCCESS':
                            operations = parse_result.get('operations', [])
                            if not operations:
                                report_module_health(15, "Требует внимания", "В файле не найдено операций с суммами > 0")
                                send_vk_message(
                                    user_id,
                                    '⚠️ Файл прочитан, но в нем не найдено финансовых операций с суммами больше 0.\n'
                                    'Убедитесь, что в файле есть заполненные колонки с датой и суммой.',
                                    get_main_keyboard(user_id),
                                )
                                continue

                            send_vk_message(user_id, f'✅ Извлек {len(operations)} операций.\n⚡ Анализирую и сохраняю в базу...')
                            stats = import_parsed_operations(internal_uid, operations)
                            report_msg = (
                                f'📊 **Результат импорта:**\n• Всего операций: {stats["total"]}\n'
                                f'• Автоматически распределено: {stats["verified"]}\n'
                                f'• Требует проверки: {stats["needs_review"]}'
                            )
                            if user_id in user_states and user_states[user_id].get('state') == 'wait_import_file':
                                del user_states[user_id]

                            if stats['needs_review'] == 0:
                                send_vk_message(user_id, report_msg + '\n\n🎉 Все операции распределены идеально!', get_main_keyboard(user_id))
                            else:
                                report_msg += f'\n\n📥 Нажмите кнопку «Разобрать операции ({stats["needs_review"]})», чтобы распределить их пакетами по 7 штук!'
                                send_vk_message(user_id, report_msg, get_main_keyboard(user_id))
                            report_module_health(15, "В строю")
                        else:
                            report_module_health(15, "Требует внимания", parse_result.get('message', 'Ошибка парсинга'))
                            send_vk_message(user_id, f'❌ Не удалось разобрать файл: {parse_result.get("message")}', get_main_keyboard(user_id))
                    else:
                        send_vk_message(user_id, '⚠️ Пожалуйста, отправьте файл в формате .CSV, .XLSX или .XLS')
                except Exception as e:
                    report_module_health(15, "Требует внимания", str(e))
                    print(f'Ошибка при обработке документа: {e}')
                    send_vk_message(user_id, '❌ Произошла ошибка при загрузке файла.')
                continue

        # ==============================================================
        # 2. ФИЛЬТР ПУСТЫХ СООБЩЕНИЙ
        # ==============================================================
        if not user_text:
            continue

        user_text_lower = user_text.lower()
        state = user_states.get(user_id, {}).get('state', '')

        if state == 'wait_import_file' and not any(cmd in user_text_lower for cmd in ['отмена', 'назад']):
            send_vk_message(user_id, '⚠️ Пожалуйста, прикрепите файл выписки (.CSV или .XLSX) как документ к сообщению.\nДля выхода нажмите «🚫 Отмена» или «🔙 Назад».')
            continue

        # ==============================================================
        # 3. МАРШРУТИЗАЦИЯ (STATE MACHINE / РОУТЕР)
        # ==============================================================
        # Шаг 0: Голосовые команды управления списками (Модули №6, 7, 8)
        try:
            if handle_list_voice_commands(user_id, user_text, user_text_lower, state, user_states):
                continue
        except Exception as e_voice_cmd:
            report_module_health(6, "Требует внимания", str(e_voice_cmd))

        # Шаг 1: Базовые команды, автотесты и навигация (Модули №17, 19)
        try:
            if handle_base_commands(user_id, user_text_lower, state, user_states):
                report_module_health(19, "В строю")
                continue
        except Exception as e_base:
            report_module_health(19, "Требует внимания", str(e_base))

        # Шаг 2: Управление структурой категорий и статей (Модуль №16)
        try:
            if handle_structure(user_id, user_text, user_text_lower, state, user_states):
                report_module_health(16, "В строю")
                continue
        except Exception as e_struct:
            report_module_health(16, "Требует внимания", str(e_struct))

        # Шаг 3: Очередь разбора и обучение (Модули №13, 14)
        try:
            if handle_queue_and_learning(user_id, user_text, user_text_lower, state, user_states, MAX_ATTEMPTS):
                report_module_health(13, "В строю")
                report_module_health(14, "В строю")
                continue
        except Exception as e_queue:
            report_module_health(13, "Требует внимания", str(e_queue))

        # Шаг 4: Обработка чеков (Модули №10, 11, 12)
        try:
            if handle_receipt(user_id, user_text, user_text_lower, state, user_states):
                report_module_health(11, "В строю")
                report_module_health(12, "В строю")
                continue
        except Exception as e_rcpt:
            report_module_health(11, "Требует внимания", str(e_rcpt))

        # Шаг 5: Быстрый ввод, история, текстовый CRUD (Модули №2, 4, 5, 9)
        try:
            if handle_transaction(user_id, user_text, state, user_states):
                report_module_health(2, "В строю")
                continue
        except Exception as e_tx:
            report_module_health(2, "Требует внимания", str(e_tx))

        # Фоллбэк
        send_vk_message(user_id, '⚠️ Неверный ввод. Пожалуйста, выберите вариант из меню.\nДля выхода нажмите «🚫 Отмена».', get_main_keyboard(user_id))
