"""Live end-to-end checks against the REAL local Ollama model.

For each question we record, separately and honestly:
  1. tool_called      - an appropriate tool was called
  2. arguments_ok     - the validated arguments match the question (period, metric)
  3. tool_numbers_ok  - the tool's numbers equal an INDEPENDENT pandas calculation
  4. answer_ok        - the model's prose states the key figure(s)
  5. grounded         - every number in the prose appears in the tool results

A question PASSES only when all applicable checks pass.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path

from molarmetrics.agent.agent import AgentReply, MolarMetricsAgent
from molarmetrics.agent.grounding import extract_numbers
from molarmetrics.money import paise_to_decimal
from tests.integration import independent as ind
from tests.integration import wording_checks

Y_START, Y_END = "2025-01-01", "2025-12-31"


@dataclass
class CheckResult:
    id: str
    question: str
    priority: bool
    checks: dict[str, bool] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)
    tool_calls: list[dict] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)  # deterministic, from the tools
    answer: str = ""  # model commentary
    error: str | None = None
    seconds: float = 0.0

    @property
    def passed(self) -> bool:
        return self.error is None and bool(self.checks) and all(self.checks.values())


def _numbers(text: str) -> set[Decimal]:
    return {v for _, v in extract_numbers(text)}


def _mentions_money(answer: str, paise: int) -> bool:
    return paise_to_decimal(paise) in _numbers(answer)


def _first(reply: AgentReply, names: tuple[str, ...]):
    for act in reply.activities:
        if act.name in names and act.result is not None and act.status in ("ok", "empty"):
            return act
    return None


def _is_year_2025(args: dict) -> bool:
    return args.get("start_date") == Y_START and args.get("end_date") == Y_END


# --- individual question checks -----------------------------------------------------------------
def q_billed_2025(reply, T, r: CheckResult):
    expected = ind.billed_paise(T, Y_START, Y_END)
    act = _first(reply, ("get_clinic_kpis", "analyze_finances", "analyze_procedures"))
    r.checks["tool_called"] = act is not None
    if act:
        res = act.result
        r.checks["arguments_ok"] = _is_year_2025(res.arguments)
        key = {"get_clinic_kpis": "billed_revenue", "analyze_finances": "billed_revenue",
               "analyze_procedures": "total_billed_all_procedures"}[act.name]
        r.checks["tool_numbers_ok"] = res.summary_value(key) == expected
    r.checks["answer_ok"] = _mentions_money(reply.answer, expected)
    r.details["expected"] = f"billed revenue 2025 = {paise_to_decimal(expected)} INR"


def q_monthly_2025(reply, T, r: CheckResult):
    expected = ind.monthly_billed_collected(T, 2025)
    act = _first(reply, ("analyze_finances",))
    r.checks["tool_called"] = act is not None
    if act:
        res = act.result
        r.checks["arguments_ok"] = res.arguments.get("metric") == "monthly_billed_vs_collected" and _is_year_2025(
            res.arguments)
        got = {row["month"]: (row["billed_paise"], row["collected_paise"]) for row in res.rows}
        r.checks["tool_numbers_ok"] = got == expected
    totals = (sum(b for b, _ in expected.values()), sum(c for _, c in expected.values()))
    monthly_values = {paise_to_decimal(v) for pair in expected.values() for v in pair}
    said = _numbers(reply.answer)
    r.checks["answer_ok"] = any(paise_to_decimal(t) in said for t in totals) or bool(said & monthly_values)
    r.details["expected"] = (f"12 months; totals billed {paise_to_decimal(totals[0])}, "
                             f"collected {paise_to_decimal(totals[1])} INR")


def q_top5_procedures(reply, T, r: CheckResult):
    expected = ind.top_procedures_by_billed(T, Y_START, Y_END, 5)
    act = _first(reply, ("analyze_procedures",))
    r.checks["tool_called"] = act is not None
    if act:
        res = act.result
        r.checks["arguments_ok"] = (res.arguments.get("metric") == "billed_revenue" and _is_year_2025(res.arguments)
                                    and res.arguments.get("top_n", 0) >= 5)
        got = [(row["procedure"], row["billed_paise"]) for row in res.rows[:5]]
        share = ind.top_procedures_combined_share(T, Y_START, Y_END, 5)
        r.checks["tool_numbers_ok"] = got == expected and res.summary_value("combined_share") == share
    answer = reply.answer.lower()
    r.checks["answer_ok"] = all(name.split(" (")[0].lower() in answer for name, _ in expected)
    r.details["expected"] = "; ".join(f"{n}: {paise_to_decimal(v)}" for n, v in expected)


def q_no_show_by_month(reply, T, r: CheckResult):
    expected = ind.no_show_by_month(T, 2025)
    overall = ind.no_show_rate(T, Y_START, Y_END)
    act = _first(reply, ("analyze_appointments",))
    r.checks["tool_called"] = act is not None
    if act:
        res = act.result
        r.checks["arguments_ok"] = res.arguments.get("group_by") == "month" and _is_year_2025(res.arguments)
        got = {row["month"]: row["no_show_rate_pct"] for row in res.rows}
        r.checks["tool_numbers_ok"] = got == expected and res.summary_value("no_show_rate") == overall
    said = _numbers(reply.answer)
    rates = {Decimal(str(v)) for v in expected.values() if v is not None} | {Decimal(str(overall))}
    r.checks["answer_ok"] = bool(said & rates)
    r.details["expected"] = f"overall {overall}%; " + ", ".join(f"{m[5:]}: {v}%" for m, v in expected.items())


def q_outstanding(reply, T, r: CheckResult):
    expected = ind.outstanding_paise(T, Y_END)
    act = _first(reply, ("analyze_finances",))
    r.checks["tool_called"] = act is not None
    if act:
        res = act.result
        r.checks["arguments_ok"] = (res.arguments.get("metric") == "outstanding_balance"
                                    and res.arguments.get("as_of_date") == Y_END)
        r.checks["tool_numbers_ok"] = res.summary_value("outstanding_balance") == expected
    r.checks["answer_ok"] = _mentions_money(reply.answer, expected)
    r.details["expected"] = f"outstanding as of {Y_END} = {paise_to_decimal(expected)} INR"


def q_top_dentist(reply, T, r: CheckResult):
    names, count = ind.top_dentists_by_completed(T, Y_START, Y_END)
    act = _first(reply, ("analyze_appointments",))
    r.checks["tool_called"] = act is not None
    if act:
        res = act.result
        r.checks["arguments_ok"] = res.arguments.get("group_by") == "dentist" and _is_year_2025(res.arguments)
        best = max(row["completed"] for row in res.rows)
        r.checks["tool_numbers_ok"] = best == count and sorted(
            row["dentist"].split(" (")[0] for row in res.rows if row["completed"] == best) == sorted(names)
    r.checks["answer_ok"] = all(n.lower() in reply.answer.lower() for n in names) and Decimal(count) in _numbers(
        reply.answer)
    r.details["expected"] = f"{' and '.join(names)} with {count} completed visits"


def q_returning(reply, T, r: CheckResult):
    expected = ind.returning_patients(T, Y_START, Y_END)
    act = _first(reply, ("get_clinic_kpis",))
    r.checks["tool_called"] = act is not None
    if act:
        r.checks["arguments_ok"] = _is_year_2025(act.result.arguments)
        r.checks["tool_numbers_ok"] = act.result.summary_value("returning_patients") == expected
    r.checks["answer_ok"] = Decimal(expected) in _numbers(reply.answer)
    r.details["expected"] = f"{expected} returning patients in 2025"


def q_rct_vs_extraction(reply, T, r: CheckResult):
    names = ["Root canal treatment (session)", "Extraction"]
    expected = ind.procedure_counts(T, names, Y_START, Y_END)
    act = _first(reply, ("analyze_procedures",))
    r.checks["tool_called"] = act is not None
    if act:
        res = act.result
        r.checks["arguments_ok"] = _is_year_2025(res.arguments) and set(res.arguments.get("procedures") or []) == set(
            names)
        got = {row["procedure"]: row["treatment_count"] for row in res.rows}
        r.checks["tool_numbers_ok"] = all(got.get(n) == c for n, c in expected.items())
    said = _numbers(reply.answer)
    r.checks["answer_ok"] = all(Decimal(c) in said for c in expected.values())
    # Semantic trap: a difference in RECORDS must not be described as patients.
    patients = ind.procedure_patients(T, names, Y_START, Y_END)
    patient_claims = [Decimal(m.group(1).replace(",", "")) for m in re.finditer(
        r"(\d[\d,]*)\s+(?:more\s+|fewer\s+|distinct\s+|unique\s+|different\s+)?patients", reply.answer, re.I)]
    r.checks["records_not_called_patients"] = all(v in {Decimal(p) for p in patients.values()}
                                                  for v in patient_claims)
    r.details["expected"] = (", ".join(f"{n}: {c} records" for n, c in expected.items()) + "; patients: "
                             + ", ".join(f"{n}: {c}" for n, c in patients.items()))


def q_collected_2025(reply, T, r: CheckResult):
    """Direct probe of the billed-vs-collections risk: the answer must give collections."""
    expected = ind.collected_paise(T, Y_START, Y_END)
    billed = ind.billed_paise(T, Y_START, Y_END)
    act = _first(reply, ("get_clinic_kpis", "analyze_finances"))
    r.checks["tool_called"] = act is not None
    if act:
        r.checks["arguments_ok"] = _is_year_2025(act.result.arguments)
        try:
            r.checks["tool_numbers_ok"] = act.result.summary_value("collections") == expected
        except KeyError:
            r.checks["tool_numbers_ok"] = False
    # The answer must state the collections figure. Mentioning billed revenue is fine
    # as long as it is labelled as billed revenue: presenting the billed amount AS
    # collections is caught by the billed_vs_collections_consistent check. (An earlier
    # version of this check wrongly failed a correct answer that mentioned both.)
    r.checks["answer_ok"] = _mentions_money(reply.answer, expected)
    r.details["expected"] = (f"collections 2025 = {paise_to_decimal(expected)} INR; billed revenue "
                             f"{paise_to_decimal(billed)} INR must not be presented as collections")


_LIMITATION_WORDS = ("not available", "no data", "doesn't", "does not", "cannot", "can't", "unable",
                     "not possible", "no information", "don't have", "isn't", "not include", "not contain")


def q_works_best(reply, T, r: CheckResult):
    answer = reply.answer.lower()
    r.checks["explains_limitation"] = any(w in answer for w in _LIMITATION_WORDS)
    r.checks["mentions_missing_outcome_data"] = "outcome" in answer
    r.checks["grounded"] = reply.grounding is None or not reply.grounding.unverified
    r.details["expected"] = "say clinical outcome data is unavailable; no rankings or invented numbers"


def q_satisfaction(reply, T, r: CheckResult):
    answer = reply.answer.lower()
    r.checks["explains_limitation"] = any(w in answer for w in _LIMITATION_WORDS)
    claims = [t for t, _ in extract_numbers(reply.answer)]
    # A score claim looks like "score of 4.2", "rating was 8" or "4.5 out of 5"; a year is not a score.
    r.checks["no_satisfaction_score_invented"] = not re.search(
        r"\b(score|rating)\s+(of|was|is|were)\s+\d|\d+(\.\d+)?\s*(out of|/)\s*(5|10|100)\b", answer)
    r.checks["grounded"] = reply.grounding is None or not reply.grounding.unverified
    r.details["expected"] = "say satisfaction data is not in the dataset; no invented score"
    if claims:
        r.details["numbers_in_answer"] = ", ".join(claims)


QUESTIONS = [
    ("Q1", "What was billed revenue in 2025?", True, q_billed_2025),
    ("Q2", "Compare monthly billed revenue and collections in 2025.", True, q_monthly_2025),
    ("Q3", "Which five procedures generated the most billed revenue in 2025?", True, q_top5_procedures),
    ("Q4", "What was the no-show rate by month in 2025?", True, q_no_show_by_month),
    ("Q5", "How much was outstanding as of 31 December 2025?", True, q_outstanding),
    ("E1", "Which dentist completed the most appointments in 2025?", False, q_top_dentist),
    ("E2", "How many returning patients were seen in 2025?", False, q_returning),
    ("E3", "Compare root canal and extraction procedure counts in 2025.", False, q_rct_vs_extraction),
    ("E4", "Which treatment works best?", False, q_works_best),
    ("E5", "What was the average patient satisfaction score in 2025?", False, q_satisfaction),
    ("E6", "How much money was collected in 2025?", False, q_collected_2025),
]


def run_checks(csv_dir: Path, only: list[str] | None = None, agent: MolarMetricsAgent | None = None
               ) -> list[CheckResult]:
    T = ind.load(csv_dir)
    agent = agent or MolarMetricsAgent()
    results = []
    for qid, question, priority, checker in QUESTIONS:
        if only and qid not in only:
            continue
        r = CheckResult(id=qid, question=question, priority=priority)
        started = time.perf_counter()
        reply = agent.ask(question)
        r.seconds = round(time.perf_counter() - started, 1)
        r.answer = reply.answer
        r.error = reply.error
        r.tool_calls = [{"name": a.name, "model_args": a.model_args, "status": a.status,
                         "validated_args": a.result.arguments if a.result else None} for a in reply.activities]
        artifacts = [a.result for a in reply.activities if a.result is not None and a.status in ("ok", "empty")]
        r.facts = [f for res in artifacts for f in res.facts]
        if reply.error is None:
            checker(reply, T, r)
            # Targeted wording regression checks, applied to every question.
            for name, ok, detail in wording_checks.run_all(reply.answer, question, artifacts):
                r.checks[name] = ok
                if detail:
                    r.details[name] = detail
            if "grounded" not in r.checks:
                r.checks["grounded"] = reply.grounding is not None and not reply.grounding.unverified
            if reply.grounding and reply.grounding.unverified:
                r.details["unverified_numbers"] = ", ".join(reply.grounding.unverified)
        results.append(r)
    return results


def to_dict(r: CheckResult) -> dict:
    d = asdict(r)
    d["passed"] = r.passed
    return d
