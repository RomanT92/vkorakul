# -*- coding: utf-8 -*-
from vk_api.keyboard import VkKeyboard, VkKeyboardColor

def get_main_keyboard(user_id=None, count=None):
    """Главное меню бота"""
    unreviewed_count = 0
    if count is not None:
        unreviewed_count = count
    elif user_id is not None:
        try:
            from db import get_unreviewed_count
            unreviewed_count = get_unreviewed_count(user_id)
        except Exception as e:
            print(f"Ошибка получения счетчика в клавиатуре: {e}")
            unreviewed_count = 0

    keyboard = VkKeyboard(one_time=False)
    if unreviewed_count > 0:
        btn_text = f"📥 Разобрать операции ({unreviewed_count})"
    else:
        btn_text = "📥 Разобрать операции"

    keyboard.add_button(btn_text, color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('📊 Импорт статистики прошлого', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('📂 Категории и статьи', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('❓ Помощь', color=VkKeyboardColor.SECONDARY)
    return keyboard

def get_crud_keyboard():
    """Меню управления структурой"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('➕ Создать', color=VkKeyboardColor.POSITIVE)
    keyboard.add_button('✏️ Переименовать', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('🔀 Удалить / перенести', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('🔙 Назад', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_del_move_keyboard():
    """Подменю: Удаление или Перенос"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('🗑 Удалить', color=VkKeyboardColor.NEGATIVE)
    keyboard.add_button('➡️ Перенести', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('🔙 Назад', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_entity_keyboard():
    """Выбор уровня структуры"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('📁 Категорию', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('📂 Подкатегорию', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('📄 Статью', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('🔙 Назад', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_move_entity_keyboard():
    """Выбор уровня для переноса"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('📂 Подкатегорию', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('📄 Статью', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('🔙 Назад', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_numbered_keyboard(count, show_back=True):
    """Универсальная клавиатура с цифрами"""
    keyboard = VkKeyboard(one_time=False)
    limit = min(count, 36)
    for i in range(1, limit + 1):
        keyboard.add_button(str(i), color=VkKeyboardColor.SECONDARY)
        if i % 4 == 0 and i != limit:
            keyboard.add_line()
    keyboard.add_line()
    if show_back:
        keyboard.add_button('🔙 Назад', color=VkKeyboardColor.NEGATIVE)
        keyboard.add_button('🚫 Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_yes_no_keyboard(show_back=True, show_promote_article=False):
    """Клавиатура подтверждения с опцией 'Сделать отдельной статьёй'"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('✅ Да', color=VkKeyboardColor.POSITIVE)
    keyboard.add_button('❌ Нет', color=VkKeyboardColor.NEGATIVE)
    if show_promote_article:
        keyboard.add_line()
        keyboard.add_button('📄 Сделать отдельной статьёй', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    if show_back:
        keyboard.add_button('🔙 Назад', color=VkKeyboardColor.NEGATIVE)
        keyboard.add_button('🚫 Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def type_keyboard(show_back=True):
    """Выбор типа транзакции"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('📉 Расход', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('📈 Доход', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    if show_back:
        keyboard.add_button('🔙 Назад', color=VkKeyboardColor.NEGATIVE)
        keyboard.add_button('🚫 Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_cancel_keyboard(show_back=False):
    """Кнопка Отмена"""
    keyboard = VkKeyboard(one_time=False)
    if show_back:
        keyboard.add_button('🔙 Назад', color=VkKeyboardColor.NEGATIVE)
    keyboard.add_button('🚫 Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_receipt_mode_keyboard(show_back=True):
    """Выбор режима чека"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('🧾 Общий итог', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('📋 По позициям', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    if show_back:
        keyboard.add_button('🔙 Назад', color=VkKeyboardColor.NEGATIVE)
        keyboard.add_button('🚫 Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_receipt_review_keyboard(count, show_back=True):
    """Клавиатура позиций чека"""
    keyboard = VkKeyboard(one_time=False)
    limit = min(count, 36)
    for i in range(1, limit + 1):
        keyboard.add_button(str(i), color=VkKeyboardColor.SECONDARY)
        if i % 4 == 0 and i != limit:
            keyboard.add_line()
    keyboard.add_line()
    keyboard.add_button('✅ Готово', color=VkKeyboardColor.POSITIVE)
    keyboard.add_line()
    if show_back:
        keyboard.add_button('🔙 Назад', color=VkKeyboardColor.NEGATIVE)
        keyboard.add_button('🚫 Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_queue_review_keyboard(count, show_apply_all=False, show_back=True):
    """
    Клавиатура очереди разбора с кнопками:
    Сохранить пакет, Удалить мусор, Всё в мусор.
    """
    keyboard = VkKeyboard(one_time=False)
    limit = min(count, 36)
    for i in range(1, limit + 1):
        keyboard.add_button(str(i), color=VkKeyboardColor.SECONDARY)
        if i % 4 == 0 and i != limit:
            keyboard.add_line()
    keyboard.add_line()
    if show_apply_all:
        keyboard.add_button('⚡ Применить для всех оставшихся', color=VkKeyboardColor.PRIMARY)
        keyboard.add_line()
    keyboard.add_button('💾 Сохранить пакет', color=VkKeyboardColor.POSITIVE)
    keyboard.add_line()
    keyboard.add_button('🗑 Удалить мусор', color=VkKeyboardColor.NEGATIVE)
    keyboard.add_button('💥 Всё в мусор', color=VkKeyboardColor.NEGATIVE)
    keyboard.add_line()
    if show_back:
        keyboard.add_button('🔙 Назад', color=VkKeyboardColor.NEGATIVE)
        keyboard.add_button('🚫 Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_queue_item_action_keyboard():
    """Клавиатура действия над конкретным пунктом из очереди разбора"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('📂 Изменить категорию', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('🗑 Удалить как мусор', color=VkKeyboardColor.NEGATIVE)
    keyboard.add_line()
    keyboard.add_button('⏩ Пропустить', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('🔙 Назад к списку', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_multi_tx_review_keyboard(count, show_apply_all=False, show_back=True):
    """Клавиатура ревью массового ввода"""
    keyboard = VkKeyboard(one_time=False)
    limit = min(count, 36)
    for i in range(1, limit + 1):
        keyboard.add_button(str(i), color=VkKeyboardColor.SECONDARY)
        if i % 4 == 0 and i != limit:
            keyboard.add_line()
    keyboard.add_line()
    if show_apply_all:
        keyboard.add_button('⚡ Применить для всех оставшихся', color=VkKeyboardColor.PRIMARY)
        keyboard.add_line()
    keyboard.add_button('✅ Готово', color=VkKeyboardColor.POSITIVE)
    keyboard.add_line()
    if show_back:
        keyboard.add_button('🔙 Назад', color=VkKeyboardColor.NEGATIVE)
        keyboard.add_button('🚫 Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_tx_action_keyboard():
    """Клавиатура действий над конкретной операцией"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('✏️ Изменить сумму', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('📂 Изменить категорию', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('📄 Сделать отдельной статьёй', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('🗑 Удалить операцию', color=VkKeyboardColor.NEGATIVE)
    keyboard.add_line()
    keyboard.add_button('🔙 Назад к списку', color=VkKeyboardColor.NEGATIVE)
    keyboard.add_button('🚫 Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard
