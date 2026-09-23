# -*- coding: utf-8 -*-
import os
import json
import time
import threading
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from db.connection import get_db_connection

app = FastAPI(title="Оракул Admin | FastAPI Backend")

# ====================================================================
# ЕДИНАЯ ПАПКА ADMIN ДЛЯ ШАБЛОНОВ И СТАТИКИ (АБСОЛЮТНЫЙ РЕЗОЛВ)
# ====================================================================
admin_dir = Path(__file__).resolve().parent

app.mount("/static", StaticFiles(directory=str(admin_dir)), name="static")
templates = Jinja2Templates(directory=str(admin_dir))

# ====================================================================
# IN-MEMORY ХРАНИЛИЩЕ СОСТОЯНИЯ МОНИТОРИНГА (WATCHDOG & 26 МОДУЛЕЙ)
# ====================================================================
SYSTEM_HEALTH_STATE: Dict[str, Any] = {
    "last_heartbeat": 0.0,
    "bot_version": "6.5.0",
    "trigger_test_requested": False,
    "module_statuses": {}
}

MODULES_REGISTRY = [
    # СЛОЙ 1: Диспетчеризация, Авторизация и FSM
    {"num": 1, "name": "Авторизация и профиль пользователя", "files": "db/connection.py, db/transactions.py", "test_cmd": "/start, начать, любое сообщение", "layer": "Core / Auth", "default_status": "Не проверялся"},
    {"num": 2, "name": "Диспетчер намерений (Надрежим)", "files": "config.py, handlers_transaction.py", "test_cmd": "Привет, Что умеешь?, помощь", "layer": "NLP / Router", "default_status": "Не проверялся"},
    {"num": 3, "name": "Свободный диалог («Поболтать»)", "files": "services.py, handlers_transaction.py", "test_cmd": "Как копить деньги?, Расскажи о бюджете", "layer": "AI / Chat", "default_status": "Не проверялся"},
    {"num": 4, "name": "Управление состояниями (FSM)", "files": "handlers_base.py, keyboards.py", "test_cmd": "отмена, назад, стоп", "layer": "Navigation / FSM", "default_status": "Не проверялся"},

    # СЛОЙ 2: Ввод и распознавание операций
    {"num": 5, "name": "Определение типа (Доход / Расход)", "files": "handlers_tx_parser.py, config.py", "test_cmd": "Зарплата 80000, Премия 15000, Кэшбэк 400", "layer": "NLP / Type", "default_status": "Не проверялся"},
    {"num": 6, "name": "Быстрый ввод траты (Fast-Path)", "files": "handlers_tx_parser.py", "test_cmd": "Такси 500, кофе 250, 300 бензин", "layer": "Parser / Fast-Path", "default_status": "Не проверялся"},
    {"num": 7, "name": "Сложный NLP-ввод с описанием", "files": "handlers_transaction.py, services.py", "test_cmd": "Купил в магните продукты на 1450 рублей", "layer": "NLP / Transaction", "default_status": "Не проверялся"},
    {"num": 8, "name": "Множественный ввод операций", "files": "handlers_transaction.py, handlers_tx_parser.py", "test_cmd": "Такси 300, обед 450, аптека 1200", "layer": "Batch / Parser", "default_status": "Не проверялся"},
    {"num": 9, "name": "Голосовой ввод операций (Whisper)", "files": "main.py, services.py", "test_cmd": "[Голосовое сообщение с перечислением трат]", "layer": "Media / NLP", "default_status": "Не проверялся"},

    # СЛОЙ 3: Интеллектуальный поиск и категоризация
    {"num": 10, "name": "Точный и триграммный поиск синонимов", "files": "db/structure.py, db/transactions.py", "test_cmd": "шиномонтажка, пятерочка, макдак", "layer": "Search / Trigram", "default_status": "Не проверялся"},
    {"num": 11, "name": "LLM-классификатор по меню", "files": "config.py, services.py, db/structure.py", "test_cmd": "Болгарка 4500, Стеклоочиститель 350", "layer": "Business Logic", "default_status": "Не проверялся"},
    {"num": 12, "name": "Валидатор категорий (Anti-Hallucination)", "files": "handlers_tx_parser.py", "test_cmd": "[Проверка недопустимости несуществующих категорий]", "layer": "Validation / Logic", "default_status": "Не проверялся"},
    {"num": 13, "name": "Интерактивное дообучение синонимам", "files": "handlers_learning.py, db/structure.py", "test_cmd": "[Подтверждение новой привязки в диалоге]", "layer": "Active Learning", "default_status": "Не проверялся"},

    # СЛОЙ 4: Редактирование и работа с операциями
    {"num": 14, "name": "Правка суммы последней операции", "files": "handlers_voice_commands.py, db/transactions.py", "test_cmd": "Не 500, а 650; Измени сумму на 1200", "layer": "CRUD / Edit", "default_status": "Не проверялся"},
    {"num": 15, "name": "Правка категории последней операции", "files": "handlers_voice_commands.py, db/transactions.py", "test_cmd": "Перенеси в кафе; Это продукты", "layer": "CRUD / Edit", "default_status": "Не проверялся"},
    {"num": 16, "name": "Отмена / удаление последней операции", "files": "handlers_voice_commands.py, db/transactions.py", "test_cmd": "Отмени последнюю; Удали последнюю трату", "layer": "CRUD / Delete", "default_status": "Не проверялся"},
    {"num": 17, "name": "Пакетная привязка категорий к списку", "files": "handlers_voice_commands.py", "test_cmd": "Второе это другое, третье быт, пятое гигиена", "layer": "Batch Processing", "default_status": "Не проверялся"},
    {"num": 18, "name": "Пакетное редактирование сумм и названий", "files": "handlers_voice_commands.py, db/transactions.py", "test_cmd": "Измени сумму у четвертой на 250, первая огурцы", "layer": "Batch Processing", "default_status": "Не проверялся"},
    {"num": 19, "name": "Пакетное удаление по номерам", "files": "handlers_voice_commands.py, db/transactions.py", "test_cmd": "Удали первую и третью, удали всё", "layer": "Batch / Delete", "default_status": "Не проверялся"},

    # СЛОЙ 5: Чеки, Выписки и Отчёты
    {"num": 20, "name": "Распознавание чека (общая сумма)", "files": "config.py, handlers_receipt.py", "test_cmd": "[Фотография чека из супермаркета]", "layer": "Vision / OCR", "default_status": "Не проверялся"},
    {"num": 21, "name": "Построчный разбор кассовых чеков", "files": "config.py, handlers_receipt.py", "test_cmd": "Разбери чек построчно", "layer": "Vision / Parser", "default_status": "Не проверялся"},
    {"num": 22, "name": "Очередь нераспознанных операций", "files": "handlers_queue.py, handlers_queue_batch.py", "test_cmd": "Разобрать операции, разобрать завалы", "layer": "Queue Management", "default_status": "Не проверялся"},
    {"num": 23, "name": "Импорт банковских выписок (CSV/XLSX)", "files": "config.py, handlers_base.py, db/imports.py", "test_cmd": "Импорт статистики прошлого + [Файл выписки]", "layer": "Data Ingestion", "default_status": "Не проверялся"},
    {"num": 24, "name": "Выписка и история транзакций", "files": "db/transactions.py, handlers_history.py", "test_cmd": "Покажи траты за неделю, выписка", "layer": "Reporting", "default_status": "Не проверялся"},

    # СЛОЙ 6: Управление структурой и Системный контроль
    {"num": 25, "name": "Управление структурой (CRUD статей)", "files": "handlers_structure.py, db/structure.py, keyboards.py", "test_cmd": "Категории и статьи, Создать, Переименовать", "layer": "Metadata CRUD", "default_status": "Не проверялся"},
    {"num": 26, "name": "Сторожевой таймер и панель контроля (Watchdog)", "files": "admin/admin_server.py, test_runner.py", "test_cmd": "Пинг бота каждые 30с, кнопка [Запустить автотест]", "layer": "Watchdog / Health", "default_status": "В строю"}
]

@app.get("/", response_class=HTMLResponse)
async def admin_index(request: Request):
    """Главная страница панели управления."""
    return templates.TemplateResponse(request=request, name="index.html")

# ====================================================================
# СЕРВИСНЫЕ И ДИАГНОСТИЧЕСКИЕ ЭНДПОИНТЫ
# ====================================================================
@app.get("/api/ping")
async def ping_db():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
        return JSONResponse(content={"status": "SUCCESS", "message": "Подключение к Supabase PostgreSQL активно!"})
    except Exception as e:
        return JSONResponse(content={"status": "ERROR", "message": str(e)})

@app.get("/api/stats")
async def get_system_stats():
    """Сводные метрики эталона и очереди модерации."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        COUNT(DISTINCT category) as cats,

                        COUNT(DISTINCT (category || '|' || subcategory)) as subs,
                        COUNT(DISTINCT (category || '|' || subcategory || '|' || article)) as arts,
                        COUNT(*) as syns
                    FROM global_dictionary;
                """)
                g_row = cur.fetchone()
                
                cur.execute("""
                    SELECT 
                        COUNT(*) FILTER (WHERE is_deleted = FALSE) as pending,
                        COUNT(*) FILTER (WHERE is_deleted = TRUE) as trash
                    FROM user_dictionary u
                    WHERE NOT EXISTS (
                        SELECT 1 FROM global_dictionary g 
                        WHERE LOWER(g.synonym) = LOWER(u.synonym) AND g.type = u.type
                    );
                """)
                m_row = cur.fetchone()

        return JSONResponse(content={
            "status": "SUCCESS",
            "stats": {
                "categories": g_row[0] or 0,
                "subcategories": g_row[1] or 0,
                "articles": g_row[2] or 0,
                "synonyms": g_row[3] or 0,
                "pending": m_row[0] or 0,
                "trash": m_row[1] or 0
            }
        })
    except Exception as e:
        return JSONResponse(content={"status": "ERROR", "message": str(e)})

# ====================================================================
# МОНИТОРИНГ ФУНКЦИОНАЛА И WATCHDOG (ТЕЛЕМЕТРИЯ БОТА)
# ====================================================================
class HeartbeatPayload(BaseModel):
    bot_version: Optional[str] = "6.5.0"

@app.post("/api/heartbeat")
async def receive_heartbeat(p: HeartbeatPayload):
    """Прием сигналов жизни от бота (раз в 30 секунд)."""
    now = time.time()
    SYSTEM_HEALTH_STATE["last_heartbeat"] = now
    if p.bot_version:
        SYSTEM_HEALTH_STATE["bot_version"] = p.bot_version

    should_run_tests = bool(SYSTEM_HEALTH_STATE.get("trigger_test_requested", False))
    if should_run_tests:
        SYSTEM_HEALTH_STATE["trigger_test_requested"] = False

    return JSONResponse(content={
        "status": "SUCCESS",
        "message": "Heartbeat acknowledged",
        "server_time": now,
        "run_tests": should_run_tests
    })

class ModuleStatusPayload(BaseModel):
    module_num: int
    status: str
    error_details: Optional[str] = ""

@app.post("/api/module_status")
async def update_module_status(p: ModuleStatusPayload):
    """Обновление статуса конкретного модуля (1..26)."""
    if 1 <= p.module_num <= len(MODULES_REGISTRY):
        SYSTEM_HEALTH_STATE["module_statuses"][str(p.module_num)] = {
            "status": p.status,
            "error": p.error_details or "",
            "updated_at": time.time()
        }
        return JSONResponse(content={"status": "SUCCESS", "module_num": p.module_num, "current_status": p.status})
    return JSONResponse(content={"status": "ERROR", "message": f"Номер модуля должен быть от 1 до {len(MODULES_REGISTRY)}"})

@app.get("/api/health")
async def get_system_health():
    """Отдает состояние сторожевого таймера, 26 модулей и процент боеготовности."""
    now = time.time()
    last_hb = SYSTEM_HEALTH_STATE["last_heartbeat"]
    diff_sec = int(now - last_hb) if last_hb > 0 else 999999
    
    timeout_threshold = 75

    is_online = (last_hb > 0) and (diff_sec <= timeout_threshold)

    total_modules = len(MODULES_REGISTRY)
    operational_count = 0
    attention_count = 0

    processed_modules = []
    for m in MODULES_REGISTRY:
        k = str(m["num"])
        dyn = SYSTEM_HEALTH_STATE["module_statuses"].get(k, {})
        base_status = dyn.get("status", m["default_status"])
        err = dyn.get("error", "")
        updated_at = dyn.get("updated_at", None)

        effective_status = base_status if is_online else "Нет связи"

        if effective_status == "В строю":
            operational_count += 1
        else:
            attention_count += 1

        processed_modules.append({
            "num": m["num"],
            "name": m["name"],
            "files": m["files"],
            "test_cmd": m["test_cmd"],
            "layer": m["layer"],
            "status": effective_status,
            "error": err,
            "updated_at": updated_at
        })

    readiness = int(round((operational_count / total_modules) * 100)) if is_online else 0

    return JSONResponse(content={
        "status": "SUCCESS",
        "connection_status": "ONLINE" if is_online else "OFFLINE",
        "last_heartbeat": last_hb,
        "diff_seconds": diff_sec,
        "bot_version": SYSTEM_HEALTH_STATE["bot_version"],
        "total_modules": total_modules,
        "operational_count": operational_count if is_online else 0,
        "attention_count": attention_count if is_online else total_modules,
        "readiness_percentage": readiness,
        "modules": processed_modules
    })

@app.post("/api/trigger_test")
async def trigger_self_test():
    """
    Моментальный запуск полного аудита 26 модулей без задержек.
    Запускает run_all_self_tests() напрямую в фоновом потоке.
    """
    try:
        from test_runner import run_all_self_tests
        threading.Thread(target=run_all_self_tests, daemon=True).start()
        return JSONResponse(content={
            "status": "SUCCESS",
            "message": "Автотесты запущены моментально в фоновом потоке!"
        })
    except Exception as e:
        SYSTEM_HEALTH_STATE["trigger_test_requested"] = True
        return JSONResponse(content={
            "status": "SUCCESS",
            "message": f"Тесты инициированы через очередь: {e}"
        })

# ====================================================================
# КАТАЛОГ И ЭТАЛОН (GLOBAL_DICTIONARY)
# ====================================================================
@app.get("/api/catalog")
async def get_catalog():
    """Возвращает плоский список и иерархическое дерево для Drag & Drop."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, type, category, subcategory, article, synonym
                    FROM global_dictionary
                    ORDER BY type, category, subcategory, article, synonym;
                """)
                rows = cur.fetchall()

        items = []
        tree = {"Расход": {}, "Доход": {}}
        articles_map = {}

        for r in rows:
            r_id, op_type, cat, sub, art, syn = r
            if op_type not in tree:
                tree[op_type] = {}
            if cat not in tree[op_type]:
                tree[op_type][cat] = {}
            if sub not in tree[op_type][cat]:
                tree[op_type][cat][sub] = []

            key = f"{op_type}|{cat}|{sub}|{art}"
            if key not in articles_map:
                art_obj = {"id": r_id, "article": art, "synonyms": []}
                articles_map[key] = art_obj
                tree[op_type][cat][sub].append(art_obj)
            
            if syn and syn.lower() != art.lower():
                articles_map[key]["synonyms"].append(syn)

        for key, art_obj in articles_map.items():
            op_type, cat, sub, art = key.split("|")
            items.append({
                "id": art_obj["id"],
                "type": op_type,
                "category": cat,
                "subcategory": sub,
                "article": art,
                "synonyms": ", ".join(art_obj["synonyms"])
            })

        return JSONResponse(content={
            "status": "SUCCESS",
            "items": items,
            "tree": tree
        })
    except Exception as e:
        return JSONResponse(content={"status": "ERROR", "message": str(e)})

class MovePayload(BaseModel):
    level: str
    type: str
    fromCategory: str
    fromSubcategory: str
    article: Optional[str] = None
    toCategory: str
    toSubcategory: Optional[str] = None

@app.post("/api/catalog/move")
async def move_catalog_entity(p: MovePayload):
    """Перемещение статьи или подкатегории (отработка Drag & Drop)."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                if p.level == 'article':
                    cur.execute("""
                        UPDATE global_dictionary
                        SET category = %s, subcategory = %s
                        WHERE type = %s AND category = %s AND subcategory = %s AND article = %s;
                    """, (p.toCategory, p.toSubcategory, p.type, p.fromCategory, p.fromSubcategory, p.article))
                elif p.level == 'subcategory':
                    cur.execute("""
                        UPDATE global_dictionary
                        SET category = %s
                        WHERE type = %s AND category = %s AND subcategory = %s;
                    """, (p.toCategory, p.type, p.fromCategory, p.fromSubcategory))
                conn.commit()
        return JSONResponse(content={"status": "SUCCESS"})
    except Exception as e:
        return JSONResponse(content={"status": "ERROR", "message": str(e)})

class EntityPayload(BaseModel):
    level: str
    type: str
    category: str
    subcategory: Optional[str] = ""
    article: Optional[str] = ""
    synonyms: Optional[str] = ""

@app.post("/api/catalog/create")
async def create_catalog_entity(p: EntityPayload):
    """Создание категории, подкатегории или статьи в базе."""
    try:
        cat = p.category.strip()
        sub = p.subcategory.strip() if p.subcategory else f"Другое {cat.lower()}"
        art = p.article.strip() if p.article else f"Другое {sub.lower()}"
        
        syn_list = [s.strip() for s in p.synonyms.split(",") if s.strip()] if p.synonyms else []
        if art.lower() not in [s.lower() for s in syn_list]:
            syn_list.insert(0, art)

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for syn in syn_list:
                    cur.execute("""
                        INSERT INTO global_dictionary (type, category, subcategory, article, synonym, is_default)
                        VALUES (%s, %s, %s, %s, %s, TRUE)
                        ON CONFLICT DO NOTHING;
                    """, (p.type, cat, sub, art, syn))
                conn.commit()
        return JSONResponse(content={"status": "SUCCESS"})
    except Exception as e:
        return JSONResponse(content={"status": "ERROR", "message": str(e)})

class RenamePayload(BaseModel):
    level: str
    type: str
    category: str
    subcategory: Optional[str] = ""
    oldName: str
    newName: str

@app.post("/api/catalog/rename")
async def rename_catalog_entity(p: RenamePayload):
    """Переименование категории, подкатегории или статьи."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                if p.level == 'category':
                    cur.execute("""
                        UPDATE global_dictionary SET category = %s
                        WHERE type = %s AND category = %s;
                    """, (p.newName, p.type, p.oldName))
                elif p.level == 'subcategory':
                    cur.execute("""
                        UPDATE global_dictionary SET subcategory = %s
                        WHERE type = %s AND category = %s AND subcategory = %s;
                    """, (p.newName, p.type, p.category, p.oldName))
                elif p.level == 'article':
                    cur.execute("""
                        UPDATE global_dictionary SET article = %s
                        WHERE type = %s AND category = %s AND subcategory = %s AND article = %s;
                    """, (p.newName, p.type, p.category, p.subcategory, p.oldName))
                conn.commit()
        return JSONResponse(content={"status": "SUCCESS"})
    except Exception as e:
        return JSONResponse(content={"status": "ERROR", "message": str(e)})

class DeletePayload(BaseModel):
    level: str
    type: str
    category: str
    subcategory: Optional[str] = ""
    article: Optional[str] = ""

@app.post("/api/catalog/delete")
async def delete_catalog_entity(p: DeletePayload):
    """Удаление сущности из эталона."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                if p.level == 'category':
                    cur.execute("DELETE FROM global_dictionary WHERE type = %s AND category = %s;", (p.type, p.category))
                elif p.level == 'subcategory':
                    cur.execute("DELETE FROM global_dictionary WHERE type = %s AND category = %s AND subcategory = %s;", (p.type, p.category, p.subcategory))
                elif p.level == 'article':
                    cur.execute("DELETE FROM global_dictionary WHERE type = %s AND category = %s AND subcategory = %s AND article = %s;", (p.type, p.category, p.subcategory, p.article))
                conn.commit()
        return JSONResponse(content={"status": "SUCCESS"})
    except Exception as e:
        return JSONResponse(content={"status": "ERROR", "message": str(e)})

# ====================================================================
# МОДЕРАЦИЯ НОВЫХ СЛОВ ПОЛЬЗОВАТЕЛЕЙ (USER_DICTIONARY)
# ====================================================================
@app.get("/api/words/pending")
async def get_pending_words():
    """Слова пользователей, ожидающие одобрения в эталон."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, type, category, subcategory, article, synonym
                    FROM user_dictionary u
                    WHERE is_deleted = FALSE
                      AND NOT EXISTS (
                          SELECT 1 FROM global_dictionary g 
                          WHERE LOWER(g.synonym) = LOWER(u.synonym) AND g.type = u.type
                      )
                    ORDER BY id DESC;
                """)
                rows = cur.fetchall()
        
        results = [{
            "id": r[0], "type": r[1], "category": r[2], 
            "subcategory": r[3], "article": r[4], "synonym": r[5]
        } for r in rows]
        return JSONResponse(content={"status": "SUCCESS", "rows": results})
    except Exception as e:
        return JSONResponse(content={"status": "ERROR", "message": str(e)})

@app.get("/api/words/trash")
async def get_trash_words():
    """Слова, отправленные в корзину."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, type, category, subcategory, article, synonym
                    FROM user_dictionary
                    WHERE is_deleted = TRUE
                    ORDER BY id DESC;
                """)
                rows = cur.fetchall()
        
        results = [{
            "id": r[0], "type": r[1], "category": r[2], 
            "subcategory": r[3], "article": r[4], "synonym": r[5]
        } for r in rows]
        return JSONResponse(content={"status": "SUCCESS", "rows": results})
    except Exception as e:
        return JSONResponse(content={"status": "ERROR", "message": str(e)})

class BatchIds(BaseModel):
    ids: List[int]

@app.post("/api/words/approve")
async def approve_words(p: BatchIds):
    """Одобрение выбранных слов в глобальный эталон."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT type, category, subcategory, article, synonym 
                    FROM user_dictionary WHERE id = ANY(%s);
                """, (p.ids,))
                to_insert = cur.fetchall()

                for row in to_insert:
                    cur.execute("""
                        INSERT INTO global_dictionary (type, category, subcategory, article, synonym, is_default)
                        VALUES (%s, %s, %s, %s, %s, TRUE)
                        ON CONFLICT DO NOTHING;
                    """, row)
                conn.commit()
        return JSONResponse(content={"status": "SUCCESS", "count": len(to_insert)})
    except Exception as e:
        return JSONResponse(content={"status": "ERROR", "message": str(e)})

@app.post("/api/words/trash")
async def trash_words(p: BatchIds):
    """Отправка записей в корзину (is_deleted = TRUE)."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE user_dictionary SET is_deleted = TRUE WHERE id = ANY(%s);", (p.ids,))
                conn.commit()
        return JSONResponse(content={"status": "SUCCESS", "count": len(p.ids)})
    except Exception as e:
        return JSONResponse(content={"status": "ERROR", "message": str(e)})

@app.post("/api/words/restore")
async def restore_words(p: BatchIds):
    """Восстановление записей из корзины."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE user_dictionary SET is_deleted = FALSE WHERE id = ANY(%s);", (p.ids,))
                conn.commit()
        return JSONResponse(content={"status": "SUCCESS", "count": len(p.ids)})
    except Exception as e:
        return JSONResponse(content={"status": "ERROR", "message": str(e)})
