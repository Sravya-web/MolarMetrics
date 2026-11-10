"""LIVE end-to-end tests against the real local Ollama model.

Deselected by default. Run with:   pytest -m integration
(or: python scripts/run_integration_checks.py, which also writes a report)

If Ollama is not reachable these tests are SKIPPED, which means NOT RUN.
Mocked tests elsewhere are not proof that the real agent works.
"""

import httpx
import pytest

from molarmetrics.config import get_settings
from tests.integration.live_checks import QUESTIONS, run_checks

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def results(real_db_path):
    s = get_settings()
    try:
        names = [m["name"] for m in httpx.get(f"{s.ollama_base_url}/api/tags", timeout=5).json()["models"]]
    except (httpx.HTTPError, KeyError, ValueError):
        pytest.skip("NOT RUN: Ollama is not reachable")
    if s.ollama_model not in names:
        pytest.skip(f"NOT RUN: model {s.ollama_model} is not installed")
    return {r.id: r for r in run_checks(real_db_path.parent / "csv")}


@pytest.mark.parametrize("qid", [q[0] for q in QUESTIONS])
def test_question(results, qid):
    r = results[qid]
    assert r.error is None, r.error
    failed = [k for k, ok in r.checks.items() if not ok]
    assert not failed, f"{qid} failed {failed}; answer: {r.answer!r}"
