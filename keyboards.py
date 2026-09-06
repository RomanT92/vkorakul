# -*- coding: utf-8 -*-
from vk_api.keyboard import VkKeyboard, VkKeyboardColor

# ====================================================================
# ГЕНЕРАТОРЫ КЛАВИАТУР (МНОГОУРОВНЕВОЕ МЕНЮ)
# ====================================================================

def get_main_keyboard(user_id=None, count=None):
    """
    Главное меню бота с динамическим счетчиком на кнопке.
    Если передан user_id (VK ID или внутренний ID), функция сама делает
    сверхбыстрый запрос в PostgreSQL и выводит точное количество неразобранных операций.
    """
    unreviewed_count = 0
    if count is not None:
        unreviewed_count = count
    elif user_id is not None:
        try:
            from db import get_unreviewed_count
            unreviewed_count = get_unreviewed_count(user_id)
        except Exception as e:
            print(f"Ошибка получения счетчика неразобранных операций: {e}")
            unreviewed_count = 0

    keyboard = VkKeyboard(one_time=False)
    
    if unreviewed_count > 0:
        btn_text = f"Разобрать операции ({unreviewed_count})"
        btn_color = VkKeyboardColor.POSITIVE  # Выделяем зеленым при наличии операций
    else:
        btn_text = "Разобрать операции"
        btn_color = VkKeyboardColor.SECONDARY # Серая кнопка, когда все чисто
        
    keyboard.add_button(btn_text, color=btn_color)
    keyboard.add_line()
    keyboard.add_button('Категории и статьи', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('Помощь', color=VkKeyboardColor.SECONDARY)
    return keyboard

def get_crud_keyboard():
    """Меню управления структурой (Создать, Переименовать, Удалить/Перенести)"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Создать', color=VkKeyboardColor.POSITIVE)
    keyboard.add_button('Переименовать', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Удалить / перенести', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('Назад', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_del_move_keyboard():
    """Подменю для выбора действия: Удаление или Перемещение"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Удалить', color=VkKeyboardColor.NEGATIVE)
    keyboard.add_button('Перенести', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Назад', color=VkKeyboardColor.SECONDARY)
    return keyboard

def get_entity_keyboard():
    """Выбор уровня структуры: Категория, Подкатегория или Статья"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Категорию', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('Подкатегорию', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Статью', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Назад', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_move_entity_keyboard():
    """Выбор уровня для переноса (категорию переносить нельзя)"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Подкатегорию', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('Статью', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Назад', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_numbered_keyboard(count):
    """Универсальная клавиатура с цифрами для постраничного выбора из списков"""
    keyboard = VkKeyboard(one_time=False)
    limit = min(count, 36) # Ограничение ВК: не более 40 кнопок в сообщении
    for i in range(1, limit + 1):
        keyboard.add_button(str(i), color=VkKeyboardColor.SECONDARY)
        if i % 4 == 0 and i != limit:
            keyboard.add_line()
    keyboard.add_line()
    keyboard.add_button('Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_yes_no_keyboard():
    """Клавиатура подтверждения операции: Да / Нет / Отмена"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Да', color=VkKeyboardColor.POSITIVE)
    keyboard.add_button('Нет', color=VkKeyboardColor.NEGATIVE)
    keyboard.add_line()
    keyboard.add_button('Отмена', color=VkKeyboardColor.SECONDARY)
    return keyboard

def type_keyboard():
    """Выбор типа транзакции или категории: Расход / Доход"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Расход', color=VkKeyboardColor.NEGATIVE)
    keyboard.add_button('Доход', color=VkKeyboardColor.POSITIVE)
    keyboard.add_line()
    keyboard.add_button('Отмена', color=VkKeyboardColor.SECONDARY)
    return keyboard

def get_cancel_keyboard():
    """Кнопка Отмена для безопасного выхода из любого текстового диалога"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_receipt_mode_keyboard():
    """Выбор режима обработки фото чека: Общий итог или По позициям"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('Общий итог', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('По позициям', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_receipt_review_keyboard(count):
    """Клавиатура для проверки распознанных позиций чека"""
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
    Клавиатура для пакетного ревью нераспознанных операций.
    Параметр show_apply_all активирует кнопку быстрого применения ко всем оставшимся.
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
