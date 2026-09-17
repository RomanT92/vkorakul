// ====================================================================
// ВЕБ-ПРИЛОЖЕНИЕ: АДМИН-ПАНЕЛЬ СИСТЕМЫ «ОРАКУЛ» v6.4
// ====================================================================

var DB_CONFIG = {
  host: "aws-0-eu-central-1.pooler.supabase.com",
  port: 6543,
  database: "postgres",
  user: "postgres.lgmwmzzvhqvpihwttlsb",
  password: "W3geb8KYdbase"
};

function getJdbcConnection() {
  var url = "jdbc:postgresql://" + DB_CONFIG.host + ":" + DB_CONFIG.port + "/" + DB_CONFIG.database + "?sslmode=require";
  return Jdbc.getConnection(url, DB_CONFIG.user, DB_CONFIG.password);
}

function doGet(e) {
  var template = HtmlService.createTemplateFromFile('index');
  return template.evaluate()
    .setTitle('Оракул Admin | Центр управления')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/**
 * КНОПКА 1: СИНХРОНИЗАЦИЯ С POSTGRESQL (Загрузка эталона из Таблицы в БД)
 */
function syncGlobalBaseToPostgres() {
  var conn = null;
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName("База Синонимов");
    if (!sheet) return { status: "ERROR", message: "Лист 'База Синонимов' не найден" };

    var data = sheet.getDataRange().getValues();
    if (data.length < 2) return { status: "ERROR", message: "В таблице нет данных" };

    var recordsToInsert = [];

    for (var i = 1; i < data.length; i++) {
      var row = data[i];
      var isChecked = row[0];

      if (isChecked === true || isChecked === "TRUE") {
        var opType = (row[1] || "Расход").toString().trim();
        if (opType === "Приход") opType = "Доход";
        var cat = (row[2] || "").toString().trim();
        var sub = (row[3] || "").toString().trim();
        var art = (row[4] || "").toString().trim();

        if (!cat || !sub || !art) continue;

        // Базовое слово статьи
        recordsToInsert.push({
          type: opType, category: cat, subcategory: sub, article: art, synonym: art.toLowerCase().trim()
        });

        // Синонимы из строки
        for (var col = 5; col < row.length; col++) {
          var syn = (row[col] || "").toString().trim().toLowerCase();
          if (syn && syn !== art.toLowerCase().trim()) {
            recordsToInsert.push({
              type: opType, category: cat, subcategory: sub, article: art, synonym: syn
            });
          }
        }
      }
    }

    if (recordsToInsert.length === 0) {
      return { status: "ERROR", message: "Нет утвержденных строк (с галочкой) для отправки в базу" };
    }

    conn = getJdbcConnection();
    conn.setAutoCommit(false);

    var stmt = conn.createStatement();
    // Очищаем старый глобальный справочник
    stmt.execute("TRUNCATE TABLE global_dictionary RESTART IDENTITY CASCADE;");

    var insertSql = "INSERT INTO global_dictionary (type, category, subcategory, article, synonym, is_default) VALUES (?, ?, ?, ?, ?, TRUE) ON CONFLICT DO NOTHING;";
    var pstmt = conn.prepareStatement(insertSql);

    for (var j = 0; j < recordsToInsert.length; j++) {
      var r = recordsToInsert[j];
      pstmt.setString(1, r.type);
      pstmt.setString(2, r.category);
      pstmt.setString(3, r.subcategory);
      pstmt.setString(4, r.article);
      pstmt.setString(5, r.synonym);
      pstmt.addBatch();

      if (j % 500 === 0) {
        pstmt.executeBatch();
      }
    }
    pstmt.executeBatch();
    conn.commit();

    return { status: "SUCCESS", count: recordsToInsert.length };
  } catch (err) {
    if (conn) {
      try { conn.rollback(); } catch(e){}
    }
    return { status: "ERROR", message: err.toString() };
  } finally {
    if (conn) {
      try { conn.close(); } catch(e){}
    }
  }
}

/**
 * КНОПКА 2: СБОР НОВЫХ СЛОВ ИЗ POSTGRESQL (Забирает слова пользователей из БД в Таблицу)
 */
function fetchNewWordsFromPostgres() {
  var conn = null;
  try {
    conn = getJdbcConnection();
    var stmt = conn.createStatement();
    
    var query = "SELECT DISTINCT u.type, u.category, u.subcategory, u.article, u.synonym " +
                "FROM user_dictionary u " +
                "WHERE u.is_deleted = FALSE " +
                "  AND NOT EXISTS ( " +
                "      SELECT 1 FROM global_dictionary g " +
                "      WHERE LOWER(g.synonym) = LOWER(u.synonym) " +
                "        AND g.type = u.type " +
                "  ) " +
                "ORDER BY u.type, u.category, u.subcategory, u.article;";

    var rs = stmt.executeQuery(query);
    var newWords = [];

    while (rs.next()) {
      newWords.push([
        false, // Чекбокс выключен для модерации
        rs.getString("type"),
        rs.getString("category"),
        rs.getString("subcategory"),
        rs.getString("article"),
        rs.getString("synonym")
      ]);
    }

    rs.close();
    stmt.close();

    if (newWords.length === 0) {
      return { status: "SUCCESS", count: 0, message: "Все слова пользователей уже есть в глобальной базе!" };
    }

    // Записываем новые строки в конец листа "База Синонимов"
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName("База Синонимов");
    var lastRow = sheet.getLastRow();

    sheet.getRange(lastRow + 1, 1, newWords.length, 6).setValues(newWords);
    sheet.getRange(lastRow + 1, 1, newWords.length, 1).setDataValidation(SpreadsheetApp.newDataValidation().requireCheckbox().build());

    return { status: "SUCCESS", count: newWords.length };
  } catch (err) {
    return { status: "ERROR", message: err.toString() };
  } finally {
    if (conn) {
      try { conn.close(); } catch(e){}
    }
  }
}

/**
 * ПОЛУЧЕНИЕ КАТАЛОГА ГЛОБАЛЬНОЙ БАЗЫ
 */
function getGlobalCatalogData() {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName("База Синонимов");
    if (!sheet) return { status: "ERROR", message: "Лист 'База Синонимов' не найден" };

    var data = sheet.getDataRange().getValues();
    if (data.length < 2) {
      return { status: "SUCCESS", items: [], tree: {}, stats: { categories: 0, subcategories: 0, articles: 0, synonyms: 0 } };
    }

    var items = [];
    var tree = { "Расход": {}, "Доход": {} };
    var uniqueCats = new Set();
    var uniqueSubs = new Set();
    var totalArticles = 0;
    var totalSynonyms = 0;

    for (var i = 1; i < data.length; i++) {
      var row = data[i];
      var isChecked = row[0];

      if (isChecked === true || isChecked === "TRUE") {
        var opType = (row[1] || "Расход").toString().trim();
        if (opType === "Приход") opType = "Доход";
        var cat = (row[2] || "").toString().trim();
        var sub = (row[3] || "").toString().trim();
        var art = (row[4] || "").toString().trim();

        if (!cat || !sub || !art) continue;

        uniqueCats.add(opType + "|" + cat);
        uniqueSubs.add(opType + "|" + cat + "|" + sub);
        totalArticles++;

        var syns = [];
        for (var col = 5; col < row.length; col++) {
          var val = (row[col] || "").toString().trim();
          if (val) syns.push(val);
        }
        totalSynonyms += syns.length;

        items.push({
          rowIndex: i + 1,
          type: opType,
          category: cat,
          subcategory: sub,
          article: art,
          synonyms: syns.join(", "),
          synonymsCount: syns.length
        });

        if (!tree[opType]) tree[opType] = {};
        if (!tree[opType][cat]) tree[opType][cat] = {};
        if (!tree[opType][cat][sub]) tree[opType][cat][sub] = [];
        tree[opType][cat][sub].push({
          rowIndex: i + 1,
          article: art,
          synonyms: syns
        });
      }
    }

    return {
      status: "SUCCESS",
      items: items,
      tree: tree,
      stats: {
        categories: uniqueCats.size,
        subcategories: uniqueSubs.size,
        articles: totalArticles,
        synonyms: totalSynonyms
      }
    };
  } catch (err) {
    return { status: "ERROR", message: err.toString() };
  }
}

/**
 * СОЗДАНИЕ, ПЕРЕИМЕНОВАНИЕ, УДАЛЕНИЕ И ПЕРЕНОС СУЩНОСТЕЙ
 */
function addGlobalEntity(payload) {
  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("База Синонимов");
    if (!sheet) return { status: "ERROR", message: "Лист не найден" };

    var level = payload.level;
    var type = payload.type || "Расход";
    var cat = (payload.category || "").trim();
    var sub = (payload.subcategory || "").trim();
    var art = (payload.article || "").trim();
    var synsRaw = payload.synonyms || "";

    if (!cat) return { status: "ERROR", message: "Укажите категорию" };

    if (level === "category") {
      if (!sub) sub = "Другое " + cat.toLowerCase();
      if (!art) art = "Другое " + sub.toLowerCase();
    } else if (level === "subcategory") {
      if (!sub) return { status: "ERROR", message: "Укажите подкатегорию" };
      if (!art) art = "Другое " + sub.toLowerCase();
    } else if (level === "article") {
      if (!sub || !art) return { status: "ERROR", message: "Укажите подкатегорию и статью" };
    }

    var synsList = synsRaw ? synsRaw.split(",").map(function(s){ return s.trim(); }).filter(Boolean) : [];
    var rowToAppend = [true, type, cat, sub, art].concat(synsList);

    sheet.appendRow(rowToAppend);
    var lastRow = sheet.getLastRow();
    sheet.getRange(lastRow, 1).setDataValidation(SpreadsheetApp.newDataValidation().requireCheckbox().build());

    return { status: "SUCCESS" };
  } catch (err) {
    return { status: "ERROR", message: err.toString() };
  }
}

function renameGlobalEntity(payload) {
  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("База Синонимов");
    if (!sheet) return { status: "ERROR", message: "Лист не найден" };

    var level = payload.level;
    var type = payload.type;
    var cat = payload.category;
    var sub = payload.subcategory;
    var oldName = (payload.oldName || "").trim();
    var newName = (payload.newName || "").trim();

    if (!newName) return { status: "ERROR", message: "Новое имя не может быть пустым" };

    var data = sheet.getDataRange().getValues();
    var updated = 0;

    for (var i = 1; i < data.length; i++) {
      var rowType = (data[i][1] || "").toString().trim();
      if (rowType === "Приход") rowType = "Доход";
      if (rowType !== type) continue;

      if (level === "category" && data[i][2] === oldName) {
        data[i][2] = newName;
        updated++;
      } else if (level === "subcategory" && data[i][2] === cat && data[i][3] === oldName) {
        data[i][3] = newName;
        if (data[i][4] === ("Другое " + oldName.toLowerCase())) {
          data[i][4] = "Другое " + newName.toLowerCase();
        }
        updated++;
      } else if (level === "article" && data[i][2] === cat && data[i][3] === sub && data[i][4] === oldName) {
        data[i][4] = newName;
        updated++;
      }
    }

    if (updated > 0) {
      sheet.getRange(1, 1, data.length, data[0].length).setValues(data);
      return { status: "SUCCESS", updatedCount: updated };
    }
    return { status: "ERROR", message: "Совпадений не найдено" };
  } catch (err) {
    return { status: "ERROR", message: err.toString() };
  }
}

function deleteGlobalEntity(payload) {
  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("База Синонимов");
    if (!sheet) return { status: "ERROR", message: "Лист не найден" };

    var level = payload.level;
    var type = payload.type;
    var cat = payload.category;
    var sub = payload.subcategory;
    var art = payload.article;

    var data = sheet.getDataRange().getValues();
    var rowsToDelete = [];

    for (var i = 1; i < data.length; i++) {
      var rowType = (data[i][1] || "").toString().trim();
      if (rowType === "Приход") rowType = "Доход";
      if (rowType !== type) continue;

      var match = false;
      if (level === "category" && data[i][2] === cat) match = true;
      else if (level === "subcategory" && data[i][2] === cat && data[i][3] === sub) match = true;
      else if (level === "article" && data[i][2] === cat && data[i][3] === sub && data[i][4] === art) match = true;

      if (match) rowsToDelete.push(i + 1);
    }

    if (rowsToDelete.length === 0) return { status: "ERROR", message: "Строки не найдены" };

    rowsToDelete.sort(function(a, b) { return b - a; });
    for (var d = 0; d < rowsToDelete.length; d++) {
      sheet.deleteRow(rowsToDelete[d]);
    }
    return { status: "SUCCESS", deletedCount: rowsToDelete.length };
  } catch (err) {
    return { status: "ERROR", message: err.toString() };
  }
}

function moveGlobalEntity(payload) {
  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("База Синонимов");
    if (!sheet) return { status: "ERROR", message: "Лист не найден" };

    var level = payload.level;
    var type = payload.type;
    var fromCat = payload.fromCategory;
    var fromSub = payload.fromSubcategory;
    var toCat = payload.toCategory;
    var toSub = payload.toSubcategory;
    var art = payload.article;

    var data = sheet.getDataRange().getValues();
    var updated = 0;

    for (var i = 1; i < data.length; i++) {
      var rowType = (data[i][1] || "").toString().trim();
      if (rowType === "Приход") rowType = "Доход";
      if (rowType !== type) continue;

      if (level === "subcategory") {
        if (data[i][2] === fromCat && data[i][3] === fromSub) {
          data[i][2] = toCat;
          updated++;
        }
      } else if (level === "article") {
        if (data[i][2] === fromCat && data[i][3] === fromSub && data[i][4] === art) {
          data[i][2] = toCat;
          data[i][3] = toSub;
          updated++;
        }
      }
    }

    if (updated > 0) {
      sheet.getRange(1, 1, data.length, data[0].length).setValues(data);
      return { status: "SUCCESS", updatedCount: updated };
    }
    return { status: "ERROR", message: "Строки не найдены" };
  } catch (err) {
    return { status: "ERROR", message: err.toString() };
  }
}

/**
 * МОДЕРАЦИЯ ПОЛЬЗОВАТЕЛЬСКИХ СЛОВ
 */
function getUserWordsData() {
  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("База Синонимов");
    if (!sheet) return { status: "ERROR", message: "Лист не найден" };

    var data = sheet.getDataRange().getValues();
    if (data.length < 2) return { status: "SUCCESS", rows: [], categories: [] };

    var pendingRows = [];
    var categoriesSet = {};

    for (var i = 1; i < data.length; i++) {
      var row = data[i];
      var isChecked = row[0];

      if (isChecked === false || isChecked === "" || isChecked === "FALSE") {
        var opType = (row[1] || "Расход").toString().trim();
        if (opType === "Приход") opType = "Доход";
        var cat = (row[2] || "").toString().trim();
        var sub = (row[3] || "").toString().trim();
        var art = (row[4] || "").toString().trim();

        if (cat) categoriesSet[cat] = true;

        var syns = [];
        for (var col = 5; col < row.length; col++) {
          var val = (row[col] || "").toString().trim();
          if (val) syns.push(val);
        }

        pendingRows.push({
          rowIndex: i + 1,
          type: opType,
          category: cat || "Не указана",
          subcategory: sub || "Не указана",
          article: art || "—",
          synonyms: syns.length > 0 ? syns.join(", ") : art
        });
      }
    }

    return {
      status: "SUCCESS",
      rows: pendingRows,
      categories: Object.keys(categoriesSet).sort()
    };
  } catch (err) {
    return { status: "ERROR", message: err.toString() };
  }
}

function approveWordsBatch(rowIndices) {
  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("База Синонимов");
    if (!sheet) return { status: "ERROR", message: "Лист не найден" };
    rowIndices.forEach(function(r) { sheet.getRange(r, 1).setValue(true); });
    return { status: "SUCCESS", updatedCount: rowIndices.length };
  } catch (err) {
    return { status: "ERROR", message: err.toString() };
  }
}

function deleteWordsBatch(rowIndices) {
  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("База Синонимов");
    if (!sheet) return { status: "ERROR", message: "Лист не найден" };
    var sorted = rowIndices.slice().sort(function(a, b) { return b - a; });
    for (var i = 0; i < sorted.length; i++) { sheet.deleteRow(sorted[i]); }
    return { status: "SUCCESS", deletedCount: sorted.length };
  } catch (err) {
    return { status: "ERROR", message: err.toString() };
  }
}

function getSystemOverviewStats() {
  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("База Синонимов");
    var totalRows = sheet ? Math.max(0, sheet.getLastRow() - 1) : 0;
    var data = sheet ? sheet.getRange(2, 1, totalRows, 1).getValues() : [];
    var pendingCount = 0;
    for (var i = 0; i < data.length; i++) {
      if (data[i][0] === false || data[i][0] === "" || data[i][0] === "FALSE") pendingCount++;
    }
    return {
      status: "SUCCESS",
      totalDictionaryWords: totalRows,
      pendingCount: pendingCount,
      approvedCount: totalRows - pendingCount
    };
  } catch (e) {
    return { status: "ERROR", message: e.toString() };
  }
}
