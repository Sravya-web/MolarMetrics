"""Every tool result states explicit metric names, units, aggregation types and
date ranges, plus deterministic facts that are correct by construction."""

import json

import pytest

from molarmetrics.analytics import analyses as A
from molarmetrics.analytics.db import connect_readonly
from molarmetrics.analytics.params import AppointmentArgs, FinanceArgs, KpiArgs, ProcedureArgs
from molarmetrics.analytics.results import AGGREGATIONS, UNITS
from tests.integration.wording_checks import run_all

W = {"start_date": "2025-01-01", "end_date": "2025-02-28"}


def _variants(conn, period: dict) -> dict:
    return {
        "kpis": A.clinic_kpis(conn, KpiArgs(**period)),
        "appointments_month_status": A.appointments(conn, AppointmentArgs(**period)),
        "appointments_month_no_show": A.appointments(conn, AppointmentArgs(**period, metric="no_show_rate")),
        "appointments_dentist_completed": A.appointments(
            conn, AppointmentArgs(**period, group_by="dentist", metric="completed_visits")),
        "procedures_top3_billed": A.procedures(conn, ProcedureArgs(**period, top_n=3)),
        "procedures_compare_count": A.procedures(
            conn, ProcedureArgs(**period, metric="count", procedures=["root canal", "extraction"])),
        "procedures_compare_billed": A.procedures(conn, ProcedureArgs(**period, procedures=["root canal", "extraction"])),
        "finances_monthly": A.finances(conn, FinanceArgs(**period)),
        "finances_outstanding": A.finances(conn, FinanceArgs(metric="outstanding_balance",
                                                             as_of_date=period["end_date"])),
    }


@pytest.fixture()
def results(mini_conn):
    return _variants(mini_conn, W)


def test_every_number_declares_unit_and_aggregation(results):
    for name, r in results.items():
        for s in r.summary:
            assert s.unit in UNITS and s.aggregation in AGGREGATIONS, (name, s.key)
            if s.kind in ("count", "inr"):
                assert s.date_basis in ("appointment date", "payment date", "as-of date") or \
                    s.aggregation == "difference", (name, s.key)
        for c in r.columns:
            assert c.unit in UNITS and c.aggregation in AGGREGATIONS, (name, c.key)


def test_date_ranges_are_explicit(results):
    for name, r in results.items():
        expected = {"as_of": "2025-02-28"} if name == "finances_outstanding" else {"start": "2025-01-01",
                                                                                  "end": "2025-02-28"}
        assert r.date_range == expected, name


def test_facts_exist_and_never_say_average_or_majority(results):
    for name, r in results.items():
        assert r.facts, name
        for fact in r.facts:
            assert "average" not in fact.lower() and "majority" not in fact.lower(), (name, fact)


def test_facts_copied_verbatim_pass_every_wording_check(results):
    """If the model copies the facts exactly, it can never trip a regression check."""
    for name, r in results.items():
        for check, ok, detail in run_all(" ".join(r.facts), "", [r]):
            assert ok, (name, check, detail)


def test_model_json_has_facts_metrics_and_units(results):
    payload = json.loads(results["finances_monthly"].to_model_content())
    assert payload["facts_calculated_by_molarmetrics"] == results["finances_monthly"].facts
    collections = next(m for m in payload["metrics"] if m["metric"] == "collections")
    assert (collections["unit"], collections["aggregation"], collections["date_basis"]) == (
        "INR", "sum", "payment date")
    assert payload["columns"]["Billed revenue"] == "INR, sum"  # one unit legend per column
    assert payload["columns"]["Collections"] == "INR, sum"
    assert "Billed revenue" in payload["rows"][0]


def test_combined_share_of_listed_procedures_hand_checked(results):
    r = results["procedures_top3_billed"]
    assert r.summary_value("listed_procedures_billed_revenue") == 1_850_000  # 900000 + 700000 + 250000
    assert r.summary_value("combined_share") == 90.9  # 1,850,000 / 2,035,000
    assert any("90.9% of all billed revenue" in f and "which is more than half" in f for f in r.facts)


def test_no_trivial_combined_share_when_every_procedure_is_listed(mini_conn):
    r = A.procedures(mini_conn, ProcedureArgs(**W, top_n=20))  # all 10 catalogue procedures
    assert "combined_share" not in {s.key for s in r.summary}
    assert not any("listed procedures account for" in f for f in r.facts)
    assert any(f.startswith("Top 10 procedures by billed revenue") for f in r.facts)  # the list fact remains
    for check, ok, detail in run_all(" ".join(r.facts), "", [r]):
        assert ok, (check, detail)


def test_kpi_facts_name_their_units_and_measures(results):
    facts = " ".join(results["kpis"].facts)
    assert "9 appointments were scheduled: 5 completed visits, 2 cancelled appointments and 2 no-show" in facts
    assert "22.2% of scheduled appointments (2 no-show appointments ÷ 9 scheduled appointments)" in facts
    assert "4 unique patients" in facts and "2 of these patients were returning patients" in facts
    assert "(sum of treatment net fees, by treatment date): ₹20,350.00" in facts
    assert "(sum of payments received, by payment date): ₹13,350.00" in facts


def test_monthly_difference_fact_is_one_period_total(results):
    assert any("collections were ₹7,000.00 lower than billed revenue" in f and "not a per-month figure" in f
               for f in results["finances_monthly"].facts)


def test_comparison_fact_separates_records_from_patients_and_is_not_truncated(results):
    r = results["procedures_compare_count"]
    sentence = next(f for f in r.facts if "more treatment records than" in f)
    assert sentence.endswith("distinct patients were 1 and 1.")
    assert next(s for s in r.summary if s.key == "comparison").formatted == sentence  # no "…" truncation


def test_outstanding_facts_decompose_the_balance(results):
    facts = " ".join(results["finances_outstanding"].facts)
    assert ("the outstanding balance was ₹8,000.00: net fees of ₹22,850.00 for treatments on or before "
            "28 Feb 2025, minus ₹14,850.00 of payments received") in facts
    assert "4 treatment records had an unpaid balance" in facts


def test_model_json_size_budget_on_real_data(real_db_path):
    conn = connect_readonly(real_db_path)
    try:
        sizes = {name: len(r.to_model_content()) for name, r in
                 _variants(conn, {"start_date": "2024-01-01", "end_date": "2025-12-31"}).items()}
    finally:
        conn.close()
    assert max(sizes.values()) < 7000, sizes
