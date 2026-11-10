"""Rule-based scope check for clinical outcome / quality questions.

Why this exists
---------------
MolarMetrics has no clinical outcome, diagnosis or quality data. In testing,
llama3.2:3b sometimes answered "Which treatment works best?" by ranking
procedures by revenue, which is misleading in a healthcare setting.

So, for a small set of clearly out-of-scope phrasings, the app does not offer
the analytics tools for that turn. The MODEL still writes the reply (it is not
a canned answer), but it cannot present revenue as "best". The UI labels these
replies so the behaviour is transparent. Patterns are deliberately narrow to
avoid blocking legitimate operational questions.
"""

from __future__ import annotations

import re

from molarmetrics.dataset import PAYMENTS, TREATMENTS, DatasetContext, resolve

_PATTERNS = [
    r"\bworks?\s+(the\s+)?best\b",
    r"\bmost\s+effective\b",
    r"\b(effectiveness|efficacy)\b",
    r"\bsuccess\s+rates?\b",
    r"\b(clinical|treatment|patient)\s+outcomes?\b",
    r"\b(best|better|worst|good|bad)\s+(dentist|doctor|treatment|procedure)s?\b",
    r"\b(dentist|doctor|treatment|procedure)s?\s+(is|are|was|were)\s+(the\s+)?(best|better|worst)\b",
    r"\bdiagnos(e|is|es|ing)\b",
    r"\bshould\s+(i|we|my|the\s+patient)\b.*\b(get|have|choose|undergo|do)\b",
    r"\brecommend\w*\s+(a\s+|the\s+)?(treatment|procedure)\b",
    r"\bquality\s+of\s+(care|treatment|work)\b",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in _PATTERNS]

SCOPE_REFUSAL = "MolarMetrics cannot answer that, because its data has no clinical outcome information."


def build_scope_prompt(ctx: DatasetContext | None = None) -> str:
    """Prompt for the tool-free reply to a clinical-outcome question. Example
    questions use the dataset's own record types and latest year."""
    ctx = resolve(ctx)
    if ctx.is_sample:
        return (
            "You are MolarMetrics, an analytics assistant for a FICTIONAL dental clinic with SYNTHETIC DEMO DATA.\n"
            "The data contains only appointments, treatment billing records and payments. It has NO clinical "
            "outcome, diagnosis, success-rate or quality data.\n"
            "The user's question asks about clinical effectiveness, quality, diagnosis or treatment advice.\n"
            f'Begin your reply with exactly this sentence: "{SCOPE_REFUSAL}"\n'
            "Then, in one or two more sentences, without giving any numbers or ranking treatments or dentists, "
            "suggest one or two operational questions it can answer, such as \"Which procedures generated the "
            "most billed revenue in 2025?\" or \"What was the no-show rate by month in 2025?\".")
    year = ctx.example_year()
    examples = [f"What was the no-show rate by month in {year}?"]
    if ctx.has(TREATMENTS):
        examples.insert(0, f"Which procedures generated the most billed revenue in {year}?")
    contents = "appointments" + (", treatment billing records" if ctx.has(TREATMENTS) else "") + \
        (" and payments" if ctx.has(PAYMENTS) else "")
    return (
        "You are MolarMetrics, an analytics assistant for a dental clinic.\n"
        f"The data contains only {contents}. It has NO clinical outcome, diagnosis, success-rate or quality data.\n"
        "The user's question asks about clinical effectiveness, quality, diagnosis or treatment advice.\n"
        f'Begin your reply with exactly this sentence: "{SCOPE_REFUSAL}"\n'
        "Then, in one or two more sentences, without giving any numbers or ranking treatments or dentists, "
        "suggest one or two operational questions it can answer, such as "
        + " or ".join(f'"{q}"' for q in examples) + ". Never mention tools, models or how you work.")


SCOPE_SYSTEM_PROMPT = build_scope_prompt()


def is_clinical_outcome_question(question: str) -> bool:
    return any(p.search(question or "") for p in _COMPILED)
