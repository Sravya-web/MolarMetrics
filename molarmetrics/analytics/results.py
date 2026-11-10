"""The structured result every analysis returns.

Beginner note
-------------
An ``AnalysisResult`` is plain, typed data: definitions, the date range used,
the validated arguments, rows, warnings and chart metadata. Every number
carries an explicit UNIT (INR, appointments, patients, treatment records,
payments, percent) and AGGREGATION (sum, count, distinct count, ratio, share,
difference), and each result has ``facts``: short sentences written by
Python, not by the AI model. Two things are made from it:

* ``to_model_content()``: a SHORT JSON summary that goes to the language
  model (facts it can quote, formatted numbers, row count limited).
* The full object is kept by the app (as the tool "artifact") to draw tables
  and charts. Charts are never drawn from the model's prose.
"""

from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from molarmetrics import DATA_NOTICE
from molarmetrics.money import indian_grouping, format_inr, paise_to_plain

ValueKind = Literal["text", "month", "count", "inr", "percent"]
MODEL_MAX_ROWS = 24  # keep large result sets out of the model's context
_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def pct(numerator: int, denominator: int) -> float | None:
    """Percentage rounded half-up to 1 decimal, computed exactly from integers.
    Returns None when the denominator is zero (the rate is undefined)."""
    if not denominator:
        return None
    value = (Decimal(int(numerator)) * 100 / Decimal(int(denominator))).quantize(Decimal("0.1"), ROUND_HALF_UP)
    return float(value)


def month_label(ym: str) -> str:
    """'2025-01' -> 'Jan 2025'."""
    year, month = ym.split("-")
    return f"{_MONTHS[int(month) - 1]} {year}"


def display_date(iso: str) -> str:
    """'2025-01-05' -> '5 Jan 2025' (for display; tools keep ISO dates)."""
    year, month, day = iso.split("-")
    return f"{int(day)} {_MONTHS[int(month) - 1]} {year}"


def display_period(period: str) -> str:
    """'2025-01-01 to 2025-12-31' -> '1 Jan 2025 – 31 Dec 2025'; 'as of 2025-12-31' -> 'As of 31 Dec 2025'."""
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", period or "")
    if period.startswith("as of") and len(dates) == 1:
        return f"As of {display_date(dates[0])}"
    if len(dates) == 2:
        return f"{display_date(dates[0])} – {display_date(dates[1])}"
    return period


def format_value(value: Any, kind: ValueKind) -> str:
    if value is None:
        return "n/a"
    if kind == "inr":
        return format_inr(int(value))
    if kind == "count":
        return indian_grouping(int(value))
    if kind == "percent":
        return f"{float(value):.1f}%"
    if kind == "month":
        return month_label(str(value))
    return sanitize_text(value)


def sanitize_text(value: Any, max_len: int = 120) -> str:
    """Database text is untrusted: strip control characters and cap its length."""
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value))
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def human_period(start: str, end: str) -> str:
    """'2025-01-01', '2025-12-31' -> '1 Jan 2025 to 31 Dec 2025' (used in facts)."""
    return f"{display_date(start)} to {display_date(end)}"


# Documented vocabularies, so every number says what it counts and how.
UNITS = ("INR", "appointments", "patients", "treatment records", "payments", "percent", "text", "month")
AGGREGATIONS = ("sum", "count", "distinct count", "ratio", "share", "difference", "max", "min", "label", "group")


class Column(BaseModel):
    key: str
    label: str
    kind: ValueKind
    unit: str  # one of UNITS
    aggregation: str  # one of AGGREGATIONS

    @property
    def display_label(self) -> str:
        """Label with its unit, e.g. 'Billed revenue (INR)' or 'Scheduled (appointments)'."""
        if self.unit in ("text", "month") or self.unit.lower() in self.label.lower():
            return self.label
        return f"{self.label} ({'%' if self.unit == 'percent' else self.unit})"


class SummaryItem(BaseModel):
    key: str  # the explicit metric name, e.g. "billed_revenue"
    label: str
    value: Any
    kind: ValueKind
    unit: str  # one of UNITS
    aggregation: str  # one of AGGREGATIONS
    date_basis: str | None = None  # "appointment date", "payment date" or "as-of date"
    note: str | None = None  # e.g. the denominator of a rate

    @property
    def formatted(self) -> str:
        if self.kind == "text":  # our own sentences: sanitise, but don't cut them mid-sentence
            return sanitize_text(self.value, max_len=400)
        return format_value(self.value, self.kind)


class ChartSpec(BaseModel):
    """Declarative chart metadata. The app turns this into a Plotly figure with
    fixed, trusted code; no model-generated chart code is ever executed."""

    type: Literal["bar", "grouped_bar", "stacked_bar", "line"]
    x: str
    y: list[str]
    title: str
    y_title: str
    orientation: Literal["v", "h"] = "v"


class AnalysisResult(BaseModel):
    tool: str
    title: str
    # "unavailable": the dataset lacks the records this analysis needs (e.g. an
    # appointments-only upload asked about revenue). Never shown as zeros.
    status: Literal["ok", "empty", "unavailable", "error"] = "ok"
    notice: str = DATA_NOTICE
    arguments: dict[str, Any] = Field(default_factory=dict)
    period: str = ""
    date_range: dict[str, str] = Field(default_factory=dict)  # {"start","end"} or {"as_of"}, inclusive
    facts: list[str] = Field(default_factory=list)  # deterministic sentences written by Python
    definitions: dict[str, str] = Field(default_factory=dict)
    summary: list[SummaryItem] = Field(default_factory=list)
    columns: list[Column] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    chart: ChartSpec | None = None

    # --- views -------------------------------------------------------------------
    def summary_value(self, key: str) -> Any:
        for item in self.summary:
            if item.key == key:
                return item.value
        raise KeyError(key)

    def formatted_rows(self) -> list[dict[str, str]]:
        """Rows with unit-labelled headers and formatted values (for display / the model)."""
        return [{c.display_label: format_value(row.get(c.key), c.kind) for c in self.columns} for row in self.rows]

    def csv_rows(self) -> list[dict[str, Any]]:
        """Rows for CSV download: exact INR values (from paise), plain numbers."""
        out = []
        for row in self.rows:
            rec = {}
            for c in self.columns:
                v = row.get(c.key)
                if c.kind == "inr":
                    rec[c.key.replace("_paise", "_inr")] = None if v is None else paise_to_plain(v)
                elif c.kind == "text":
                    rec[c.key] = None if v is None else sanitize_text(v)
                else:
                    rec[c.key] = v
            out.append(rec)
        return out

    def to_model_content(self, max_rows: int = MODEL_MAX_ROWS) -> str:
        """Compact JSON for the language model. The facts come first: they are
        complete, correct sentences calculated by MolarMetrics, so the model can
        quote them instead of doing arithmetic or choosing its own wording."""
        payload: dict[str, Any] = {
            "tool": self.tool,
            "status": self.status,
            "data": f"{self.notice} (fictional clinic)" if self.notice == DATA_NOTICE else self.notice,
            "date_range": self.date_range,
            "facts_calculated_by_molarmetrics": self.facts,
            "metrics": [
                {"metric": s.key, "label": s.label, "value": s.formatted, "unit": s.unit,
                 "aggregation": s.aggregation,
                 **({"date_basis": s.date_basis} if s.date_basis else {}),
                 **({"note": s.note} if s.note else {})}
                for s in self.summary
            ],
            "arguments_used": self.arguments,
        }
        if self.rows:
            # Units and aggregation are stated ONCE per column (a legend) instead of
            # being repeated in every row, which keeps 24-month tables compact.
            payload["columns"] = {c.label: f"{'%' if c.unit == 'percent' else c.unit}, {c.aggregation}"
                                  for c in self.columns if c.unit not in ("text", "month")}
            rows = [{c.label: format_value(row.get(c.key), c.kind) for c in self.columns} for row in self.rows]
            payload["rows"] = rows[:max_rows]
            if len(rows) > max_rows:
                payload["rows_note"] = f"Showing {max_rows} of {len(rows)} rows; the app displays the full table."
        if self.notes:
            payload["notes"] = self.notes
        if self.warnings:
            payload["warnings"] = self.warnings
        payload["definitions"] = self.definitions
        return json.dumps(payload, ensure_ascii=False)


def unavailable_result(tool: str, title: str, message: str, *, arguments: dict, period: str,
                       date_range: dict[str, str], notice: str) -> AnalysisResult:
    """The dataset cannot answer this (missing record type). The message names
    the records to add; it is a fact so the model can quote it verbatim."""
    return AnalysisResult(tool=tool, title=title, status="unavailable", notice=notice, arguments=arguments,
                          period=period, date_range=date_range, facts=[message])


def error_result(tool: str, message: str, arguments: dict | None = None) -> AnalysisResult:
    """A friendly, stack-trace-free error result."""
    return AnalysisResult(tool=tool, title="Could not run analysis", status="error",
                          arguments=arguments or {}, warnings=[message])
