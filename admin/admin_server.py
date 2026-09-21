# -*- coding: utf-8 -*-
import os
import json
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List, Optional
from db.connection import get_db_connection

app = FastAPI(title="Оракул Admin | FastAPI Backend")

# ====================================================================
# HTML ШАБЛОНЫ (ИНТЕРФЕЙС АДМИНКИ)
# ====================================================================
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
if not os.path.exists(templates_dir):
    os.makedirs(templates_dir, exist_ok=True)

templates = Jinja2Templates(directory=templates_dir)

@app.get("/", response_class=HTMLResponse)
async def admin_index(request: Request):
    """Главная страница панели управления."""
    return templates.TemplateResponse("index.html", {"request": request})

# ====================================================================
# СЕРВИСНЫЕ И ДИАГНОСТИЧЕСКИЕ ЭНДПОИНТЫ
# ====================================================================
@app.get("/api/ping")
async def ping_db():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
        return {"status": "SUCCESS", "message": "Подключение к Supabase PostgreSQL активно!"}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

@app.get("/api/stats")
async def get_system_stats():
    """Сводные метрики эталона и очереди модерации."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # 1. Метрики эталона
                cur.execute("""
                    SELECT 
                        COUNT(DISTINCT category) as cats,

                        COUNT(DISTINCT (category || '|' || subcategory)) as subs,
                        COUNT(DISTINCT (category || '|' || subcategory || '|' || article)) as arts,
                        COUNT(*) as syns
                    FROM global_dictionary;
                """)
                g_row = cur.fetchone()
                
                # 2. Метрики модерации
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

        return {
            "status": "SUCCESS",
            "stats": {
                "categories": g_row[0] or 0,
                "subcategories": g_row[1] or 0,
                "articles": g_row[2] or 0,
                "synonyms": g_row[3] or 0,
                "pending": m_row[0] or 0,
                "trash": m_row[1] or 0
            }
        }
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

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

        return {
            "status": "SUCCESS",
            "items": items,
            "tree": tree
        }
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

class MovePayload(BaseModel):
    level: str # 'subcategory' или 'article'
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
        return {"status": "SUCCESS"}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

class EntityPayload(BaseModel):
    level: str # 'category', 'subcategory', 'article'
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
        return {"status": "SUCCESS"}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

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
        return {"status": "SUCCESS"}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

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
        return {"status": "SUCCESS"}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

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
        return {"status": "SUCCESS", "rows": results}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

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
        return {"status": "SUCCESS", "rows": results}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

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
        return {"status": "SUCCESS", "count": len(to_insert)}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

@app.post("/api/words/trash")
async def trash_words(p: BatchIds):
    """Отправка записей в корзину (is_deleted = TRUE)."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE user_dictionary SET is_deleted = TRUE WHERE id = ANY(%s);", (p.ids,))
                conn.commit()
        return {"status": "SUCCESS", "count": len(p.ids)}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

@app.post("/api/words/restore")
async def restore_words(p: BatchIds):
    """Восстановление записей из корзины."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE user_dictionary SET is_deleted = FALSE WHERE id = ANY(%s);", (p.ids,))
                conn.commit()
        return {"status": "SUCCESS", "count": len(p.ids)}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}
