"""The four analyses behind the four agent tools (and the dashboard).

Each function takes an open read-only connection plus VALIDATED arguments and
returns an ``AnalysisResult``. Python and SQL do every calculation here,
including comparisons ("highest month"), differences and percentages, so
the language model only has to choose a tool and explain its output.

Every number is labelled with an explicit unit, aggregation and date basis,
and each result carries ``facts``: complete sentences written here in Python
(never by the model). Facts never call a total an "average", and they always
name what is being counted (patients, appointments, treatment records,
payments) so the model has correct wording to copy.
"""

from __future__ import annotations

import sqlite3

from molarmetrics.analytics import metrics as M
from molarmetrics.analytics.definitions import pick
from molarmetrics.analytics.params import (
    DATA_END,
    DATA_START,
    AppointmentArgs,
    FinanceArgs,
    KpiArgs,
    ProcedureArgs,
)
from molarmetrics.analytics.results import (
    AnalysisResult,
    ChartSpec,
    Column,
    SummaryItem,
    display_date,
    format_value,
    human_period,
    month_label,
    pct,
    sanitize_text,
)

WORKLOAD_NOTE = ("Appointment counts describe scheduling workload only. They are not a measure of "
                 "clinical quality or dentist performance.")
APPT_DATE = "appointment date"
PAY_DATE = "payment date"
AS_OF = "as-of date"


def _period_text(start: str, end: str) -> str:
    return f"{start} to {end}"


def _n(value) -> str:
    """A count with digit grouping, e.g. 2,954."""
    return format_value(value, "count")


def _inr(paise) -> str:
    return format_value(paise, "inr")


def _no_show_text(no_show: int, scheduled: int) -> str:
    rate = pct(no_show, scheduled)
    if rate is None:
        return "not available, because no appointments were scheduled"
    return (f"{rate:.1f}% of scheduled appointments ({_n(no_show)} no-show appointments ÷ "
            f"{_n(scheduled)} scheduled appointments)")


def _status_fact(period: str, t: dict) -> str:
    return (f"From {period}, {_n(t['scheduled'])} appointments were scheduled: {_n(t['completed'])} completed "
            f"visits, {_n(t['cancelled'])} cancelled appointments and {_n(t['no_show'])} no-show appointments.")


def _coverage(start: str, end: str) -> tuple[list[str], list[str], bool]:
    """Notes/warnings about how the requested period relates to the data.
    Returns (notes, warnings, completely_outside)."""
    notes, warnings = [], []
    if end < DATA_START or start > DATA_END:
        warnings.append(f"No data for this period: the synthetic dataset covers {DATA_START} to {DATA_END}.")
        return notes, warnings, True
    if start < DATA_START or end > DATA_END:
        warnings.append(f"The period extends beyond the available data ({DATA_START} to {DATA_END}); "
                        "only records inside that window exist.")
    if start == DATA_START and end == DATA_END:
        notes.append(f"This covers the full data period ({DATA_START} to {DATA_END}).")
    return notes, warnings, False


def _ties(rows: list[dict], key: str, label_key: str, highest: bool = True) -> tuple[list[str], object]:
    """Labels of the row(s) with the highest (or lowest) value; ties are all returned."""
    candidates = [r for r in rows if r.get(key) is not None]
    if not candidates:
        return [], None
    best = (max if highest else min)(r[key] for r in candidates)
    return [sanitize_text(r[label_key], 80) for r in candidates if r[key] == best], best


def _appointment_count_items(t: dict, rate_label: str) -> list[SummaryItem]:
    return [
        SummaryItem(key="scheduled_appointments", label="Scheduled appointments", value=t["scheduled"],
                    kind="count", unit="appointments", aggregation="count", date_basis=APPT_DATE),
        SummaryItem(key="completed_visits", label="Completed visits", value=t["completed"], kind="count",
                    unit="appointments", aggregation="count", date_basis=APPT_DATE),
        SummaryItem(key="cancelled_appointments", label="Cancelled appointments", value=t["cancelled"],
                    kind="count", unit="appointments", aggregation="count", date_basis=APPT_DATE),
        SummaryItem(key="no_show_appointments", label="No-show appointments", value=t["no_show"], kind="count",
                    unit="appointments", aggregation="count", date_basis=APPT_DATE),
        SummaryItem(key="no_show_rate", label=rate_label, value=pct(t["no_show"], t["scheduled"]),
                    kind="percent", unit="percent", aggregation="ratio", date_basis=APPT_DATE,
                    note=f"{t['no_show']:,} no-shows / {t['scheduled']:,} scheduled appointments"),
    ]


# --- 1. KPIs ---------------------------------------------------------------------------
def clinic_kpis(conn: sqlite3.Connection, args: KpiArgs) -> AnalysisResult:
    s, e = args.start_date, args.end_date
    period = human_period(s, e)
    notes, warnings, outside = _coverage(s, e)
    sc = M.status_counts(conn, s, e)
    pc = M.patient_counts(conn, s, e)
    br = M.billed_revenue(conn, s, e)
    co = M.collections(conn, s, e)
    if sc["scheduled"] == 0:
        warnings.append("No scheduled appointments in this period, so the no-show rate is undefined (n/a).")
    empty = outside or (sc["scheduled"] == 0 and br["treatment_count"] == 0 and co["payment_count"] == 0)
    facts = [
        _status_fact(period, sc),
        f"No-show rate from {period}: {_no_show_text(sc['no_show'], sc['scheduled'])}.",
        f"{_n(pc['unique_patients_seen'])} unique patients had at least one completed visit from {period}; "
        f"{_n(pc['returning_patients'])} of these patients were returning patients (they had an earlier "
        "completed visit, including visits before the period).",
        f"Billed revenue from {period} (sum of treatment net fees, by treatment date): "
        f"{_inr(br['billed_paise'])}.",
        f"Collections from {period} (sum of payments received, by payment date): {_inr(co['collected_paise'])}.",
    ]
    return AnalysisResult(
        tool="get_clinic_kpis",
        title=f"Clinic KPIs, {_period_text(s, e)}",
        status="empty" if empty else "ok",
        arguments=args.model_dump(),
        period=_period_text(s, e),
        date_range={"start": s, "end": e},
        facts=facts,
        definitions=pick("scheduled_appointments", "completed_visits", "no_show_rate", "unique_patients_seen",
                         "returning_patients", "billed_revenue", "collections"),
        summary=_appointment_count_items(sc, "No-show rate") + [
            SummaryItem(key="unique_patients_seen", label="Unique patients seen", value=pc["unique_patients_seen"],
                        kind="count", unit="patients", aggregation="distinct count", date_basis=APPT_DATE),
            SummaryItem(key="returning_patients", label="Returning patients", value=pc["returning_patients"],
                        kind="count", unit="patients", aggregation="distinct count", date_basis=APPT_DATE),
            SummaryItem(key="billed_revenue", label="Billed revenue", value=br["billed_paise"], kind="inr",
                        unit="INR", aggregation="sum", date_basis=APPT_DATE),
            SummaryItem(key="collections", label="Collections", value=co["collected_paise"], kind="inr",
                        unit="INR", aggregation="sum", date_basis=PAY_DATE),
        ],
        notes=notes + ["Billed revenue (fees charged, by treatment date) and collections (payments received, "
                       "by payment date) are different measures."],
        warnings=warnings,
    )


# --- 2. Appointments -------------------------------------------------------------------------
def appointments(conn: sqlite3.Connection, args: AppointmentArgs) -> AnalysisResult:
    s, e = args.start_date, args.end_date
    period = human_period(s, e)
    notes, warnings, outside = _coverage(s, e)
    by_month = args.group_by == "month"
    rows = M.status_counts_by_month(conn, s, e) if by_month else M.status_counts_by_dentist(conn, s, e)
    for r in rows:
        r["no_show_rate_pct"] = pct(r["no_show"], r["scheduled"])
        if by_month:
            r["month_label"] = month_label(r["month"])
    label_key = "month_label" if by_month else "dentist"
    totals = {k: sum(r[k] for r in rows) for k in M.STATUS_KEYS}
    summary = _appointment_count_items(totals, "Overall no-show rate")
    facts = [_status_fact(period, totals),
             f"Overall no-show rate from {period}: {_no_show_text(totals['no_show'], totals['scheduled'])}."]

    group_word = "month" if by_month else "dentist"

    def detail(labels: list[str]) -> str:
        if len(labels) != 1:
            return ""
        row = next(r for r in rows if sanitize_text(r[label_key], 80) == labels[0])
        return f" ({_n(row['no_show'])} no-show appointments ÷ {_n(row['scheduled'])} scheduled appointments)"

    if args.metric == "no_show_rate":
        hi, hi_val = _ties(rows, "no_show_rate_pct", label_key, highest=True)
        lo, lo_val = _ties(rows, "no_show_rate_pct", label_key, highest=False)
        if hi:
            summary.append(SummaryItem(key="highest_no_show", label=f"Highest no-show rate ({group_word})",
                                       value=f"{' and '.join(hi)}: {hi_val:.1f}%", kind="text", unit="text",
                                       aggregation="max", date_basis=APPT_DATE))
            summary.append(SummaryItem(key="lowest_no_show", label=f"Lowest no-show rate ({group_word})",
                                       value=f"{' and '.join(lo)}: {lo_val:.1f}%", kind="text", unit="text",
                                       aggregation="min", date_basis=APPT_DATE))
            facts.append(f"Highest no-show rate by {group_word}: {hi_val:.1f}% in {' and '.join(hi)}{detail(hi)}.")
            facts.append(f"Lowest no-show rate by {group_word}: {lo_val:.1f}% in {' and '.join(lo)}{detail(lo)}.")
        undefined = [str(r[label_key]) for r in rows if r["no_show_rate_pct"] is None]
        if undefined:
            warnings.append(f"No appointments (rate undefined, shown as n/a) for: {', '.join(undefined)}.")
    elif args.metric == "completed_visits":
        top, top_val = _ties(rows, "completed", label_key)
        if top and top_val:
            summary.append(SummaryItem(key="most_completed", label=f"Most completed visits ({group_word})",
                                       value=f"{' and '.join(top)}: {top_val:,}", kind="text", unit="text",
                                       aggregation="max", date_basis=APPT_DATE))
            facts.append(f"Most completed visits by {group_word} from {period}: {' and '.join(top)} with "
                         f"{_n(top_val)} completed appointments.")
    else:
        top, top_val = _ties(rows, "scheduled", label_key)
        if top and top_val:
            summary.append(SummaryItem(key="busiest", label=f"Most scheduled appointments ({group_word})",
                                       value=f"{' and '.join(top)}: {top_val:,}", kind="text", unit="text",
                                       aggregation="max", date_basis=APPT_DATE))
            facts.append(f"Most scheduled appointments by {group_word} from {period}: {' and '.join(top)} with "
                         f"{_n(top_val)} scheduled appointments.")

    if not by_month:
        notes.append(WORKLOAD_NOTE)
        facts.append("Appointment counts describe scheduling workload, not clinical quality or dentist performance.")
        if args.metric == "completed_visits":
            rows.sort(key=lambda r: (-r["completed"], r["dentist_id"]))

    key_cols = ([Column(key="month", label="Month", kind="month", unit="month", aggregation="group")] if by_month
                else [Column(key="dentist", label="Dentist", kind="text", unit="text", aggregation="group"),
                      Column(key="specialty", label="Specialty", kind="text", unit="text", aggregation="label")])
    columns = key_cols + [
        Column(key="scheduled", label="Scheduled", kind="count", unit="appointments", aggregation="count"),
        Column(key="completed", label="Completed", kind="count", unit="appointments", aggregation="count"),
        Column(key="cancelled", label="Cancelled", kind="count", unit="appointments", aggregation="count"),
        Column(key="no_show", label="No-shows", kind="count", unit="appointments", aggregation="count"),
        Column(key="no_show_rate_pct", label="No-show rate", kind="percent", unit="percent", aggregation="ratio"),
    ]
    x = "month_label" if by_month else "dentist"
    if args.metric == "no_show_rate":
        chart = ChartSpec(type="line" if by_month else "bar", x=x, y=["no_show_rate_pct"],
                          title=f"No-show rate by {group_word}", y_title="No-show rate (%)")
    elif args.metric == "completed_visits":
        chart = ChartSpec(type="bar", x=x, y=["completed"], title=f"Completed visits by {group_word}",
                          y_title="Completed visits")
    else:
        chart = ChartSpec(type="stacked_bar", x=x, y=["completed", "cancelled", "no_show"],
                          title=f"Appointments by status and {group_word}", y_title="Appointments")
    if totals["scheduled"] == 0 and not outside:
        warnings.append("No appointments were scheduled in this period.")
    return AnalysisResult(
        tool="analyze_appointments",
        title=f"Appointments by {group_word}, {_period_text(s, e)}",
        status="empty" if (outside or totals["scheduled"] == 0) else "ok",
        arguments=args.model_dump(),
        period=_period_text(s, e),
        date_range={"start": s, "end": e},
        facts=facts,
        definitions=pick("scheduled_appointments", "completed_visits", "no_show_rate"),
        summary=summary, columns=columns, rows=rows, notes=notes, warnings=warnings,
        chart=None if totals["scheduled"] == 0 else chart,
    )


# --- 3. Procedures --------------------------------------------------------------------------------
def procedures(conn: sqlite3.Connection, args: ProcedureArgs) -> AnalysisResult:
    s, e = args.start_date, args.end_date
    period = human_period(s, e)
    notes, warnings, outside = _coverage(s, e)
    all_rows = M.procedure_breakdown(conn, s, e)
    total_count = sum(r["treatment_count"] for r in all_rows)
    total_billed = sum(r["billed_paise"] for r in all_rows)
    for r in all_rows:
        r["share_of_billed_pct"] = pct(r["billed_paise"], total_billed)
        r["share_of_count_pct"] = pct(r["treatment_count"], total_count)

    rows = [r for r in all_rows if not args.procedures or r["procedure"] in args.procedures]
    sort_key = "billed_paise" if args.metric == "billed_revenue" else "treatment_count"
    rows.sort(key=lambda r: (-r[sort_key], r["procedure"]))
    if len(rows) > args.top_n:
        notes.append(f"Showing the top {args.top_n} of {len(rows)} procedures by {args.metric.replace('_', ' ')}.")
        rows = rows[: args.top_n]

    billed_metric = args.metric == "billed_revenue"
    metric_label = "billed revenue" if billed_metric else "treatment records"
    kind = "inr" if billed_metric else "count"
    unit = "INR" if billed_metric else "treatment records"
    share_key = "share_of_billed_pct" if billed_metric else "share_of_count_pct"
    grand_total = total_billed if billed_metric else total_count

    def amount(value: int) -> str:
        return _inr(value) if billed_metric else f"{_n(value)} treatment records"

    summary = [
        SummaryItem(key="total_billed_all_procedures", label="Billed revenue, all procedures", value=total_billed,
                    kind="inr", unit="INR", aggregation="sum", date_basis=APPT_DATE),
        SummaryItem(key="total_records_all_procedures", label="Treatment records, all procedures",
                    value=total_count, kind="count", unit="treatment records", aggregation="count",
                    date_basis=APPT_DATE),
    ]
    facts: list[str] = []
    if rows and rows[0][sort_key] > 0:
        top, top_val = _ties(rows, sort_key, "procedure")
        summary.append(SummaryItem(key="top_procedure", label=f"Highest {metric_label}",
                                   value=f"{' and '.join(top)}: {format_value(top_val, kind)}", kind="text",
                                   unit="text", aggregation="max", date_basis=APPT_DATE))
    if rows and grand_total > 0 and not args.procedures:
        items = [f"{i}. {sanitize_text(r['procedure'], 80)}: {amount(r[sort_key])} "
                 f"({r[share_key]:.1f}% of all {metric_label})" for i, r in enumerate(rows[:5], start=1)]
        more = f"; {len(rows) - 5} more in the table" if len(rows) > 5 else ""
        facts.append(f"Top {len(rows)} procedures by {metric_label} from {period}: " + "; ".join(items) + more + ".")
    if rows and grand_total > 0 and len(rows) < len(all_rows):
        # The one value added for demo readiness: the combined share of the
        # listed procedures, so any "majority" claim can be checked against it.
        # Only meaningful for a subset: listing every procedure is trivially 100%.
        listed_total = sum(r[sort_key] for r in rows)
        combined = pct(listed_total, grand_total)
        summary.append(SummaryItem(
            key="listed_procedures_billed_revenue" if billed_metric else "listed_procedures_treatment_records",
            label=f"Total for the {len(rows)} listed procedures", value=listed_total, kind=kind, unit=unit,
            aggregation="sum", date_basis=APPT_DATE))
        summary.append(SummaryItem(
            key="combined_share", label=f"Combined share of the {len(rows)} listed procedures", value=combined,
            kind="percent", unit="percent", aggregation="share", date_basis=APPT_DATE,
            note=f"{format_value(listed_total, kind)} of {format_value(grand_total, kind)}"))
        half = "more than half" if combined > 50 else ("exactly half" if combined == 50 else "less than half")
        facts.append(f"Together, the {len(rows)} listed procedures account for {combined:.1f}% of all "
                     f"{metric_label} from {period} ({amount(listed_total)} of {amount(grand_total)}), "
                     f"which is {half}.")
    if args.procedures and len(rows) <= 5:
        # Spell out records AND patients for compared procedures, so the model
        # cannot mistake a count of records for a count of patients.
        for r in rows:
            name = sanitize_text(r["procedure"], 80)
            summary.append(SummaryItem(
                key=f"procedure:{r['procedure']}", label=name, kind="text", unit="text", aggregation="label",
                value=f"{r['treatment_count']:,} treatment records for {r['patients']:,} patients, "
                      f"billed {_inr(r['billed_paise'])}"))
            facts.append(f"{name}: {_n(r['treatment_count'])} treatment records for {_n(r['patients'])} patients "
                         f"from {period}; billed revenue {_inr(r['billed_paise'])}.")
    if len(args.procedures) == 2 and len(rows) == 2:
        a, b = rows  # already sorted, so a >= b
        a_name, b_name = sanitize_text(a["procedure"], 80), sanitize_text(b["procedure"], 80)
        diff = a[sort_key] - b[sort_key]
        summary.append(SummaryItem(key="difference", label=f"Difference in {metric_label} ({a['procedure']} minus "
                                   f"{b['procedure']})", value=diff, kind=kind, unit=unit, aggregation="difference",
                                   date_basis=APPT_DATE))
        # A ready-made, correct sentence: small models copy these more reliably
        # than they reason about "records" versus "patients".
        if not billed_metric:
            sentence = (f"{a_name} had {diff:,} more treatment records than {b_name} "
                        f"({a['treatment_count']:,} vs {b['treatment_count']:,}). These are records, not patients: "
                        f"distinct patients were {a['patients']:,} and {b['patients']:,}.")
        else:
            sentence = (f"{a_name} billed revenue: {_inr(a['billed_paise'])}; {b_name} billed revenue: "
                        f"{_inr(b['billed_paise'])}; so {a_name} billed {_inr(diff)} more than {b_name}.")
        summary.append(SummaryItem(key="comparison", label="Comparison", value=sentence, kind="text", unit="text",
                                   aggregation="label"))
        facts.append(sentence)
    notes.append("Treatment records are procedure line items, not patients; see 'Patients treated'.")
    notes.append("This is billing data: it cannot show which treatment works best clinically.")
    if any("Root canal" in r["procedure"] for r in rows) or not args.procedures:
        notes.append("Root canal treatment is recorded per SESSION; one tooth's course can be 1-3 records.")
    notes.append("Share percentages compare each procedure with all procedures in the period.")
    if total_count == 0 and not outside:
        warnings.append("No treatment records in this period.")
    if total_count == 0:
        facts.append(f"No treatment records were found from {period}.")

    columns = [
        Column(key="procedure", label="Procedure", kind="text", unit="text", aggregation="group"),
        Column(key="treatment_count", label="Treatment records", kind="count", unit="treatment records",
               aggregation="count"),
        Column(key="patients", label="Patients treated", kind="count", unit="patients", aggregation="distinct count"),
        Column(key="billed_paise", label="Billed revenue", kind="inr", unit="INR", aggregation="sum"),
        Column(key="share_of_billed_pct", label="Share of billed revenue", kind="percent", unit="percent",
               aggregation="share"),
        Column(key="share_of_count_pct", label="Share of treatment records", kind="percent", unit="percent",
               aggregation="share"),
    ]
    return AnalysisResult(
        tool="analyze_procedures",
        title=f"Procedures by {metric_label}, {_period_text(s, e)}",
        status="empty" if (outside or total_count == 0) else "ok",
        arguments=args.model_dump(),
        period=_period_text(s, e),
        date_range={"start": s, "end": e},
        facts=facts,
        definitions=pick("treatment_count", "patients_treated", "billed_revenue"),
        summary=summary, columns=columns, rows=rows, notes=notes, warnings=warnings,
        chart=None if total_count == 0 else ChartSpec(
            type="bar", x="procedure", y=[sort_key], orientation="h",
            title=f"{metric_label.capitalize()} by procedure",
            y_title="Billed revenue (INR)" if billed_metric else "Treatment records"),
    )


# --- 4. Finances ------------------------------------------------------------------------------------
def finances(conn: sqlite3.Connection, args: FinanceArgs) -> AnalysisResult:
    if args.metric == "outstanding_balance":
        return _outstanding(conn, args)
    s, e = args.start_date, args.end_date
    period = human_period(s, e)
    notes, warnings, outside = _coverage(s, e)
    rows = M.billed_vs_collected_by_month(conn, s, e)
    for r in rows:
        r["difference_paise"] = r["billed_paise"] - r["collected_paise"]
        r["month_label"] = month_label(r["month"])
    billed = sum(r["billed_paise"] for r in rows)
    collected = sum(r["collected_paise"] for r in rows)
    if billed == 0 and collected == 0 and not outside:
        warnings.append("No billed treatments or payments in this period.")
    notes += [
        "Billed revenue uses the treatment (appointment) date; collections use the payment date. A month's "
        "collections can include payments for treatments billed earlier.",
        "Billed minus collected for a period is NOT the outstanding balance; use the outstanding_balance metric.",
    ]
    diff = billed - collected
    facts = [
        f"Billed revenue from {period} (sum of treatment net fees, by treatment date): {_inr(billed)} in total.",
        f"Collections from {period} (sum of payments received, by payment date): {_inr(collected)} in total.",
    ]
    if diff > 0:
        facts.append(f"Over the whole period, collections were {_inr(diff)} lower than billed revenue. This is one "
                     "total for the period, not a per-month figure, and it is not the unpaid balance.")
    elif diff < 0:
        facts.append(f"Over the whole period, collections were {_inr(-diff)} higher than billed revenue (collections "
                     "can include payments for treatments billed before the period). This is one total for the "
                     "period, not a per-month figure.")
    else:
        facts.append("Over the whole period, collections equalled billed revenue.")
    return AnalysisResult(
        tool="analyze_finances",
        title=f"Monthly billed revenue vs collections, {_period_text(s, e)}",
        status="empty" if (outside or (billed == 0 and collected == 0)) else "ok",
        arguments={"metric": args.metric, "start_date": s, "end_date": e},
        period=_period_text(s, e),
        date_range={"start": s, "end": e},
        facts=facts,
        definitions=pick("billed_revenue", "collections"),
        summary=[
            SummaryItem(key="billed_revenue", label="Total billed revenue", value=billed, kind="inr", unit="INR",
                        aggregation="sum", date_basis=APPT_DATE),
            SummaryItem(key="collections", label="Total collections", value=collected, kind="inr", unit="INR",
                        aggregation="sum", date_basis=PAY_DATE),
            SummaryItem(key="difference",
                        label="Difference between billed and collected (not the same as the unpaid balance)",
                        value=diff, kind="inr", unit="INR", aggregation="difference"),
        ],
        columns=[
            Column(key="month", label="Month", kind="month", unit="month", aggregation="group"),
            Column(key="billed_paise", label="Billed revenue", kind="inr", unit="INR", aggregation="sum"),
            Column(key="collected_paise", label="Collections", kind="inr", unit="INR", aggregation="sum"),
            Column(key="difference_paise", label="Billed minus collected", kind="inr", unit="INR",
                   aggregation="difference"),
        ],
        rows=rows, notes=notes, warnings=warnings,
        chart=None if (billed == 0 and collected == 0) else ChartSpec(
            type="grouped_bar", x="month_label", y=["billed_paise", "collected_paise"],
            title="Billed revenue vs collections by month", y_title="INR"),
    )


def _outstanding(conn: sqlite3.Connection, args: FinanceArgs) -> AnalysisResult:
    d = args.as_of_date
    day = display_date(d)
    notes, warnings = [], []
    if d < DATA_START:
        warnings.append(f"No data before {DATA_START}, so nothing could be outstanding on {d}.")
    elif d > DATA_END:
        warnings.append(f"The data ends on {DATA_END}; no treatments or payments after that date are recorded.")
    o = M.outstanding_as_of(conn, d)
    for row in o["aging"]:
        row["share_of_outstanding_pct"] = pct(row["outstanding_paise"], o["outstanding_paise"])
    notes += [
        "Aging buckets group unpaid amounts by days between the treatment date and the as-of date.",
        "start_date and end_date are not used for the outstanding balance.",
    ]
    if o["treatments_considered"] == 0 and not warnings:
        warnings.append(f"No treatments on or before {d}.")
    facts = [
        f"As of {day}, the outstanding balance was {_inr(o['outstanding_paise'])}: net fees of "
        f"{_inr(o['billed_to_date_paise'])} for treatments on or before {day}, minus "
        f"{_inr(o['paid_to_date_paise'])} of payments received against those treatments by {day}.",
        f"{_n(o['treatments_with_balance'])} treatment records had an unpaid balance as of {day}.",
    ]
    return AnalysisResult(
        tool="analyze_finances",
        title=f"Outstanding balance as of {d}",
        status="empty" if o["treatments_considered"] == 0 else "ok",
        arguments={"metric": args.metric, "as_of_date": d},
        period=f"as of {d}",
        date_range={"as_of": d},
        facts=facts,
        definitions=pick("outstanding_balance"),
        summary=[
            SummaryItem(key="outstanding_balance", label=f"Outstanding balance as of {d}",
                        value=o["outstanding_paise"], kind="inr", unit="INR", aggregation="difference",
                        date_basis=AS_OF, note="net fees minus payments received, both up to the as-of date"),
            SummaryItem(key="billed_to_date", label=f"Net fees for treatments up to {d}",
                        value=o["billed_to_date_paise"], kind="inr", unit="INR", aggregation="sum", date_basis=AS_OF),
            SummaryItem(key="paid_to_date", label=f"Payments received against them up to {d}",
                        value=o["paid_to_date_paise"], kind="inr", unit="INR", aggregation="sum", date_basis=AS_OF),
            SummaryItem(key="treatments_with_balance", label="Treatment records with an unpaid balance",
                        value=o["treatments_with_balance"], kind="count", unit="treatment records",
                        aggregation="count", date_basis=AS_OF),
        ],
        columns=[
            Column(key="bucket", label="Days since treatment", kind="text", unit="text", aggregation="group"),
            Column(key="treatments_with_balance", label="Treatment records with balance", kind="count",
                   unit="treatment records", aggregation="count"),
            Column(key="outstanding_paise", label="Outstanding", kind="inr", unit="INR", aggregation="sum"),
            Column(key="share_of_outstanding_pct", label="Share of outstanding", kind="percent", unit="percent",
                   aggregation="share"),
        ],
        rows=o["aging"], notes=notes, warnings=warnings,
        chart=None if o["outstanding_paise"] == 0 else ChartSpec(
            type="bar", x="bucket", y=["outstanding_paise"], title="Outstanding balance by age",
            y_title="INR"),
    )
