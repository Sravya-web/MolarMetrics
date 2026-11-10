"""CSV import: parsing, mapping, validation, review decisions and atomic build.

Expected totals are hand calculations (examples/README.md), not outputs of
MolarMetrics code.
"""

import shutil

import pytest

from molarmetrics.analytics import analyses as A
from molarmetrics.analytics.db import connect_readonly
from molarmetrics.analytics.params import arg_models_for
from molarmetrics.ingest import build as B
from molarmetrics.ingest.parsing import MoneyError, UploadRejected, parse_csv, parse_money
from molarmetrics.ingest.validate import FileConfig, ImportConfig, validate_batch
from tests.web.helpers import (
    LAKEVIEW,
    LAKEVIEW_DECISIONS,
    SUNRISE,
    choices,
    csv_bytes,
    import_files,
    lakeview_config,
    load_bundle,
    sunrise_config,
)

APPT_HEADER = ["appointment_id", "patient_id", "appointment_date", "status"]


def _codes(report, severity="blocking"):
    return [i.code for i in report.issues if i.severity == severity]


def _validate(*files, unit="rupees", date_format=None, decisions=None):
    parsed = [parse_csv(f"f{i}", name, data) for i, (name, data) in enumerate(files)]
    report, issues, data = validate_batch(parsed, choices(parsed, unit=unit, date_format=date_format,
                                                          decisions=decisions))
    return report, issues, data


# --- suggestions --------------------------------------------------------------------------
def test_record_types_and_column_mappings_are_suggested():
    files = {f.filename: f for f in load_bundle("sunrise-dental")}
    cfg = {c.file_id: c for c in sunrise_config(list(files.values())).files}
    appt = cfg[files["appointments.csv"].file_id]
    assert appt.record_type == "appointments"
    assert appt.mapping == {"appointment_id": "Appt ID", "patient_id": "Patient Code", "appointment_date": "Visit Date",
                            "status": "Status", "appointment_time": "Time", "dentist_id": "Doctor"}
    assert appt.status_map == {"attended": "completed", "dna": "no_show", "cancelled": "cancelled"}
    treat = cfg[files["treatments.csv"].file_id]
    assert treat.mapping["net_fee"] == "Net (Rs)" and treat.mapping["listed_fee"] == "Fee (Rs)"
    assert cfg[files["payments.csv"].file_id].mapping["amount"] == "Amount (Rs)"


def test_money_units_and_ambiguous_dates_must_be_confirmed():
    files = load_bundle("sunrise-dental")
    report, _, data = validate_batch(files, choices(files))  # nothing confirmed yet
    assert not report.ready and data is None
    codes = _codes(report)
    assert codes.count("date_format_ambiguous") == 3  # appointments, payments, patients
    assert codes.count("money_unit_unconfirmed") == 2  # treatments, payments
    appt_dates = next(f for f in report.files if f.record_type == "appointments").date_fields[0]
    assert appt_dates.ambiguous and set(appt_dates.candidates) == {"DD/MM/YYYY", "MM/DD/YYYY"}


# --- the two hand-checked bundles --------------------------------------------------------------
def test_sunrise_bundle_imports_with_hand_calculated_totals(tmp_path):
    files = load_bundle("sunrise-dental")
    db_path, ctx = import_files(tmp_path, files, sunrise_config(files))
    assert (ctx.coverage_start, ctx.coverage_end) == (SUNRISE["start"], SUNRISE["end"])
    assert ctx.has("treatments") and ctx.has("payments") and ctx.has("dentist_breakdown")
    models = arg_models_for(ctx)
    with connect_readonly(db_path) as conn:
        k = A.clinic_kpis(conn, models["get_clinic_kpis"](), ctx)
        assert k.summary_value("scheduled_appointments") == SUNRISE["scheduled"]
        assert k.summary_value("completed_visits") == SUNRISE["completed"]
        assert k.summary_value("no_show_rate") == SUNRISE["no_show_rate"]  # 3 / 16 = 18.75% -> 18.8%
        assert k.summary_value("unique_patients_seen") == SUNRISE["unique"]
        assert k.summary_value("returning_patients") == SUNRISE["returning"]
        assert k.summary_value("billed_revenue") == SUNRISE["billed"]
        assert k.summary_value("collections") == SUNRISE["collected"]
        f = A.finances(conn, models["analyze_finances"](), ctx)
        assert [(r["month"], r["billed_paise"], r["collected_paise"]) for r in f.rows] == [
            ("2025-01", 1_000_000, 800_000), ("2025-02", 1_800_000, 1_400_000), ("2025-03", 1_900_000, 1_520_000)]
        o = A.finances(conn, models["analyze_finances"](metric="outstanding_balance"), ctx)
        assert o.summary_value("outstanding_balance") == SUNRISE["outstanding"]
        assert o.summary_value("treatments_with_balance") == 3
        p = A.procedures(conn, models["analyze_procedures"](top_n=3), ctx)
        assert [(r["procedure"], r["billed_paise"]) for r in p.rows] == [
            ("Crown", 2_300_000), ("Root canal treatment", 800_000), ("Scaling", 540_000)]
        d = A.appointments(conn, models["analyze_appointments"](group_by="dentist", metric="completed_visits"), ctx)
        assert [(r["dentist"], r["completed"]) for r in d.rows] == [
            ("Dr. Meera Nair (S-D1)", 5), ("Dr. Karan Shah (S-D2)", 4), ("Dr. Leela Pillai (S-D3)", 2)]


def test_lakeview_review_groups_must_be_decided_before_import():
    files = load_bundle("lakeview-dental")
    report, _, data = validate_batch(files, lakeview_config(files, decisions={}))
    assert not report.ready and data is None and report.blocking == 0 and report.needs_review == 2
    groups = {g.code: g for g in report.review_groups}
    assert groups["payments_before_treatment"].count == 1
    assert "Row 7 in payments.csv" in groups["payments_before_treatment"].examples[0]
    unattended = groups["treatments_on_unattended_appointments"]
    assert unattended.count == 1 and "is the 1 payment linked to them" in unattended.exclude_effect
    assert {i.code for i in report.issues if i.severity == "review"} == {
        "payment_before_treatment", "treatment_on_unattended_appointment"}


def test_lakeview_decisions_change_what_is_imported_and_are_recorded(tmp_path):
    files = load_bundle("lakeview-dental")
    db_path, ctx = import_files(tmp_path, files, lakeview_config(files))
    assert ctx.import_notes == (
        "1 treatment record on cancelled or no-show appointments was left out at import, with 1 linked payment.",
        "1 payment dated before its treatment is included as recorded (reviewed at import).")
    with connect_readonly(db_path) as conn:
        k = A.clinic_kpis(conn, arg_models_for(ctx)["get_clinic_kpis"](), ctx)
        assert (k.summary_value("billed_revenue"), k.summary_value("collections")) == (
            LAKEVIEW["billed"], LAKEVIEW["collected"])
        assert set(ctx.import_notes) <= set(k.notes)  # shown with money results, never silent
        o = A.finances(conn, arg_models_for(ctx)["analyze_finances"](metric="outstanding_balance"), ctx)
        assert o.summary_value("outstanding_balance") == LAKEVIEW["outstanding"]
    # Including everything instead: the cancellation fee (₹500) and its payment (₹500) are added.
    _, ctx2 = import_files(tmp_path, files, lakeview_config(files, decisions={
        "payments_before_treatment": "include", "treatments_on_unattended_appointments": "include"}), "ds2")
    with connect_readonly(tmp_path / "datasets" / "ds2" / "clinic.sqlite3") as conn:
        k = A.clinic_kpis(conn, arg_models_for(ctx2)["get_clinic_kpis"](), ctx2)
        assert (k.summary_value("billed_revenue"), k.summary_value("collections")) == (4_150_000, 3_150_000)


def test_excluding_early_payments_removes_them_from_collections(tmp_path):
    files = load_bundle("lakeview-dental")
    decisions = {**LAKEVIEW_DECISIONS, "payments_before_treatment": "exclude"}
    db_path, ctx = import_files(tmp_path, files, lakeview_config(files, decisions=decisions))
    with connect_readonly(db_path) as conn:
        k = A.clinic_kpis(conn, arg_models_for(ctx)["get_clinic_kpis"](), ctx)
        assert k.summary_value("collections") == LAKEVIEW["collected"] - 500_000  # the ₹5,000 crown advance
    assert any("left out at import" in n for n in ctx.import_notes)


# --- capability gating: appointments alone ------------------------------------------------------
def test_appointments_only_import_reports_money_as_unavailable_not_zero(tmp_path):
    files = load_bundle("lakeview-dental", only=("appointments",))
    db_path, ctx = import_files(tmp_path, files, choices(files))
    assert sorted(ctx.capabilities) == ["appointments", "dentist_breakdown"]
    models = arg_models_for(ctx)
    with connect_readonly(db_path) as conn:
        k = A.clinic_kpis(conn, models["get_clinic_kpis"](), ctx)
        keys = {s.key for s in k.summary}
        assert "billed_revenue" not in keys and "collections" not in keys
        assert k.summary_value("completed_visits") == LAKEVIEW["completed"]
        assert k.summary_value("no_show_rate") == LAKEVIEW["no_show_rate"]
        assert any("Add treatment records" in f for f in k.facts)
        assert any("Add payment records" in f for f in k.facts)
        assert A.procedures(conn, models["analyze_procedures"](), ctx).status == "unavailable"
        assert A.finances(conn, models["analyze_finances"](), ctx).status == "unavailable"
        out = A.finances(conn, models["analyze_finances"](metric="outstanding_balance"), ctx)
        assert out.status == "unavailable" and "Add treatment and payment records" in out.facts[0]
        by_dentist = A.appointments(conn, models["analyze_appointments"](group_by="dentist"), ctx)
        assert [r["dentist"] for r in by_dentist.rows] == ["L-D1", "L-D2"]  # codes, no dentists file
        assert "specialty" not in {c.key for c in by_dentist.columns}


def test_treatments_without_payments_show_billed_only(tmp_path):
    files = load_bundle("lakeview-dental", only=("appointments", "treatments"))
    db_path, ctx = import_files(tmp_path, files, lakeview_config(files, decisions={
        "treatments_on_unattended_appointments": "exclude"}))
    with connect_readonly(db_path) as conn:
        f = A.finances(conn, arg_models_for(ctx)["analyze_finances"](), ctx)
        assert f.status == "ok" and [c.key for c in f.columns] == ["month", "billed_paise"]
        assert f.summary_value("billed_revenue") == LAKEVIEW["billed"]
        assert any("Add payment records to see collections" in x for x in f.facts)


# --- exact money ----------------------------------------------------------------------------------
@pytest.mark.parametrize("raw, unit, paise", [
    ("1,23,456.78", "rupees", 12_345_678), ("₹1,500.00", "rupees", 150_000), ("Rs. 1500", "rupees", 150_000),
    ("0.07", "rupees", 7), ("12.340", "rupees", 1_234), ("150050", "paise", 150_050), ("150050.00", "paise", 150_050),
    ("123,456", "rupees", 12_345_600),
])
def test_money_is_parsed_exactly_to_paise(raw, unit, paise):
    assert parse_money(raw, unit) == paise


@pytest.mark.parametrize("raw, unit", [("12.345", "rupees"), ("-500", "rupees"), ("(500)", "rupees"),
                                       ("1e5", "rupees"), ("1.234,56", "rupees"), ("12,34", "rupees"),
                                       ("1500.5", "paise"), ("abc", "rupees")])
def test_ambiguous_or_invalid_amounts_are_rejected(raw, unit):
    with pytest.raises(MoneyError):
        parse_money(raw, unit)


def test_blank_amounts_are_never_treated_as_zero():
    appts = csv_bytes(APPT_HEADER, [["A1", "P1", "2025-01-05", "completed"]])
    treats = csv_bytes(["treatment_id", "appointment_id", "procedure", "net_fee"], [["T1", "A1", "Scaling", ""]])
    report, issues, data = _validate(("appointments.csv", appts), ("treatments.csv", treats))
    assert data is None and "blank_required" not in _codes(report)
    assert "blank_net_fee" in _codes(report)
    discount = csv_bytes(["treatment_id", "appointment_id", "procedure", "listed_fee", "discount"],
                         [["T1", "A1", "Scaling", "1500", ""]])
    report, _, data = _validate(("appointments.csv", appts), ("treatments.csv", discount))
    assert data is None and "blank_discount" in _codes(report)


def test_fee_and_discount_must_be_consistent():
    appts = csv_bytes(APPT_HEADER, [["A1", "P1", "2025-01-05", "completed"]])
    header = ["treatment_id", "appointment_id", "procedure", "listed_fee", "discount", "net_fee"]
    treats = csv_bytes(header, [["T1", "A1", "Scaling", "1500", "100", "1500"],
                                ["T2", "A1", "Filling", "1000", "1200", "0"]])
    report, _, _ = _validate(("appointments.csv", appts), ("treatments.csv", treats))
    by_row = {i.row: i.code for i in report.issues if i.severity == "blocking"}
    assert by_row == {2: "fee_mismatch", 3: "discount_exceeds_fee"}


def test_payments_may_not_exceed_the_net_fee():
    appts = csv_bytes(APPT_HEADER, [["A1", "P1", "2025-01-05", "completed"]])
    treats = csv_bytes(["treatment_id", "appointment_id", "procedure", "net_fee"], [["T1", "A1", "Crown", "1000"]])
    pays = csv_bytes(["payment_id", "treatment_id", "payment_date", "amount"],
                     [["PM1", "T1", "2025-01-05", "600"], ["PM2", "T1", "2025-01-09", "600"]])
    report, _, data = _validate(("appointments.csv", appts), ("treatments.csv", treats), ("payments.csv", pays))
    overpaid = next(i for i in report.issues if i.code == "overpaid_treatment")
    assert "₹1,200.00, more than its net fee of ₹1,000.00" in overpaid.message and data is None


# --- dates ----------------------------------------------------------------------------------------
def test_ambiguous_dates_are_imported_as_the_user_chooses():
    rows = [["A1", "P1", "06/01/2025", "completed"], ["A2", "P2", "03/02/2025", "completed"]]
    data_bytes = csv_bytes(APPT_HEADER, rows)
    _, _, dmy = _validate(("appointments.csv", data_bytes), date_format="DD/MM/YYYY")
    _, _, mdy = _validate(("appointments.csv", data_bytes), date_format="MM/DD/YYYY")
    assert [a["appointment_datetime"][:10] for a in dmy.appointments] == ["2025-01-06", "2025-02-03"]
    assert [a["appointment_datetime"][:10] for a in mdy.appointments] == ["2025-06-01", "2025-03-02"]


def test_unambiguous_day_first_dates_need_no_question():
    report, _, data = _validate(("appointments.csv", csv_bytes(APPT_HEADER, [
        ["A1", "P1", "13/01/2025", "completed"], ["A2", "P2", "03/02/2025", "completed"]])))
    assert report.ready and data.appointments[1]["appointment_datetime"].startswith("2025-02-03")


def test_invalid_dates_are_reported_with_spreadsheet_row_numbers():
    report, _, _ = _validate(("appointments.csv", csv_bytes(APPT_HEADER, [
        ["A1", "P1", "2025-01-05", "completed"], ["A2", "P2", "2025-02-30", "completed"]])))
    bad = next(i for i in report.issues if i.code == "invalid_date")
    assert bad.row == 3 and "2025-02-30" in bad.message  # header = row 1


def test_blank_lines_keep_row_numbers_aligned_with_the_spreadsheet():
    data = b"appointment_id,patient_id,appointment_date,status\nA1,P1,2025-01-05,completed\n\nA1,P2,2025-01-06,completed\n"
    report, _, _ = _validate(("appointments.csv", data))
    dup = next(i for i in report.issues if i.code == "duplicate_id")
    assert dup.row == 4 and "already used in row 2" in dup.message


# --- identifiers and relationships ----------------------------------------------------------------
def test_missing_and_duplicate_identifiers_block_import():
    report, _, data = _validate(("appointments.csv", csv_bytes(APPT_HEADER, [
        ["A1", "P1", "2025-01-05", "completed"], ["", "P2", "2025-01-06", "completed"],
        ["A1", "P3", "2025-01-07", "completed"]])))
    assert data is None
    assert {(i.code, i.row) for i in report.issues if i.severity == "blocking"} == {
        ("blank_required", 3), ("duplicate_id", 4)}


def test_broken_relationships_are_reported_not_dropped():
    appts = csv_bytes(APPT_HEADER + ["dentist_id"], [["A1", "P1", "2025-01-05", "completed", "D9"],
                                                    ["A2", "P404", "2025-01-06", "completed", "D1"]])
    patients = csv_bytes(["patient_id"], [["P1"]])
    dentists = csv_bytes(["dentist_id"], [["D1"]])
    treats = csv_bytes(["treatment_id", "appointment_id", "procedure", "net_fee"], [["T1", "A77", "Scaling", "100"]])
    pays = csv_bytes(["payment_id", "treatment_id", "payment_date", "amount"], [["PM1", "T88", "2025-01-05", "100"]])
    report, _, data = _validate(("appointments.csv", appts), ("patients.csv", patients), ("dentists.csv", dentists),
                                ("treatments.csv", treats), ("payments.csv", pays))
    assert data is None
    assert {i.code for i in report.issues if i.severity == "blocking"} == {
        "unknown_dentist", "unknown_patient", "unknown_appointment", "unknown_treatment"}


def test_unmapped_status_labels_block_until_mapped():
    data_bytes = csv_bytes(APPT_HEADER, [["A1", "P1", "2025-01-05", "Booked"], ["A2", "P1", "2025-01-06", "Seen"]])
    parsed = [parse_csv("f0", "appointments.csv", data_bytes)]
    cfg = choices(parsed)
    report, _, _ = validate_batch(parsed, cfg)
    unmapped = next(i for i in report.issues if i.code == "status_unmapped")
    assert "'Booked' (1 row)" in unmapped.message
    cfg.files[0].status_map["booked"] = "cancelled"
    assert validate_batch(parsed, cfg)[0].ready


def test_required_fields_and_dependencies_are_enforced():
    report, _, _ = _validate(("appointments.csv", csv_bytes(["appointment_id", "patient_id", "status"],
                                                           [["A1", "P1", "completed"]])))
    assert "required_field_unmapped" in _codes(report)
    pays = csv_bytes(["payment_id", "treatment_id", "payment_date", "amount"], [["PM1", "T1", "2025-01-05", "100"]])
    report, _, _ = _validate(("payments.csv", pays))
    assert {"appointments_missing", "treatments_missing_for_payments"} <= set(_codes(report))


def test_two_files_of_the_same_type_are_rejected():
    a = csv_bytes(APPT_HEADER, [["A1", "P1", "2025-01-05", "completed"]])
    report, _, _ = _validate(("appointments.csv", a), ("appointments-2.csv", a))
    assert "duplicate_record_type" in _codes(report)


def test_unmapped_columns_are_listed_as_not_stored():
    data_bytes = csv_bytes(APPT_HEADER + ["Patient name", "Phone"], [["A1", "P1", "2025-01-05", "completed", "X", "9"]])
    report, _, data = _validate(("appointments.csv", data_bytes))
    note = next(i for i in report.issues if i.code == "columns_ignored")
    assert "Patient name" in note.message and "not stored" in note.message
    assert set(data.appointments[0]) == {"appointment_id", "patient_id", "dentist_id", "appointment_datetime", "status"}


# --- file structure ----------------------------------------------------------------------------------
def test_unreadable_files_are_rejected_in_plain_language():
    with pytest.raises(UploadRejected, match="Excel workbook"):
        parse_csv("x", "a.csv", b"PK\x03\x04rest")
    with pytest.raises(UploadRejected, match="CSV text file"):
        parse_csv("x", "a.csv", b"abc\x00def")
    with pytest.raises(UploadRejected, match="empty"):
        parse_csv("x", "a.csv", b"  \n\n")


def test_rows_with_extra_values_block_with_their_row_number():
    pf = parse_csv("x", "a.csv", b"a,b\n1,2\n3,4,5\n")
    problem = next(p for p in pf.problems if p.code == "too_many_values")
    assert problem.row == 3 and problem.severity == "blocking"


def test_duplicate_column_names_are_renamed_with_a_warning():
    pf = parse_csv("x", "a.csv", b"Date,Status,Date\n2025-01-01,done,2025-01-02\n")
    assert pf.columns == ["Date", "Status", "Date (column 3)"]
    assert any(p.code == "duplicate_column_name" for p in pf.problems)


# --- atomic build ------------------------------------------------------------------------------------
def test_a_failed_build_leaves_no_partial_dataset(tmp_path, monkeypatch):
    files = load_bundle("sunrise-dental")
    report, _, data = validate_batch(files, sunrise_config(files))

    def broken(*_args, **_kwargs):
        raise B.ImportFailed("simulated failure")

    monkeypatch.setattr(B, "verify_database", broken)
    with pytest.raises(B.ImportFailed):
        B.atomic_import(data, "Sunrise", tmp_path / "datasets", "new")
    assert list((tmp_path / "datasets").iterdir()) == []  # no final folder and no temporary folder


def test_server_side_revalidation_ignores_a_tampered_config():
    files = load_bundle("sunrise-dental")
    cfg = sunrise_config(files)
    cfg.files[0] = FileConfig(file_id=cfg.files[0].file_id, record_type="appointments",
                              mapping={"appointment_id": "No such column"})
    report, _, data = validate_batch(files, ImportConfig(name="x", files=cfg.files))
    assert data is None and "column_missing" in _codes(report)


def test_the_bundled_sample_folder_is_never_written(tmp_path):
    """Importing writes only under the given datasets folder."""
    files = load_bundle("lakeview-dental", only=("appointments",))
    import_files(tmp_path, files, choices(files))
    assert [p.name for p in (tmp_path / "datasets").iterdir()] == ["ds1"]
    shutil.rmtree(tmp_path / "datasets")
