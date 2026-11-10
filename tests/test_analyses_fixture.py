"""The four analyses (tool back-ends) on the hand-checked fixture."""

from molarmetrics.analytics import analyses as A
from molarmetrics.analytics.params import AppointmentArgs, FinanceArgs, KpiArgs, ProcedureArgs
from molarmetrics.analytics.results import pct

W = {"start_date": "2025-01-01", "end_date": "2025-02-28"}


def test_pct_rounds_half_up_and_handles_zero_denominator():
    assert pct(2, 9) == 22.2
    assert pct(1, 16) == 6.3  # 6.25 rounds half-up (banker's rounding would give 6.2)
    assert pct(0, 5) == 0.0
    assert pct(3, 0) is None


def test_kpis(mini_conn):
    r = A.clinic_kpis(mini_conn, KpiArgs(**W))
    assert r.status == "ok"
    assert r.summary_value("scheduled_appointments") == 9
    assert r.summary_value("completed_visits") == 5
    assert r.summary_value("no_show_rate") == 22.2
    no_show = next(s for s in r.summary if s.key == "no_show_rate")
    assert no_show.note == "2 no-shows / 9 scheduled appointments"  # the denominator is explicit
    assert r.summary_value("unique_patients_seen") == 4
    assert r.summary_value("returning_patients") == 2
    assert r.summary_value("billed_revenue") == 2_035_000
    assert r.summary_value("collections") == 1_335_000
    assert {"billed_revenue", "collections", "no_show_rate"} <= set(r.definitions)


def test_kpis_empty_period(mini_conn):
    r = A.clinic_kpis(mini_conn, KpiArgs(start_date="2023-01-01", end_date="2023-06-30"))
    assert r.status == "empty"
    assert r.summary_value("no_show_rate") is None
    assert any("No data for this period" in w for w in r.warnings)


def test_no_show_rate_by_month(mini_conn):
    r = A.appointments(mini_conn, AppointmentArgs(**W, metric="no_show_rate"))
    assert [row["no_show_rate_pct"] for row in r.rows] == [25.0, 20.0]
    assert r.summary_value("highest_no_show") == "Jan 2025: 25.0%"
    assert r.summary_value("lowest_no_show") == "Feb 2025: 20.0%"
    assert r.chart.type == "line" and r.chart.y == ["no_show_rate_pct"]


def test_no_show_rate_undefined_month_is_flagged(mini_conn):
    r = A.appointments(mini_conn, AppointmentArgs(start_date="2025-01-01", end_date="2025-03-31",
                                                  metric="no_show_rate"))
    assert r.rows[-1]["month"] == "2025-03" and r.rows[-1]["no_show_rate_pct"] is None
    assert any("Mar 2025" in w for w in r.warnings)


def test_completed_visits_by_dentist(mini_conn):
    r = A.appointments(mini_conn, AppointmentArgs(**W, group_by="dentist", metric="completed_visits"))
    assert [row["dentist_id"] for row in r.rows] == ["D02", "D01"]  # sorted by completed visits
    assert r.summary_value("most_completed") == "Dr. Test B. (D02): 3"
    assert any("not a measure of clinical quality" in n for n in r.notes)


def test_top_procedures_by_billed_revenue(mini_conn):
    r = A.procedures(mini_conn, ProcedureArgs(**W, top_n=3))
    assert [row["procedure"] for row in r.rows] == ["Crown placement", "Root canal treatment (session)", "Extraction"]
    assert [row["share_of_billed_pct"] for row in r.rows] == [44.2, 34.4, 12.3]
    assert r.summary_value("total_billed_all_procedures") == 2_035_000
    assert any("top 3" in n for n in r.notes)


def test_compare_two_procedures_by_count(mini_conn):
    r = A.procedures(mini_conn, ProcedureArgs(**W, metric="count", procedures=["root canal", "extraction"]))
    assert [(row["procedure"], row["treatment_count"]) for row in r.rows] == [
        ("Root canal treatment (session)", 2), ("Extraction", 1)]
    assert r.summary_value("difference") == 1  # calculated by Python, not by the model


def test_monthly_billed_vs_collected(mini_conn):
    r = A.finances(mini_conn, FinanceArgs(**W))
    assert [(row["billed_paise"], row["collected_paise"]) for row in r.rows] == [(485_000, 385_000),
                                                                                 (1_550_000, 950_000)]
    assert r.summary_value("billed_revenue") == 2_035_000
    assert r.summary_value("collections") == 1_335_000
    assert r.summary_value("difference") == 700_000


def test_outstanding_balance_result(mini_conn):
    r = A.finances(mini_conn, FinanceArgs(metric="outstanding_balance", as_of_date="2025-02-28"))
    assert r.summary_value("outstanding_balance") == 800_000
    assert r.summary_value("treatments_with_balance") == 4
    assert r.arguments == {"metric": "outstanding_balance", "as_of_date": "2025-02-28"}
    assert sum(row["outstanding_paise"] for row in r.rows) == 800_000


def test_model_content_is_compact_and_formatted(mini_conn):
    r = A.finances(mini_conn, FinanceArgs(**W))
    content = r.to_model_content()
    assert "₹20,350.00" in content and "₹13,350.00" in content  # pre-formatted for quoting
    assert "SYNTHETIC DEMO DATA" in content
    assert len(content) < 7000  # the size budget is enforced on the real data in test_tool_metadata.py


def test_model_content_limits_rows():
    from molarmetrics.analytics.results import AnalysisResult, Column

    r = AnalysisResult(tool="t", title="t",
                       columns=[Column(key="n", label="N", kind="count", unit="appointments", aggregation="count")],
                       rows=[{"n": i} for i in range(100)])
    import json
    payload = json.loads(r.to_model_content(max_rows=24))
    assert len(payload["rows"]) == 24 and "24 of 100" in payload["rows_note"]
