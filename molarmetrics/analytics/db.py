"""Read-only database access.

Analytics code opens the database in SQLite read-only mode, so no tool can
ever modify data, even if asked to.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from molarmetrics.config import get_settings


class DatabaseNotFoundError(RuntimeError):
    """Raised when the synthetic database has not been generated yet."""


def connect_readonly(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open the MolarMetrics database read-only. Create one connection per
    request/thread (SQLite connections should not be shared across threads)."""
    path = Path(db_path) if db_path else get_settings().db_path
    if not path.exists():
        raise DatabaseNotFoundError(
            f"Database not found at {path}. Generate it with: python -m molarmetrics.data.generate"
        )
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn
