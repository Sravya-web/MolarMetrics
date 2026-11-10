"""CSV export of analysis results (shared by the Streamlit app and the web API).

Beginner notes
--------------
* Money is written as exact rupees converted from integer paise
  (``paise_to_plain``), so a downloaded file never shows float drift.
* Spreadsheet programs run a cell as a formula when its text starts with
  ``=``, ``+``, ``-`` or ``@``. Text that came from a data file (a procedure or
  dentist name, a dataset name) could therefore smuggle a formula into a
  download. ``csv_safe_text`` neutralises such TEXT cells with a leading
  apostrophe. Numeric columns are never touched, so ``-1500.00`` stays a number.
"""

from __future__ import annotations

import csv
import io
import re

from molarmetrics.analytics.results import AnalysisResult, sanitize_text
from molarmetrics.money import paise_to_plain

# Characters that make a spreadsheet treat a cell as a formula (ASCII and the
# full-width forms some spreadsheet locales also accept), plus tab/CR/LF.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r", "\n", "＝", "＋", "－", "＠")


def csv_safe_text(value) -> str:
    """Make one TEXT cell safe to open in a spreadsheet. Numbers must not be
    passed through this (they would gain an apostrophe)."""
    if value is None:
        return ""
    text = str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def write_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def result_csv_rows(result: AnalysisResult, dataset_label: str | None = None) -> list[dict]:
    """Exact values for download: INR from integer paise, plain counts and
    percentages, formula-safe text. ``dataset_label`` adds a dataset column."""
    if result.rows:
        rows = []
        for row in result.rows:
            rec = {}
            for c in result.columns:
                v = row.get(c.key)
                if c.kind == "inr":
                    rec[c.key.replace("_paise", "_inr")] = None if v is None else paise_to_plain(v)
                elif c.kind == "text":
                    rec[c.key] = None if v is None else csv_safe_text(sanitize_text(v))
                else:
                    rec[c.key] = v
            rows.append(rec)
    else:
        rows = []
        for s in result.summary:
            value = s.value
            if s.kind == "inr" and value is not None:
                value = paise_to_plain(value)
            elif s.kind == "text" and value is not None:
                value = csv_safe_text(sanitize_text(value, max_len=400))
            rows.append({"metric": csv_safe_text(s.label), "metric_name": s.key, "value": value, "unit": s.unit,
                         "aggregation": s.aggregation, "date_basis": s.date_basis or "",
                         "note": csv_safe_text(s.note or "")})
    for row in rows:
        row["period"] = result.period
        if dataset_label is not None:
            row["dataset"] = csv_safe_text(sanitize_text(dataset_label))
        row["data_notice"] = result.notice
    return rows


def result_csv_bytes(result: AnalysisResult, dataset_label: str | None = None) -> bytes:
    return write_csv(result_csv_rows(result, dataset_label))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def csv_filename(result: AnalysisResult, dataset_label: str | None = None, title: str | None = None) -> str:
    """Download filename. The sample keeps its original ``..._synthetic.csv``
    name; uploaded datasets are named after the dataset and the analysis title
    (never an internal tool name)."""
    if dataset_label is None:
        return f"molarmetrics_{_slug(f'{result.tool}_{result.period}')}_synthetic.csv"
    stem = _slug(f"{dataset_label}_{title or result.title.split(',')[0]}_{result.period}")[:150]
    return f"molarmetrics_{stem}.csv"
