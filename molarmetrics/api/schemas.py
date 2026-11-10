"""Typed API contracts (Pydantic). The frontend's ``web/src/api/types.ts``
mirrors these. Every analysis uses ONE structure (``AnalysisPayload``):
dataset identity, applied date range and filters, metrics with explicit
units and aggregation, Python-written facts, a table, a chart spec,
definitions, notes and warnings."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from molarmetrics.ingest.validate import ImportConfig, ValidationReport

AnalysisKind = Literal["kpis", "appointments", "procedures", "finances", "outstanding"]
ResultStatus = Literal["ok", "empty", "unavailable", "error"]


class ErrorBody(BaseModel):
    code: str
    message: str


class DatasetRef(BaseModel):
    id: str
    name: str
    kind: Literal["sample", "uploaded"]


class Coverage(BaseModel):
    start: str
    end: str
    label: str


class DatasetMeta(DatasetRef):
    coverage: Coverage
    capabilities: list[str]
    counts: dict[str, int]
    import_notes: list[str]
    created_at: str
    last_used_at: str
    expires_at: str | None  # uploaded datasets only
    active: bool


class Limits(BaseModel):
    max_file_mb: int
    max_files: int


class SessionState(BaseModel):
    datasets: list[DatasetMeta]
    active_dataset_id: str | None
    questions_available: bool
    retention_hours: float
    limits: Limits


class ActivateRequest(BaseModel):
    dataset_id: str


# --- analyses ---------------------------------------------------------------------------
class MetricOut(BaseModel):
    key: str
    label: str
    value: Any
    kind: str  # inr (integer paise) | count | percent | text | month
    unit: str
    aggregation: str
    date_basis: str | None
    note: str | None
    formatted: str


class ColumnOut(BaseModel):
    key: str
    label: str
    kind: str
    unit: str
    aggregation: str


class TableOut(BaseModel):
    columns: list[ColumnOut]
    rows: list[dict[str, Any]]  # raw values (money in integer paise)
    display: list[dict[str, str]]  # the same cells, formatted exactly for display


class SeriesOut(BaseModel):
    key: str
    label: str
    kind: str


class ChartOut(BaseModel):
    type: Literal["bar", "grouped_bar", "stacked_bar", "line"]
    x: str
    series: list[SeriesOut]
    title: str
    y_title: str
    orientation: Literal["v", "h"]


class DefinitionOut(BaseModel):
    key: str
    label: str
    text: str


class AnalysisPayload(BaseModel):
    id: str
    kind: AnalysisKind
    dataset: DatasetRef
    title: str
    status: ResultStatus
    date_range: dict[str, str]
    period_label: str
    filters: dict[str, Any]
    metrics: list[MetricOut]
    facts: list[str]
    table: TableOut | None
    chart: ChartOut | None
    definitions: list[DefinitionOut]
    notes: list[str]
    warnings: list[str]
    unavailable_reason: str | None
    export_url: str | None


# --- overview ---------------------------------------------------------------------------
class PeriodPreset(BaseModel):
    key: str
    label: str
    start: str
    end: str


class AppliedPeriod(BaseModel):
    start: str
    end: str
    label: str
    clamped: bool


class KpiOut(BaseModel):
    key: str
    label: str
    status: Literal["available", "unavailable"]
    kind: Literal["inr", "count", "percent"]
    value: int | float | None
    display: str | None  # the card value (compact for money)
    exact: str | None  # exact value, e.g. ₹47,000.00
    detail: str | None  # e.g. "3 of 16 scheduled appointments"
    reason: str | None  # why unavailable, e.g. "Add payment records to see collections."
    definition: str


class FinanceRow(BaseModel):
    month: str
    month_label: str
    billed_paise: int
    collected_paise: int | None
    cumulative_billed_paise: int
    cumulative_collected_paise: int | None
    billed: str
    collected: str | None
    cumulative_billed: str
    cumulative_collected: str | None


class FinanceSection(BaseModel):
    has_collections: bool
    rows: list[FinanceRow]
    total_billed: str
    total_collected: str | None
    export_url: str


class AppointmentRow(BaseModel):
    month: str
    month_label: str
    scheduled: int
    completed: int
    cancelled: int
    no_show: int
    no_show_rate_pct: float | None


class AppointmentSection(BaseModel):
    rows: list[AppointmentRow]
    export_url: str


class ProcedureRow(BaseModel):
    procedure: str
    billed_paise: int
    billed: str
    treatment_count: int
    share_pct: float | None


class ProcedureSection(BaseModel):
    rows: list[ProcedureRow]
    total_procedures: int
    export_url: str


class OverviewPayload(BaseModel):
    dataset: DatasetRef
    period: AppliedPeriod
    presets: list[PeriodPreset]
    kpis: list[KpiOut]
    finance: FinanceSection | None
    appointments: AppointmentSection | None
    top_procedures: ProcedureSection | None
    unavailable: list[str]  # plain sentences: what to add to see more
    notes: list[str]
    warnings: list[str]


# --- questions ----------------------------------------------------------------------------
class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    id: str
    dataset: DatasetRef
    question: str
    answer: str
    status: Literal["answered", "out_of_scope", "not_available", "no_match"]
    results: list[AnalysisPayload]


class Suggestions(BaseModel):
    dataset: DatasetRef
    questions: list[str]


# --- uploads ------------------------------------------------------------------------------
class UploadedFileOut(BaseModel):
    file_id: str
    filename: str
    size: int
    rows: int
    columns: list[str]
    preview: list[list[str]]


class UploadBatchOut(BaseModel):
    batch_id: str
    files: list[UploadedFileOut]
    config: ImportConfig
    report: ValidationReport


class UploadRejection(BaseModel):
    filename: str
    message: str


class UploadRejectedBody(ErrorBody):
    files: list[UploadRejection]
