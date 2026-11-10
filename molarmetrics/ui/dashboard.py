"""Dashboard tab: date filter, KPI tiles and four charts. Works without Ollama."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import streamlit as st

from molarmetrics.analytics.definitions import DEFINITIONS, LABELS
from molarmetrics.data.catalog import PERIOD_END, PERIOD_START
from molarmetrics.money import format_inr, format_inr_compact
from molarmetrics.ui.components import cached_analysis, db_signature, render_result

TILE_HEIGHT = 190  # px

PRESETS = {
    "All data": (PERIOD_START, PERIOD_END),
    "2024": (date(2024, 1, 1), date(2024, 12, 31)),
    "2025": (date(2025, 1, 1), date(2025, 12, 31)),
}


def _apply_preset() -> None:
    preset = st.session_state.get("dash_preset")
    if preset in PRESETS:
        st.session_state["dash_range"] = PRESETS[preset]


def _range_edited() -> None:
    picked = st.session_state.get("dash_range")
    st.session_state["dash_preset"] = next((k for k, v in PRESETS.items() if tuple(picked or ()) == v), None)


def _filter_row() -> tuple[date, date]:
    st.session_state.setdefault("dash_range", PRESETS["All data"])
    st.session_state.setdefault("dash_preset", "All data")
    left, right, _ = st.columns([2, 2, 3], vertical_alignment="bottom")
    left.segmented_control("Period", list(PRESETS), key="dash_preset", on_change=_apply_preset)
    picked = right.date_input("Date range", key="dash_range", min_value=PERIOD_START, max_value=PERIOD_END,
                              format="DD/MM/YYYY", on_change=_range_edited)
    if isinstance(picked, (tuple, list)) and len(picked) == 2:
        return picked[0], picked[1]
    start = picked[0] if isinstance(picked, (tuple, list)) and picked else PERIOD_START
    st.caption("Select an end date to complete the range; showing a single day for now.")
    return start, start


def render_dashboard(db_path: Path) -> None:
    sig = db_signature(db_path)
    start, end = _filter_row()
    s, e = start.isoformat(), end.isoformat()

    kpis = cached_analysis("get_clinic_kpis", {"start_date": s, "end_date": e}, sig)
    monthly_money = cached_analysis("analyze_finances", {"metric": "monthly_billed_vs_collected",
                                                         "start_date": s, "end_date": e}, sig)
    monthly_appts = cached_analysis("analyze_appointments", {"start_date": s, "end_date": e,
                                                             "group_by": "month", "metric": "status_counts"}, sig)
    no_show = cached_analysis("analyze_appointments", {"start_date": s, "end_date": e,
                                                       "group_by": "month", "metric": "no_show_rate"}, sig)
    procedures = cached_analysis("analyze_procedures", {"start_date": s, "end_date": e,
                                                        "metric": "treatment_count", "top_n": 10}, sig)
    outstanding = cached_analysis("analyze_finances", {"metric": "outstanding_balance", "as_of_date": e}, sig)

    if kpis.status == "error":
        st.error(" ".join(kpis.warnings))
        return
    v = {item.key: item for item in kpis.summary}
    billed_trend = [r["billed_paise"] / 100 for r in monthly_money.rows]
    collected_trend = [r["collected_paise"] / 100 for r in monthly_money.rows]
    completed_trend = [r["completed"] for r in monthly_appts.rows]
    scheduled_trend = [r["scheduled"] for r in monthly_appts.rows]
    spark = len(monthly_appts.rows) >= 3

    def tile(col, key, label, value, trend=None, caption=None):
        # A fixed height keeps every tile in a row aligned, with or without a sparkline.
        col.metric(label, value, help=DEFINITIONS.get(key), border=True, height=TILE_HEIGHT,
                   chart_data=trend if (spark and trend) else None, chart_type="line")
        if caption:
            col.caption(caption)

    row1 = st.columns(4)
    tile(row1[0], "scheduled_appointments", "Scheduled appointments",
         v["scheduled_appointments"].formatted, scheduled_trend)
    tile(row1[1], "completed_visits", "Completed visits", v["completed_visits"].formatted, completed_trend)
    tile(row1[2], "unique_patients_seen", "Unique patients seen", v["unique_patients_seen"].formatted)
    tile(row1[3], "returning_patients", "Returning patients", v["returning_patients"].formatted)
    row2 = st.columns(4)
    tile(row2[0], "billed_revenue", "Billed revenue", format_inr_compact(v["billed_revenue"].value),
         billed_trend, f"Exact: {format_inr(v['billed_revenue'].value)}")
    tile(row2[1], "collections", "Collections", format_inr_compact(v["collections"].value),
         collected_trend, f"Exact: {format_inr(v['collections'].value)}")
    tile(row2[2], "no_show_rate", "No-show rate", v["no_show_rate"].formatted, None,
         f"Denominator: {v['no_show_rate'].note}")
    out_value = outstanding.summary_value("outstanding_balance") if outstanding.status != "error" else None
    tile(row2[3], "outstanding_balance", f"Outstanding as of {end.strftime('%d %b %Y')}",
         format_inr_compact(out_value) if out_value is not None else "n/a", None,
         f"Exact: {format_inr(out_value)}" if out_value is not None else None)

    for w in kpis.warnings:
        st.warning(w)

    st.divider()
    render_result(monthly_money, "dash_money", table_expanded=False)
    left, right = st.columns(2, gap="large")
    with left:
        render_result(monthly_appts, "dash_status", table_expanded=False)
    with right:
        render_result(procedures, "dash_procedures", table_expanded=False)
    left, right = st.columns(2, gap="large")
    with left:
        render_result(no_show, "dash_noshow", table_expanded=False)
    with right:
        st.markdown("**Metric definitions**")
        for key in ("scheduled_appointments", "no_show_rate", "returning_patients", "billed_revenue",
                    "collections", "outstanding_balance", "treatment_count"):
            st.markdown(f"- **{LABELS[key]}**: {DEFINITIONS[key]}")
