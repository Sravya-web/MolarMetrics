"""MolarMetrics: AI-powered dental clinic analytics (Streamlit entry point).

Run from the project folder, with the virtual environment active:

    streamlit run app.py
"""

from __future__ import annotations

import logging

import streamlit as st

from molarmetrics import APP_NAME, DATA_NOTICE, TAGLINE
from molarmetrics.config import get_settings  # importing this also disables remote tracing
from molarmetrics.ui.about import render_about
from molarmetrics.ui.chat import render_chat
from molarmetrics.ui.components import cached_ollama_status
from molarmetrics.ui.dashboard import render_dashboard
from molarmetrics.ui.explorer import render_explorer
from molarmetrics.ui.theme import APP_CSS, SYNTHETIC_BADGE_HTML

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(
    page_title=f"{APP_NAME}: dental clinic analytics",
    page_icon=":material/dentistry:",
    layout="wide",
    menu_items={"About": f"{APP_NAME}: {TAGLINE} A local portfolio prototype on synthetic demo data."},
)
st.markdown(APP_CSS, unsafe_allow_html=True)

settings = get_settings()
status = cached_ollama_status()

with st.sidebar:
    st.title(APP_NAME)
    st.caption(TAGLINE)
    st.badge(DATA_NOTICE, icon=":material/science:", color="orange")
    st.markdown(
        f"Welcome to **{APP_NAME}**, a local analytics assistant for a *fictional* Indian dental clinic. "
        "Explore the dashboard, or ask questions in plain English: a local model picks a tool and the "
        "numbers are calculated by Python and SQL."
    )
    st.divider()
    if status.ready:
        st.success(f"Chat ready · `{status.model}` on Ollama {status.version}", icon=":material/check_circle:")
    else:
        st.warning(status.message, icon=":material/cloud_off:")
    if st.button("Re-check Ollama", icon=":material/refresh:", width="stretch"):
        cached_ollama_status.clear()
        st.rerun()
    st.caption("Runs on this computer. No cloud APIs; remote tracing disabled.")
    st.divider()
    st.caption("Descriptive operations analytics only: no diagnosis, treatment advice or clinical-quality "
               "judgements.")

st.title(APP_NAME)
st.markdown(f'<p class="mm-tagline">{TAGLINE} &nbsp; {SYNTHETIC_BADGE_HTML}</p>', unsafe_allow_html=True)

if not settings.db_path.exists():
    st.error(f"The synthetic database was not found at `{settings.db_path}`.")
    st.code("python -m molarmetrics.data.generate", language="bash")
    st.stop()

dashboard_tab, chat_tab, explorer_tab, about_tab = st.tabs(
    ["Dashboard", "Ask MolarMetrics", "Data Explorer", "About & Data Quality"], key="tab", bind="query-params")
with dashboard_tab:
    render_dashboard(settings.db_path)
with chat_tab:
    render_chat(status)
with explorer_tab:
    render_explorer(settings.data_dir)
with about_tab:
    render_about(settings, status)
