"""Number grounding check and the rule-based clinical-scope check."""

from decimal import Decimal

import pytest

from molarmetrics.agent.grounding import check_grounding, extract_numbers
from molarmetrics.agent.scope import is_clinical_outcome_question

TOOL = '{"summary": {"Billed revenue": "₹68,09,100.00", "No-show rate": "7.6% (225 / 2,954)"}, "period": "2025-01-01 to 2025-12-31"}'


def test_extract_numbers_handles_indian_grouping_decimals_and_ids():
    values = [v for _, v in extract_numbers("₹68,09,100.00 and 7.6% for P0001 and D02 in 2025")]
    assert values == [Decimal("6809100.00"), Decimal("7.6"), Decimal("2025")]


def test_list_markers_are_not_treated_as_claims():
    assert [v for _, v in extract_numbers("1. Composite filling\n2. Crown placement")] == []


def test_grounded_answer_passes_even_with_different_digit_grouping():
    report = check_grounding("Billed revenue in 2025 was ₹6,809,100 and the no-show rate was 7.6%.", [TOOL])
    assert report.ok and report.unverified == []


def test_invented_or_self_calculated_numbers_are_flagged():
    report = check_grounding("Billed revenue was ₹68,09,100.00, about ₹5,67,425 per month.", [TOOL])
    assert not report.ok and report.unverified == ["5,67,425"]


def test_answer_without_tool_call_is_unverified():
    report = check_grounding("Revenue was ₹10,00,000.", [])
    assert not report.ok and "No tool was called" in report.message


def test_numbers_from_the_question_are_allowed():
    assert check_grounding("Here are the top 5 procedures.", [TOOL], "Which five procedures... top 5?").ok


@pytest.mark.parametrize("question", [
    "Which treatment works best?", "Who is the best dentist?", "What is the success rate of root canals?",
    "Should I get an implant or a bridge?", "Which procedure is most effective?", "Can you diagnose my pain?",
    "Which dentist is better?", "What are the clinical outcomes of implants?",
])
def test_clinical_outcome_questions_are_detected(question):
    assert is_clinical_outcome_question(question)


@pytest.mark.parametrize("question", [
    "What was billed revenue in 2025?", "Which dentist completed the most appointments in 2025?",
    "Which five procedures generated the most billed revenue in 2025?", "What was the no-show rate by month?",
    "Compare root canal and extraction procedure counts in 2025.", "What are the best months for appointments?",
    "How much was outstanding as of 31 December 2025?",
])
def test_operational_questions_are_not_blocked(question):
    assert not is_clinical_outcome_question(question)
