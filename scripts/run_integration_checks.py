"""Run the live Ollama end-to-end checks and write an honest report.

    python scripts/run_integration_checks.py            # all questions
    python scripts/run_integration_checks.py Q1 Q5      # selected questions

Writes reports/integration_report.json and reports/integration_report.md.
If Ollama cannot be reached, every check is recorded as NOT RUN.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx  # noqa: E402

from molarmetrics import APP_NAME  # noqa: E402
from molarmetrics.config import get_settings  # noqa: E402
from tests.integration.live_checks import QUESTIONS, run_checks, to_dict  # noqa: E402


def main(argv: list[str]) -> int:
    settings = get_settings()
    out_dir = PROJECT_ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    # A run of selected questions must never overwrite the full report.
    stem = "integration_report_subset" if argv else "integration_report"
    header = {"app": APP_NAME, "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "model": settings.ollama_model, "base_url": settings.ollama_base_url}
    try:
        names = [m["name"] for m in httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=5).json()["models"]]
        reachable = settings.ollama_model in names
        reason = "" if reachable else f"model {settings.ollama_model} not installed"
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        reachable, reason = False, f"Ollama not reachable: {exc}"

    if not reachable:
        report = {**header, "status": "NOT RUN", "reason": reason,
                  "results": [{"id": q[0], "question": q[1], "status": "NOT RUN"} for q in QUESTIONS]}
        (out_dir / f"{stem}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"NOT RUN: {reason}")
        return 2

    results = run_checks(settings.data_dir / "csv", only=argv or None)
    priority = [r for r in results if r.priority]
    report = {
        **header,
        "status": "PASS" if all(r.passed for r in results) else "FAIL",
        "priority_passed": f"{sum(r.passed for r in priority)}/{len(priority)}",
        "all_passed": f"{sum(r.passed for r in results)}/{len(results)}",
        "results": [to_dict(r) for r in results],
    }
    (out_dir / f"{stem}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                                     encoding="utf-8")
    lines = [f"# {APP_NAME} live integration report", "",
             f"Run at {header['run_at_utc']} with `{settings.ollama_model}` on {settings.ollama_base_url}.", "",
             f"**Priority questions passed: {report['priority_passed']}** · All questions passed: "
             f"{report['all_passed']}", "",
             "Checks: tool called · arguments match the question · tool numbers equal an independent pandas "
             "calculation · answer states the key figure · every number in the answer appears in tool results · "
             "wording regression checks (no total called an average; 'majority' only with a calculated share "
             "above 50%; patients / appointments / treatment records / payments not mixed up; billed revenue "
             "and collections not swapped).", "",
             "| ID | Question | Result | Checks | Tools called | Seconds |", "|---|---|---|---|---|---|"]
    for r in results:
        checks = ", ".join(f"{k} {'✓' if v else '✗'}" for k, v in r.checks.items()) or (r.error or "")
        tools = ", ".join(c["name"] for c in r.tool_calls) or "none"
        lines.append(f"| {r.id} | {r.question} | {'PASS' if r.passed else 'FAIL'} | {checks} | {tools} | {r.seconds} |")
    lines += ["", "## Answers", "",
              "For each question: **Tool facts** are deterministic sentences calculated by MolarMetrics; "
              "**Model commentary** is what the language model wrote.", ""]
    for r in results:
        lines += [f"**{r.id}. {r.question}**", ""]
        if r.facts:
            lines += ["Tool facts (calculated by MolarMetrics):", ""] + [f"- {f}" for f in r.facts] + [""]
        lines += [f"Model commentary ({settings.ollama_model}):", "", f"> {r.answer or r.error}", "",
                  f"Expected: {r.details.get('expected', '-')}", ""]
        problems = {k: v for k, v in r.details.items() if k not in ("expected",)}
        for key, value in problems.items():
            lines += [f"- {key}: {value}"]
        if problems:
            lines.append("")
    (out_dir / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    for r in results:
        print(f"[{'PASS' if r.passed else 'FAIL'}] {r.id} ({r.seconds}s) {r.question}")
        print(f"       tools: {[(c['name'], c['validated_args']) for c in r.tool_calls]}")
        print(f"       checks: {r.checks}")
        print(f"       answer: {r.answer or r.error}")
    print(f"\nPriority passed {report['priority_passed']}; all passed {report['all_passed']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
