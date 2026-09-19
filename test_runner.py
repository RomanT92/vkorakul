# -*- coding: utf-8 -*-
import sys
import time
import traceback
from datetime import datetime

# Импорты ядра
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

# Служебный ID для тестов в песочнице
TEST_VK_ID = 999999999

def run_test_module(mod_num: int, name: str, test_func):
    """Выполняет тест, замеряет время и отправляет статус в дашборд."""
    print(f"[{mod_num:02d}/19] Тестирую: {name}...", end=" ", flush=True)
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
# ТЕСТОВЫЕ КЕЙСЫ ДЛЯ КАЖДОГО ИЗ 19 МОДУЛЕЙ
# ====================================================================

# 1. Регистрация и контекст пользователя
def test_mod_01():
    uid = get_or_create_user(TEST_VK_ID)
    if uid and isinstance(uid, int):
        return True, ""
    return False, f"Не удалось получить internal uid для {TEST_VK_ID}"

# 2. Быстрый ввод трат и доходов (текст)
def test_mod_02():
    res = _try_fast_single_transaction_parse("Шиномонтаж 2600")
    if not res or res["item"] != "Шиномонтаж" or res["amount"] != 2600.0:
        return False, f"Fast-Path вернул некорректные данные: {res}"
    op_type, _ = detect_operation_type("зарплата 50000", "Расход", "зарплата")
    if op_type != "Доход":
        return False, f"detect_operation_type не определил Доход: {op_type}"
    return True, ""

# 3. Голосовой ввод операций (Whisper & AI Tunnel Client)
def test_mod_03():
    # Проверка доступности API OpenAI через AI Tunnel
    res = ai_client.models.list()
    if res and hasattr(res, "data"):
        return True, ""
    return False, "AI Tunnel не вернул список моделей"

# 4. Интерактивная классификация статей
def test_mod_04():
    uid = get_or_create_user(TEST_VK_ID)
    menu_full = get_full_menu(uid)
    if not menu_full or "Расход" not in menu_full:
        return False, "Меню пользователя пустое или не содержит 'Расход'"
    v_cat, v_sub = _validate_ai_category_choice(menu_full, "Расход", "НесуществующаяКатегория", "НесуществующаяПодкатегория")
    if v_cat is not None:
        return False, f"Валидатор пропустил несуществующую категорию: {v_cat}"
    return True, ""

# 5. Голосовое и текстовое редактирование
def test_mod_05():
    uid = get_or_create_user(TEST_VK_ID)
    save_transaction(uid, "Расход", "Автомобиль", "Обслуживание", "ТестРедакт", 500.0, "", "ТестРедакт", "verified")
    last_tx = get_last_transaction(uid)
    if not last_tx or last_tx["article"] != "ТестРедакт":
        return False, "Не удалось сохранить и прочитать тестовую операцию"
    tx_id = last_tx["id"]
    ok_amt = update_transaction_amount(uid, tx_id, 750.0)
    ok_cat = update_transaction_category(uid, tx_id, "Автомобиль", "Заправка", "ТестРедакт")
    delete_transaction_by_id(uid, tx_id)
    if ok_amt and ok_cat:
        return True, ""
    return False, "Сбой update_transaction_amount или update_transaction_category"

# 6. Пакетная привязка категорий к списку
def test_mod_06():
    res = parse_voice_list_command_with_ai("Второе это такси, третье продукты")
    if not res or res.get("action") not in ["batch_set", "set_category"]:
        return False, f"parse_voice_list_command_with_ai не распознал пакетную команду: {res}"
    return True, ""

# 7. Пакетное редактирование сумм и названий
def test_mod_07():
    res = parse_voice_list_command_with_ai("первая операция это огурцы, а сумма 250")
    act = res.get("action")
    if act in ["rename_item", "rename_item_and_amount", "edit_amount"]:
        return True, ""
    return False, f"Парсер не распознал смену названия/суммы: {res}"

# 8. Пакетное и точечное удаление записей
def test_mod_08():
    res = parse_voice_list_command_with_ai("удали первую и третью")
    if res.get("action") == "delete" and len(res.get("indices", [])) >= 2:
        return True, ""
    return False, f"Парсер не распознал удаление по номерам: {res}"

# 9. Выписка и история транзакций
def test_mod_09():
    uid = get_or_create_user(TEST_VK_ID)
    hist = get_user_history(uid, limit=5)
    if isinstance(hist, dict) and "items" in hist and "total_expense" in hist:
        return True, ""
    return False, f"get_user_history вернул неверную структуру: {hist}"

# 10. Распознавание чека (общая сумма)
def test_mod_10():
    # Проверка доступности GPT-4o в AI Tunnel
    resp = ai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "PING. Ответь строго словом PONG"}],
        max_tokens=5
    )
    txt = resp.choices[0].message.content.strip()
    if "PONG" in txt.upper():
        return True, ""
    return False, f"GPT-4o вернул неожиданный ответ: {txt}"

# 11. Построчный разбор кассовых чеков
def test_mod_11():
    # Проверка функции очистки названий чеков от брендов
    clean_map = normalize_receipt_items_with_ai(["Колбаса Останкино", "Молоко Домик в деревне"])
    if clean_map and isinstance(clean_map, dict):
        return True, ""
    return False, f"normalize_receipt_items_with_ai вернул пустую карту: {clean_map}"

# 12. Пакетная авто-классификация чека
def test_mod_12():
    menu_str = "[Расход]\nПродукты: Еда, Напитки"
    ai_cat, ai_sub = categorize_with_ai("Хлеб", menu_str)
    if ai_cat and ai_sub and ai_cat != "UNKNOWN":
        return True, ""
    return False, f"categorize_with_ai сбой: {ai_cat} -> {ai_sub}"

# 13. Очередь нераспознанных операций
def test_mod_13():
    uid = get_or_create_user(TEST_VK_ID)
    unv = get_unverified_transactions(uid)
    if isinstance(unv, list):
        return True, ""
    return False, f"get_unverified_transactions вернул не список: {unv}"

# 14. Обучение бота новым синонимам
def test_mod_14():
    uid = get_or_create_user(TEST_VK_ID)
    # 1. Запоминаем синоним
    ok_learn = learn_user_word(uid, "Расход", "Транспорт", "Автомобиль", "Шиномонтаж", "тест_шинка")
    # 2. Проверяем умный поиск
    found = smart_search_item(uid, "тест_шинка", op_type="Расход")
    # 3. Тест превращения в статью
    ok_prom = promote_synonym_to_article(uid, "Расход", "Транспорт", "Автомобиль", "тест_шинка")
    # Очистка
    db_delete_entity(uid, "article", "Расход", "Транспорт", "Автомобиль", "Тест_шинка")
    if ok_learn and found["status"] == "FOUND" and ok_prom:
        return True, ""
    return False, f"Сбой обучения синонимов: learn={ok_learn}, search={found['status']}, prom={ok_prom}"

# 15. Импорт банковских выписок (CSV/XLSX)
def test_mod_15():
    uid = get_or_create_user(TEST_VK_ID)
    fake_ops = [
        ["01.01.2025", "Расход", 150.0, "Пятерочка тест"],
        ["02.01.2025", "Доход", 1000.0, "Аванс тест"]
    ]
    stats = import_parsed_operations(uid, fake_ops)
    # Очистка
    delete_all_user_transactions(uid, period="all")
    if stats.get("total", 0) >= 2:
        return True, ""
    return False, f"import_parsed_operations не загрузил операции: {stats}"

# 16. Управление структурой (CRUD статей)
def test_mod_16():
    uid = get_or_create_user(TEST_VK_ID)
    ok_add_sub = db_add_subcategory(uid, "Расход", "ТестКат", "ТестПодкат")
    ok_add_art = db_add_article(uid, "Расход", "ТестКат", "ТестПодкат", "ТестСтатья")
    ok_ren = db_rename_article(uid, "Расход", "ТестКат", "ТестПодкат", "ТестСтатья", "ТестСтатья2")
    ok_del = db_delete_entity(uid, "category", "Расход", "ТестКат")
    if ok_add_sub and ok_add_art and ok_ren and ok_del:
        return True, ""
    return False, f"Сбой CRUD: add_sub={ok_add_sub}, add_art={ok_add_art}, ren={ok_ren}, del={ok_del}"

# 17. Двусторонняя синхронизация словарей
def test_mod_17():
    new_words = get_new_unharvested_words()
    if isinstance(new_words, list):
        return True, ""
    return False, f"get_new_unharvested_words вернул не список: {new_words}"

# 18. Административная веб-панель (Webhook Google Таблиц)
def test_mod_18():
    res = send_to_google_sheets({"action": "ping"})
    # Если вернулся JSON с любым статусом (даже UNKNOWN_ACTION) — вебхук живой и принимает POST
    if isinstance(res, dict) and "status" in res:
        return True, ""
    return False, f"Google Apps Script вебхук недоступен: {res}"

# 19. Навигация и управление состояниями
def test_mod_19():
    from handlers_base import handle_base_commands
    user_states = {TEST_VK_ID: {"state": "wait_import_file"}}
    # Проверяем, сбрасывает ли команда "отмена" состояние пользователя
    handled = handle_base_commands(TEST_VK_ID, "отмена", "wait_import_file", user_states)
    if handled and TEST_VK_ID not in user_states:
        return True, ""
    return False, "Команда 'отмена' не очистила состояние пользователя"

# ====================================================================
# ГЛАВНЫЙ ЦИКЛ ПРОГОНА ТЕСТОВ
# ====================================================================
TESTS_REGISTRY = [
    (1, "Регистрация и контекст пользователя", test_mod_01),
    (2, "Быстрый ввод трат и доходов (текст)", test_mod_02),
    (3, "Голосовой ввод операций", test_mod_03),
    (4, "Интерактивная классификация статей", test_mod_04),
    (5, "Голосовое и текстовое редактирование", test_mod_05),
    (6, "Пакетная привязка категорий к списку", test_mod_06),
    (7, "Пакетное редактирование сумм и названий", test_mod_07),
    (8, "Пакетное и точечное удаление записей", test_mod_08),
    (9, "Выписка и история транзакций", test_mod_09),
    (10, "Распознавание чека (общая сумма)", test_mod_10),
    (11, "Построчный разбор кассовых чеков", test_mod_11),
    (12, "Пакетная авто-классификация чека", test_mod_12),
    (13, "Очередь нераспознанных операций", test_mod_13),
    (14, "Обучение бота новым синонимам", test_mod_14),
    (15, "Импорт банковских выписок (CSV/XLSX)", test_mod_15),
    (16, "Управление структурой (CRUD статей)", test_mod_16),
    (17, "Двусторонняя синхронизация словарей", test_mod_17),
    (18, "Административная веб-панель", test_mod_18),
    (19, "Навигация и управление состояниями", test_mod_19),
]

def run_all_self_tests():
    """Запускает полный аудит всех 19 модулей и возвращает сводку."""
    print("=" * 65)
    print("🚀 СТАРТ СКВОЗНОГО АУДИТА СИСТЕМЫ «ОРАКУЛ» (19 МОДУЛЕЙ)")
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
        time.sleep(0.15) # Микропауза для стабильности вебхука Таблицы

    print("=" * 65)
    pct = round((passed / len(TESTS_REGISTRY)) * 100, 1)
    print(f"🏁 ИТОГИ АУДИТА: Успешно: {passed}/{len(TESTS_REGISTRY)} ({pct}%) | Сбоев: {failed}")
    print("=" * 65)
    return passed, failed, errors

if __name__ == "__main__":
    run_all_self_tests()
