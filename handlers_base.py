# -*- coding: utf-8 -*-
from keyboards import get_main_keyboard, get_crud_keyboard, get_cancel_keyboard
from services import send_vk_message, send_to_google_sheets
from db import migrate_dictionary_from_gs, get_new_unharvested_words

def handle_base_commands(user_id, user_text_lower, state, user_states):
    """
    Обработчик базовой навигации, команд отмены, помощи и импорта статистики.
    """
    
