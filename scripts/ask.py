"""Ask MolarMetrics a question from the terminal (handy for testing and demos).

    python scripts/ask.py "What was billed revenue in 2025?"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from molarmetrics.agent.agent import MolarMetricsAgent  # noqa: E402


def main() -> int:
    question = " ".join(sys.argv[1:]).strip() or "What was billed revenue in 2025?"
    agent = MolarMetricsAgent()
    reply = agent.ask(question)
    print(f"\nQ: {question}\n")
    if reply.error:
        print(f"ERROR: {reply.error}")
        return 1
    for a in reply.activities:
        print(f"TOOL CALL  {a.name}({json.dumps(a.model_args, ensure_ascii=False)})  -> {a.status}")
        if a.result is not None:
            print(f"  validated: {json.dumps(a.result.arguments, ensure_ascii=False)}")
            print("  TOOL FACTS (calculated by MolarMetrics, not by the model):")
            for fact in a.result.facts:
                print(f"    - {fact}")
        else:
            print(f"  returned: {a.content[:300]}")
    print(f"\nMODEL COMMENTARY ({agent.settings.ollama_model}, may paraphrase):\n{reply.answer}\n")
    if reply.grounding:
        print(f"Number check: {reply.grounding.message}")
    for note in reply.notes:
        print(f"Note: {note}")
    print(f"({reply.seconds}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
