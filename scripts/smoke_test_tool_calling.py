"""Stage 1 smoke test: prove REAL tool calling with Ollama + LangChain.

What it does
------------
1. Builds a tiny temporary SQLite appointments fixture (12 rows, 7 completed).
2. Defines one typed tool that counts appointments by status.
3. Connects ChatOllama to a LangChain agent (``create_agent``).
4. Asks: "How many completed appointments are there?"
5. Checks that the model actually CALLED the tool (not just guessed).
6. Checks the tool's count and the model's answer against the known answer.

Run from the project root:

    python scripts/smoke_test_tool_calling.py

Exit code 0 = PASS, 1 = FAIL, 2 = BLOCKED (Ollama not reachable).
A JSON record is written to reports/stage1_smoke_test.json.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from molarmetrics.config import get_settings  # noqa: E402  (also disables remote tracing)

import httpx  # noqa: E402
from langchain.agents import create_agent  # noqa: E402
from langchain.agents.middleware import (  # noqa: E402
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langchain_ollama import ChatOllama  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

# --- 1. Tiny fixture with a known answer -------------------------------------
FIXTURE_ROWS = [
    ("FX01", "completed"), ("FX02", "cancelled"), ("FX03", "completed"),
    ("FX04", "no_show"), ("FX05", "completed"), ("FX06", "completed"),
    ("FX07", "cancelled"), ("FX08", "completed"), ("FX09", "no_show"),
    ("FX10", "completed"), ("FX11", "cancelled"), ("FX12", "completed"),
]
EXPECTED_COMPLETED = sum(1 for _, status in FIXTURE_ROWS if status == "completed")  # 7
QUESTION = "How many completed appointments are there?"


def build_fixture(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE appointments (appointment_id TEXT PRIMARY KEY, "
            "status TEXT NOT NULL CHECK (status IN ('completed','cancelled','no_show')))"
        )
        conn.executemany("INSERT INTO appointments VALUES (?, ?)", FIXTURE_ROWS)


# --- 2. A typed tool ------------------------------------------------------------
class CountArgs(BaseModel):
    """Arguments the model may send. Literal = only these exact values allowed."""

    status: Literal["completed", "cancelled", "no_show"] = Field(
        default="completed",
        description="Appointment status to count. Use 'completed' for completed appointments.",
    )


def make_tool(db_path: Path):
    @tool("count_appointments", args_schema=CountArgs)
    def count_appointments(status: str = "completed") -> str:
        """Count appointments with a given status in the clinic database.

        Use this whenever the user asks how many appointments have a status.
        """
        # Parameterized SQL: the status value is passed separately, never
        # pasted into the SQL text, so it cannot change the query.
        with sqlite3.connect(db_path) as conn:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM appointments WHERE status = ?", (status,)
            ).fetchone()
        return json.dumps({"status": status, "appointment_count": count})

    return count_appointments


def main() -> int:
    settings = get_settings()
    report: dict = {
        "test": "stage1_tool_calling_smoke_test",
        "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": settings.ollama_model,
        "base_url": settings.ollama_base_url,
        "question": QUESTION,
        "expected_completed": EXPECTED_COMPLETED,
    }

    # Pre-flight: is Ollama reachable and is the model present?
    try:
        tags = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=5).json()
    except httpx.HTTPError as exc:
        report.update(verdict="BLOCKED", reason=f"Ollama not reachable: {exc}")
        print("BLOCKED: Ollama is not reachable. Start it with:  ollama serve")
        _write(report)
        return 2
    names = [m.get("name") for m in tags.get("models", [])]
    if settings.ollama_model not in names:
        report.update(verdict="BLOCKED", reason=f"Model missing. Installed: {names}")
        print(f"BLOCKED: model {settings.ollama_model!r} not found. Run:  ollama pull {settings.ollama_model}")
        _write(report)
        return 2

    with tempfile.TemporaryDirectory(prefix="molarmetrics_smoke_") as tmp:
        db_path = Path(tmp) / "fixture.db"
        build_fixture(db_path)

        # --- 3. ChatOllama + agent with bounded behaviour ----------------------
        model = ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=0,  # low temperature = more deterministic tool choice
            seed=42,
            num_ctx=4096,
            client_kwargs={"timeout": settings.ollama_timeout_seconds},
        )
        agent = create_agent(
            model=model,
            tools=[make_tool(db_path)],
            system_prompt=(
                "You answer questions about a clinic database. Always call a tool "
                "to get numbers. Never guess numbers. Answer in one sentence."
            ),
            middleware=[
                ModelCallLimitMiddleware(run_limit=4, exit_behavior="end"),
                ToolCallLimitMiddleware(run_limit=3, exit_behavior="end"),
            ],
        )

        # --- 4. Ask the question --------------------------------------------------
        started = time.perf_counter()
        result = agent.invoke(
            {"messages": [{"role": "user", "content": QUESTION}]},
            config={"recursion_limit": 10},
        )
        report["seconds"] = round(time.perf_counter() - started, 1)

    # --- 5. Did the model really call the tool? ----------------------------------
    messages = result["messages"]
    tool_calls = [tc for m in messages if isinstance(m, AIMessage) for tc in m.tool_calls]
    tool_outputs = [m.content for m in messages if isinstance(m, ToolMessage)]
    final_answer = next(
        (m.content for m in reversed(messages) if isinstance(m, AIMessage) and not m.tool_calls),
        "",
    )
    report["tool_calls"] = [{"name": tc["name"], "args": tc["args"]} for tc in tool_calls]
    report["tool_outputs"] = tool_outputs
    report["final_answer"] = final_answer

    tool_was_called = any(tc["name"] == "count_appointments" for tc in tool_calls)
    tool_counts = []
    for out in tool_outputs:
        try:
            tool_counts.append(json.loads(out)["appointment_count"])
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    # --- 6. Compare with the known answer ---------------------------------------
    tool_count_correct = EXPECTED_COMPLETED in tool_counts
    answer_has_count = bool(re.search(rf"\b{EXPECTED_COMPLETED}\b|\bseven\b", final_answer, re.I))

    report["checks"] = {
        "model_called_the_tool": tool_was_called,
        "tool_returned_expected_count": tool_count_correct,
        "final_answer_states_expected_count": answer_has_count,
    }
    passed = all(report["checks"].values())
    report["verdict"] = "PASS" if passed else "FAIL"
    _write(report)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if passed else 1


def _write(report: dict) -> None:
    out = PROJECT_ROOT / "reports" / "stage1_smoke_test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
