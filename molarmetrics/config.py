"""Central configuration for MolarMetrics.

Beginner note
-------------
Every setting lives here so the rest of the code never reads environment
variables directly. Values come from (in priority order):

1. Real environment variables (e.g. ``export OLLAMA_MODEL=...``)
2. A local ``.env`` file in the project root (copy ``.env.example``)
3. The defaults below

Importing this module also switches OFF LangChain/LangSmith remote tracing,
so no prompts, questions or results are ever sent to a cloud service.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:  # python-dotenv is optional at runtime; the defaults still work without it
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
except ImportError:  # pragma: no cover - dependency is listed in requirements.txt
    pass

# Privacy guard: force tracing off AFTER loading .env, so a stray .env value
# cannot re-enable it. MolarMetrics keeps inference and analytics local.
for _var in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING"):
    os.environ[_var] = "false"

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


@dataclass(frozen=True)
class Settings:
    """Runtime settings. Frozen so nothing can change them by accident."""

    ollama_model: str
    ollama_base_url: str
    ollama_timeout_seconds: float
    ollama_num_ctx: int
    data_dir: Path
    db_path: Path

    @property
    def ollama_is_local(self) -> bool:
        """True when the Ollama URL points at this computer."""
        host = (urlparse(self.ollama_base_url).hostname or "").lower()
        return host in {"localhost", "127.0.0.1", "::1"}


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def get_settings() -> Settings:
    """Read settings fresh each call (cheap, and easy to override in tests)."""
    data_dir = Path(_env("MOLARMETRICS_DATA_DIR", str(DEFAULT_DATA_DIR))).expanduser()
    db_path = Path(_env("MOLARMETRICS_DB_PATH", str(data_dir / "molarmetrics.db"))).expanduser()
    return Settings(
        ollama_model=_env("OLLAMA_MODEL", "llama3.2:3b"),
        ollama_base_url=_env("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        ollama_timeout_seconds=float(_env("OLLAMA_TIMEOUT_SECONDS", "120")),
        ollama_num_ctx=int(_env("OLLAMA_NUM_CTX", "8192")),
        data_dir=data_dir,
        db_path=db_path,
    )
