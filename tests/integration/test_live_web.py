"""LIVE: the real local model answers through the web API, on UPLOADED data.

Needs Ollama running with llama3.2:3b. Deselected by default; run with:

    python -m pytest -m integration tests/integration/test_live_web.py

If the model is not reachable these tests are skipped and must be reported
as NOT RUN. The sample database path points at a missing file throughout, so
any fallback to sample data would fail loudly.
"""

import json

import pytest
from fastapi.testclient import TestClient

from molarmetrics.agent.ollama_status import check_ollama
from molarmetrics.api.app import create_app
from molarmetrics.api.ask_service import AskService
from molarmetrics.api.presenters import prohibited_terms
from molarmetrics.api.settings import WebSettings
from tests.web.conftest import HEADERS, import_lakeview, import_sunrise

pytestmark = pytest.mark.integration


@pytest.fixture()
def live(tmp_path, monkeypatch):
    if not check_ollama().ready:
        pytest.skip("NOT RUN: Ollama with llama3.2:3b is not reachable")
    monkeypatch.setenv("MOLARMETRICS_DB_PATH", str(tmp_path / "no-sample.db"))
    settings = WebSettings(runtime_dir=tmp_path / "runtime", retention_hours=24, max_file_mb=5, max_files=10,
                           sweep_minutes=10, allowed_hosts=("testserver",))
    with TestClient(create_app(settings, AskService()), headers=HEADERS) as client:
        yield client


def _ask(client, ds, question):
    response = client.post(f"/api/datasets/{ds['id']}/ask", json={"question": question}, timeout=300)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dataset"]["id"] == ds["id"]
    assert not prohibited_terms(body["answer"]), body["answer"]
    return body


def _metric(body, key):
    for result in body["results"]:
        for m in result["metrics"]:
            if m["key"] == key:
                return m["value"]
    return None


def test_live_billed_revenue_comes_from_the_uploaded_dataset(live):
    ds = import_sunrise(live)
    body = _ask(live, ds, "What was billed revenue in 2025?")
    assert body["status"] == "answered"
    assert _metric(body, "billed_revenue") == 4_700_000
    assert "47,000" in body["answer"]


def test_live_monthly_question_gets_a_monthly_answer(live):
    ds = import_sunrise(live)
    body = _ask(live, ds, "Compare monthly billed revenue and collections in 2025.")
    first = body["results"][0]
    assert first["kind"] == "finances"
    months = [r["month"] for r in first["table"]["rows"] if r["billed_paise"]]
    assert months == ["2025-01", "2025-02", "2025-03"]
    assert any(m in body["answer"] for m in ("Jan", "Feb", "Mar"))


def test_live_outstanding_on_the_second_dataset(live):
    import_sunrise(live)
    ds = import_lakeview(live)
    body = _ask(live, ds, "How much was outstanding as of 30 September 2024?")
    assert _metric(body, "outstanding_balance") == 1_000_000
    assert "47,000" not in json.dumps(body, ensure_ascii=False)


def test_live_missing_records_are_explained_not_invented(live):
    ds = import_lakeview(live, only=("appointments",))
    body = _ask(live, ds, "How much revenue did the clinic bill in 2024?")
    assert "₹" not in body["answer"]
    assert "Add treatment records" in body["answer"] or body["status"] in ("no_match", "out_of_scope")
