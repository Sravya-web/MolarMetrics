"""Regression tests for the wording checks.

Uses answers recorded from the REAL model during the 10 Nov 2026 live run
(frozen here, because each live run overwrites reports/) and the real
dataset's tool results. Bad answers must be flagged; good answers must not.
"""

import pytest

from molarmetrics.analytics import analyses as A
from molarmetrics.analytics.db import connect_readonly
from molarmetrics.analytics.params import AppointmentArgs, FinanceArgs, KpiArgs, ProcedureArgs
from tests.integration.wording_checks import (
    average_misuse,
    billed_collections_swap,
    run_all,
    unit_mismatch,
    unsupported_majority,
)

Y = {"start_date": "2025-01-01", "end_date": "2025-12-31"}


@pytest.fixture(scope="module")
def tools(real_db_path):
    conn = connect_readonly(real_db_path)
    try:
        return {
            "kpis": [A.clinic_kpis(conn, KpiArgs(**Y))],
            "monthly": [A.finances(conn, FinanceArgs(**Y))],
            "top5": [A.procedures(conn, ProcedureArgs(**Y, top_n=5))],
            "top2": [A.procedures(conn, ProcedureArgs(**Y, top_n=2))],
            "no_show": [A.appointments(conn, AppointmentArgs(**Y, metric="no_show_rate"))],
            "outstanding": [A.finances(conn, FinanceArgs(metric="outstanding_balance", as_of_date="2025-12-31"))],
            "dentists": [A.appointments(conn, AppointmentArgs(**Y, group_by="dentist", metric="completed_visits"))],
            "compare": [A.procedures(conn, ProcedureArgs(**Y, metric="count", procedures=["root canal", "extraction"]))],
        }
    finally:
        conn.close()


# Real model answers from the 10 Nov 2026 live run that are correct.
GOOD = [
    ("kpis", "What was billed revenue in 2025?",
     "The billed revenue in 2025 was ₹68,09,100.00. This measure shows the total amount of money charged for "
     "treatments performed during the year 2025, based on the appointment date."),
    ("monthly", "Compare monthly billed revenue and collections in 2025.",
     "The data shows the monthly billed revenue and collections for the clinic in 2025. The total billed revenue "
     "for the year was ₹68,09,100.00, while the total collections were ₹64,18,640.00."),
    ("monthly", "Compare monthly billed revenue and collections in 2025.",
     "This means that the clinic had a shortfall of ₹3,90,460.00, which is the difference between the billed "
     "revenue and the collections."),
    ("top5", "Which five procedures generated the most billed revenue in 2025?",
     "The top 5 procedures that generated the most billed revenue in 2025 are:\n\n1. Composite filling: "
     "₹12,17,770.00\n2. Crown placement: ₹11,56,800.00\n3. Implant placement: ₹9,02,600.00\n4. Root canal "
     "treatment (session): ₹8,36,990.00\n5. Scaling: ₹7,63,210.00\n\nThese procedures accounted for the majority "
     "of the billed revenue in 2025, with the composite filling generating the highest amount."),
    ("no_show", "What was the no-show rate by month in 2025?",
     "The no-show rate by month in 2025 was as follows: Jan 2025: 4.4%, Feb 2025: 3.9%. These rates are based on "
     "the number of no-show appointments divided by the total number of scheduled appointments for each month."),
    ("outstanding", "How much was outstanding as of 31 December 2025?",
     "The outstanding balance as of 31 December 2025 was ₹9,05,720.00."),
    ("dentists", "Which dentist completed the most appointments in 2025?",
     "The dentist who completed the most appointments in 2025 was Dr. Arjun B. (D02) with 471 completed visits."),
    ("kpis", "How many returning patients were seen in 2025?", "The clinic saw 606 returning patients in 2025."),
    ("compare", "Compare root canal and extraction procedure counts in 2025.",
     "The data shows that in 2025, there were 286 treatment records for Root canal treatment (session) and 163 "
     "treatment records for Extraction. This means that Root canal treatment had 123 more treatment records than "
     "Extraction. These are records, not patients. The billed revenue for Root canal treatment was ₹8,36,990.00 "
     "and for Extraction was ₹3,87,290.00."),
    # 11 Nov 2026 live run: a correct monthly answer that the 70-character window once misread.
    ("monthly", "Compare monthly billed revenue and collections in 2025.",
     "The monthly billed revenue and collections in 2025 are as follows:\n\n- The highest monthly billed revenue "
     "was ₹7,24,260.00 in December 2025.\n- The lowest monthly billed revenue was ₹4,12,810.00 in February "
     "2025.\n- The highest monthly collections were ₹6,72,820.00 in December 2025.\n- The lowest monthly "
     "collections were ₹4,03,360.00 in August 2025.\n\nThe difference between billed and collected revenue for "
     "the whole period was ₹3,90,460.00, with collections being ₹3,90,460.00 lower than billed revenue."),
    ("kpis", "What was the average patient satisfaction score in 2025?",
     "The average patient satisfaction score in 2025 is not available, as the data does not contain clinical "
     "outcome information."),
]


@pytest.mark.parametrize("tool, question, answer", GOOD)
def test_correct_real_answers_are_not_flagged(tools, tool, question, answer):
    for check, ok, detail in run_all(answer, question, tools[tool]):
        assert ok, (check, detail)


# --- the documented errors (and the anticipated swap) must be flagged ---------------
def test_total_described_as_average_is_flagged(tools):
    ok, detail = average_misuse("This means that the clinic collected ₹3,90,460.00 less than what was billed, "
                                "on average.", "Compare monthly billed revenue and collections in 2025.",
                                tools["monthly"])
    assert not ok and "on average" in detail


def test_majority_without_a_share_above_half_is_flagged(tools):
    answer = "These procedures accounted for the majority of the billed revenue in 2025."
    ok, _ = unsupported_majority(answer, "", tools["top2"])  # top 2 together = 34.9%, rows at most 17.9%
    assert not ok
    ok, _ = unsupported_majority(answer, "", tools["top5"])  # top 5 together = 71.6%, calculated by the tool
    assert ok


def test_records_described_as_patients_is_flagged(tools):
    ok, detail = unit_mismatch("This means that 123 more patients had root canal treatment than extraction.", "",
                               tools["compare"])
    assert not ok and "123 is a count of treatment records" in detail


def test_patients_described_as_appointments_is_flagged(tools):
    ok, _ = unit_mismatch("The clinic saw 606 returning appointments in 2025.", "", tools["kpis"])
    assert not ok


def test_billed_and_collections_swap_is_flagged(tools):
    ok, detail = billed_collections_swap(
        "The total collections were ₹68,09,100.00, while billed revenue was ₹64,18,640.00.", "", tools["monthly"])
    assert not ok and "presented as collected" in detail and "presented as billed" in detail


# --- phrasings the checks must NOT misread ---------------------------------------------
@pytest.mark.parametrize("answer", [
    "Collections were lower than billed revenue by ₹3,90,460.00.",
    "The difference between billed revenue and collections was ₹3,90,460.00.",
    "Collections were ₹3,90,460.00 lower than billed revenue over the whole period.",
    "Billed revenue (₹68,09,100.00) was higher than collections (₹64,18,640.00).",
    "Billed revenue and collections were ₹68,09,100.00 and ₹64,18,640.00 respectively.",
    "₹68,09,100.00 was billed and ₹64,18,640.00 was collected.",
])
def test_correct_money_phrasings_are_not_flagged(tools, answer):
    ok, detail = billed_collections_swap(answer, "", tools["monthly"])
    assert ok, detail


def test_negated_average_and_majority_are_not_flagged(tools):
    assert average_misuse("This is one total for the period, not an average.", "", tools["monthly"])[0]
    assert unsupported_majority("These do not make up the majority of revenue.", "", tools["top2"])[0]


def test_outstanding_decomposition_is_read_correctly(tools):
    answer = ("As of 31 Dec 2025 the outstanding balance was ₹9,05,720.00: net fees of ₹1,37,99,880.00 minus "
              "₹1,28,94,160.00 of payments received.")
    ok, detail = billed_collections_swap(answer, "", tools["outstanding"])
    assert ok, detail
