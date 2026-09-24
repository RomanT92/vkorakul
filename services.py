# -*- coding: utf-8 -*-
"""
services.py — Фасад внешних сервисов и шлюзов (Facade Pattern).
Обеспечивает 100% обратную совместимость для всех модулей бота:
- services_vk: взаимодействие с VK API, LongPoll и сторожевым таймером (Watchdog)
- services_ai: нейросетевой слой (LLM, Vision OCR, Whisper) через AITunnel
- services_parser: обработка и интеллектуальный маппинг банковских выписок
"""

from services_vk import (
    vk_session,
    longpoll,
    vk,
    send_vk_message,
    send_to_google_sheets,
    send_heartbeat,
    report_module_health
)

from services_ai import (
    ai_client,
    get_image_base64_uri,
    parse_voice_list_command_with_ai,
    parse_list_command_with_ai,
    categorize_with_ai,
    extract_transaction_with_ai,
    extract_operations_with_ai,
    transcribe_audio_with_ai,
    extract_receipt_total_with_ai,
    extract_receipt_items_with_ai,
    normalize_receipt_items_with_ai,
    categorize_batch_with_ai
)

from services_parser import (
    _clean_amount,
    _detect_bank_columns,
    parse_bank_file_with_ai
)

__all__ = [
    "vk_session",
    "longpoll",
    "vk",
    "send_vk_message",
    "send_to_google_sheets",
    "send_heartbeat",
    "report_module_health",
    "ai_client",
    "get_image_base64_uri",
    "parse_voice_list_command_with_ai",
    "parse_list_command_with_ai",
    "categorize_with_ai",
    "extract_transaction_with_ai",
    "extract_operations_with_ai",
    "transcribe_audio_with_ai",
    "extract_receipt_total_with_ai",
    "extract_receipt_items_with_ai",
    "normalize_receipt_items_with_ai",
    "categorize_batch_with_ai",
    "_clean_amount",
    "_detect_bank_columns",
    "parse_bank_file_with_ai"
]
