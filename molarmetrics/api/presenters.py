"""Turn analysis results into API payloads.

Users never see internal names: tools become neutral analysis kinds
("finances", "procedures"…), and error details stay in the logs. Charts and
tables are built from the structured rows, never from generated prose.
"""

from __future__ import annotations

import re
import uuid
from urllib.parse import urlencode

from molarmetrics.analytics.definitions import LABELS
from molarmetrics.analytics.results import AnalysisResult, display_period, format_value, sanitize_text
from molarmetrics.api.schemas import (
    AnalysisPayload,
    ChartOut,
    ColumnOut,
    DatasetRef,
    DefinitionOut,
    MetricOut,
    SeriesOut,
    TableOut,
)

TOOL_TO_KIND = {"get_clinic_kpis": "kpis", "analyze_appointments": "appointments",
                "analyze_procedures": "procedures", "analyze_finances": "finances"}
KIND_TO_TOOL = {"kpis": "get_clinic_kpis", "appointments": "analyze_appointments",
                "procedures": "analyze_procedures", "finances": "analyze_finances",
                "outstanding": "analyze_finances"}
PUBLIC_FILTERS = ("start_date", "end_date", "as_of_date", "group_by", "metric", "top_n", "procedures")

# Words that must never reach a user: implementation details and model branding.
PROHIBITED = re.compile(
    r"\b(?:AI|A\.I\.|artificial intelligence|machine learning|language model|LLM|llama|ollama|langchain|langgraph|"
    r"python|sql|sqlite|json|database|tool|tools|function|functions|model|prompt|trace|traceback|stack trace|"
    r"get_clinic_kpis|analyze_\w+)\b|\b[a-z]+_[a-z_]+\b",
    re.IGNORECASE)
_AI = re.compile(r"\bAI\b")  # "AI" is matched case-sensitively so words like "ai" in names are not hit


def prohibited_terms(text: str) -> list[str]:
    hits = [m.group(0) for m in PROHIBITED.finditer(text or "") if m.group(0).lower() != "ai" or _AI.search(m.group(0))]
    return hits


def analysis_kind(result: AnalysisResult) -> str:
    kind = TOOL_TO_KIND.get(result.tool, "kpis")
    if kind == "finances" and result.arguments.get("metric") == "outstanding_balance":
        return "outstanding"
    return kind


def display_title(result: AnalysisResult, kind: str) -> str:
    if kind == "kpis":
        return "Clinic summary"
    if kind == "outstanding":
        as_of = result.date_range.get("as_of")
        return f"Outstanding balance on {display_period('as of ' + as_of)[6:]}" if as_of else "Outstanding balance"
    if kind == "finances":
        return "Monthly billed revenue and collections" if any(c.key == "collected_paise" for c in result.columns) \
            else "Monthly billed revenue"
    if kind == "procedures":
        metric = "billed revenue" if result.arguments.get("metric") == "billed_revenue" else "treatment records"
        if result.arguments.get("procedures"):
            return f"Selected procedures by {metric}"
        return f"Top procedures by {metric}"
    if result.chart is not None:
        return sanitize_text(result.chart.title)
    return sanitize_text(result.title.split(",")[0])


def export_url(dataset_id: str, kind: str, arguments: dict) -> str:
    params: list[tuple[str, str]] = [("analysis", kind)]
    for key in PUBLIC_FILTERS:
        value = arguments.get(key)
        if value is None or value == []:
            continue
        for v in value if isinstance(value, list) else [value]:
            params.append((key, str(v)))
    return f"/api/datasets/{dataset_id}/export.csv?{urlencode(params)}"


def to_payload(result: AnalysisResult, dataset: DatasetRef) -> AnalysisPayload:
    kind = analysis_kind(result)
    filters = {k: result.arguments[k] for k in PUBLIC_FILTERS if k in result.arguments}
    if kind == "outstanding":
        filters = {k: v for k, v in filters.items() if k not in ("start_date", "end_date")}
    base = dict(id=uuid.uuid4().hex[:12], kind=kind, dataset=dataset, title=display_title(result, kind),
                date_range=result.date_range, period_label=display_period(result.period), filters=filters)
    if result.status == "error":
        # Details stay in the logs; users get a plain sentence.
        return AnalysisPayload(**base, status="error", metrics=[], facts=[], table=None, chart=None, definitions=[],
                               notes=[], warnings=["This analysis could not be completed."],
                               unavailable_reason=None, export_url=None)
    if result.status == "unavailable":
        return AnalysisPayload(**base, status="unavailable", metrics=[], facts=list(result.facts), table=None,
                               chart=None, definitions=[], notes=list(result.notes), warnings=list(result.warnings),
                               unavailable_reason=result.facts[0] if result.facts else None, export_url=None)
    metrics = [MetricOut(key=s.key, label=sanitize_text(s.label, 200), value=s.value, kind=s.kind, unit=s.unit,
                         aggregation=s.aggregation, date_basis=s.date_basis, note=s.note, formatted=s.formatted)
               for s in result.summary]
    table = None
    if result.rows:
        columns = [ColumnOut(key=c.key, label=c.label, kind=c.kind, unit=c.unit, aggregation=c.aggregation)
                   for c in result.columns]
        rows = [{k: (sanitize_text(v) if isinstance(v, str) else v) for k, v in row.items()} for row in result.rows]
        display = [{c.key: format_value(row.get(c.key), c.kind) for c in result.columns} for row in result.rows]
        table = TableOut(columns=columns, rows=rows, display=display)
    chart = None
    if result.chart is not None and result.rows:
        labels = {c.key: c for c in result.columns}
        chart = ChartOut(type=result.chart.type, x=result.chart.x,
                         series=[SeriesOut(key=k, label=labels[k].label if k in labels else k,
                                           kind=labels[k].kind if k in labels else "count") for k in result.chart.y],
                         title=sanitize_text(result.chart.title), y_title=result.chart.y_title,
                         orientation=result.chart.orientation)
    definitions = [DefinitionOut(key=k, label=LABELS.get(k, k.replace("_", " ").capitalize()), text=v)
                   for k, v in result.definitions.items()]
    return AnalysisPayload(**base, status=result.status, metrics=metrics, facts=list(result.facts), table=table,
                           chart=chart, definitions=definitions, notes=list(result.notes),
                           warnings=list(result.warnings), unavailable_reason=None,
                           export_url=export_url(dataset.id, kind, result.arguments))
