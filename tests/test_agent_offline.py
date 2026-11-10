"""Offline tests of the agent's wiring (no Ollama needed).

These check message parsing, limits and friendly errors. They are NOT proof
that the real model works: see tests/integration and
scripts/run_integration_checks.py for the live checks.
"""

import httpx
from langchain_core.messages import AIMessage, ToolMessage

from molarmetrics.agent.agent import MAX_MODEL_CALLS, MAX_TOOL_CALLS, MolarMetricsAgent
from molarmetrics.agent.tools import build_tools


def _agent(mini_db):
    return MolarMetricsAgent(db_path=mini_db)  # constructing does not contact Ollama


def test_parse_pairs_tool_calls_with_results_and_checks_grounding(mini_db):
    agent = _agent(mini_db)
    tool = build_tools(mini_db)[0]
    tool_msg = tool.invoke({"type": "tool_call", "name": tool.name, "id": "c1",
                            "args": {"start_date": "2025-01-01", "end_date": "2025-02-28"}})
    messages = [
        AIMessage(content="", tool_calls=[{"name": "get_clinic_kpis", "id": "c1", "type": "tool_call",
                                           "args": {"start_date": "2025-01-01", "end_date": "2025-02-28"}}]),
        tool_msg,
        AIMessage(content="Billed revenue was ₹20,350.00 from 2025-01-01 to 2025-02-28."),
    ]
    reply = agent._parse("What was billed revenue?", messages)
    assert reply.tool_names == ["get_clinic_kpis"]
    assert reply.activities[0].status == "ok"
    assert reply.activities[0].result.summary_value("billed_revenue") == 2_035_000
    assert reply.grounding.ok


def test_parse_flags_answers_without_tools(mini_db):
    reply = _agent(mini_db)._parse("q", [AIMessage(content="Revenue was ₹99,99,999.")])
    assert "without calling a tool" in reply.notes[0]
    assert not reply.grounding.ok


def test_parse_marks_failed_tool_calls_as_errors(mini_db):
    messages = [AIMessage(content="", tool_calls=[{"name": "analyze_procedures", "id": "x", "type": "tool_call",
                                                   "args": {"top_n": 500}}]),
                ToolMessage(content="Error: top_n must be <= 20", tool_call_id="x", status="error")]
    reply = _agent(mini_db)._parse("q", messages)
    assert reply.activities[0].status == "error"
    assert any("final answer" in n for n in reply.notes)


def test_friendly_errors_have_actionable_commands_and_no_traces(mini_db):
    agent = _agent(mini_db)
    msg = agent._friendly_error(httpx.ConnectError("connection refused"))
    assert "ollama serve" in msg
    assert "timed out" not in agent._friendly_error(ValueError("boom")).lower()
    assert "Traceback" not in agent._friendly_error(RuntimeError("x"))


def test_limits_are_bounded():
    assert MAX_MODEL_CALLS <= 5 and MAX_TOOL_CALLS <= 3


def test_empty_question_is_rejected_without_calling_the_model(mini_db):
    assert _agent(mini_db).ask("   ").error == "Please type a question."
