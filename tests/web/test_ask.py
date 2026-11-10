"""Ask MolarMetrics through the API, with a scripted stand-in for the local
model (offline). These check the web layer's wiring and safeguards; they are
not evidence that the real model answers well (see tests/integration)."""

import csv
import io
import logging
import threading
import time

from molarmetrics.agent.ollama_status import OllamaStatus
from molarmetrics.api import ask_service as ask_module
from molarmetrics.api.ask_service import UNAVAILABLE_MESSAGE, AskService
from molarmetrics.api.presenters import prohibited_terms
from tests.web.conftest import import_lakeview, import_sunrise

KPIS_2025 = {"start_date": "2025-01-01", "end_date": "2025-12-31"}


def _ask(client, ds, question):
    return client.post(f"/api/datasets/{ds['id']}/ask", json={"question": question})


def test_answers_come_from_the_uploaded_dataset_never_the_sample(client, script, monkeypatch, tmp_path):
    ds = import_sunrise(client)
    monkeypatch.setenv("MOLARMETRICS_DB_PATH", str(tmp_path / "no-sample-here.db"))  # sample unreachable
    script.then(script.tool_call("get_clinic_kpis", KPIS_2025),
                "From 1 Jan 2025 to 31 Dec 2025, billed revenue was ₹47,000.00.")
    body = _ask(client, ds, "What was billed revenue in 2025?").json()
    assert body["status"] == "answered" and body["dataset"]["id"] == ds["id"]
    assert body["answer"] == "From 1 Jan 2025 to 31 Dec 2025, billed revenue was ₹47,000.00."
    result = body["results"][0]
    assert result["kind"] == "kpis" and result["dataset"]["name"] == "Sunrise Dental"
    billed = next(m for m in result["metrics"] if m["key"] == "billed_revenue")
    assert (billed["value"], billed["formatted"]) == (4_700_000, "₹47,000.00")
    rows = list(csv.DictReader(io.StringIO(client.get(result["export_url"]).content.decode("utf-8-sig"))))
    assert next(r for r in rows if r["metric_name"] == "billed_revenue")["value"] == "47000.00"


def test_numbers_not_in_the_results_are_never_shown(client, script):
    ds = import_sunrise(client)
    script.then(script.tool_call("get_clinic_kpis", KPIS_2025), "Billed revenue in 2025 was ₹99,999.00.")
    body = _ask(client, ds, "What was billed revenue in 2025?").json()
    assert "99,999" not in body["answer"] and "₹47,000.00" in body["answer"]  # Python-written facts instead


def test_answers_that_mention_internals_are_replaced(client, script):
    ds = import_sunrise(client)
    script.then(script.tool_call("get_clinic_kpis", KPIS_2025),
                "The get_clinic_kpis tool returned billed revenue of ₹47,000.00 from the database.")
    body = _ask(client, ds, "What was billed revenue in 2025?").json()
    assert not prohibited_terms(body["answer"]) and "₹47,000.00" in body["answer"]


def test_monthly_questions_get_monthly_results_and_answers(client, script):
    ds = import_sunrise(client)
    script.then(script.tool_call("get_clinic_kpis", KPIS_2025), "In 2025, billed revenue was ₹47,000.00 in total.")
    body = _ask(client, ds, "What was monthly billed revenue in 2025?").json()
    first = body["results"][0]
    assert first["kind"] == "finances"
    assert [r["month"] for r in first["table"]["rows"]][:3] == ["2025-01", "2025-02", "2025-03"]
    assert "Mar 2025" in body["answer"] and "₹19,000.00" in body["answer"]  # highest month, not a yearly total


def test_monthly_no_show_question_gets_a_monthly_table(client, script):
    ds = import_lakeview(client)
    script.then(script.tool_call("get_clinic_kpis", {"start_date": "2024-01-01", "end_date": "2024-12-31"}),
                "The no-show rate in 2024 was 20.0%.")
    body = _ask(client, ds, "What was the no-show rate each month in 2024?").json()
    first = body["results"][0]
    assert first["kind"] == "appointments" and first["filters"]["metric"] == "no_show_rate"
    rates = {r["month"]: r["no_show_rate_pct"] for r in first["table"]["rows"]}
    assert (rates["2024-07"], rates["2024-08"], rates["2024-09"]) == (25.0, 0.0, 33.3)


def test_missing_data_is_explained_instead_of_answered(client, script):
    ds = import_lakeview(client, only=("appointments",))
    script.then(script.tool_call("analyze_finances", {}), "Billed revenue was ₹0.00.")
    body = _ask(client, ds, "How much revenue did we bill?").json()
    assert body["status"] == "not_available"
    assert "Add treatment records" in body["answer"] and "₹" not in body["answer"]
    assert body["results"][0]["status"] == "unavailable" and body["results"][0]["table"] is None


def test_clinical_effectiveness_questions_are_declined(client, script):
    ds = import_sunrise(client)
    script.then("MolarMetrics cannot answer that, because its data has no clinical outcome information. "
                "Try asking which procedures generated the most billed revenue in 2025.")
    body = _ask(client, ds, "Which treatment works best?").json()
    assert body["status"] == "out_of_scope" and body["results"] == []
    assert body["answer"].startswith("MolarMetrics cannot answer that")
    script.then("Crowns work best: they earned ₹23,000.00.")
    body = _ask(client, ds, "Which treatment works best?").json()
    assert "23,000" not in body["answer"] and body["answer"].startswith("MolarMetrics cannot answer that")


def test_switching_datasets_clears_the_conversation(app, client, script):
    sunrise = import_sunrise(client)
    lakeview = import_lakeview(client)
    script.then(script.tool_call("get_clinic_kpis", KPIS_2025), "Billed revenue was ₹47,000.00.")
    _ask(client, sunrise, "What was billed revenue in 2025?")
    conversations = app.state.mm.ask._conversations
    assert any(k[1] == sunrise["id"] for k in conversations)
    client.put("/api/session/active", json={"dataset_id": lakeview["id"]})
    assert not conversations


def test_a_second_question_waits_for_the_first(client, script):
    ds = import_sunrise(client)
    script.gate = threading.Event()
    script.then(script.tool_call("get_clinic_kpis", KPIS_2025), "Billed revenue was ₹47,000.00.")
    first: dict = {}
    worker = threading.Thread(target=lambda: first.setdefault("r", _ask(client, ds, "What was billed revenue?")))
    worker.start()
    try:
        deadline = time.time() + 5
        while time.time() < deadline and not any(lock.locked() for lock in
                                                 client.app.state.mm.ask._locks.values()):
            time.sleep(0.02)
        second = _ask(client, ds, "And collections?")
        assert second.status_code == 409 and second.json()["error"]["code"] == "busy"
    finally:
        script.gate.set()
        worker.join(10)
    assert first["r"].status_code == 200


def test_a_failed_answer_can_be_retried(client, script):
    ds = import_sunrise(client)
    failed = _ask(client, ds, "What was billed revenue in 2025?")  # the model has nothing to say: it fails
    assert failed.status_code == 502
    assert failed.json()["error"]["message"] == "Something went wrong while answering. Please try again."
    assert "Traceback" not in failed.text
    script.then(script.tool_call("get_clinic_kpis", KPIS_2025), "Billed revenue was ₹47,000.00.")
    assert _ask(client, ds, "What was billed revenue in 2025?").status_code == 200


def test_when_the_question_service_is_down_the_overview_still_works(web_settings, monkeypatch):
    from fastapi.testclient import TestClient

    from molarmetrics.api.app import create_app
    from tests.web.conftest import HEADERS

    monkeypatch.setattr(ask_module, "check_ollama", lambda **_: OllamaStatus(
        base_url="http://127.0.0.1:9", model="m", is_local=True))
    with TestClient(create_app(web_settings, AskService()), headers=HEADERS) as c:
        ds = import_sunrise(c)
        assert c.get("/api/session").json()["questions_available"] is False
        response = _ask(c, ds, "What was billed revenue?")
        assert response.status_code == 503 and response.json()["error"]["message"] == UNAVAILABLE_MESSAGE
        assert c.get(f"/api/datasets/{ds['id']}/overview").status_code == 200


def test_questions_are_never_logged(client, script, caplog):
    ds = import_sunrise(client)
    secret = "patient Ravi Kumar phone 9876543210"
    caplog.set_level(logging.DEBUG)
    script.then(script.tool_call("get_clinic_kpis", KPIS_2025), "Billed revenue was ₹47,000.00.")
    _ask(client, ds, f"What was billed revenue for {secret}?")
    _ask(client, ds, f"Why did {secret} cancel?")  # fails: nothing scripted
    assert caplog.records, "expected request logs"
    assert all(secret not in r.getMessage() and "Ravi" not in r.getMessage() for r in caplog.records)
    assert any("outcome=" in r.getMessage() for r in caplog.records)


def test_suggested_questions_follow_the_data(client):
    sunrise = import_sunrise(client)
    questions = client.get(f"/api/datasets/{sunrise['id']}/suggestions").json()["questions"]
    assert "What was billed revenue in 2025?" in questions
    assert "How much was outstanding as of 12 March 2025?" in questions
    appts_only = import_lakeview(client, only=("appointments",))
    questions = client.get(f"/api/datasets/{appts_only['id']}/suggestions").json()["questions"]
    assert questions[0] == "How many completed visits were there in 2024?"
    assert not any("revenue" in q or "outstanding" in q for q in questions)


def test_empty_and_overlong_questions_are_rejected(client):
    ds = import_sunrise(client)
    assert _ask(client, ds, "   ").json()["error"]["message"] == "Please type a question."
    assert _ask(client, ds, "x" * 501).status_code == 422


def test_suggestions_use_the_latest_well_covered_year():
    from molarmetrics.api.ask_service import best_year
    from molarmetrics.dataset import SAMPLE_CONTEXT, DatasetContext

    assert best_year(SAMPLE_CONTEXT) == 2025  # 2024 (leap year) must not win by one day
    spanning = DatasetContext(kind="uploaded", name="x", coverage_start="2024-07-01", coverage_end="2025-02-28",
                              capabilities=frozenset({"appointments"}), procedure_names=(), notice="")
    assert best_year(spanning) == 2024
