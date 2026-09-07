# -*- coding: utf-8 -*-
from vk_api.keyboard import VkKeyboard, VkKeyboardColor

# ====================================================================
# ЕДИНАЯ ДИЗАЙН-СИСТЕМА С ИКОНКАМИ:
# 🔴 NEGATIVE  (Красный)  — 🚫 Отмена, 🔙 Назад, 🗑 Удалить, ❌ Нет
# 🟢 POSITIVE  (Зеленый)  — ✅ Готово, 💾 Сохранить пакет, ➕ Создать, ✅ Да
# ⚪ SECONDARY (Серый)    — Все стандартные пункты меню, списки и цифры
# 🔵 PRIMARY   (Синий)    — Особые действия (⚡ Применить, ✏️ Переименовать, ➡️ Перенести, чеки)
# ====================================================================

def get_main_keyboard(user_id=None, count=None):
    """
    Главное меню бота.
    Серые кнопки с понятными иконками и динамическим счетчиком.
    """
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
    keyboard.add_button('📂 Категории и статьи', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('❓ Помощь', color=VkKeyboardColor.SECONDARY)
    return keyboard


def get_crud_keyboard():
    """Меню управления структурой"""
    keyboard = VkKeyboard(one_time=False)
    # ➕ Создать — зеленый
    keyboard.add_button('➕ Создать', color=VkKeyboardColor.POSITIVE)
    # ✏️ Переименовать — синий
    keyboard.add_button('✏️ Переименовать', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    # 🔀 Удалить / перенести — серый
    keyboard.add_button('🔀 Удалить / перенести', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    # 🔙 Назад — красный
    keyboard.add_button('🔙 Назад', color=VkKeyboardColor.NEGATIVE)
    return keyboard


def get_del_move_keyboard():
    """Подменю: Удаление или Перенос"""
    keyboard = VkKeyboard(one_time=False)
    # 🗑 Удалить — красный
    keyboard.add_button('🗑 Удалить', color=VkKeyboardColor.NEGATIVE)
    # ➡️ Перенести — синий
    keyboard.add_button('➡️ Перенести', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    # 🔙 Назад — красный
    keyboard.add_button('🔙 Назад', color=VkKeyboardColor.NEGATIVE)
    return keyboard


def get_entity_keyboard():
    """Выбор уровня структуры: Категория, Подкатегория или Статья"""
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


def get_numbered_keyboard(count):
    """Универсальная клавиатура с цифрами для выбора из списков"""
    keyboard = VkKeyboard(one_time=False)
    limit = min(count, 36)
    for i in range(1, limit + 1):
        keyboard.add_button(str(i), color=VkKeyboardColor.SECONDARY)
        if i % 4 == 0 and i != limit:
            keyboard.add_line()
    keyboard.add_line()
    keyboard.add_button('🚫 Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard


def get_yes_no_keyboard():
    """Клавиатура подтверждения операции"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('✅ Да', color=VkKeyboardColor.POSITIVE)
    keyboard.add_button('❌ Нет', color=VkKeyboardColor.NEGATIVE)
    keyboard.add_line()
    keyboard.add_button('🚫 Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard


def type_keyboard():
    """Выбор типа транзакции: Расход / Доход"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('📉 Расход', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('📈 Доход', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('🚫 Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard


def get_cancel_keyboard():
    """Одиночная кнопка Отмена"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('🚫 Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard


def get_receipt_mode_keyboard():
    """Выбор режима обработки чека"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('🧾 Общий итог', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('📋 По позициям', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('🚫 Отмена', color=VkKeyboardColor.NEGATIVE)
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
    keyboard.add_button('✅ Готово', color=VkKeyboardColor.POSITIVE)
    keyboard.add_button('🚫 Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard


def get_queue_review_keyboard(count, show_apply_all=False):
    """Клавиатура для пакета операций"""
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
    keyboard.add_button('🚫 Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard
