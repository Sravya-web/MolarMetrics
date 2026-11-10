"""Targeted regression checks for wording errors seen in live model answers.

Each check is a pure function ``(answer, question, artifacts) -> (ok, detail)``.
``artifacts`` are the structured ``AnalysisResult`` objects the tools returned,
so the checks compare the model's words with what was actually calculated
(units, aggregation types and metric names), never with other prose.

The four checks target errors observed or anticipated during live testing:

1. ``average_misuse``          a total described as an average ("on average")
2. ``unsupported_majority``    "majority" without a calculated share above 50%
3. ``unit_mismatch``           e.g. a difference in treatment records called "patients"
4. ``billed_collections_swap`` a billed amount presented as collections, or vice versa

They are deliberately narrow heuristics. They catch these specific errors;
they cannot judge every phrasing, so reading the answers still matters.
"""

from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal
from typing import Callable

from molarmetrics.analytics.results import AnalysisResult

Check = Callable[[str, str, list[AnalysisResult]], tuple[bool, str]]

_AVERAGE = re.compile(r"\b(on average|averages?|averaged|mean)\b", re.I)
_MAJORITY = re.compile(r"\b(majority|more than half|over half|most of the (?:billed |total )?(?:revenue|billing))\b",
                       re.I)

_NOUN_UNIT = {
    "patient": "patients", "patients": "patients",
    "appointment": "appointments", "appointments": "appointments", "visit": "appointments", "visits": "appointments",
    "no-show": "appointments", "no-shows": "appointments", "cancellation": "appointments",
    "cancellations": "appointments",
    "record": "treatment records", "records": "treatment records", "treatment": "treatment records",
    "treatments": "treatment records", "session": "treatment records", "sessions": "treatment records",
    "payment": "payments", "payments": "payments",
}
_MODIFIER = r"(?:more|fewer|unique|distinct|returning|new|completed|scheduled|cancelled|no-show|treatment|unpaid|additional)"
_NUM_NOUN = re.compile(
    r"(?<![\w.,₹])(\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?\s+(?:" + _MODIFIER + r"\s+){0,2}"
    r"(patients?|appointments?|visits?|no-shows?|cancellations?|records?|treatments?|sessions?|payments?)\b", re.I)

# Atomic group: the whole number is taken or nothing, so backtracking can never
# turn "₹3,90,460.00 less" into the false amount "3,90,460.0".
_AMOUNT = re.compile(r"₹\s?(?P<num>(?>\d[\d,]*(?:\.\d+)?))")
_KEYWORDS = (
    ("billed", r"billed|billing|revenue|charged|net fees?"),
    ("collected", r"collections?|collected|received|paid|payments?"),
    ("outstanding", r"outstanding|unpaid|balance|owed"),
)
_DIFF_NOUN = re.compile(r"\b(difference|gap|shortfall)\b", re.I)  # "the difference ... was ₹X"
_DIFF_COMPARATIVE = re.compile(r"\b(than|lower|higher|less|more|exceed\w*)\b", re.I)
_DIFF_AFTER = re.compile(r"^\s*(?:less|more|lower|higher|fewer)\b", re.I)  # "₹X less than"
_DIFF_BY = re.compile(r"\bby\s*$", re.I)  # "lower than billed revenue by ₹X"


def _money_family(metric_key: str) -> str | None:
    k = metric_key.lower()
    if "difference" in k:
        return "difference"
    if "outstanding" in k:
        return "outstanding"
    if "collect" in k or k == "paid_to_date":
        return "collected"
    if "billed" in k:
        return "billed"
    return None


def _money_values(artifacts: list[AnalysisResult]) -> dict[Decimal, set[str]]:
    """Every INR value in the structured results, mapped to its metric family."""
    out: dict[Decimal, set[str]] = defaultdict(set)

    def add(key: str, paise) -> None:
        family = _money_family(key)
        if family and paise is not None:
            out[Decimal(abs(int(paise))) / 100].add(family)

    for res in artifacts:
        for s in res.summary:
            if s.kind == "inr":
                add(s.key, s.value)
        for row in res.rows:
            for c in res.columns:
                if c.kind == "inr":
                    add(c.key, row.get(c.key))
    return out


def _count_values(artifacts: list[AnalysisResult]) -> dict[Decimal, set[str]]:
    """Every count in the structured results, mapped to its unit."""
    out: dict[Decimal, set[str]] = defaultdict(set)
    for res in artifacts:
        for s in res.summary:
            if s.kind == "count" and s.value is not None:
                out[Decimal(abs(int(s.value)))].add(s.unit)
        for row in res.rows:
            for c in res.columns:
                if c.kind == "count" and row.get(c.key) is not None:
                    out[Decimal(abs(int(row[c.key])))].add(c.unit)
    return out


def _shares(artifacts: list[AnalysisResult]) -> list[float]:
    values = [float(s.value) for res in artifacts for s in res.summary
              if s.aggregation == "share" and s.value is not None]
    values += [float(row[c.key]) for res in artifacts for row in res.rows for c in res.columns
               if c.aggregation == "share" and row.get(c.key) is not None]
    return values


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?;])\s+|\n+", text or "") if s.strip()]


_NEGATED = re.compile(r"\b(?:not|no|never|isn['’]t|aren['’]t|wasn['’]t|rather than|instead of)\b(?:\s+\w+){0,3}\s*$",
                      re.I)


def _affirmed(pattern: re.Pattern, text: str) -> re.Match | None:
    """First match that is not negated ("not an average", "not a majority")."""
    for m in pattern.finditer(text or ""):
        if not _NEGATED.search(text[max(0, m.start() - 30):m.start()]):
            return m
    return None


# --- the four checks ---------------------------------------------------------------------
def average_misuse(answer: str, question: str, artifacts: list[AnalysisResult]) -> tuple[bool, str]:
    """No tool calculates an average, so 'average' is only acceptable when the
    question itself asks about one (e.g. to say it is unavailable) or when
    it is negated ("a total, not an average")."""
    if _AVERAGE.search(question or ""):
        return True, ""
    m = _affirmed(_AVERAGE, answer)
    return (True, "") if m is None else (False, f"uses '{m.group(0)}', but no tool calculated an average")


def unsupported_majority(answer: str, question: str, artifacts: list[AnalysisResult]) -> tuple[bool, str]:
    m = _affirmed(_MAJORITY, answer)
    if m is None or any(v > 50 for v in _shares(artifacts)):
        return True, ""
    return False, f"says '{m.group(0)}', but no calculated share above 50% is in the tool results"


def unit_mismatch(answer: str, question: str, artifacts: list[AnalysisResult]) -> tuple[bool, str]:
    known = _count_values(artifacts)
    from_question = {t.replace(",", "") for t in re.findall(r"\d[\d,]*", question or "")}
    problems = []
    for m in _NUM_NOUN.finditer(answer or ""):
        token = m.group(1)
        if re.fullmatch(r"(?:19|20)\d\d", token):
            continue  # a year, not a count
        if token.replace(",", "") in from_question or re.search(r"\btop\s*$", answer[max(0, m.start() - 6):m.start()],
                                                                re.I):
            continue  # "top 5 procedures", or a number the user supplied
        units = known.get(Decimal(token.replace(",", "")))
        if not units:
            continue  # not a tool number at all: the number-grounding check covers that
        claimed = _NOUN_UNIT[m.group(2).lower()]
        if claimed not in units:
            problems.append(f"'{m.group(0)}', but {token} is a count of {' / '.join(sorted(units))}")
    return (not problems), "; ".join(problems)


def _claimed_family(before: str, after: str, clause: str | None = None) -> str | None:
    """Which measure does the sentence say this amount is? Rules, in order:
    1. a keyword right after the amount: "₹X of payments received"
    2. "... by ₹X" or "₹X less/more/lower/higher": a difference
    3. a difference noun earlier in the clause: "the difference ... was ₹X"
    4. the nearest keyword before the amount, unless a comparative ("than",
       "lower") sits between them, which again makes it a difference."""
    for family, pattern in _KEYWORDS:  # "₹X of payments received" / "₹X was collected"
        if re.match(r"^\s*(?:(?:of|in|from|as)\s+(?:the\s+)?(?:total\s+)?|(?:was|were|is|are|has been|had been)\s+)"
                    r"(?:" + pattern + r")\b", after, re.I):
            return family
    # Rule 3 looks at the WHOLE clause: a 70-character window can cut "difference" in half
    # ("The difference between billed and collected revenue for the whole period was ₹X").
    if _DIFF_BY.search(before) or _DIFF_AFTER.match(after) or _DIFF_NOUN.search(clause if clause is not None else before):
        return "difference"
    nearest = None
    for family, pattern in _KEYWORDS:
        for km in re.finditer(r"\b(?:" + pattern + r")\b", before, re.I):
            if nearest is None or km.end() > nearest[1]:
                nearest = (family, km.end())
    if nearest is None:
        return None  # e.g. a list item "Composite filling: ₹X" with no metric word
    return "difference" if _DIFF_COMPARATIVE.search(before[nearest[1]:]) else nearest[0]


def billed_collections_swap(answer: str, question: str, artifacts: list[AnalysisResult]) -> tuple[bool, str]:
    known = _money_values(artifacts)
    problems = []
    for sentence in _sentences(answer):
        if re.search(r"\brespectively\b", sentence, re.I):
            continue  # "A and B were ₹X and ₹Y respectively": ambiguous to a heuristic, so skipped
        previous_end = 0
        for m in _AMOUNT.finditer(sentence):
            # Only look back to the previous amount, so each amount gets its own clause.
            clause = sentence[previous_end:m.start()]
            before = clause[-70:]
            after = sentence[m.end():m.end() + 30]
            previous_end = m.end()
            families = known.get(Decimal(m.group("num").replace(",", "")))
            if not families:
                continue  # not a tool amount: the number-grounding check covers that
            if re.match(r"^\s*(?:,|and|&)\s*₹", after):
                continue  # paired amounts "₹X and ₹Y": which is which is ambiguous, so skipped
            claim = _claimed_family(before, after, clause)
            if claim is None:
                continue
            if claim not in families:
                problems.append(f"₹{m.group('num')} is presented as {claim}, but the tools calculated it as "
                                f"{' / '.join(sorted(families))}")
    return (not problems), "; ".join(problems)


CHECKS: dict[str, Check] = {
    "no_average_misuse": average_misuse,
    "majority_supported": unsupported_majority,
    "units_consistent": unit_mismatch,
    "billed_vs_collections_consistent": billed_collections_swap,
}


def run_all(answer: str, question: str, artifacts: list[AnalysisResult]) -> list[tuple[str, bool, str]]:
    return [(name, *check(answer, question, artifacts)) for name, check in CHECKS.items()]
