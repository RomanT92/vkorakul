# -*- coding: utf-8 -*-
from vk_api.keyboard import VkKeyboard, VkKeyboardColor

# ====================================================================
# ГЕНЕРАТОРЫ КЛАВИАТУР (МНОГОУРОВНЕВОЕ МЕНЮ)
# ====================================================================

def get_main_keyboard():
    """Главное меню бота с кнопкой разбора операций"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Разобрать операции', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Категории и статьи', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('Помощь', color=VkKeyboardColor.SECONDARY)
    return keyboard

def get_crud_keyboard():
    """Меню управления структурой"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Создать', color=VkKeyboardColor.POSITIVE)
    keyboard.add_button('Переименовать', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Удалить / перенести', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('Назад', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_del_move_keyboard():
    """Подменю для удаления и переноса"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Удалить', color=VkKeyboardColor.NEGATIVE)
    keyboard.add_button('Перенести', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Назад', color=VkKeyboardColor.SECONDARY)
    return keyboard

def get_entity_keyboard():
    """Выбор уровня структуры (Категория, Подкатегория, Статья)"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Категорию', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('Подкатегорию', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Статью', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Назад', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_move_entity_keyboard():
    """Для переноса категорию выбрать нельзя, поэтому кнопок меньше"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Подкатегорию', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('Статью', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Назад', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_numbered_keyboard(count):
    """Универсальная клавиатура с цифрами для выбора из списков"""
    keyboard = VkKeyboard(one_time=False)
    limit = min(count, 36)
    for i in range(1, limit + 1):
        keyboard.add_button(str(i), color=VkKeyboardColor.SECONDARY)
        if i % 4 == 0 and i != limit:
            keyboard.add_line()
    keyboard.add_line()
    keyboard.add_button('Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_yes_no_keyboard():
    """Клавиатура подтверждения"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Да', color=VkKeyboardColor.POSITIVE)
    keyboard.add_button('Нет', color=VkKeyboardColor.NEGATIVE)
    keyboard.add_line()
    keyboard.add_button('Отмена', color=VkKeyboardColor.SECONDARY)
    return keyboard

def type_keyboard():
    """Выбор типа транзакции"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Расход', color=VkKeyboardColor.NEGATIVE)
    keyboard.add_button('Доход', color=VkKeyboardColor.POSITIVE)
    keyboard.add_line()
    keyboard.add_button('Отмена', color=VkKeyboardColor.SECONDARY)
    return keyboard

def get_cancel_keyboard():
    """Кнопка Отмена для выхода из любого диалога"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_receipt_mode_keyboard():
    """Выбор режима обработки чека"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Общий итог', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('По позициям', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_receipt_review_keyboard(count):
    """Клавиатура для ревью позиций чека"""
    keyboard = VkKeyboard(one_time=False)
    limit = min(count, 36)
    for i in range(1, limit + 1):
        keyboard.add_button(str(i), color=VkKeyboardColor.SECONDARY)
        if i % 4 == 0 and i != limit:
            keyboard.add_line()
    keyboard.add_line()
    keyboard.add_button('Готово', color=VkKeyboardColor.POSITIVE)
    keyboard.add_button('Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_queue_review_keyboard(count, show_apply_all=False):
    """
    Клавиатура для ревью пакета операций.
    Если show_apply_all=True, добавляется кнопка 'Применить для всех оставшихся'.
    """
    keyboard = VkKeyboard(one_time=False)
    limit = min(count, 36)
    for i in range(1, limit + 1):
        keyboard.add_button(str(i), color=VkKeyboardColor.SECONDARY)
        if i % 4 == 0 and i != limit:
            keyboard.add_line()

    keyboard.add_line()
    if show_apply_all:
        keyboard.add_button('Применить для всех оставшихся', color=VkKeyboardColor.PRIMARY)
        keyboard.add_line()

    keyboard.add_button('Сохранить пакет', color=VkKeyboardColor.POSITIVE)
    keyboard.add_button('Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard
