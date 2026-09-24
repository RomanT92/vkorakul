# -*- coding: utf-8 -*-
import os
import re
import json
import tempfile
import requests
import pandas as pd

from services_ai import ai_client
from config import PROMPT_FILE_MAPPING

# ====================================================================
# УМНЫЙ ПАРСИНГ ВЫПИСОК (БАНКИ РФ + ПАНДАС + ИИ)
# ====================================================================
def _clean_amount(raw_val):
    """Очищает и приводит сумму операции к типу float с учетом знака."""
    if raw_val is None:
        return 0.0
    s = str(raw_val).strip()
    if not s or s.lower() in ["nan", "none", "null", ""]:
        return 0.0
    is_negative = ('-' in s) or ('CR' in s.upper())
    clean_s = re.sub(r'[^\d.,]', '', s)
    if not clean_s:
        return 0.0
    if '.' in clean_s and ',' in clean_s:
        if clean_s.rfind(',') > clean_s.rfind('.'):
            clean_s = clean_s.replace('.', '').replace(',', '.')
        else:
            clean_s = clean_s.replace(',', '')
    elif ',' in clean_s:
        clean_s = clean_s.replace(',', '.')
    try:
        val = float(clean_s)
        return -val if is_negative else val
    except ValueError:
        return 0.0

def _detect_bank_columns(df):
    """Автоматически находит индексы колонок в банковских выписках РФ."""
    date_keywords = ["дата операции", "дата платежа", "дата проводки", "дата", "date"]
    amount_keywords = ["сумма операции", "сумма платежа", "сумма в валюте счета", "сумма", "amount"]
    expense_keywords = ["сумма списания", "списание", "расход", "дебет", "debit", "снятие"]
    income_keywords = ["сумма зачисления", "зачисление", "пополнение", "приход", "доход", "кредит", "credit"]
    desc_keywords = ["описание операции", "назначение платежа", "детали платежа", "контрагент", "описание", "получатель", "категория", "merchant", "description"]

    max_scan_rows = min(25, len(df))
    for r_idx in range(max_scan_rows):
        row_cells = [str(cell).lower().strip() for cell in df.iloc[r_idx].values]
        found_date = None
        found_amount = None
        found_expense = None
        found_income = None
        found_desc = None

        for c_idx, cell in enumerate(row_cells):
            if not cell:
                continue
            if found_date is None and any(kw in cell for kw in date_keywords):
                found_date = c_idx
                continue
            if found_expense is None and any(kw in cell for kw in expense_keywords):
                found_expense = c_idx
                continue
            if found_income is None and any(kw in cell for kw in income_keywords):
                found_income = c_idx
                continue
            if found_amount is None and any(kw in cell for kw in amount_keywords):
                found_amount = c_idx
                continue
            if found_desc is None and any(kw in cell for kw in desc_keywords):
                found_desc = c_idx
                continue

        has_amount = (found_amount is not None) or (found_expense is not None and found_income is not None)
        if found_date is not None and has_amount and found_desc is not None:
            return {
                "header_row": r_idx,
                "date_col": found_date,
                "desc_col": found_desc,
                "amount_col": found_amount,
                "expense_col": found_expense,
                "income_col": found_income
            }
    return None

def parse_bank_file_with_ai(file_url, file_ext):
    """Скачивает файл выписки, определяет его структуру и возвращает плоский список операций."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(file_url, headers=headers, timeout=35)
        if response.status_code != 200:
            return {"status": "ERROR", "message": f"Не удалось скачать файл от ВК (HTTP {response.status_code})"}

        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            temp_file.write(response.content)
            temp_file_path = temp_file.name

        dfs = {}
        if file_ext == ".csv":
            loaded_df = None
            for enc in ["utf-8-sig", "windows-1251", "utf-8", "cp1251"]:
                for sep in [";", ",", "\t"]:
                    try:
                        test_df = pd.read_csv(temp_file_path, header=None, dtype=str, encoding=enc, sep=sep, on_bad_lines='skip')
                        if test_df.shape[1] > 1 and len(test_df) > 0:
                            loaded_df = test_df
                            break
                    except Exception:
                        continue
                if loaded_df is not None:
                    break
            if loaded_df is None:
                loaded_df = pd.read_csv(temp_file_path, header=None, dtype=str, errors='replace')
            dfs = {"Выписка": loaded_df}
        else:
            try:
                dfs = pd.read_excel(temp_file_path, sheet_name=None, header=None, dtype=str)
            except Exception:
                dfs = pd.read_excel(temp_file_path, sheet_name=None, header=None, dtype=str, engine='openpyxl')

        os.remove(temp_file_path)

        parsed_operations = []
        for sheet_name, df in dfs.items():
            if df is None or df.empty or len(df) < 2:
                continue

            auto_meta = _detect_bank_columns(df)
            if auto_meta is not None:
                h_idx = auto_meta["header_row"]
                d_col = auto_meta["date_col"]
                desc_col = auto_meta["desc_col"]
                amt_col = auto_meta["amount_col"]
                exp_col = auto_meta["expense_col"]
                inc_col = auto_meta["income_col"]

                for i in range(h_idx + 1, len(df)):
                    row = df.iloc[i].values
                    if d_col >= len(row) or desc_col >= len(row):
                        continue
                    date_val = str(row[d_col]).strip()
                    desc_val = str(row[desc_col]).strip()
                    if not date_val or not desc_val or date_val.lower() in ["nan", "none", "nat", "дата"]:
                        continue

                    final_amount = 0.0
                    op_type = "Расход"

                    if exp_col is not None and inc_col is not None:
                        exp_amt = abs(_clean_amount(row[exp_col])) if exp_col < len(row) else 0.0
                        inc_amt = abs(_clean_amount(row[inc_col])) if inc_col < len(row) else 0.0
                        if inc_amt > 0:
                            final_amount = inc_amt
                            op_type = "Доход"
                        elif exp_amt > 0:
                            final_amount = exp_amt
                            op_type = "Расход"
                    elif amt_col is not None and amt_col < len(row):
                        raw_amt = _clean_amount(row[amt_col])
                        if raw_amt > 0:
                            final_amount = raw_amt
                            op_type = "Доход" if any(w in desc_val.lower() for w in ["зарплата", "пополнение", "перевод от", "аванс"]) else "Расход"
                        elif raw_amt < 0:
                            final_amount = abs(raw_amt)
                            op_type = "Расход"

                    if final_amount > 0:
                        parsed_operations.append([date_val, op_type, final_amount, desc_val])

                if len(parsed_operations) > 0:
                    continue

            # Резервный анализ через GPT-4o
            sample_df = df.head(50).fillna("")
            csv_sample = sample_df.to_csv(index=False, sep=";")
            try:
                ai_response = ai_client.chat.completions.create(
                    model="gemini-2.5-flash",
                    temperature=0.0,
                    messages=[
                        {"role": "system", "content": PROMPT_FILE_MAPPING},
                        {"role": "user", "content": f"Вкладка: {sheet_name}\nСтроки файла:\n{csv_sample}"}
                    ]
                )
                mapping_text = ai_response.choices[0].message.content.strip()
                match = re.search(r'\{.*\}', mapping_text, re.DOTALL)
                if not match:
                    continue
                mapping = json.loads(match.group(0))
                file_type = mapping.get("file_type")

                if file_type == "flat":
                    h_idx = int(mapping.get("header_row_index") or 0)
                    d_col = int(mapping.get("date_col_idx") or 0)
                    desc_col = int(mapping.get("desc_col_idx") or 1)
                    amt_col = mapping.get("amount_col_idx")
                    amt_col = int(amt_col) if amt_col is not None else None
                    is_signed = mapping.get("is_amount_signed", False)

                    for i in range(h_idx + 1, len(df)):
                        row = df.iloc[i].values
                        if d_col >= len(row) or desc_col >= len(row):
                            continue
                        date_val = str(row[d_col]).strip()
                        desc_val = str(row[desc_col]).strip()
                        if not date_val or not desc_val or date_val.lower() in ["nan", "none", "nat"]:
                            continue
                        if amt_col is not None and amt_col < len(row):
                            val = _clean_amount(row[amt_col])
                            op_type = "Доход" if (is_signed and val > 0) else "Расход"
                            final_amt = abs(val)
                            if final_amt > 0:
                                parsed_operations.append([date_val, op_type, final_amt, desc_val])

                elif file_type == "matrix":
                    h_idx = int(mapping.get("header_row_index") or 0)
                    cat_col = int(mapping.get("category_col_idx") or 0)
                    start_col = int(mapping.get("date_start_col_idx") or 1)
                    days_row = df.iloc[h_idx].values

                    stop_words = ["план", "факт", "баланс", "итого", "максимум", "минимум", "средне", "осталось", "резерв", "долг"]
                    for i in range(h_idx + 1, len(df)):
                        row = df.iloc[i].values
                        if cat_col >= len(row):
                            continue
                        cat_name = str(row[cat_col]).strip()
                        if not cat_name or cat_name.lower() in ["nan", "none"]:
                            continue
                        if any(w in cat_name.lower() for w in stop_words):
                            continue

                        for col_idx in range(start_col, len(row)):
                            day_val = str(days_row[col_idx]).strip() if col_idx < len(days_row) else ""
                            amt = abs(_clean_amount(row[col_idx]))
                            if amt > 0 and day_val and day_val.lower() not in ["nan", "none"]:
                                parsed_operations.append([f"{day_val} число ({sheet_name})", "Расход", amt, cat_name])

            except Exception as e_sheet:
                print(f"Ошибка ИИ-маппинга листа {sheet_name}: {e_sheet}")
                continue

        if not parsed_operations:
            return {"status": "ERROR", "message": "Не удалось найти финансовые операции в файле."}
        return {"status": "SUCCESS", "operations": parsed_operations}

    except Exception as e:
        print(f"Критическая ошибка парсинга: {e}")
        return {"status": "ERROR", "message": str(e)}
