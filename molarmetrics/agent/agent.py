"""The MolarMetrics agent: ChatOllama + LangChain ``create_agent`` + four tools.

Data flow for one question
--------------------------
user question
  -> model (llama3.2:3b via Ollama) reads the system prompt + tool descriptions
  -> model emits a structured tool call, e.g. analyze_finances(metric=..., ...)
  -> LangChain validates the arguments (Pydantic) and runs OUR Python/SQL
  -> tool returns (short JSON for the model, full AnalysisResult for the app)
  -> model writes a short answer quoting the tool's numbers
  -> app shows: answer + grounding check + tables/charts from the AnalysisResult

Safety limits: at most 4 model calls and 3 tool calls per question, a
recursion limit, a per-request timeout, and one retry for transient server
errors only. Users never see stack traces.

Privacy: questions can contain patient information, so they are NEVER
logged (not even truncated). Logs carry only error categories and exception
type names.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx
from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
    ToolErrorMiddleware,
)
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_ollama import ChatOllama
from langgraph.errors import GraphRecursionError

from molarmetrics.agent.grounding import GroundingReport, check_grounding
from molarmetrics.agent.prompts import build_system_prompt
from molarmetrics.agent.scope import build_scope_prompt, is_clinical_outcome_question
from molarmetrics.agent.tools import build_tools
from molarmetrics.analytics.results import AnalysisResult
from molarmetrics.config import Settings, get_settings
from molarmetrics.dataset import DatasetContext, resolve

log = logging.getLogger("molarmetrics.agent")

MAX_MODEL_CALLS = 4
MAX_TOOL_CALLS = 3
RECURSION_LIMIT = 12
MAX_HISTORY_MESSAGES = 4  # last 2 question/answer pairs from THIS session only


@dataclass
class ToolActivity:
    """One tool call, for the 'tool activity' panel."""

    call_id: str
    name: str
    model_args: dict  # exactly what the model sent
    status: str  # ok | empty | error
    content: str  # exactly what the model received back
    result: AnalysisResult | None = None  # validated args, rows, chart (for the app)


@dataclass
class AgentReply:
    question: str
    answer: str
    activities: list[ToolActivity] = field(default_factory=list)
    grounding: GroundingReport | None = None
    seconds: float = 0.0
    error: str | None = None
    # Machine-readable error category for callers that write their own wording:
    # "unavailable" (server/model not reachable), "timeout", "limit", "failed".
    error_kind: str | None = None
    notes: list[str] = field(default_factory=list)
    scope_limited: bool = False  # True when the rule-based scope check withheld tools

    @property
    def tool_names(self) -> list[str]:
        return [a.name for a in self.activities]


def _transient(exc: BaseException) -> bool:
    """Retry only errors that a second attempt might fix (server hiccups),
    never 'Ollama is not running' or timeouts (that would just double the wait)."""
    if isinstance(exc, (ConnectionError, httpx.ConnectError, httpx.TimeoutException)):
        return False
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and status >= 500


def error_kind(exc: BaseException) -> str:
    """A category for logs and callers; never includes request content."""
    text = str(exc).lower()
    if isinstance(exc, (ConnectionError, httpx.ConnectError)) or "failed to connect" in text:
        return "unavailable"
    if isinstance(exc, httpx.TimeoutException) or "timed out" in text:
        return "timeout"
    if "not found" in text and "model" in text:
        return "unavailable"
    if isinstance(exc, GraphRecursionError):
        return "limit"
    return "failed"


def _tool_error_message(exc: Exception, request) -> str:
    """Unexpected tool failures become a short message (no stack trace)."""
    name = request.tool_call.get("name", "tool")
    # Type name only: an exception message could echo request content.
    log.error("Tool %s failed unexpectedly (%s)", name, type(exc).__name__)
    return (f"ERROR: the {name} analysis failed unexpectedly ({type(exc).__name__}). "
            "No result is available; tell the user it could not be calculated.")


class MolarMetricsAgent:
    def __init__(self, settings: Settings | None = None, db_path=None, model=None,
                 ctx: DatasetContext | None = None):
        """``model`` can be injected for offline tests; by default it is ChatOllama.
        ``ctx`` binds the agent to one dataset (its prompt, tools and database);
        without it the agent uses the bundled sample, as before."""
        self.settings = settings or get_settings()
        self.ctx = resolve(ctx)
        self.scope_prompt = build_scope_prompt(self.ctx)
        self.model = model or ChatOllama(
            model=self.settings.ollama_model,
            base_url=self.settings.ollama_base_url,
            temperature=0,  # deterministic, sober tool selection
            seed=42,
            num_ctx=self.settings.ollama_num_ctx,  # room for prompt + tool schemas + results
            num_predict=400,  # bound answer length (and time)
            keep_alive="20m",  # keep the model loaded between demo questions
            client_kwargs={"timeout": self.settings.ollama_timeout_seconds},
        )
        self.tools = build_tools(db_path, ctx)
        self.graph = create_agent(
            model=self.model,
            tools=self.tools,
            system_prompt=build_system_prompt(self.ctx),
            middleware=[
                ModelCallLimitMiddleware(run_limit=MAX_MODEL_CALLS, exit_behavior="end"),
                ToolCallLimitMiddleware(run_limit=MAX_TOOL_CALLS, exit_behavior="end"),
                ModelRetryMiddleware(max_retries=1, retry_on=_transient, on_failure="error",
                                     initial_delay=1.0, jitter=False),
                ToolErrorMiddleware(on_error=_tool_error_message),
            ],
        )

    # ------------------------------------------------------------------------------
    def ask(self, question: str, history: list[tuple[str, str]] | None = None) -> AgentReply:
        """Answer one question. ``history`` is this session's earlier
        (role, text) pairs; only plain text is passed, never other users' data."""
        question = (question or "").strip()
        if not question:
            return AgentReply(question=question, answer="", error="Please type a question.")
        messages = []
        for role, text in (history or [])[-MAX_HISTORY_MESSAGES:]:
            messages.append(HumanMessage(text) if role == "user" else AIMessage(text))
        messages.append(HumanMessage(question))

        started = time.perf_counter()
        if is_clinical_outcome_question(question):
            return self._answer_out_of_scope(question, started)
        try:
            state = self.graph.invoke({"messages": messages}, config={"recursion_limit": RECURSION_LIMIT})
        except Exception as exc:  # converted to a friendly message below
            kind = error_kind(exc)
            log.error("Question failed (category=%s, error=%s)", kind, type(exc).__name__)
            return AgentReply(question=question, answer="", error=self._friendly_error(exc), error_kind=kind,
                              seconds=round(time.perf_counter() - started, 1))
        reply = self._parse(question, state["messages"][len(messages):])
        reply.seconds = round(time.perf_counter() - started, 1)
        return reply

    def _answer_out_of_scope(self, question: str, started: float) -> AgentReply:
        """Clinical outcome/quality questions: the model replies WITHOUT tools."""
        try:
            msg = self.model.invoke([SystemMessage(self.scope_prompt), HumanMessage(question)])
        except Exception as exc:
            kind = error_kind(exc)
            log.error("Scope reply failed (category=%s, error=%s)", kind, type(exc).__name__)
            return AgentReply(question=question, answer="", error=self._friendly_error(exc), error_kind=kind,
                              seconds=round(time.perf_counter() - started, 1))
        answer = (msg.content if isinstance(msg.content, str) else str(msg.content)).strip()
        return AgentReply(
            question=question, answer=answer, scope_limited=True,
            grounding=check_grounding(answer, [], question) if answer else None,
            seconds=round(time.perf_counter() - started, 1),
            notes=["Scope check: this looks like a clinical outcome or quality question, which this data cannot "
                   "answer. The analytics tools were not offered for this reply (rule-based check)."],
        )

    def _parse(self, question: str, new_messages: list) -> AgentReply:
        calls: dict[str, ToolActivity] = {}
        order: list[str] = []
        answer = ""
        for msg in new_messages:
            if isinstance(msg, AIMessage):
                for tc in msg.tool_calls:
                    calls[tc["id"]] = ToolActivity(call_id=tc["id"], name=tc["name"], model_args=dict(tc["args"]),
                                                   status="pending", content="")
                    order.append(tc["id"])
                if not msg.tool_calls and isinstance(msg.content, str) and msg.content.strip():
                    answer = msg.content.strip()
            elif isinstance(msg, ToolMessage):
                act = calls.get(msg.tool_call_id)
                if act is None:
                    continue
                act.content = msg.content if isinstance(msg.content, str) else str(msg.content)
                artifact = getattr(msg, "artifact", None)
                act.result = artifact if isinstance(artifact, AnalysisResult) else None
                if act.result is not None:
                    act.status = act.result.status
                else:  # argument validation failed before our code ran, or limit reached
                    act.status = "error"
        activities = [calls[i] for i in order]
        notes = []
        if not activities:
            notes.append("The model answered without calling a tool.")
        if any(a.status == "pending" for a in activities):
            notes.append("A tool call was not executed (step limit reached).")
        if not answer:
            notes.append("The model did not write a final answer within its step limit; the tool results "
                         "below were calculated directly from the data.")
        tool_contents = [a.content for a in activities if a.status in ("ok", "empty")]
        return AgentReply(question=question, answer=answer, activities=activities,
                          grounding=check_grounding(answer, tool_contents, question) if answer else None,
                          notes=notes)

    def _friendly_error(self, exc: Exception) -> str:
        url, model = self.settings.ollama_base_url, self.settings.ollama_model
        text = str(exc).lower()
        if isinstance(exc, (ConnectionError, httpx.ConnectError)) or "failed to connect" in text:
            return (f"Could not reach Ollama at {url}. Start it with `ollama serve` (or open the Ollama app), "
                    "then ask again. The dashboard and data explorer still work.")
        if isinstance(exc, httpx.TimeoutException) or "timed out" in text:
            return (f"The model did not respond within {self.settings.ollama_timeout_seconds:.0f} seconds. "
                    "Try again: the first question after a pause can be slow while the model loads.")
        if "not found" in text and "model" in text:
            return f"The model '{model}' is not available in Ollama. Run: ollama pull {model}"
        if isinstance(exc, GraphRecursionError):
            return "The assistant reached its step limit without finishing. Try a simpler or more specific question."
        return (f"Something went wrong while answering ({type(exc).__name__}). Try rephrasing the question; "
                "the dashboard still works.")
