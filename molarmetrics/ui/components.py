"""Reusable Streamlit pieces: result rendering, CSV export, cached analyses."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from molarmetrics import DATA_NOTICE
from molarmetrics.agent.ollama_status import OllamaStatus, check_ollama
from molarmetrics.agent.tools import TOOL_SPECS, run_analysis
from molarmetrics.analytics.results import AnalysisResult, display_period, sanitize_text
from molarmetrics.money import paise_to_plain
from molarmetrics.ui.charts import PLOTLY_CONFIG, build_figure

_SPECS = {name: (model, fn) for name, model, fn, _ in TOOL_SPECS}


def db_signature(db_path: Path) -> str:
    """Changes whenever the database file is regenerated (invalidates caches)."""
    return f"{db_path}:{db_path.stat().st_mtime_ns}"


@st.cache_data(show_spinner=False, max_entries=256)
def cached_analysis(tool: str, args: dict, signature: str) -> AnalysisResult:
    """Run one analysis directly (no language model). ``signature`` is only a cache key."""
    db_path = signature.rsplit(":", 1)[0]
    model, fn = _SPECS[tool]
    return run_analysis(tool, model, fn, args, db_path)


@st.cache_data(ttl=20, show_spinner=False)
def cached_ollama_status() -> OllamaStatus:
    return check_ollama()


def result_table(result: AnalysisResult) -> pd.DataFrame:
    if result.rows:
        return pd.DataFrame(result.formatted_rows())
    return pd.DataFrame([{"Metric": s.label, "Value": s.formatted, "Note": s.note or ""} for s in result.summary])


def result_csv_bytes(result: AnalysisResult) -> bytes:
    """Exact values for download: INR from integer paise, plain counts/percentages."""
    if result.rows:
        rows = result.csv_rows()
    else:
        rows = []
        for s in result.summary:
            value = s.value
            if s.kind == "inr" and value is not None:
                value = paise_to_plain(value)
            rows.append({"metric": s.label, "metric_name": s.key, "value": value, "unit": s.unit,
                         "aggregation": s.aggregation, "date_basis": s.date_basis or "", "note": s.note or ""})
    for row in rows:
        row["period"] = result.period
        row["data_notice"] = DATA_NOTICE
    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def csv_filename(result: AnalysisResult) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", f"{result.tool}_{result.period}".lower()).strip("_")
    return f"molarmetrics_{slug}_synthetic.csv"


def _escape_md(text: str) -> str:
    return text.replace("$", r"\$")  # '$' would otherwise start LaTeX in st.markdown


def render_facts_box(result: AnalysisResult) -> None:
    """The tool's own deterministic sentences, visibly separate from model commentary."""
    with st.container(border=True):
        st.caption(":material/calculate: **Calculated by MolarMetrics tools** · deterministic, "
                   "not written by the AI model")
        for fact in result.facts:
            st.markdown(f"- {_escape_md(fact)}")


def render_result(result: AnalysisResult, key: str, *, show_chart: bool = True, table_expanded: bool = True,
                  show_title: bool = True, label_facts: bool = False) -> None:
    """Facts + chart + table + notes + CSV download for one structured result.

    ``label_facts=True`` (chat) shows the facts in a labelled box so they are
    clearly distinguished from the model's commentary above them. On the
    dashboard there is no model text, so facts appear as a plain caption.
    """
    if result.status == "error":
        st.warning(" ".join(result.warnings) or "The analysis could not be completed.")
        return
    if show_title:
        heading = result.chart.title if result.chart is not None else result.title.split(",")[0]
        st.markdown(f"**{sanitize_text(heading)}**")
        st.caption(display_period(result.period))
    if label_facts and result.facts:
        render_facts_box(result)
    for w in result.warnings:
        st.warning(w)
    fig = build_figure(result) if show_chart else None
    if fig is not None:
        st.plotly_chart(fig, width="stretch", theme=None, config=PLOTLY_CONFIG, key=f"{key}_chart")
    table = result_table(result)
    if not table.empty:
        with st.expander("Table view" if fig is not None else "Results table", expanded=table_expanded):
            st.dataframe(table, hide_index=True, width="stretch")
    if result.facts and not label_facts:
        st.caption(_escape_md(" ".join(result.facts)))
    if result.notes:
        st.caption(" ".join(result.notes))
    st.download_button("Download CSV", data=result_csv_bytes(result), file_name=csv_filename(result),
                       mime="text/csv", key=f"{key}_csv", on_click="ignore", icon=":material/download:")
