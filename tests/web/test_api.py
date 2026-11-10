"""Web API: sessions and ownership, uploads and atomic import, the overview,
exports, retention and removal. Totals are the hand calculations in
examples/README.md."""

import csv
import io
import json
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from molarmetrics.api import uploads as uploads_module
from molarmetrics.api.app import create_app
from molarmetrics.api.ask_service import AskService
from molarmetrics.api.presenters import prohibited_terms
from molarmetrics.ingest.build import ImportFailed
from tests.web.conftest import HEADERS, confirm, import_lakeview, import_sunrise, upload
from tests.web.helpers import csv_bytes


def _kpis(overview: dict) -> dict:
    return {k["key"]: k for k in overview["kpis"]}


def _csv(response) -> list[dict]:
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))


# --- sessions --------------------------------------------------------------------------------
def test_a_new_session_starts_empty_and_sample_data_is_not_loaded(client):
    response = client.get("/api/session")
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    state = response.json()
    assert state["datasets"] == [] and state["active_dataset_id"] is None
    assert state["retention_hours"] == 24


def test_explore_sample_data_explicitly_activates_the_sample(client):
    meta = client.post("/api/datasets/sample").json()
    assert (meta["kind"], meta["name"], meta["active"]) == ("sample", "Sample clinic", True)
    assert meta["coverage"]["start"] == "2024-01-01" and meta["counts"]["appointments"] == 5929
    overview = client.get(f"/api/datasets/{meta['id']}/overview").json()
    assert _kpis(overview)["billed_revenue"]["status"] == "available"
    assert client.post("/api/datasets/sample").json()["id"] == meta["id"]  # idempotent


def test_state_changing_requests_need_the_app_header(app):
    with TestClient(app) as bare:  # no X-MolarMetrics header, like a cross-site form
        assert bare.post("/api/datasets/sample").status_code == 403


def test_requests_for_other_hosts_are_refused(client):
    assert client.get("/api/session", headers={"host": "evil.example"}).status_code == 400


def test_another_session_cannot_use_a_dataset_id(client, other_client):
    ds = import_sunrise(client)
    ds_id = ds["id"]
    for method, url, body in [
        ("get", f"/api/datasets/{ds_id}", None),
        ("get", f"/api/datasets/{ds_id}/overview", None),
        ("get", f"/api/datasets/{ds_id}/suggestions", None),
        ("get", f"/api/datasets/{ds_id}/export.csv?analysis=kpis", None),
        ("post", f"/api/datasets/{ds_id}/ask", {"question": "What was billed revenue?"}),
        ("put", "/api/session/active", {"dataset_id": ds_id}),
        ("delete", f"/api/datasets/{ds_id}", None),
    ]:
        response = getattr(other_client, method)(url, **({"json": body} if body else {}))
        assert response.status_code == 404, (method, url, response.status_code)
    assert client.get(f"/api/datasets/{ds_id}/overview").status_code == 200  # still there for its owner


def test_another_session_cannot_see_an_upload_in_review(client, other_client):
    batch = upload(client, "sunrise-dental")
    assert other_client.get(f"/api/uploads/{batch['batch_id']}").status_code == 404
    assert other_client.post(f"/api/uploads/{batch['batch_id']}/import", json=batch["config"]).status_code == 404


# --- uploads and import ---------------------------------------------------------------------------
def test_upload_returns_previews_suggestions_and_a_blocking_report(client):
    batch = upload(client, "sunrise-dental")
    files = {f["filename"]: f for f in batch["files"]}
    assert files["appointments.csv"]["rows"] == 16
    assert files["appointments.csv"]["preview"][0][:3] == ["SA01", "S-P01", "06/01/2025"]
    assert batch["report"]["ready"] is False
    assert {i["code"] for i in batch["report"]["issues"] if i["severity"] == "blocking"} == {
        "date_format_ambiguous", "money_unit_unconfirmed"}


def test_files_can_be_removed_before_import(client):
    batch = upload(client, "sunrise-dental")
    patients = next(f for f in batch["files"] if f["filename"] == "patients.csv")
    after = client.delete(f"/api/uploads/{batch['batch_id']}/files/{patients['file_id']}").json()
    assert [f["filename"] for f in after["files"]] == ["appointments.csv", "dentists.csv", "payments.csv",
                                                      "treatments.csv"]


@pytest.mark.parametrize("name, data, fragment", [
    ("notes.txt", b"a,b\n1,2\n", "Only .csv files"),
    ("book.csv", b"PK\x03\x04binary", "Excel workbook"),
    ("big.csv", b"a,b\n" + b"1,2\n" * 600_000, "larger than 2 MB"),
])
def test_unreadable_uploads_are_rejected_with_plain_reasons(client, name, data, fragment):
    response = client.post("/api/uploads", files=[("files", (name, data, "text/csv"))])
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "upload_rejected" and fragment in body["files"][0]["message"]


def test_import_requires_a_ready_report(client):
    batch = upload(client, "sunrise-dental")
    response = client.post(f"/api/uploads/{batch['batch_id']}/import", json=batch["config"])
    assert response.status_code == 422 and response.json()["error"]["code"] == "not_ready"
    assert client.get("/api/session").json()["datasets"] == []


def test_sunrise_overview_matches_hand_calculations(client):
    ds = import_sunrise(client)
    assert ds["active"] and ds["coverage"]["label"] == "6 Jan 2025 – 12 Mar 2025"
    overview = client.get(f"/api/datasets/{ds['id']}/overview").json()
    k = _kpis(overview)
    assert (k["billed_revenue"]["value"], k["billed_revenue"]["exact"]) == (4_700_000, "₹47,000.00")
    assert (k["collections"]["value"], k["collections"]["exact"]) == (3_720_000, "₹37,200.00")
    assert (k["outstanding_balance"]["value"], k["outstanding_balance"]["detail"]) == (980_000, "On 12 Mar 2025")
    assert (k["completed_visits"]["value"], k["completed_visits"]["detail"]) == (11, "of 16 scheduled appointments")
    assert (k["no_show_rate"]["display"], k["no_show_rate"]["detail"]) == ("18.8%", "3 of 16 scheduled appointments")
    rows = overview["finance"]["rows"]
    assert [(r["month_label"], r["billed_paise"], r["collected_paise"]) for r in rows] == [
        ("Jan 2025", 1_000_000, 800_000), ("Feb 2025", 1_800_000, 1_400_000), ("Mar 2025", 1_900_000, 1_520_000)]
    assert [r["cumulative_billed_paise"] for r in rows] == [1_000_000, 2_800_000, 4_700_000]
    assert [r["cumulative_collected_paise"] for r in rows] == [800_000, 2_200_000, 3_720_000]
    assert [(p["procedure"], p["billed"]) for p in overview["top_procedures"]["rows"][:2]] == [
        ("Crown", "₹23,000.00"), ("Root canal treatment", "₹8,000.00")]
    assert overview["unavailable"] == []


def test_period_filter_is_clamped_to_coverage_and_presets_follow_the_data(client):
    ds = import_sunrise(client)
    overview = client.get(f"/api/datasets/{ds['id']}/overview",
                          params={"start": "2025-02-01", "end": "2025-12-31"}).json()
    assert overview["period"] == {"start": "2025-02-01", "end": "2025-03-12", "label": "1 Feb 2025 – 12 Mar 2025",
                                  "clamped": True}
    assert [r["month"] for r in overview["finance"]["rows"]] == ["2025-02", "2025-03"]  # no empty Apr–Dec
    assert _kpis(overview)["billed_revenue"]["value"] == 3_700_000  # 18,000 + 19,000
    assert [p["label"] for p in overview["presets"]] == ["All data"]  # one partial year: no duplicate preset
    bad = client.get(f"/api/datasets/{ds['id']}/overview", params={"start": "2025-03-01", "end": "2025-01-01"})
    assert bad.status_code == 422


def test_switching_datasets_changes_the_overview_and_never_mixes_data(client):
    sunrise = import_sunrise(client)
    lakeview = import_lakeview(client)
    state = client.get("/api/session").json()
    assert state["active_dataset_id"] == lakeview["id"] and len(state["datasets"]) == 2
    lk = _kpis(client.get(f"/api/datasets/{lakeview['id']}/overview").json())
    assert (lk["billed_revenue"]["value"], lk["collections"]["value"], lk["outstanding_balance"]["value"]) == (
        4_100_000, 3_100_000, 1_000_000)
    client.put("/api/session/active", json={"dataset_id": sunrise["id"]})
    assert client.get("/api/session").json()["active_dataset_id"] == sunrise["id"]
    sk = _kpis(client.get(f"/api/datasets/{sunrise['id']}/overview").json())
    assert sk["billed_revenue"]["value"] == 4_700_000
    sample = client.post("/api/datasets/sample").json()
    sample_billed = _kpis(client.get(f"/api/datasets/{sample['id']}/overview").json())["billed_revenue"]["value"]
    assert sample_billed not in (4_700_000, 4_100_000) and sample_billed > 100_000_000


def test_import_notes_from_review_decisions_are_shown(client):
    lakeview = import_lakeview(client)
    assert lakeview["import_notes"][0].startswith("1 treatment record on cancelled or no-show appointments")
    overview = client.get(f"/api/datasets/{lakeview['id']}/overview").json()
    assert lakeview["import_notes"][1] in overview["notes"]


def test_appointments_only_overview_shows_no_money(client):
    ds = import_lakeview(client, only=("appointments",))
    overview = client.get(f"/api/datasets/{ds['id']}/overview").json()
    k = _kpis(overview)
    assert overview["finance"] is None and overview["top_procedures"] is None
    assert [r["scheduled"] for r in overview["appointments"]["rows"]] == [4, 3, 3]
    assert {key for key, v in k.items() if v["status"] == "available"} == {
        "completed_visits", "no_show_rate", "scheduled_appointments", "unique_patients_seen"}
    assert all(v["value"] is None for v in k.values() if v["kind"] == "inr")  # unavailable, never zero
    assert "Add payment records to see collections and outstanding balances." in overview["unavailable"]
    assert "₹0" not in json.dumps(overview, ensure_ascii=False)


def test_a_failed_import_keeps_the_active_dataset(client, monkeypatch, web_settings):
    sunrise = import_sunrise(client)
    batch = upload(client, "lakeview-dental")
    config = confirm(batch, "Lakeview", unit="paise", decisions={
        "payments_before_treatment": "include", "treatments_on_unattended_appointments": "exclude"})

    def failing_import(*_args, **_kwargs):
        raise ImportFailed("simulated disk failure")

    monkeypatch.setattr(uploads_module, "atomic_import", failing_import)
    response = client.post(f"/api/uploads/{batch['batch_id']}/import", json=config)
    assert response.status_code == 500
    assert response.json()["error"]["message"] == "The import couldn't be completed. Your current data is unchanged."
    state = client.get("/api/session").json()
    assert state["active_dataset_id"] == sunrise["id"] and len(state["datasets"]) == 1
    assert [p.name for p in web_settings.datasets_dir.iterdir()] == [sunrise["id"]]
    assert _kpis(client.get(f"/api/datasets/{sunrise['id']}/overview").json())["billed_revenue"]["value"] == 4_700_000


def test_issues_report_lists_rows_and_is_formula_safe(client):
    data = csv_bytes(["appointment_id", "patient_id", "appointment_date", "status"],
                     [["=HYPERLINK(1)", "P1", "2025-01-05", "completed"], ["=HYPERLINK(1)", "P2", "2025-01-06",
                                                                          "completed"]])
    response = client.post("/api/uploads", files=[("files", ("appointments.csv", data, "text/csv"))])
    batch_id = response.json()["batch_id"]
    rows = _csv(client.get(f"/api/uploads/{batch_id}/issues.csv"))
    dup = next(r for r in rows if "already used" in r["problem"])
    assert dup["row"] == "3" and dup["severity"] == "Must fix" and dup["value"].startswith("'=")


# --- exports ------------------------------------------------------------------------------------
def test_exports_use_the_selected_dataset_and_exact_amounts(client):
    sunrise = import_sunrise(client)
    lakeview = import_lakeview(client)
    s_url = client.get(f"/api/datasets/{sunrise['id']}/overview").json()["finance"]["export_url"]
    l_url = client.get(f"/api/datasets/{lakeview['id']}/overview").json()["finance"]["export_url"]
    s_rows, l_rows = _csv(client.get(s_url)), _csv(client.get(l_url))
    assert [(r["month"], r["billed_inr"], r["collected_inr"]) for r in s_rows] == [
        ("2025-01", "10000.00", "8000.00"), ("2025-02", "18000.00", "14000.00"), ("2025-03", "19000.00", "15200.00")]
    assert {r["dataset"] for r in s_rows} == {"Sunrise Dental"}
    assert l_rows[0]["difference_inr"] == "-2500.00"  # Jul 2024: 8,100 billed − 10,600 collected; still a number
    assert {r["dataset"] for r in l_rows} == {"Lakeview Dental"}
    response = client.get(s_url)
    assert "molarmetrics_sunrise_dental" in response.headers["content-disposition"]


def test_exported_text_cells_cannot_run_as_formulas(client):
    batch = upload(client, "sunrise-dental")
    config = confirm(batch, "=cmd|' /C calc'!A0", unit="rupees", date_format="DD/MM/YYYY")
    ds = client.post(f"/api/uploads/{batch['batch_id']}/import", json=config).json()
    rows = _csv(client.get(f"/api/datasets/{ds['id']}/export.csv?analysis=kpis"))
    assert all(r["dataset"].startswith("'=") for r in rows)
    assert next(r for r in rows if r["metric_name"] == "billed_revenue")["value"] == "47000.00"


def test_unavailable_results_cannot_be_exported(client):
    ds = import_lakeview(client, only=("appointments",))
    assert client.get(f"/api/datasets/{ds['id']}/export.csv?analysis=finances").status_code == 422


# --- removal and retention ----------------------------------------------------------------------
def test_remove_dataset_deletes_its_files(client, web_settings):
    ds = import_sunrise(client)
    folder = web_settings.datasets_dir / ds["id"]
    assert (folder / "clinic.sqlite3").exists()
    state = client.delete(f"/api/datasets/{ds['id']}").json()
    assert state["datasets"] == [] and state["active_dataset_id"] is None
    assert not folder.exists()
    assert client.get(f"/api/datasets/{ds['id']}/overview").status_code == 404


def test_removing_the_sample_never_deletes_the_bundled_file(client):
    from molarmetrics.config import get_settings

    sample = client.post("/api/datasets/sample").json()
    client.delete(f"/api/datasets/{sample['id']}")
    assert get_settings().db_path.exists()


def _age_dataset(app, dataset_id: str, hours: float):
    store = app.state.mm.store
    with store._tx() as c:
        c.execute("UPDATE datasets SET last_used_at = ? WHERE id = ?", (time.time() - hours * 3600, dataset_id))


def test_expired_datasets_are_deleted_on_access(app, client, web_settings):
    ds = import_sunrise(client)
    _age_dataset(app, ds["id"], 25)
    response = client.get(f"/api/datasets/{ds['id']}/overview")
    assert response.status_code == 410 and "expired" in response.json()["error"]["message"]
    assert not (web_settings.datasets_dir / ds["id"]).exists()


def test_startup_deletes_only_expired_uploads(app, client, web_settings, script):
    old = import_sunrise(client)
    fresh = import_lakeview(client)
    _age_dataset(app, old["id"], 30)
    (web_settings.datasets_dir / ".half-finished.tmp").mkdir()
    with TestClient(create_app(web_settings, AskService(model_factory=script.model)), headers=HEADERS):
        pass  # a new server process starting up
    assert not (web_settings.datasets_dir / old["id"]).exists()
    assert (web_settings.datasets_dir / fresh["id"] / "clinic.sqlite3").exists()
    assert not (web_settings.datasets_dir / ".half-finished.tmp").exists()
    assert client.get(f"/api/datasets/{fresh['id']}/overview").status_code == 200


def test_the_running_sweep_removes_expired_uploads_and_reviews(app, client, web_settings):
    ds = import_sunrise(client)
    batch = upload(client, "lakeview-dental")
    _age_dataset(app, ds["id"], 25)
    with app.state.mm.store._tx() as c:
        c.execute("UPDATE batches SET last_used_at = ?", (time.time() - 25 * 3600,))
    removed = app.state.mm.retention.sweep()
    assert removed["datasets"] == 1 and removed["uploads_in_review"] == 1
    assert not (web_settings.staging_dir / batch["batch_id"]).exists()


# --- templates ------------------------------------------------------------------------------------
def test_templates_and_example_bundle(client):
    appts = client.get("/api/templates/appointments.csv").content.decode()
    assert appts.splitlines()[0] == "appointment_id,patient_id,appointment_date,status,appointment_time,dentist_id"
    assert client.get("/api/templates/treatments.csv").content.decode().splitlines()[0].endswith("discount_inr")
    names = zipfile.ZipFile(io.BytesIO(client.get("/api/templates/example-bundle.zip").content)).namelist()
    assert sorted(Path(n).name for n in names) == ["appointments.csv", "dentists.csv", "patients.csv",
                                                   "payments.csv", "treatments.csv"]
    catalog = {r["key"]: r for r in client.get("/api/record-types").json()}
    assert catalog["appointments"]["one_row"].startswith("One booked appointment")


def test_the_templates_import_cleanly(client):
    files = [("files", (f"{t}.csv", client.get(f"/api/templates/{t}.csv").content, "text/csv"))
             for t in ("appointments", "treatments", "payments", "patients", "dentists")]
    batch = client.post("/api/uploads", files=files).json()
    config = confirm(batch, "Template check", unit="rupees")
    report = client.post(f"/api/uploads/{batch['batch_id']}/validate", json=config).json()
    assert report["ready"], report["issues"]


# --- user-facing text ------------------------------------------------------------------------------
def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            if k not in ("export_url", "key", "code", "kind", "id", "x", "unit", "aggregation", "date_basis",
                         "capabilities", "record_type", "suggested_record_type", "field", "file_id", "status",
                         "money_unit", "money_unit_suggestion", "chosen", "suggested", "candidates", "detected",
                         "filters", "columns", "rows", "mapping", "date_range", "decision", "batch_id", "config",
                         "severity", "series", "suggestions"):
                yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def test_user_facing_text_has_no_implementation_details(client):
    sunrise = import_sunrise(client)
    lakeview = import_lakeview(client)
    sample = client.post("/api/datasets/sample").json()
    payloads = [client.get("/api/session").json()]
    for ds in (sunrise, lakeview, sample):
        payloads.append(client.get(f"/api/datasets/{ds['id']}/overview").json())
        payloads.append(client.get(f"/api/datasets/{ds['id']}/suggestions").json())
    payloads.append(upload(client, "sunrise-dental"))
    payloads.append(client.get("/api/datasets/nope/overview").json())
    for payload in payloads:
        for text in _strings(payload):
            assert not prohibited_terms(text), text
