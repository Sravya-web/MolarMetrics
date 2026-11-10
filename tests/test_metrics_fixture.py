"""Metric calculations checked against HAND-CALCULATED values.

See tests/fixtures/mini_clinic.py for the rows and the arithmetic. The
expected numbers here are literals, not outputs of MolarMetrics code.
"""

from molarmetrics.analytics import metrics as M

W = ("2025-01-01", "2025-02-28")


# --- scheduled / completed / no-show denominators ----------------------------------
def test_status_counts_in_window(mini_conn):
    assert M.status_counts(mini_conn, *W) == {"scheduled": 9, "completed": 5, "cancelled": 2, "no_show": 2}


def test_status_counts_by_month_include_cancellations_in_denominator(mini_conn):
    jan, feb = M.status_counts_by_month(mini_conn, *W)
    assert jan == {"month": "2025-01", "scheduled": 4, "completed": 2, "cancelled": 1, "no_show": 1}
    assert feb == {"month": "2025-02", "scheduled": 5, "completed": 3, "cancelled": 1, "no_show": 1}


def test_months_are_chronological_and_zero_filled(mini_conn):
    rows = M.status_counts_by_month(mini_conn, "2024-11-01", "2025-03-31")
    assert [r["month"] for r in rows] == ["2024-11", "2024-12", "2025-01", "2025-02", "2025-03"]
    assert rows[0]["scheduled"] == 0 and rows[-1]["scheduled"] == 0  # empty months kept, not dropped


def test_status_counts_by_dentist(mini_conn):
    d01, d02 = M.status_counts_by_dentist(mini_conn, *W)
    assert (d01["dentist_id"], d01["scheduled"], d01["completed"], d01["cancelled"], d01["no_show"]) == ("D01", 4, 2, 1, 1)
    assert (d02["dentist_id"], d02["scheduled"], d02["completed"], d02["cancelled"], d02["no_show"]) == ("D02", 5, 3, 1, 1)


def test_dentists_with_no_appointments_are_kept(mini_conn):
    rows = M.status_counts_by_dentist(mini_conn, "2023-01-01", "2023-12-31")
    assert [r["scheduled"] for r in rows] == [0, 0]


# --- returning patients use history before the window ------------------------------
def test_patient_counts_full_window(mini_conn):
    assert M.patient_counts(mini_conn, *W) == {"unique_patients_seen": 4, "returning_patients": 2}


def test_returning_patient_uses_history_before_window(mini_conn):
    # January only: P1 returns because of a DECEMBER 2024 visit; P2's January visit is a first visit.
    assert M.patient_counts(mini_conn, "2025-01-01", "2025-01-31") == {"unique_patients_seen": 2,
                                                                        "returning_patients": 1}
    # February only: P2 returns because of a JANUARY visit (outside this window); P3, P4 are first visits.
    assert M.patient_counts(mini_conn, "2025-02-01", "2025-02-28") == {"unique_patients_seen": 3,
                                                                        "returning_patients": 1}


def test_cancelled_and_no_show_visits_do_not_make_a_patient_returning(mini_conn):
    # P3 (cancelled first) and P4 (no-show first) are NOT returning in February.
    assert M.patient_counts(mini_conn, "2025-02-10", "2025-02-28")["returning_patients"] == 0


# --- money: billed vs collected, appointment date vs payment date --------------------
def test_billed_revenue_window(mini_conn):
    assert M.billed_revenue(mini_conn, *W) == {"billed_paise": 2_035_000, "treatment_count": 7}


def test_billed_revenue_keeps_paise_exact(mini_conn):
    # T5 listed 350050 paise (Rs 3,500.50) less a 50 paise discount = exactly 350000.
    assert M.billed_revenue(mini_conn, "2025-01-15", "2025-01-15")["billed_paise"] == 350_000


def test_collections_window(mini_conn):
    assert M.collections(mini_conn, *W) == {"collected_paise": 1_335_000, "payment_count": 7}


def test_appointment_date_vs_payment_date_filtering(mini_conn):
    jan, feb = M.billed_vs_collected_by_month(mini_conn, *W)
    # January collections include PM3, a payment for a DECEMBER treatment (T2),
    # while January billed revenue excludes T2 entirely.
    assert jan == {"month": "2025-01", "billed_paise": 485_000, "collected_paise": 385_000}
    assert feb == {"month": "2025-02", "billed_paise": 1_550_000, "collected_paise": 950_000}


def test_no_double_counting_with_multiple_treatments_and_split_payments(mini_conn):
    # A6 has two treatments (T6, T7) and T7 has three payments. A naive
    # appointments-treatments-payments join would repeat T7's fee per payment.
    assert M.billed_revenue(mini_conn, "2025-02-03", "2025-02-03")["billed_paise"] == 1_250_000
    rows = M.procedure_breakdown(mini_conn, "2025-02-01", "2025-02-28")
    crown = next(r for r in rows if r["procedure"] == "Crown placement")
    assert crown == {"procedure": "Crown placement", "treatment_count": 1, "patients": 1, "billed_paise": 900_000}


def test_procedure_breakdown_counts_records_and_distinct_patients(mini_conn):
    rows = {r["procedure"]: r for r in M.procedure_breakdown(mini_conn, *W)}
    rct = rows["Root canal treatment (session)"]
    assert (rct["treatment_count"], rct["patients"], rct["billed_paise"]) == (2, 1, 700_000)  # 2 sessions, 1 patient
    assert rows["Consultation"]["treatment_count"] == 2 and rows["Consultation"]["billed_paise"] == 50_000
    assert rows["Composite filling"]["treatment_count"] == 0  # only in December, outside W
    assert sum(r["billed_paise"] for r in rows.values()) == 2_035_000


# --- outstanding balance at different as-of dates -------------------------------------
def test_outstanding_before_any_treatment_is_zero(mini_conn):
    o = M.outstanding_as_of(mini_conn, "2024-12-09")
    assert (o["outstanding_paise"], o["treatments_considered"]) == (0, 0)


def test_outstanding_on_treatment_day(mini_conn):
    assert M.outstanding_as_of(mini_conn, "2024-12-10")["outstanding_paise"] == 100_000


def test_outstanding_end_of_january(mini_conn):
    o = M.outstanding_as_of(mini_conn, "2025-01-31")
    assert (o["billed_to_date_paise"], o["paid_to_date_paise"], o["outstanding_paise"]) == (735_000, 535_000, 200_000)
    assert o["treatments_with_balance"] == 1


def test_outstanding_end_of_february_with_aging(mini_conn):
    o = M.outstanding_as_of(mini_conn, "2025-02-28")
    assert (o["billed_to_date_paise"], o["paid_to_date_paise"], o["outstanding_paise"]) == (2_285_000, 1_485_000, 800_000)
    assert o["treatments_with_balance"] == 4
    aging = {b["bucket"]: (b["treatments_with_balance"], b["outstanding_paise"]) for b in o["aging"]}
    assert aging == {"0-30 days": (3, 700_000), "31-90 days": (1, 100_000), "91-180 days": (0, 0),
                     "181+ days": (0, 0)}


def test_outstanding_excludes_payments_after_as_of_date(mini_conn):
    # PM9 (Rs 3,000, 2025-03-10) only counts from March onwards.
    assert M.outstanding_as_of(mini_conn, "2025-03-09")["outstanding_paise"] == 800_000
    o = M.outstanding_as_of(mini_conn, "2025-03-31")
    assert (o["outstanding_paise"], o["treatments_with_balance"]) == (500_000, 3)


# --- empty periods -------------------------------------------------------------------------
def test_empty_period_returns_zeros_not_errors(mini_conn):
    empty = ("2023-01-01", "2023-12-31")
    assert M.status_counts(mini_conn, *empty) == {"scheduled": 0, "completed": 0, "cancelled": 0, "no_show": 0}
    assert M.billed_revenue(mini_conn, *empty) == {"billed_paise": 0, "treatment_count": 0}
    assert M.collections(mini_conn, *empty) == {"collected_paise": 0, "payment_count": 0}
    assert M.patient_counts(mini_conn, *empty) == {"unique_patients_seen": 0, "returning_patients": 0}
