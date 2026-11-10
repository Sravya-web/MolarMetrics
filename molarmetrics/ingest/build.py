"""Build an uploaded dataset's SQLite database, atomically.

Beginner notes
--------------
* The tables and columns have the SAME names as the bundled sample database,
  so the existing, tested analytics SQL runs on uploads unchanged. Optional
  fields are nullable, and the synthetic-catalog rules (fixed procedure names,
  FDI teeth…) are not applied to real clinic data.
* Money is INTEGER paise with CHECK constraints, exactly like the sample.
* Atomic: the database is written inside a temporary folder in one
  transaction, re-opened and verified, and only then renamed into place. If
  anything fails, the temporary folder is deleted and the previously active
  dataset is untouched.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from molarmetrics.dataset import META_TABLE_DDL, write_meta
from molarmetrics.ingest.validate import NormalizedData

SCHEMA_VERSION = 1
DB_FILENAME = "clinic.sqlite3"

UPLOAD_SCHEMA = """
CREATE TABLE patients (
    patient_id        TEXT PRIMARY KEY,
    registration_date TEXT CHECK (registration_date IS NULL OR registration_date = date(registration_date))
);

CREATE TABLE dentists (
    dentist_id   TEXT PRIMARY KEY,
    display_name TEXT,
    specialty    TEXT
);

CREATE TABLE appointments (
    appointment_id       TEXT PRIMARY KEY,
    patient_id           TEXT NOT NULL,
    dentist_id           TEXT,
    appointment_datetime TEXT NOT NULL CHECK (appointment_datetime = datetime(appointment_datetime)),
    status               TEXT NOT NULL CHECK (status IN ('completed', 'cancelled', 'no_show'))
);

CREATE TABLE treatments (
    treatment_id     TEXT PRIMARY KEY,
    appointment_id   TEXT NOT NULL REFERENCES appointments(appointment_id),
    procedure_name   TEXT NOT NULL,
    listed_fee_paise INTEGER CHECK (listed_fee_paise IS NULL
                                    OR (typeof(listed_fee_paise) = 'integer' AND listed_fee_paise >= 0)),
    discount_paise   INTEGER CHECK (discount_paise IS NULL
                                    OR (typeof(discount_paise) = 'integer' AND discount_paise >= 0)),
    net_fee_paise    INTEGER NOT NULL CHECK (typeof(net_fee_paise) = 'integer' AND net_fee_paise >= 0),
    CHECK (listed_fee_paise IS NULL OR discount_paise IS NULL OR net_fee_paise = listed_fee_paise - discount_paise)
);

CREATE TABLE payments (
    payment_id     TEXT PRIMARY KEY,
    treatment_id   TEXT NOT NULL REFERENCES treatments(treatment_id),
    payment_date   TEXT NOT NULL CHECK (payment_date = date(payment_date)),
    amount_paise   INTEGER NOT NULL CHECK (typeof(amount_paise) = 'integer' AND amount_paise > 0),
    payment_method TEXT
);

CREATE INDEX idx_appointments_datetime ON appointments(appointment_datetime);
CREATE INDEX idx_appointments_patient ON appointments(patient_id);
CREATE INDEX idx_treatments_appointment ON treatments(appointment_id);
CREATE INDEX idx_payments_treatment ON payments(treatment_id);
CREATE INDEX idx_payments_date ON payments(payment_date);
"""

_COLUMNS = {
    "patients": ("patient_id", "registration_date"),
    "dentists": ("dentist_id", "display_name", "specialty"),
    "appointments": ("appointment_id", "patient_id", "dentist_id", "appointment_datetime", "status"),
    "treatments": ("treatment_id", "appointment_id", "procedure_name", "listed_fee_paise", "discount_paise",
                   "net_fee_paise"),
    "payments": ("payment_id", "treatment_id", "payment_date", "amount_paise", "payment_method"),
}


class ImportFailed(RuntimeError):
    """The new dataset could not be written or verified; nothing was activated."""


def _insert(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    cols = _COLUMNS[table]
    conn.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                     [tuple(r[c] for c in cols) for r in rows])


def write_database(data: NormalizedData, name: str, db_path: Path) -> dict:
    """Write every table in ONE transaction. Returns the metadata stored."""
    meta = {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "coverage_start": data.coverage[0],
        "coverage_end": data.coverage[1],
        "capabilities": data.capabilities,
        "procedure_names": data.procedure_names,
        "import_notes": data.import_notes,
        "counts": {t: len(getattr(data, t)) for t in _COLUMNS},
    }
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.executescript(UPLOAD_SCHEMA + META_TABLE_DDL + ";")
        with conn:
            for table in ("patients", "dentists", "appointments", "treatments", "payments"):
                _insert(conn, table, getattr(data, table))
            write_meta(conn, meta)
    finally:
        conn.close()
    return meta


def verify_database(data: NormalizedData, db_path: Path) -> None:
    """Re-open read-only and check counts, keys and money totals match exactly."""
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ImportFailed("integrity check failed")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise ImportFailed("foreign key check failed")
        for table in _COLUMNS:
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if n != len(getattr(data, table)):
                raise ImportFailed(f"{table}: wrote {n} rows, expected {len(getattr(data, table))}")
        net = conn.execute("SELECT COALESCE(SUM(net_fee_paise), 0) FROM treatments").fetchone()[0]
        paid = conn.execute("SELECT COALESCE(SUM(amount_paise), 0) FROM payments").fetchone()[0]
        if net != sum(t["net_fee_paise"] for t in data.treatments) or \
                paid != sum(p["amount_paise"] for p in data.payments):
            raise ImportFailed("money totals do not match")
    finally:
        conn.close()


def atomic_import(data: NormalizedData, name: str, datasets_root: Path, dataset_id: str) -> tuple[Path, dict]:
    """Create ``datasets_root/<dataset_id>/clinic.sqlite3`` or nothing at all."""
    datasets_root.mkdir(parents=True, exist_ok=True)
    tmp = datasets_root / f".{dataset_id}.tmp"
    final = datasets_root / dataset_id
    if final.exists() or tmp.exists():
        raise ImportFailed("dataset folder already exists")
    tmp.mkdir()
    try:
        meta = write_database(data, name, tmp / DB_FILENAME)
        verify_database(data, tmp / DB_FILENAME)
        os.replace(tmp, final)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return final / DB_FILENAME, meta
