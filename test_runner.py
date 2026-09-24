# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import traceback
import requests
from datetime import datetime

# Импорты ядра бота и внешних сервисов
from services import (
    ai_client,
    send_to_google_sheets,
    report_module_health,
    categorize_with_ai,
    extract_transaction_with_ai,
    parse_voice_list_command_with_ai,
    normalize_receipt_items_with_ai
)
from db import (
    get_db_connection,
    get_or_create_user,
    smart_search_item,
    save_transaction,
    learn_user_word,
    get_full_menu,
    get_unverified_transactions,
    resolve_unverified_item,
    get_user_history,
    delete_transaction_by_id,
    delete_all_user_transactions,
    get_last_transaction,
    update_transaction_amount,
    update_transaction_category,
    db_add_subcategory,
    db_add_article,
    db_rename_category,
    db_rename_subcategory,
    db_rename_article,
    db_delete_entity,
    db_move_entity,
    import_parsed_operations,
    get_new_unharvested_words
)
from db.transactions import (
    promote_synonym_to_article,
    get_canonical_article_for_sub,
    delete_unverified_by_text
)
from handlers_tx_parser import (
    _try_fast_single_transaction_parse,
    detect_operation_type,
    _validate_ai_category_choice,
    _find_best_matching_article_in_sub
)
from handlers_structure_nlp import find_entity_in_menu
from handlers_history import apply_edit_to_last_transaction

# Служебный ID для тестов в песочнице
TEST_VK_ID = 999999999

def run_test_module(mod_num: int, name: str, test_func):
    """Выполняет тест, замеряет время и отправляет статус в дашборд."""
    print(f"[{mod_num:02d}/27] Тестирую: {name}...", end=" ", flush=True)
    start_t = time.time()
    try:
        ok, err_msg = test_func()
        duration = round(time.time() - start_t, 2)
        if ok:
            print(f"✅ В СТРОЮ ({duration}с)")
            report_module_health(mod_num, "В строю", "")
            return True, ""
        else:
            print(f"❌ ОШИБКА: {err_msg}")
            report_module_health(mod_num, "Требует внимания", f"[{duration}с] {err_msg}")
            return False, err_msg
    except Exception as e:
        duration = round(time.time() - start_t, 2)
        err = f"Исключение: {str(e)}\n{traceback.format_exc()[:150]}"
        print(f"💥 СБОЙ: {err}")
        report_module_health(mod_num, "Требует внимания", f"[{duration}с] {err}")
        return False, err

# ====================================================================
# ТЕСТОВЫЕ КЕЙСЫ ДЛЯ КАЖДОГО ИЗ 27 МОДУЛЕЙ
# ====================================================================

# 1. Авторизация и профиль пользователя
def test_mod_01():
    uid = get_or_create_user(TEST_VK_ID)
    if uid and isinstance(uid, int):
        return True, ""
    return False, f"Не удалось получить internal uid для {TEST_VK_ID}"

# 2. Диспетчер намерений (Надрежим)
def test_mod_02():
    raw_res = extract_transaction_with_ai("Привет, кто ты такой?")
    if raw_res and isinstance(raw_res, str) and len(raw_res.strip()) > 0:
        return True, ""
    return False, "Диспетчер намерений не вернул ответ на приветствие"

# 3. Свободный диалог («Поболтать»)
def test_mod_03():
    res = extract_transaction_with_ai("Посоветуй как откладывать деньги?")
    if res and len(res) > 10:
        return True, ""
    return False, "Режим разговора не вернул содержательного ответа"

# 4. Управление состояниями (FSM)
def test_mod_04():
    from handlers_base import handle_base_commands
    user_states = {TEST_VK_ID: {"state": "wait_import_file"}}
    handled = handle_base_commands(TEST_VK_ID, "отмена", "wait_import_file", user_states)
    if handled and TEST_VK_ID not in user_states:
        return True, ""
    return False, "Команда 'отмена' не сбросила стейт пользователя"

# 5. Определение типа (Доход / Расход)
def test_mod_05():
    op_type_inc, _ = detect_operation_type("зарплата 60000", "Расход", "зарплата")
    op_type_exp, _ = detect_operation_type("купил бензин 1500", "Расход", "бензин")
    if op_type_inc == "Доход" and op_type_exp == "Расход":
        return True, ""
    return False, f"Сбой классификатора: Доход={op_type_inc}, Расход={op_type_exp}"

# 6. Быстрый ввод траты (Fast-Path)
def test_mod_06():
    res = _try_fast_single_transaction_parse("Шиномонтаж 2600")
    if res and res.get("item") == "Шиномонтаж" and res.get("amount") == 2600.0:
        return True, ""
    return False, f"Fast-Path вернул некорректные данные: {res}"

# 7. Сложный NLP-ввод с описанием
def test_mod_07():
    res = extract_transaction_with_ai("Вчера в ленте потратил на мясо 850 руб")
    if res and ("850" in str(res) or "мясо" in str(res).lower()):
        return True, ""
    return False, f"NLP-парсер не извлек данные: {res}"

# 8. Множественный ввод операций
def test_mod_08():
    from handlers_transaction import _try_parse_multiple_transactions
    items = _try_parse_multiple_transactions("такси 350, кофе 180, аптека 900")
    if items and len(items) >= 2:
        return True, ""
    return False, f"Парсер множественного ввода не разбил строку на операции: {items}"

# 9. Голосовой ввод операций (Whisper)
def test_mod_09():
    res = ai_client.models.list()
    if res and hasattr(res, "data"):
        return True, ""
    return False, "Шлюз Whisper / OpenAI недоступен"

# 10. Точный и триграммный поиск синонимов
def test_mod_10():
    uid = get_or_create_user(TEST_VK_ID)
    found = smart_search_item(uid, "бензин", op_type="Расход")
    if isinstance(found, dict) and "status" in found:
        return True, ""
    return False, f"smart_search_item вернул неверную структуру: {found}"

# 11. LLM-классификатор по меню
def test_mod_11():
    menu_str = "[Расход]\nАвтомобиль: Заправка, Мойка"
    cat, sub = categorize_with_ai("Лукойл дизель", menu_str)
    if cat and sub and cat != "UNKNOWN":
        return True, ""
    return False, f"categorize_with_ai не подобрал категорию: {cat} -> {sub}"

# 12. Валидатор категорий (Anti-Hallucination)
def test_mod_12():
    uid = get_or_create_user(TEST_VK_ID)
    menu_full = get_full_menu(uid)
    if not menu_full:
        return False, "Не удалось загрузить меню для теста валидатора"
    v_cat, v_sub = _validate_ai_category_choice(menu_full, "Расход", "ФантастическаяКатегория", "Несуществующая")
    if v_cat is None:
        return True, ""
    return False, f"Валидатор пропустил несуществующую категорию: {v_cat}"

# 13. Интерактивное дообучение синонимам
def test_mod_13():
    uid = get_or_create_user(TEST_VK_ID)
    ok_learn = learn_user_word(uid, "Расход", "Транспорт", "Автомобиль", "Шиномонтаж", "тест_шинка_26")
    db_delete_entity(uid, "article", "Расход", "Транспорт", "Автомобиль", "тест_шинка_26")
    if ok_learn:
        return True, ""
    return False, "learn_user_word не смог сохранить синоним"

# 14. Правка суммы последней операции
def test_mod_14():
    uid = get_or_create_user(TEST_VK_ID)
    save_transaction(uid, "Расход", "Транспорт", "Такси", "ТестСуммы", 300.0, "", "ТестСуммы", "verified")
    last_tx = get_last_transaction(uid)
    if not last_tx:
        return False, "Не удалось получить последнюю транзакцию"
    tx_id = last_tx["id"]
    ok_upd = update_transaction_amount(uid, tx_id, 450.0)
    delete_transaction_by_id(uid, tx_id)
    if ok_upd:
        return True, ""
    return False, "update_transaction_amount не обновил сумму"

# 15. Правка категории последней операции
def test_mod_15():
    uid = get_or_create_user(TEST_VK_ID)
    save_transaction(uid, "Расход", "Транспорт", "Такси", "ТестКат", 500.0, "", "ТестКат", "verified")
    last_tx = get_last_transaction(uid)
    if not last_tx:
        return False, "Не удалось получить транзакцию"
    tx_id = last_tx["id"]
    ok_cat = update_transaction_category(uid, tx_id, "Еда", "Кафе", "ТестКат")
    delete_transaction_by_id(uid, tx_id)
    if ok_cat:
        return True, ""
    return False, "update_transaction_category вернул ошибку"

# 16. Отмена / удаление последней операции
def test_mod_16():
    uid = get_or_create_user(TEST_VK_ID)
    save_transaction(uid, "Расход", "Быт", "Разное", "ТестУдаления", 150.0, "", "ТестУдаления", "verified")
    last_tx = get_last_transaction(uid)
    if not last_tx:
        return False, "Транзакция не сохранилась"
    ok_del = delete_transaction_by_id(uid, last_tx["id"])
    if ok_del:
        return True, ""
    return False, "delete_transaction_by_id не удалил транзакцию"

# 17. Пакетная привязка категорий к списку
def test_mod_17():
    res = parse_voice_list_command_with_ai("Второе это такси, третье продукты")
    if res and res.get("action") in ["batch_set", "set_category"]:
        return True, ""
    return False, f"parse_voice_list_command_with_ai сбой: {res}"

# 18. Пакетное редактирование сумм и названий
def test_mod_18():
    res = parse_voice_list_command_with_ai("первая операция это огурцы, а сумма 250")
    if res and res.get("action") in ["rename_item", "rename_item_and_amount", "edit_amount"]:
        return True, ""
    return False, f"Парсер изменения суммы/названия сбой: {res}"

# 19. Пакетное удаление по номерам
def test_mod_19():
    res = parse_voice_list_command_with_ai("удали первую и третью")
    if res and res.get("action") == "delete":
        return True, ""
    return False, f"Парсер удаления не вернул action='delete': {res}"

# 20. Распознавание чека (общая сумма)
def test_mod_20():
    """
    Экономный, но глубокий тест модуля распознавания чеков (без траты денег на тяжелый Vision):
    1. Проверка доступности шлюза нейросети (models.list — 0 токенов / 0 руб).
    2. Проверка наличия и валидности системных промптов чека в config.py.
    3. Тестирование парсера JSON-ответа чека (_extract_json_object) на Markdown-разметке ИИ.
    4. Проверка интеграции обработчика чеков с базой данных (smart_search_item).
    """
    try:
        # 1. Проверка шлюза ИИ (бесплатный запрос к API списка моделей для валидации ключа и связи)
        m_list = ai_client.models.list()
        if not m_list or not hasattr(m_list, "data"):
            return False, "Шлюз нейросети (AI Tunnel) недоступен для чеков"

        # 2. Проверка системного промпта
        from config import PROMPT_RECEIPT_TOTAL
        if not PROMPT_RECEIPT_TOTAL or "amount" not in PROMPT_RECEIPT_TOTAL.lower():
            return False, "В config.py поврежден или пуст PROMPT_RECEIPT_TOTAL"

        # 3. Проверка парсера JSON-ответов от Vision-модели (обработка markdown code fence ```json)
        import handlers_receipt
        if not hasattr(handlers_receipt, "handle_receipt") or not hasattr(handlers_receipt, "_extract_json_object"):
            return False, "В handlers_receipt.py отсутствуют ключевые функции парсинга"

        mock_ai_output = "```json\n{\n  \"item\": \"Тестовый Супермаркет\",\n  \"amount\": 1250.50,\n  \"comment\": \"Тест\"\n}\n```"
        extracted = handlers_receipt._extract_json_object(mock_ai_output)
        data = json.loads(extracted)
        if data.get("amount") != 1250.50 or data.get("item") != "Тестовый Супермаркет":
            return False, f"Парсер ответа чека вернул некорректные данные: {data}"

        # 4. Проверка готовности связки с БД
        uid = get_or_create_user(TEST_VK_ID)
        test_search = smart_search_item(uid, data["item"], "Расход")
        if not isinstance(test_search, dict) or "status" not in test_search:
            return False, "Сбой интеграции чека со справочником категорий БД"

        return True, ""
    except json.JSONDecodeError as jde:
        return False, f"Сбой парсинга JSON чека: {jde}"
    except Exception as e:
        return False, f"Сбой проверки модуля распознавания чеков: {e}"

# 21. Построчный разбор кассовых чеков
def test_mod_21():
    try:
        clean_map = normalize_receipt_items_with_ai(["Колбаса Останкино", "Молоко Домик в деревне"])
        if clean_map and isinstance(clean_map, dict):
            return True, ""
        return False, "normalize_receipt_items_with_ai вернул пустой результат"
    except Exception as e:
        return False, f"Сбой нормализации брендов чека: {e}"

# 22. Очередь нераспознанных операций
def test_mod_22():
    uid = get_or_create_user(TEST_VK_ID)
    unv = get_unverified_transactions(uid)
    if isinstance(unv, list):
        return True, ""
    return False, f"get_unverified_transactions вернул не список: {unv}"

# 23. Импорт банковских выписок (CSV/XLSX)
def test_mod_23():
    uid = get_or_create_user(TEST_VK_ID)
    fake_ops = [
        ["01.01.2025", "Расход", 100.0, "ТестПятерочка"],
        ["02.01.2025", "Доход", 5000.0, "ТестЗарплата"]
    ]
    stats = import_parsed_operations(uid, fake_ops)
    delete_all_user_transactions(uid, period="all")
    if stats.get("total", 0) >= 2:
        return True, ""
    return False, f"import_parsed_operations не сохранил операции: {stats}"

# 24. Выписка и история транзакций
def test_mod_24():
    uid = get_or_create_user(TEST_VK_ID)
    hist = get_user_history(uid, limit=5)
    if isinstance(hist, dict) and "items" in hist and "total_expense" in hist:
        return True, ""
    return False, f"get_user_history вернул неверную структуру: {hist}"

# 25. Управление структурой (CRUD статей)
def test_mod_25():
    uid = get_or_create_user(TEST_VK_ID)
    ok_sub = db_add_subcategory(uid, "Расход", "ТестКат26", "ТестПодкат26")
    ok_art = db_add_article(uid, "Расход", "ТестКат26", "ТестПодкат26", "ТестСтатья26")
    ok_del = db_delete_entity(uid, "category", "Расход", "ТестКат26")
    if ok_sub and ok_art and ok_del:
        return True, ""
    return False, "Сбой CRUD структуры категорий"

# 26. Сторожевой таймер и панель контроля (Watchdog)
def test_mod_26():
    local_port = int(os.environ.get("PORT", 3000))
    try:
        resp = requests.get(f"http://127.0.0.1:{local_port}/api/ping", timeout=3)
        if resp.status_code == 200:
            return True, ""
        return False, f"Админка вернула HTTP {resp.status_code}"
    except Exception as e:
        return False, f"Локальный веб-сервер админки не отвечает: {e}"

# 27. Создание новой статьи голосом при правке транзакций
def test_mod_27():
    uid = get_or_create_user(TEST_VK_ID)
    save_transaction(uid, "Расход", "Быт", "Мебель", "ТестЧасы", 500.0, "", "ТестЧасы", "verified")
    last_tx = get_last_transaction(uid)
    if not last_tx:
        return False, "Не удалось создать исходную транзакцию для теста"
    tx_id = last_tx["id"]

    # Вызываем перенос в новую статью «ТестНастенныеЧасы»
    ok_edit = apply_edit_to_last_transaction(TEST_VK_ID, uid, new_article_name="ТестНастенныеЧасы")
    updated_tx = get_last_transaction(uid)
    
    # Очистка за собой
    delete_transaction_by_id(uid, tx_id)
    db_delete_entity(uid, "article", "Расход", "Быт", "Мебель", "ТестНастенныеЧасы")

    if ok_edit and updated_tx and updated_tx.get("article") == "ТестНастенныеЧасы":
        return True, ""
    return False, f"Сбой переноса в новую статью: ok={ok_edit}, tx_art={updated_tx.get('article') if updated_tx else None}"

# ====================================================================
# ГЛАВНЫЙ РЕЕСТР ПРОГОНА 27 ТЕСТОВ
# ====================================================================
TESTS_REGISTRY = [
    (1, "Авторизация и профиль пользователя", test_mod_01),
    (2, "Диспетчер намерений (Надрежим)", test_mod_02),
    (3, "Свободный диалог («Поболтать»)", test_mod_03),
    (4, "Управление состояниями (FSM)", test_mod_04),
    (5, "Определение типа (Доход / Расход)", test_mod_05),
    (6, "Быстрый ввод траты (Fast-Path)", test_mod_06),
    (7, "Сложный NLP-ввод с описанием", test_mod_07),
    (8, "Множественный ввод операций", test_mod_08),
    (9, "Голосовой ввод операций (Whisper)", test_mod_09),
    (10, "Точный и триграммный поиск синонимов", test_mod_10),
    (11, "LLM-классификатор по меню", test_mod_11),
    (12, "Валидатор категорий (Anti-Hallucination)", test_mod_12),
    (13, "Интерактивное дообучение синонимам", test_mod_13),
    (14, "Правка суммы последней операции", test_mod_14),
    (15, "Правка категории последней операции", test_mod_15),
    (16, "Отмена / удаление последней операции", test_mod_16),
    (17, "Пакетная привязка категорий к списку", test_mod_17),
    (18, "Пакетное редактирование сумм и названий", test_mod_18),
    (19, "Пакетное удаление по номерам", test_mod_19),
    (20, "Распознавание чека (общая сумма)", test_mod_20),
    (21, "Построчный разбор кассовых чеков", test_mod_21),
    (22, "Очередь нераспознанных операций", test_mod_22),
    (23, "Импорт банковских выписок (CSV/XLSX)", test_mod_23),
    (24, "Выписка и история транзакций", test_mod_24),
    (25, "Управление структурой (CRUD статей)", test_mod_25),
    (26, "Сторожевой таймер и панель контроля (Watchdog)", test_mod_26),
    (27, "Создание новой статьи голосом при правке транзакций", test_mod_27),
]

def run_all_self_tests():
    """Запускает полный аудит всех 27 функциональных узлов."""
    print("=" * 65)
    print("🚀 СТАРТ СКВОЗНОГО АУДИТА СИСТЕМЫ «ОРАКУЛ» (27 МОДУЛЕЙ)")
    print(f"⏰ Время запуска: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    print("=" * 65)

    passed = 0
    failed = 0
    errors = []

    for mod_num, name, func in TESTS_REGISTRY:
        ok, err = run_test_module(mod_num, name, func)
        if ok:
            passed += 1
        else:
            failed += 1
            errors.append(f"• Модуль {mod_num} ({name}): {err}")
        time.sleep(0.1)

    print("=" * 65)
    pct = round((passed / len(TESTS_REGISTRY)) * 100, 1)
    print(f"🏁 ИТОГИ АУДИТА: Успешно: {passed}/{len(TESTS_REGISTRY)} ({pct}%) | Сбоев: {failed}")
    print("=" * 65)
    return passed, failed, errors

if __name__ == "__main__":
    run_all_self_tests()
