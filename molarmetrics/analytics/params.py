"""Validated arguments for the four analytics tools.

Beginner note
-------------
A small language model sometimes sends sloppy arguments: "2025" instead of
"2025-01-01", "Billed Revenue" instead of "billed_revenue", or null. These
Pydantic models:

1. NORMALISE harmless variations (case, spaces, a bare year), and
2. REJECT anything ambiguous or unsafe (unknown metrics, start after end,
   top_n above 20) with a clear message the model can act on.

The normalised values are shown in the app as "validated arguments", so a
user can always see exactly what was calculated.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from molarmetrics.data.catalog import PERIOD_END, PERIOD_START, PROCEDURE_ALIASES, PROCEDURE_NAMES

if TYPE_CHECKING:
    from molarmetrics.dataset import DatasetContext

DATA_START = PERIOD_START.isoformat()
DATA_END = PERIOD_END.isoformat()
MAX_TOP_N = 20

_NATURAL_FORMATS = ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
                    "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d")


def parse_date(value, role: Literal["start", "end", "point"]) -> date:
    """Parse a date leniently but unambiguously.

    * ``2025`` or ``"2025"``  -> 1 Jan 2025 (start) or 31 Dec 2025 (end/point)
    * ``"2025-03"``           -> 1 Mar 2025 (start) or 31 Mar 2025 (end/point)
    * ``"2025-03-15"``        -> that day
    * ``"31 December 2025"``, ``"Dec 31, 2025"``, ``"31/12/2025"`` (day first)
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip().strip("'\"")
    ordinal_free = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", text, flags=re.I)
    if re.fullmatch(r"\d{4}", text):
        year = int(text)
        result = date(year, 1, 1) if role == "start" else date(year, 12, 31)
    elif m := re.fullmatch(r"(\d{4})-(\d{1,2})", text):
        year, month = int(m.group(1)), int(m.group(2))
        if not 1 <= month <= 12:
            raise ValueError(f"'{text}' has an invalid month")
        last = calendar.monthrange(year, month)[1]
        result = date(year, month, 1) if role == "start" else date(year, month, last)
    else:
        result = None
        for fmt in ("%Y-%m-%d",) + _NATURAL_FORMATS:
            try:
                result = datetime.strptime(ordinal_free, fmt).date()
                break
            except ValueError:
                continue
        if result is None:
            raise ValueError(f"'{text}' is not a date. Use YYYY-MM-DD, for example 2025-01-01")
    if not 2000 <= result.year <= 2100:
        raise ValueError(f"'{text}' is outside the supported years 2000-2100")
    return result


def _canonical(value) -> str:
    return re.sub(r"[\s\-]+", "_", str(value).strip().lower())


class _Args(BaseModel):
    # extra="ignore": stray keys a small model invents are dropped, not fatal.
    model_config = ConfigDict(extra="ignore")


class DateRangeArgs(_Args):
    start_date: str = Field(
        default=DATA_START,
        description="First day to include, YYYY-MM-DD. For a year such as 2025 use 2025-01-01. "
                    "Default 2024-01-01 (start of data).",
    )
    end_date: str = Field(
        default=DATA_END,
        description="Last day to include, YYYY-MM-DD. For a year such as 2025 use 2025-12-31. "
                    "Default 2025-12-31 (end of data).",
    )

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _parse_dates(cls, value, info: ValidationInfo):
        if value is None or (isinstance(value, str) and not value.strip()):
            # The class's own default: the sample period here, or the uploaded
            # dataset's coverage in a subclass made by arg_models_for().
            return cls.model_fields[info.field_name].default
        role = "start" if info.field_name == "start_date" else "end"
        return parse_date(value, role).isoformat()

    @model_validator(mode="after")
    def _check_order(self):
        if self.start_date > self.end_date:  # ISO strings compare chronologically
            raise ValueError(f"start_date {self.start_date} is after end_date {self.end_date}")
        return self

    @property
    def start(self) -> date:
        return date.fromisoformat(self.start_date)

    @property
    def end(self) -> date:
        return date.fromisoformat(self.end_date)


def _enum_normaliser(synonyms: dict[str, str], default: str):
    def normalise(value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        key = _canonical(value)
        return synonyms.get(key, key)  # unknown values fall through to the Literal check
    return normalise


_APPT_GROUP = {"month": "month", "months": "month", "monthly": "month", "by_month": "month",
               "dentist": "dentist", "dentists": "dentist", "by_dentist": "dentist", "doctor": "dentist",
               "doctors": "dentist", "provider": "dentist"}
_APPT_METRIC = {"status_counts": "status_counts", "status": "status_counts", "statuses": "status_counts",
                "status_count": "status_counts", "counts": "status_counts", "appointments": "status_counts",
                "no_show_rate": "no_show_rate", "no_show": "no_show_rate", "no_shows": "no_show_rate",
                "noshow_rate": "no_show_rate", "no_show_rates": "no_show_rate",
                "completed_visits": "completed_visits", "completed": "completed_visits",
                "completed_appointments": "completed_visits", "visits": "completed_visits"}
_PROC_METRIC = {"billed_revenue": "billed_revenue", "revenue": "billed_revenue", "billed": "billed_revenue",
                "net_fee": "billed_revenue", "net_fees": "billed_revenue",
                "treatment_count": "treatment_count", "count": "treatment_count", "counts": "treatment_count",
                "treatment_counts": "treatment_count", "treatments": "treatment_count",
                "number": "treatment_count", "frequency": "treatment_count", "procedure_count": "treatment_count"}
_FIN_METRIC = {"monthly_billed_vs_collected": "monthly_billed_vs_collected", "monthly": "monthly_billed_vs_collected",
               "billed_vs_collected": "monthly_billed_vs_collected",
               "billed_revenue_vs_collections": "monthly_billed_vs_collected",
               "revenue_vs_collections": "monthly_billed_vs_collected",
               "collections": "monthly_billed_vs_collected",
               "outstanding_balance": "outstanding_balance", "outstanding": "outstanding_balance",
               "balance": "outstanding_balance", "receivables": "outstanding_balance",
               "outstanding_balances": "outstanding_balance"}


class KpiArgs(DateRangeArgs):
    """Arguments for get_clinic_kpis (just a date range)."""


class AppointmentArgs(DateRangeArgs):
    group_by: Literal["month", "dentist"] = Field(
        default="month", description="Group results by 'month' or by 'dentist'.")
    metric: Literal["status_counts", "no_show_rate", "completed_visits"] = Field(
        default="status_counts",
        description="'status_counts' (completed/cancelled/no-show counts), 'no_show_rate', or "
                    "'completed_visits'. Default status_counts.")

    _norm_group = field_validator("group_by", mode="before")(_enum_normaliser(_APPT_GROUP, "month"))
    _norm_metric = field_validator("metric", mode="before")(_enum_normaliser(_APPT_METRIC, "status_counts"))


def _loose(text: str) -> str:
    """Lower-case, punctuation-free, singular-ish form for forgiving comparisons."""
    words = re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split()
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words)


def resolve_procedure_name(value: str, names: tuple[str, ...] = PROCEDURE_NAMES) -> str:
    """Map a user/model-supplied procedure name to an exact name in ``names``
    (the sample catalog by default, or an uploaded dataset's own procedures).

    Order: exact (case-insensitive) -> documented alias whose target exists ->
    same words ignoring punctuation/plurals -> a unique partial match. Several
    partial matches are rejected rather than guessed."""
    text = str(value).strip()
    for name in names:
        if text.lower() == name.lower():
            return name
    alias = PROCEDURE_ALIASES.get(re.sub(r"\s+", " ", text.lower()))
    if alias and alias in names:
        return alias
    loose = _loose(text)
    same = [n for n in names if _loose(n) == loose]
    if len(same) == 1:
        return same[0]
    partial = [n for n in names if loose and (loose in _loose(n) or _loose(n) in loose)] if len(loose) >= 3 else []
    if len(partial) == 1:
        return partial[0]
    shown = ", ".join(names[:25]) + (f" and {len(names) - 25} more" if len(names) > 25 else "")
    if len(partial) > 1:
        raise ValueError(f"'{text}' matches several procedures ({', '.join(partial[:8])}). "
                         f"Name one exactly. Valid procedures: {shown}")
    raise ValueError(f"unknown procedure '{text}'. Valid procedures: {shown}")


class ProcedureArgs(DateRangeArgs):
    # The procedure names this model accepts; arg_models_for() swaps in an
    # uploaded dataset's own names.
    procedure_catalog: ClassVar[tuple[str, ...]] = PROCEDURE_NAMES

    metric: Literal["billed_revenue", "treatment_count"] = Field(
        default="billed_revenue",
        description="'billed_revenue' (sum of net fees) or 'treatment_count' (number of treatment records).")
    procedures: list[str] = Field(
        default=[],
        description="Optional list of procedure names to include, e.g. ['Root canal treatment (session)', "
                    "'Extraction']. Leave empty for all procedures.")
    top_n: int = Field(default=10, ge=1, le=MAX_TOP_N,
                       description=f"How many procedures to return, 1-{MAX_TOP_N}. Default 10.")

    _norm_metric = field_validator("metric", mode="before")(_enum_normaliser(_PROC_METRIC, "billed_revenue"))

    @field_validator("procedures", mode="before")
    @classmethod
    def _parse_procedures(cls, value):
        if value is None or value == "" or value == []:
            return []
        if isinstance(value, str):
            value = [v for v in re.split(r",|;|\band\b|\bvs\.?\b", value) if v.strip()]
        if not isinstance(value, list):
            raise ValueError("procedures must be a list of procedure names")
        resolved: list[str] = []
        for item in value:
            name = resolve_procedure_name(item, cls.procedure_catalog)
            if name not in resolved:
                resolved.append(name)
        return resolved

    @field_validator("top_n", mode="before")
    @classmethod
    def _default_top_n(cls, value):
        return 10 if value is None or value == "" else value


class FinanceArgs(DateRangeArgs):
    metric: Literal["monthly_billed_vs_collected", "outstanding_balance"] = Field(
        default="monthly_billed_vs_collected",
        description="'monthly_billed_vs_collected' (billed revenue and collections per month) or "
                    "'outstanding_balance' (unpaid amount as of as_of_date).")
    as_of_date: str = Field(
        default=DATA_END,
        description="Only for outstanding_balance: the date to measure the balance on, YYYY-MM-DD. "
                    "Default 2025-12-31.")

    _norm_metric = field_validator("metric", mode="before")(
        _enum_normaliser(_FIN_METRIC, "monthly_billed_vs_collected"))

    @field_validator("as_of_date", mode="before")
    @classmethod
    def _parse_as_of(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return cls.model_fields["as_of_date"].default
        return parse_date(value, "point").isoformat()

    @property
    def as_of(self) -> date:
        return date.fromisoformat(self.as_of_date)


# --- per-dataset argument models ---------------------------------------------------------
def _subclass(base: type[BaseModel], fields: dict, **class_vars) -> type[BaseModel]:
    """A subclass of ``base`` with new field defaults/descriptions. Validators
    are inherited, so normalisation and rejection rules stay identical."""
    namespace = {"__module__": base.__module__, "__qualname__": base.__qualname__,
                 "__annotations__": {k: t for k, (t, _) in fields.items()},
                 **{k: f for k, (_, f) in fields.items()}, **class_vars}
    return type(base.__name__, (base,), namespace)


def arg_models_for(ctx: "DatasetContext | None") -> dict[str, type[BaseModel]]:
    """Argument models whose defaults and descriptions describe ``ctx``'s
    dataset: its date coverage and its procedure names. Without a context (or
    for the sample) the original models are returned unchanged."""
    if ctx is None or ctx.is_sample:
        return {"get_clinic_kpis": KpiArgs, "analyze_appointments": AppointmentArgs,
                "analyze_procedures": ProcedureArgs, "analyze_finances": FinanceArgs}
    s, e, year = ctx.coverage_start, ctx.coverage_end, ctx.example_year()
    dates = {
        "start_date": (str, Field(default=s, description=(
            f"First day to include, YYYY-MM-DD. For a year such as {year} use {year}-01-01. "
            f"Default {s} (start of data)."))),
        "end_date": (str, Field(default=e, description=(
            f"Last day to include, YYYY-MM-DD. For a year such as {year} use {year}-12-31. "
            f"Default {e} (end of data)."))),
    }
    examples = ", ".join(f"'{n}'" for n in ctx.procedure_names[:2]) or "'Extraction'"
    procedures = (list[str], Field(default=[], description=(
        f"Optional list of procedure names to include, e.g. [{examples}]. Leave empty for all procedures.")))
    as_of = (str, Field(default=e, description=(
        f"Only for outstanding_balance: the date to measure the balance on, YYYY-MM-DD. Default {e}.")))
    return {
        "get_clinic_kpis": _subclass(KpiArgs, dates),
        "analyze_appointments": _subclass(AppointmentArgs, dates),
        "analyze_procedures": _subclass(ProcedureArgs, {**dates, "procedures": procedures},
                                        procedure_catalog=tuple(ctx.procedure_names)),
        "analyze_finances": _subclass(FinanceArgs, {**dates, "as_of_date": as_of}),
    }
