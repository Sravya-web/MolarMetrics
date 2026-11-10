"""The registry: sessions, datasets and upload batches (a small SQLite file).

Beginner notes
--------------
* A browser gets a random session token in an HttpOnly cookie. Only the
  token's SHA-256 hash is stored here, and it is the session's ID.
* Every dataset and upload batch belongs to exactly one session. Lookups
  always pass the session, so knowing a dataset's ID grants nothing.
* Uploaded rows never live here: each dataset has its own database file under
  ``runtime/datasets/<random id>/``. The sample dataset's entry just points
  at the bundled, read-only sample database.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id                TEXT PRIMARY KEY,
    created_at        REAL NOT NULL,
    last_seen         REAL NOT NULL,
    active_dataset_id TEXT
);
CREATE TABLE IF NOT EXISTS datasets (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('sample', 'uploaded')),
    name         TEXT NOT NULL,
    db_path      TEXT NOT NULL,
    created_at   REAL NOT NULL,
    last_used_at REAL NOT NULL,
    meta         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_datasets_session ON datasets(session_id);
CREATE TABLE IF NOT EXISTS batches (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    created_at   REAL NOT NULL,
    last_used_at REAL NOT NULL,
    files        TEXT NOT NULL,
    config       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_batches_session ON batches(session_id);
"""


@dataclass
class DatasetRow:
    id: str
    session_id: str
    kind: str
    name: str
    db_path: str
    created_at: float
    last_used_at: float
    meta: dict


@dataclass
class BatchRow:
    id: str
    session_id: str
    created_at: float
    last_used_at: float
    files: list[dict]
    config: dict


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._tx() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _tx(self):
        """One serialised transaction (the app is a single local process)."""
        with self._lock:
            conn = sqlite3.connect(self.path, timeout=10)
            conn.row_factory = sqlite3.Row
            try:
                with conn:
                    yield conn
            finally:
                conn.close()

    # --- sessions -------------------------------------------------------------------
    def get_session(self, session_id: str) -> sqlite3.Row | None:
        with self._tx() as c:
            return c.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()

    def create_session(self, session_id: str, now: float | None = None) -> None:
        now = now or time.time()
        with self._tx() as c:
            c.execute("INSERT OR IGNORE INTO sessions (id, created_at, last_seen) VALUES (?, ?, ?)",
                      (session_id, now, now))

    def touch_session(self, session_id: str, now: float | None = None) -> None:
        with self._tx() as c:
            c.execute("UPDATE sessions SET last_seen = ? WHERE id = ?", (now or time.time(), session_id))

    def set_active(self, session_id: str, dataset_id: str | None) -> None:
        with self._tx() as c:
            c.execute("UPDATE sessions SET active_dataset_id = ? WHERE id = ?", (dataset_id, session_id))

    def delete_session(self, session_id: str) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def sessions_idle_since(self, cutoff: float) -> list[str]:
        with self._tx() as c:
            return [r["id"] for r in c.execute("SELECT id FROM sessions WHERE last_seen < ?", (cutoff,))]

    # --- datasets ----------------------------------------------------------------------
    @staticmethod
    def _dataset(row) -> DatasetRow:
        return DatasetRow(id=row["id"], session_id=row["session_id"], kind=row["kind"], name=row["name"],
                          db_path=row["db_path"], created_at=row["created_at"], last_used_at=row["last_used_at"],
                          meta=json.loads(row["meta"]))

    def add_dataset(self, row: DatasetRow, activate: bool = True) -> None:
        """Register a dataset and (by default) make it active, in ONE transaction."""
        with self._tx() as c:
            c.execute("INSERT INTO datasets (id, session_id, kind, name, db_path, created_at, last_used_at, meta) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (row.id, row.session_id, row.kind, row.name, row.db_path, row.created_at, row.last_used_at,
                       json.dumps(row.meta)))
            if activate:
                c.execute("UPDATE sessions SET active_dataset_id = ? WHERE id = ?", (row.id, row.session_id))

    def get_dataset(self, dataset_id: str) -> DatasetRow | None:
        with self._tx() as c:
            row = c.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        return self._dataset(row) if row else None

    def list_datasets(self, session_id: str) -> list[DatasetRow]:
        with self._tx() as c:
            rows = c.execute("SELECT * FROM datasets WHERE session_id = ? ORDER BY created_at", (session_id,))
            return [self._dataset(r) for r in rows]

    def all_datasets(self) -> list[DatasetRow]:
        with self._tx() as c:
            return [self._dataset(r) for r in c.execute("SELECT * FROM datasets")]

    def touch_dataset(self, dataset_id: str, now: float | None = None) -> None:
        with self._tx() as c:
            c.execute("UPDATE datasets SET last_used_at = ? WHERE id = ?", (now or time.time(), dataset_id))

    def delete_dataset(self, dataset_id: str) -> None:
        """Remove the registry row; if it was a session's active dataset, that
        session falls back to its most recently used remaining dataset."""
        with self._tx() as c:
            row = c.execute("SELECT session_id FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
            c.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
            if row:
                nxt = c.execute("SELECT id FROM datasets WHERE session_id = ? ORDER BY last_used_at DESC LIMIT 1",
                                (row["session_id"],)).fetchone()
                c.execute("UPDATE sessions SET active_dataset_id = ? WHERE id = ? AND active_dataset_id = ?",
                          (nxt["id"] if nxt else None, row["session_id"], dataset_id))

    # --- upload batches --------------------------------------------------------------------
    @staticmethod
    def _batch(row) -> BatchRow:
        return BatchRow(id=row["id"], session_id=row["session_id"], created_at=row["created_at"],
                        last_used_at=row["last_used_at"], files=json.loads(row["files"]),
                        config=json.loads(row["config"]))

    def add_batch(self, row: BatchRow) -> None:
        with self._tx() as c:
            c.execute("INSERT INTO batches (id, session_id, created_at, last_used_at, files, config) "
                      "VALUES (?, ?, ?, ?, ?, ?)",
                      (row.id, row.session_id, row.created_at, row.last_used_at, json.dumps(row.files),
                       json.dumps(row.config)))

    def get_batch(self, batch_id: str) -> BatchRow | None:
        with self._tx() as c:
            row = c.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
        return self._batch(row) if row else None

    def update_batch(self, batch_id: str, *, files: list[dict] | None = None, config: dict | None = None,
                     now: float | None = None) -> None:
        with self._tx() as c:
            if files is not None:
                c.execute("UPDATE batches SET files = ? WHERE id = ?", (json.dumps(files), batch_id))
            if config is not None:
                c.execute("UPDATE batches SET config = ? WHERE id = ?", (json.dumps(config), batch_id))
            c.execute("UPDATE batches SET last_used_at = ? WHERE id = ?", (now or time.time(), batch_id))

    def delete_batch(self, batch_id: str) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM batches WHERE id = ?", (batch_id,))

    def all_batches(self) -> list[BatchRow]:
        with self._tx() as c:
            return [self._batch(r) for r in c.execute("SELECT * FROM batches")]
