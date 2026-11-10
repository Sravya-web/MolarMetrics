"""The Overview screen's data, composed from the existing analyses.

Rules: metrics appear only when the dataset has the records for them (a
missing record type is explained, never shown as zero); the period is
clamped to the dataset's coverage (so months outside the data are not drawn
as zeros); monthly and cumulative money are both computed here, exactly, in
integer paise.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from molarmetrics.analytics import analyses as A
from molarmetrics.analytics.definitions import DEFINITIONS
from molarmetrics.analytics.params import arg_models_for
from molarmetrics.analytics.results import AnalysisResult, display_date
from molarmetrics.api.presenters import export_url
from molarmetrics.api.schemas import (
    AppliedPeriod,
    AppointmentRow,
    AppointmentSection,
    DatasetRef,
    FinanceRow,
    FinanceSection,
    KpiOut,
    OverviewPayload,
    PeriodPreset,
    ProcedureRow,
    ProcedureSection,
)
from molarmetrics.dataset import PAYMENTS, TREATMENTS, DatasetContext
from molarmetrics.money import format_inr, format_inr_compact, indian_grouping

_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


class PeriodError(ValueError):
    pass


def coverage_label(start: str, end: str) -> str:
    return f"{display_date(start)} – {display_date(end)}"


def presets(ctx: DatasetContext) -> list[PeriodPreset]:
    cs, ce = ctx.coverage_start, ctx.coverage_end
    out = [PeriodPreset(key="all", label="All data", start=cs, end=ce)]
    for year in ctx.years():
        s, e = max(f"{year}-01-01", cs), min(f"{year}-12-31", ce)
        if (s, e) == (cs, ce) and len(ctx.years()) == 1:
            continue  # same as "All data"
        full = (s, e) == (f"{year}-01-01", f"{year}-12-31")
        first, last = _MONTHS[int(s[5:7]) - 1], _MONTHS[int(e[5:7]) - 1]
        label = str(year) if full else (f"{first} {year}" if first == last else f"{first}–{last} {year}")
        out.append(PeriodPreset(key=str(year), label=label, start=s, end=e))
    return out


def _parse_day(value: str | None, name: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise PeriodError(f"The {name} date isn't valid.") from None


def _summary(result: AnalysisResult) -> dict:
    return {s.key: s for s in result.summary}


def build_overview(conn: sqlite3.Connection, ctx: DatasetContext, dataset: DatasetRef,
                   start: str | None = None, end: str | None = None) -> OverviewPayload:
    cs, ce = ctx.coverage_start, ctx.coverage_end
    req_s, req_e = _parse_day(start, "start") or cs, _parse_day(end, "end") or ce
    if req_s > req_e:
        raise PeriodError("The start date is after the end date.")
    s, e = max(req_s, cs), min(req_e, ce)
    notes = list(ctx.import_notes)
    if s > e:
        return OverviewPayload(
            dataset=dataset, period=AppliedPeriod(start=req_s, end=req_e, label=coverage_label(req_s, req_e),
                                                  clamped=False),
            presets=presets(ctx), kpis=[], finance=None, appointments=None, top_procedures=None, unavailable=[],
            notes=notes, warnings=[f"No data for this period. Your data covers {coverage_label(cs, ce)}."])
    clamped = (s, e) != (req_s, req_e)
    if clamped:
        notes.insert(0, f"Showing {coverage_label(s, e)}, the part of the selected period your data covers.")
    models = arg_models_for(ctx)
    has_t, has_p = ctx.has(TREATMENTS), ctx.has(PAYMENTS)

    k = _summary(A.clinic_kpis(conn, models["get_clinic_kpis"](start_date=s, end_date=e), ctx))
    scheduled, no_show = k["scheduled_appointments"].value, k["no_show_appointments"].value
    kpis: list[KpiOut] = []
    unavailable: list[str] = []

    def money_card(key: str, label: str, paise: int, detail: str) -> KpiOut:
        return KpiOut(key=key, label=label, status="available", kind="inr", value=paise,
                      display=format_inr_compact(paise), exact=format_inr(paise), detail=detail,
                      reason=None, definition=DEFINITIONS[key])

    def missing_card(key: str, label: str, reason: str) -> KpiOut:
        return KpiOut(key=key, label=label, status="unavailable", kind="inr", value=None, display=None, exact=None,
                      detail=None, reason=reason, definition=DEFINITIONS[key])

    if has_t:
        kpis.append(money_card("billed_revenue", "Billed revenue", k["billed_revenue"].value,
                               "Fees charged, by treatment date"))
    else:
        kpis.append(missing_card("billed_revenue", "Billed revenue", "Add treatment records to see billed revenue."))
        unavailable.append("Add treatment records to see billed revenue and top procedures.")
    if has_p:
        kpis.append(money_card("collections", "Collections", k["collections"].value,
                               "Payments received, by payment date"))
    else:
        kpis.append(missing_card("collections", "Collections", "Add payment records to see collections."))
        unavailable.append("Add payment records to see collections and outstanding balances.")
    kpis.append(KpiOut(key="completed_visits", label="Completed visits", status="available", kind="count",
                       value=k["completed_visits"].value, display=indian_grouping(k["completed_visits"].value),
                       exact=None, detail=f"of {indian_grouping(scheduled)} scheduled appointments", reason=None,
                       definition=DEFINITIONS["completed_visits"]))
    rate = k["no_show_rate"].value
    kpis.append(KpiOut(key="no_show_rate", label="No-show rate", status="available" if rate is not None else
                       "unavailable", kind="percent", value=rate, display=f"{rate:.1f}%" if rate is not None else None,
                       exact=None, detail=(f"{indian_grouping(no_show)} of {indian_grouping(scheduled)} scheduled "
                                           "appointments") if rate is not None else None,
                       reason=None if rate is not None else "No appointments were scheduled in this period.",
                       definition=DEFINITIONS["no_show_rate"]))
    if has_t and has_p:
        o = A.finances(conn, models["analyze_finances"](metric="outstanding_balance", as_of_date=e), ctx)
        kpis.append(money_card("outstanding_balance", f"Outstanding on {display_date(e)}",
                               o.summary_value("outstanding_balance"), "Unpaid net fees up to this date"))
    else:
        kpis.append(missing_card("outstanding_balance", "Outstanding balance",
                                 "Add treatment and payment records to see outstanding balances."))
    if not has_t:
        kpis += [
            KpiOut(key="scheduled_appointments", label="Scheduled appointments", status="available", kind="count",
                   value=scheduled, display=indian_grouping(scheduled), exact=None,
                   detail="Completed, cancelled and no-show", reason=None,
                   definition=DEFINITIONS["scheduled_appointments"]),
            KpiOut(key="unique_patients_seen", label="Patients seen", status="available", kind="count",
                   value=k["unique_patients_seen"].value, display=indian_grouping(k["unique_patients_seen"].value),
                   exact=None, detail=f"{indian_grouping(k['returning_patients'].value)} returning", reason=None,
                   definition=DEFINITIONS["unique_patients_seen"]),
        ]

    finance = None
    if has_t:
        f = A.finances(conn, models["analyze_finances"](start_date=s, end_date=e), ctx)
        rows, cum_b, cum_c = [], 0, 0
        for r in f.rows:
            cum_b += r["billed_paise"]
            collected = r.get("collected_paise") if has_p else None
            if collected is not None:
                cum_c += collected
            rows.append(FinanceRow(
                month=r["month"], month_label=r["month_label"], billed_paise=r["billed_paise"],
                collected_paise=collected, cumulative_billed_paise=cum_b,
                cumulative_collected_paise=cum_c if has_p else None, billed=format_inr(r["billed_paise"]),
                collected=format_inr(collected) if collected is not None else None,
                cumulative_billed=format_inr(cum_b), cumulative_collected=format_inr(cum_c) if has_p else None))
        finance = FinanceSection(has_collections=has_p, rows=rows, total_billed=format_inr(cum_b),
                                 total_collected=format_inr(cum_c) if has_p else None,
                                 export_url=export_url(dataset.id, "finances", {
                                     "metric": "monthly_billed_vs_collected", "start_date": s, "end_date": e}))

    a = A.appointments(conn, models["analyze_appointments"](start_date=s, end_date=e), ctx)
    appointments = AppointmentSection(
        rows=[AppointmentRow(month=r["month"], month_label=r["month_label"], scheduled=r["scheduled"],
                             completed=r["completed"], cancelled=r["cancelled"], no_show=r["no_show"],
                             no_show_rate_pct=r["no_show_rate_pct"]) for r in a.rows],
        export_url=export_url(dataset.id, "appointments", {"group_by": "month", "metric": "status_counts",
                                                           "start_date": s, "end_date": e}))

    procedures = None
    if has_t:
        p = A.procedures(conn, models["analyze_procedures"](start_date=s, end_date=e, top_n=20), ctx)
        with_records = [r for r in p.rows if r["treatment_count"] > 0]
        procedures = ProcedureSection(
            rows=[ProcedureRow(procedure=r["procedure"], billed_paise=r["billed_paise"],
                               billed=format_inr(r["billed_paise"]), treatment_count=r["treatment_count"],
                               share_pct=r["share_of_billed_pct"]) for r in with_records[:5]],
            total_procedures=len(with_records),
            export_url=export_url(dataset.id, "procedures", {"metric": "billed_revenue", "top_n": 20,
                                                             "start_date": s, "end_date": e}))
    warnings = [w for w in (_warnings_for(scheduled, has_t, finance))]
    return OverviewPayload(dataset=dataset, period=AppliedPeriod(start=s, end=e, label=coverage_label(s, e),
                                                                 clamped=clamped),
                           presets=presets(ctx), kpis=kpis, finance=finance, appointments=appointments,
                           top_procedures=procedures, unavailable=unavailable, notes=notes,
                           warnings=[w for w in warnings if w])


def _warnings_for(scheduled: int, has_t: bool, finance: FinanceSection | None) -> list[str]:
    out = []
    if scheduled == 0:
        out.append("No appointments were scheduled in this period.")
    if has_t and finance is not None and all(r.billed_paise == 0 for r in finance.rows):
        out.append("No treatments were billed in this period.")
    return out
