"""Streamlit smoke test: the app starts and works WITHOUT Ollama."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture()
def app_without_ollama(monkeypatch, real_db_path):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")  # nothing listens here
    at = AppTest.from_file(APP, default_timeout=90)
    at.run()
    return at


def test_app_renders_all_tabs_without_errors(app_without_ollama):
    at = app_without_ollama
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Dashboard", "Ask MolarMetrics", "Data Explorer", "About & Data Quality"]
    assert at.title[0].value == "MolarMetrics"


def test_dashboard_kpis_render_without_ollama(app_without_ollama):
    labels = [m.label for m in app_without_ollama.metric]
    for expected in ("Scheduled appointments", "Completed visits", "Unique patients seen", "Returning patients",
                     "Billed revenue", "Collections", "No-show rate"):
        assert expected in labels


def test_chat_is_disabled_with_an_actionable_message(app_without_ollama):
    at = app_without_ollama
    assert any("ollama serve" in w.value for w in at.warning)
    assert at.chat_input[0].disabled
    assert all(b.disabled for b in at.button if b.key and b.key.startswith("ex_"))
