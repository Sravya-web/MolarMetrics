"""About & Data Quality tab: purpose, assumptions, definitions, validation, model status."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from molarmetrics import APP_NAME, DATA_NOTICE, TAGLINE, __version__
from molarmetrics.agent.ollama_status import OllamaStatus
from molarmetrics.analytics.definitions import DEFINITIONS, LABELS
from molarmetrics.config import PROJECT_ROOT, Settings
from molarmetrics.data import catalog as C

LIMITATIONS = [
    "All data is synthetic. Patterns are invented and are not evidence about real clinics.",
    "No clinical outcome, diagnosis, imaging or quality data exists. MolarMetrics cannot say which treatment "
    "works best or which dentist is better, and it does not diagnose or recommend treatments.",
    "A small local model (llama3.2:3b) chooses tools and writes the explanations. It can misphrase things: "
    "always check the table and the number check under each answer.",
    "Ages are approximate (visit year minus birth year). Payments are linked to single treatments, which "
    "simplifies real invoicing.",
    "The scope check for clinical-outcome questions is rule-based and narrow; unusual phrasings may reach the "
    "model, which is instructed to decline.",
    "This is a local portfolio prototype: no authentication, no production hardening, and no regulatory or "
    "clinical validation.",
]


def render_about(settings: Settings, status: OllamaStatus) -> None:
    st.markdown(f"### {APP_NAME}: {TAGLINE}")
    st.markdown(
        f"{APP_NAME} is a **local portfolio prototype** of a descriptive operations-analytics assistant for a "
        "fictional Indian dental clinic. A small language model running on this computer (via Ollama) chooses "
        "one of four trusted analytics tools; **Python and SQL calculate every number** from a SQLite database; "
        "the app draws tables and charts directly from those structured results."
    )
    st.warning(f"**{DATA_NOTICE}.** Every patient, dentist, appointment, fee and payment is invented. "
               "Fee ranges are illustrative assumptions, not verified prices.", icon=":material/science:")

    st.markdown("#### Model and privacy status")
    c1, c2, c3 = st.columns(3)
    c1.metric("Ollama", "Connected" if status.reachable else "Not reachable", border=True)
    c2.metric("Model", status.model, "available" if status.model_available else "not installed",
              delta_color="normal" if status.model_available else "inverse", delta_arrow="off", border=True)
    c3.metric("Inference", "Local" if status.is_local else "REMOTE URL", border=True)
    st.caption(status.message)
    if not status.is_local:
        st.error(f"OLLAMA_BASE_URL points to {status.base_url}, which is not this computer. "
                 "Questions would leave this machine.")
    st.caption("LangChain/LangSmith remote tracing is forced off at startup, and Streamlit usage statistics are "
               "disabled in .streamlit/config.toml. No cloud APIs are used.")

    st.markdown("#### Metric definitions")
    st.table(pd.DataFrame([{"Metric": LABELS.get(k, k), "Definition": v} for k, v in DEFINITIONS.items()]),
             hide_index=True, border="horizontal")

    st.markdown("#### Data generation assumptions")
    st.markdown(
        f"Seed **42**, 1,000 patients, 8 fictional dentists, appointments from **{C.PERIOD_START:%d %b %Y}** to "
        f"**{C.PERIOD_END:%d %b %Y}**, currency INR stored as integer paise. Regenerate with "
        "`python -m molarmetrics.data.generate --overwrite`; the same seed reproduces identical CSV files."
    )
    st.table(pd.DataFrame([{"Procedure": p.name, "One record represents": p.record_represents,
                            "Tooth number": "required (FDI)" if p.tooth_specific else "NULL",
                            "Illustrative listed fee (INR)": f"{p.fee_min_inr:,} to {p.fee_max_inr:,}"}
                           for p in C.PROCEDURES.values()]), hide_index=True, border="horizontal")
    dict_md = settings.data_dir / "molarmetrics_data_dictionary.md"
    if dict_md.exists():
        with st.expander("Synthetic patterns and the full data dictionary", icon=":material/menu_book:"):
            st.markdown(dict_md.read_text(encoding="utf-8"))

    st.markdown("#### Validation results")
    _render_validation(settings.data_dir / "molarmetrics_validation_report.json")

    st.markdown("#### Live model verification (last recorded run)")
    _render_integration(PROJECT_ROOT / "reports" / "integration_report.json")

    st.markdown("#### Known limitations")
    for item in LIMITATIONS:
        st.markdown(f"- {item}")
    st.caption(f"{APP_NAME} version {__version__}")


def _render_validation(path: Path) -> None:
    if not path.exists():
        st.info("No validation report found. Generate the data to create one.")
        return
    report = json.loads(path.read_text(encoding="utf-8"))
    s = report["summary"]
    icon = ":material/verified:" if s["status"] == "PASS" else ":material/error:"
    (st.success if s["status"] == "PASS" else st.error)(
        f"Validation **{s['status']}**: {s['checks_passed']} of {s['checks_total']} checks passed "
        f"(report generated {report.get('generated_at_utc', '?')} UTC).", icon=icon)
    checks = pd.DataFrame([{"Check": c["id"], "Description": c["description"],
                            "Result": "pass" if c["passed"] else ("info" if c["severity"] == "info" else "FAIL"),
                            "Violations": c["violations"]} for c in report["checks"]])
    with st.expander("All checks", icon=":material/checklist:"):
        st.dataframe(checks, hide_index=True, width="stretch")
        st.json(report.get("statistics", {}), expanded=False)


def _render_integration(path: Path) -> None:
    if not path.exists():
        st.info("No live integration report yet. Run: python scripts/run_integration_checks.py")
        return
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") == "NOT RUN":
        st.warning(f"Live checks NOT RUN: {report.get('reason')}")
        return
    st.markdown(f"Run at **{report['run_at_utc']}** with `{report['model']}`: priority questions passed "
                f"**{report['priority_passed']}**, all questions passed **{report['all_passed']}**.")
    st.dataframe(pd.DataFrame([{"ID": r["id"], "Question": r["question"], "Result": "PASS" if r["passed"] else "FAIL",
                                "Tools": ", ".join(c["name"] for c in r["tool_calls"]) or "none",
                                "Seconds": r["seconds"]} for r in report["results"]]),
                 hide_index=True, width="stretch")
