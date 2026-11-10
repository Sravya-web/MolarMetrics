"""The four analytics tools the language model may call.

Beginner note
-------------
A LangChain "tool" is a Python function plus a description and an argument
schema. The model reads the descriptions, decides which tool to call and
with which arguments; LangChain validates those arguments with our Pydantic
models; then OUR trusted Python/SQL code runs.

There is deliberately no tool for arbitrary SQL, Python, shell commands or
file access: the model can only ask the four fixed questions below.

``response_format="content_and_artifact"`` means each tool returns two things:
* content  -> a short JSON summary the MODEL reads
* artifact -> the full AnalysisResult the APP uses for tables and charts
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ValidationError

from molarmetrics.analytics import analyses
from molarmetrics.analytics.db import DatabaseNotFoundError, connect_readonly
from molarmetrics.analytics.params import AppointmentArgs, FinanceArgs, KpiArgs, ProcedureArgs
from molarmetrics.analytics.results import AnalysisResult, error_result

TOOL_SPECS: list[tuple[str, type[BaseModel], Callable, str]] = [
    (
        "get_clinic_kpis", KpiArgs, analyses.clinic_kpis,
        "Headline totals for a date range: scheduled appointments, completed visits, unique patients "
        "seen, returning patients, billed revenue, collections and no-show rate. Use for single totals, "
        "e.g. 'What was billed revenue in 2025?' or 'How many returning patients were seen in 2025?'.",
    ),
    (
        "analyze_appointments", AppointmentArgs, analyses.appointments,
        "Appointment counts grouped by month or by dentist: scheduled, completed, cancelled, no-show and "
        "no-show rate. Use for 'no-show rate by month', appointment trends, or 'which dentist completed "
        "the most appointments' (group_by='dentist', metric='completed_visits').",
    ),
    (
        "analyze_procedures", ProcedureArgs, analyses.procedures,
        "Treatment records and billed revenue per procedure, highest first. Use for 'top procedures by "
        "billed revenue' (metric='billed_revenue', top_n) or to compare specific procedures, e.g. root "
        "canal vs extraction counts (metric='treatment_count', procedures=[...]).",
    ),
    (
        "analyze_finances", FinanceArgs, analyses.finances,
        "Money questions. metric='monthly_billed_vs_collected' compares billed revenue with collections "
        "month by month. metric='outstanding_balance' gives the unpaid amount as of as_of_date "
        "(e.g. 2025-12-31).",
    ),
]
TOOL_NAMES = tuple(spec[0] for spec in TOOL_SPECS)


def run_analysis(name: str, args_model: type[BaseModel], analysis: Callable, kwargs: dict,
                 db_path: Path | str | None = None) -> AnalysisResult:
    """Validate arguments, run one analysis on a fresh read-only connection,
    and convert every expected failure into a friendly error result."""
    try:
        args = args_model(**kwargs)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}"
                             for e in exc.errors())
        return error_result(name, f"Invalid arguments: {problems}", kwargs)
    try:
        with closing(connect_readonly(db_path)) as conn:
            return analysis(conn, args)
    except DatabaseNotFoundError as exc:
        return error_result(name, str(exc), args.model_dump())
    except sqlite3.Error:
        return error_result(name, "The database query failed. Regenerate the data with "
                                  "'python -m molarmetrics.data.generate --overwrite' and try again.",
                            args.model_dump())


def build_tools(db_path: Path | str | None = None) -> list[BaseTool]:
    """Create the four tools, bound to a database path (default: settings)."""
    tools: list[BaseTool] = []
    for name, args_model, analysis, description in TOOL_SPECS:
        def _run(_name=name, _model=args_model, _analysis=analysis, **kwargs):
            result = run_analysis(_name, _model, _analysis, kwargs, db_path)
            return result.to_model_content(), result

        tools.append(StructuredTool.from_function(
            func=_run, name=name, description=description, args_schema=args_model,
            response_format="content_and_artifact",
        ))
    return tools
