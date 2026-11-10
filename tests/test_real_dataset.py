"""The tools' answers to the priority questions, cross-checked on the REAL dataset
against independent pandas calculations (a different code path from the SQL).

This verifies the numbers MolarMetrics would show for each priority question
without involving the language model at all.
"""

import pytest

from molarmetrics.analytics import analyses as A
from molarmetrics.analytics.db import connect_readonly
from molarmetrics.analytics.params import AppointmentArgs, FinanceArgs, KpiArgs, ProcedureArgs
from tests.integration import independent as ind

Y = {"start_date": "2025-01-01", "end_date": "2025-12-31"}


@pytest.fixture(scope="module")
def T(real_db_path):
    return ind.load(real_db_path.parent / "csv")


@pytest.fixture()
def conn(real_db_path):
    c = connect_readonly(real_db_path)
    yield c
    c.close()


def test_q1_billed_revenue_2025(conn, T):
    assert A.clinic_kpis(conn, KpiArgs(**Y)).summary_value("billed_revenue") == ind.billed_paise(T, *Y.values())


def test_q2_monthly_billed_and_collected_2025(conn, T):
    rows = A.finances(conn, FinanceArgs(**Y)).rows
    assert {r["month"]: (r["billed_paise"], r["collected_paise"]) for r in rows} == ind.monthly_billed_collected(T, 2025)


def test_q3_top_five_procedures_by_billed_revenue_2025(conn, T):
    r = A.procedures(conn, ProcedureArgs(**Y, top_n=5))
    assert [(row["procedure"], row["billed_paise"]) for row in r.rows] == ind.top_procedures_by_billed(
        T, *Y.values(), 5)
    # The combined share (the value that makes a "majority" claim checkable) matches pandas.
    assert r.summary_value("combined_share") == ind.top_procedures_combined_share(T, *Y.values(), 5)


def test_q4_no_show_rate_by_month_2025(conn, T):
    rows = A.appointments(conn, AppointmentArgs(**Y, metric="no_show_rate")).rows
    assert {r["month"]: r["no_show_rate_pct"] for r in rows} == ind.no_show_by_month(T, 2025)


def test_q5_outstanding_as_of_end_2025(conn, T):
    r = A.finances(conn, FinanceArgs(metric="outstanding_balance", as_of_date="2025-12-31"))
    assert r.summary_value("outstanding_balance") == ind.outstanding_paise(T, "2025-12-31")


@pytest.mark.parametrize("as_of", ["2024-03-31", "2024-12-31", "2025-06-30"])
def test_outstanding_at_other_dates(conn, T, as_of):
    r = A.finances(conn, FinanceArgs(metric="outstanding_balance", as_of_date=as_of))
    assert r.summary_value("outstanding_balance") == ind.outstanding_paise(T, as_of)


def test_returning_patients_and_collections_2025(conn, T):
    r = A.clinic_kpis(conn, KpiArgs(**Y))
    assert r.summary_value("returning_patients") == ind.returning_patients(T, *Y.values())
    assert r.summary_value("collections") == ind.collected_paise(T, *Y.values())
    assert r.summary_value("no_show_rate") == ind.no_show_rate(T, *Y.values())


def test_top_dentist_by_completed_visits_2025(conn, T):
    r = A.appointments(conn, AppointmentArgs(**Y, group_by="dentist", metric="completed_visits"))
    names, count = ind.top_dentists_by_completed(T, *Y.values())
    assert r.rows[0]["completed"] == count and r.rows[0]["dentist"].startswith(names[0])
