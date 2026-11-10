"""Answering questions in the web app, using the existing agent.

What this layer adds on top of ``MolarMetricsAgent``:

* One agent per dataset, bound to that dataset's own database and context
  (coverage, capabilities, procedure names). It is never given the default
  sample path, so an uploaded dataset can never fall back to sample data.
* Conversation memory per (session, dataset), cleared on switching datasets.
* One question at a time per session (a second one gets "busy").
* A safe answer: the generated text is shown only when every number in it is
  found in the calculated results and it contains no internal or technical
  terms; otherwise the answer is built from the Python-written facts.
* Monthly questions always get a month-by-month result and a monthly answer.
* Privacy: question text is never logged. Logs carry a request ID, timing and
  an outcome category only.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from datetime import date
from pathlib import Path

from molarmetrics.agent.agent import AgentReply, MolarMetricsAgent
from molarmetrics.agent.grounding import check_grounding
from molarmetrics.agent.ollama_status import check_ollama
from molarmetrics.agent.scope import SCOPE_REFUSAL
from molarmetrics.agent.tools import TOOL_SPECS, run_analysis
from molarmetrics.analytics.params import arg_models_for
from molarmetrics.analytics.results import AnalysisResult
from molarmetrics.api.presenters import prohibited_terms, to_payload
from molarmetrics.api.schemas import AskResponse, DatasetRef
from molarmetrics.dataset import DENTIST_BREAKDOWN, PAYMENTS, TREATMENTS, DatasetContext

log = logging.getLogger("molarmetrics.ask")

MAX_QUESTION_CHARS = 500
MAX_CONVERSATION_MESSAGES = 4
MAX_CACHED_AGENTS = 8
NO_MATCH = ("I couldn't match that question to your clinic's records. Try asking about appointments, no-shows, "
            "billed revenue, collections or procedures, or pick a suggested question.")
UNAVAILABLE_MESSAGE = "Questions are temporarily unavailable. You can still explore your overview."

_MONTHLY = re.compile(r"\b(monthly|month[- ]by[- ]month|by month|per month|each month|every month|month[- ]?wise|"
                      r"months?\s+of\b|trend|trends)\b", re.I)
_MONTH_NAME = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", re.I)
_MONEY = re.compile(r"\b(revenue|billed|billing|bills?|collect\w*|payments?|paid|income|earn\w*|fees?|money|sales|"
                    r"turnover|outstanding|owed|dues?)\b", re.I)
_NO_SHOW = re.compile(r"\bno[- ]?shows?\b|\bmissed\b|\bdid not attend\b", re.I)
_SPECS = {name: (model, fn) for name, model, fn, _ in TOOL_SPECS}
_LONG_MONTHS = ("January February March April May June July August September October November "
                "December").split()

# Question words -> words that mark a relevant fact (for the fallback answer).
_FACT_HINTS = [
    (re.compile(r"\b(revenue|billed|billing|charged|fees?)\b", re.I), ("billed revenue",)),
    (re.compile(r"\b(collect\w*|received|paid|payments?)\b", re.I), ("collections", "payments received")),
    (re.compile(r"\b(outstanding|owed|unpaid|dues?|balance)\b", re.I), ("outstanding", "unpaid")),
    (_NO_SHOW, ("no-show",)),
    (re.compile(r"\b(cancel\w*)\b", re.I), ("cancelled",)),
    (re.compile(r"\b(completed|visits?|appointments?)\b", re.I), ("completed visits", "appointments")),
    (re.compile(r"\b(patients?|returning|new)\b", re.I), ("patients",)),
    (re.compile(r"\b(procedures?|treatments?|top)\b", re.I), ("procedures", "treatment records")),
    (re.compile(r"\b(dentists?|doctors?)\b", re.I), ("by dentist",)),
]


class QuestionsUnavailable(Exception):
    pass


class Busy(Exception):
    pass


class AskFailed(Exception):
    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


class InvalidQuestion(ValueError):
    pass


def long_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {_LONG_MONTHS[d.month - 1]} {d.year}"


def best_year(ctx: DatasetContext) -> int:
    """The latest calendar year that has (nearly) as much data as the best-covered
    year, e.g. 2025 for data from Jan 2024 to Dec 2025 (a leap year must not win
    by one day), but 2024 for data from Jul 2024 to Feb 2025."""
    s, e = date.fromisoformat(ctx.coverage_start), date.fromisoformat(ctx.coverage_end)

    def days(y: int) -> int:
        return (min(e, date(y, 12, 31)) - max(s, date(y, 1, 1))).days + 1

    most = max(days(y) for y in ctx.years())
    return max(y for y in ctx.years() if days(y) >= 0.9 * most)


def suggested_questions(ctx: DatasetContext) -> list[str]:
    """Questions this dataset can answer, phrased for its actual coverage."""
    y = best_year(ctx)
    out: list[str] = []
    if not ctx.has(TREATMENTS):
        out.append(f"How many completed visits were there in {y}?")
    if ctx.has(TREATMENTS):
        out.append(f"What was billed revenue in {y}?")
    if ctx.has(TREATMENTS) and ctx.has(PAYMENTS):
        out.append(f"Compare monthly billed revenue and collections in {y}.")
    if ctx.has(TREATMENTS):
        out.append(f"Which procedures generated the most billed revenue in {y}?")
    out.append(f"What was the no-show rate by month in {y}?")
    if ctx.has("outstanding"):
        out.append(f"How much was outstanding as of {long_date(ctx.coverage_end)}?")
    if ctx.has(DENTIST_BREAKDOWN):
        out.append(f"Which dentist completed the most appointments in {y}?")
    return out[:5]


def clean_question(text: str) -> str:
    question = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", text or "").split())
    if not question:
        raise InvalidQuestion("Please type a question.")
    if len(question) > MAX_QUESTION_CHARS:
        raise InvalidQuestion(f"Questions can be up to {MAX_QUESTION_CHARS} characters.")
    return question


def _is_monthly(result: AnalysisResult) -> bool:
    return any(c.key == "month" for c in result.columns)


def _has_numbers(text: str) -> bool:
    return bool(re.search(r"\d", re.sub(r"\b(19|20)\d\d\b", "", text or "")))


class AskService:
    def __init__(self, model_factory: Callable[[], object] | None = None, status_ttl: float = 15.0):
        """``model_factory`` replaces the local model (offline tests only)."""
        self.model_factory = model_factory
        self.status_ttl = status_ttl
        self._agents: OrderedDict[str, MolarMetricsAgent] = OrderedDict()
        self._conversations: dict[tuple[str, str], list[tuple[str, str]]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._mutex = threading.Lock()
        self._status: tuple[float, bool] = (0.0, False)

    # --- availability -----------------------------------------------------------------
    def questions_available(self, refresh: bool = False) -> bool:
        if self.model_factory is not None:
            return True
        checked_at, ready = self._status
        if refresh or time.monotonic() - checked_at > self.status_ttl:
            ready = check_ollama(timeout=2.0).ready
            self._status = (time.monotonic(), ready)
        return ready

    # --- cache and conversation lifecycle ----------------------------------------------
    def forget_dataset(self, dataset_id: str) -> None:
        with self._mutex:
            self._agents.pop(dataset_id, None)
            for key in [k for k in self._conversations if k[1] == dataset_id]:
                del self._conversations[key]

    def clear_session(self, session_id: str) -> None:
        with self._mutex:
            for key in [k for k in self._conversations if k[0] == session_id]:
                del self._conversations[key]

    def _agent(self, dataset_id: str, db_path: Path, ctx: DatasetContext) -> MolarMetricsAgent:
        with self._mutex:
            agent = self._agents.get(dataset_id)
            if agent is None:
                model = self.model_factory() if self.model_factory else None
                agent = MolarMetricsAgent(db_path=db_path, ctx=ctx, model=model)
                self._agents[dataset_id] = agent
                while len(self._agents) > MAX_CACHED_AGENTS:
                    self._agents.popitem(last=False)
            self._agents.move_to_end(dataset_id)
            return agent

    # --- asking ----------------------------------------------------------------------------
    def ask(self, session_id: str, dataset: DatasetRef, db_path: Path, ctx: DatasetContext, question: str,
            request_id: str = "-") -> AskResponse:
        question = clean_question(question)
        with self._mutex:
            lock = self._locks.setdefault(session_id, threading.Lock())
        if not lock.acquire(blocking=False):
            raise Busy()
        started = time.perf_counter()
        outcome = "failed"
        try:
            if not self.questions_available():
                outcome = "unavailable"
                raise QuestionsUnavailable()
            key = (session_id, dataset.id)
            history = list(self._conversations.get(key, []))
            reply = self._agent(dataset.id, db_path, ctx).ask(question, history)
            if reply.error:
                outcome = reply.error_kind or "failed"
                if reply.error_kind == "unavailable":
                    self._status = (0.0, False)  # re-check on the next request
                    raise QuestionsUnavailable()
                raise AskFailed(outcome)
            response = compose(reply, dataset, db_path, ctx, question)
            with self._mutex:
                self._conversations[key] = (history + [("user", question), ("assistant", response.answer)])[
                    -MAX_CONVERSATION_MESSAGES:]
            outcome = response.status
            return response
        finally:
            lock.release()
            log.info("question request=%s outcome=%s seconds=%.1f", request_id, outcome,
                     time.perf_counter() - started)


# --- composing the answer -------------------------------------------------------------------
def compose(reply: AgentReply, dataset: DatasetRef, db_path: Path, ctx: DatasetContext,
            question: str) -> AskResponse:
    if reply.scope_limited:
        return AskResponse(id=uuid.uuid4().hex[:12], dataset=dataset, question=question, status="out_of_scope",
                           answer=_scope_answer(reply.answer, ctx), results=[])
    results: list[AnalysisResult] = []
    seen: set[str] = set()
    for act in reply.activities:
        r = act.result
        if r is None or r.status == "error":
            continue
        key = r.tool + json.dumps(r.arguments, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            results.append(r)
    monthly = bool(_MONTHLY.search(question))
    if monthly:
        results = _ensure_monthly(results, question, db_path, ctx)
    usable = [r for r in results if r.status in ("ok", "empty")]
    unavailable = [r for r in results if r.status == "unavailable"]
    text = (reply.answer or "").strip()
    if not results:
        status = "no_match"
        answer = text if text and not _has_numbers(text) and not prohibited_terms(text) else NO_MATCH
    elif not usable:
        status = "not_available"
        answer = " ".join(dict.fromkeys(r.facts[0] for r in unavailable if r.facts))
    else:
        status = "answered"
        grounding = check_grounding(text, [r.to_model_content() for r in results], question) if text else None
        trustworthy = (bool(text) and grounding is not None and grounding.ok and not prohibited_terms(text)
                       and (not monthly or bool(_MONTH_NAME.search(text))))
        answer = text if trustworthy else facts_answer(usable, question, monthly)
    return AskResponse(id=uuid.uuid4().hex[:12], dataset=dataset, question=question, status=status, answer=answer,
                       results=[to_payload(r, dataset) for r in results])


def _ensure_monthly(results: list[AnalysisResult], question: str, db_path: Path,
                    ctx: DatasetContext) -> list[AnalysisResult]:
    """A monthly question must come with a month-by-month result. If the
    chosen analysis gave only totals, run the monthly one for the same period."""
    if any(_is_monthly(r) and r.status in ("ok", "empty") for r in results):
        return sorted(results, key=lambda r: not _is_monthly(r))
    period = next((r.date_range for r in results if "start" in r.date_range), None)
    args = {"start_date": period["start"], "end_date": period["end"]} if period else {}
    models = arg_models_for(ctx)
    if _MONEY.search(question) and not _NO_SHOW.search(question):
        name = "analyze_finances"
        args["metric"] = "monthly_billed_vs_collected"
    else:
        name = "analyze_appointments"
        args.update(group_by="month", metric="no_show_rate" if _NO_SHOW.search(question) else "status_counts")
    extra = run_analysis(name, models[name], _SPECS[name][1], args, db_path, ctx)
    return ([extra] if extra.status != "error" else []) + results


def facts_answer(results: list[AnalysisResult], question: str, monthly: bool) -> str:
    """An answer made only of Python-written facts relevant to the question."""
    primary = next((r for r in results if _is_monthly(r)), results[0]) if monthly else results[0]
    facts = primary.facts
    if not facts:
        return "Here are the results calculated from your clinic's records."
    hints = [h for pattern, words in _FACT_HINTS if pattern.search(question) for h in words]

    def score(fact: str) -> int:
        lower = fact.lower()
        value = sum(1 for h in hints if h in lower)
        if monthly and ("monthly" in lower or "by month" in lower):
            value += 2
        return value

    ranked = sorted(range(len(facts)), key=lambda i: (-score(facts[i]), i))
    chosen = [i for i in ranked[:3] if score(facts[i]) > 0] or ranked[:2]
    return " ".join(facts[i] for i in sorted(chosen))


def _scope_answer(text: str, ctx: DatasetContext) -> str:
    text = (text or "").strip()
    if text.startswith(SCOPE_REFUSAL) and not prohibited_terms(text) and not _has_numbers(text):
        return text
    example = suggested_questions(ctx)[0]
    return (f"{SCOPE_REFUSAL} It can describe how the clinic runs instead, for example: “{example}”")
