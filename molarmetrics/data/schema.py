"""SQLite schema for the MolarMetrics synthetic database.

Beginner note
-------------
The database protects itself with constraints, so bad rows are rejected at
insert time rather than discovered later:

* PRIMARY KEY / REFERENCES  -> unique IDs and valid links between tables
* CHECK                     -> allowed values, non-negative money, net = listed - discount
* UNIQUE INDEX              -> a dentist (or patient) cannot be double-booked
* TRIGGERS                  -> rules that span two tables (e.g. only completed
                               appointments may have treatments)

Money is stored as INTEGER paise. The ``*_inr`` columns are read-only
"generated" columns derived from paise, for convenient display.
"""

from __future__ import annotations

import sqlite3

from molarmetrics.data.catalog import ALLOWED_STATUSES, GENDERS, PAYMENT_METHODS, PROCEDURE_NAMES


def _sql_list(values: tuple[str, ...]) -> str:
    # Values come from our own constant catalog (never from users), so it is
    # safe to embed them in DDL. Single quotes are escaped defensively.
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


_TOOTH_CHECK = (
    "tooth_number IS NULL OR (typeof(tooth_number) = 'integer' AND ("
    "(tooth_number / 10 BETWEEN 1 AND 4 AND tooth_number % 10 BETWEEN 1 AND 8) OR "
    "(tooth_number / 10 BETWEEN 5 AND 8 AND tooth_number % 10 BETWEEN 1 AND 5)))"
)

TABLES_DDL = f"""
CREATE TABLE patients (
    patient_id        TEXT PRIMARY KEY,
    birth_year        INTEGER NOT NULL CHECK (typeof(birth_year) = 'integer' AND birth_year BETWEEN 1900 AND 2025),
    gender            TEXT NOT NULL CHECK (gender IN ({_sql_list(GENDERS)})),
    locality          TEXT NOT NULL,
    registration_date TEXT NOT NULL CHECK (registration_date = date(registration_date))
);

CREATE TABLE dentists (
    dentist_id             TEXT PRIMARY KEY,
    fictional_display_name TEXT NOT NULL,
    specialty              TEXT NOT NULL
);

CREATE TABLE appointments (
    appointment_id       TEXT PRIMARY KEY,
    patient_id           TEXT NOT NULL REFERENCES patients(patient_id),
    dentist_id           TEXT NOT NULL REFERENCES dentists(dentist_id),
    appointment_datetime TEXT NOT NULL CHECK (appointment_datetime = datetime(appointment_datetime)),
    status               TEXT NOT NULL CHECK (status IN ({_sql_list(ALLOWED_STATUSES)})),
    visit_reason         TEXT NOT NULL
);

CREATE TABLE treatments (
    treatment_id     TEXT PRIMARY KEY,
    appointment_id   TEXT NOT NULL REFERENCES appointments(appointment_id),
    procedure_name   TEXT NOT NULL CHECK (procedure_name IN ({_sql_list(PROCEDURE_NAMES)})),
    tooth_number     INTEGER CHECK ({_TOOTH_CHECK}),
    listed_fee_paise INTEGER NOT NULL CHECK (typeof(listed_fee_paise) = 'integer' AND listed_fee_paise >= 0),
    discount_paise   INTEGER NOT NULL CHECK (typeof(discount_paise) = 'integer' AND discount_paise >= 0
                                             AND discount_paise <= listed_fee_paise),
    net_fee_paise    INTEGER NOT NULL CHECK (typeof(net_fee_paise) = 'integer'
                                             AND net_fee_paise = listed_fee_paise - discount_paise),
    listed_fee_inr   REAL GENERATED ALWAYS AS (listed_fee_paise / 100.0) VIRTUAL,
    discount_inr     REAL GENERATED ALWAYS AS (discount_paise / 100.0) VIRTUAL,
    net_fee_inr      REAL GENERATED ALWAYS AS (net_fee_paise / 100.0) VIRTUAL
);

CREATE TABLE payments (
    payment_id     TEXT PRIMARY KEY,
    treatment_id   TEXT NOT NULL REFERENCES treatments(treatment_id),
    payment_date   TEXT NOT NULL CHECK (payment_date = date(payment_date)),
    amount_paise   INTEGER NOT NULL CHECK (typeof(amount_paise) = 'integer' AND amount_paise > 0),
    payment_method TEXT NOT NULL CHECK (payment_method IN ({_sql_list(PAYMENT_METHODS)})),
    amount_inr     REAL GENERATED ALWAYS AS (amount_paise / 100.0) VIRTUAL
);

CREATE INDEX idx_appointments_datetime ON appointments(appointment_datetime);
CREATE INDEX idx_appointments_patient ON appointments(patient_id);
CREATE UNIQUE INDEX ux_appointments_dentist_slot ON appointments(dentist_id, appointment_datetime);
CREATE UNIQUE INDEX ux_appointments_patient_slot ON appointments(patient_id, appointment_datetime);
CREATE INDEX idx_treatments_appointment ON treatments(appointment_id);
CREATE INDEX idx_payments_treatment ON payments(treatment_id);
CREATE INDEX idx_payments_date ON payments(payment_date);
"""

TRIGGERS_DDL = """
CREATE TRIGGER trg_treatment_requires_completed_appointment
BEFORE INSERT ON treatments
WHEN (SELECT status FROM appointments WHERE appointment_id = NEW.appointment_id) IS NOT 'completed'
BEGIN
    SELECT RAISE(ABORT, 'treatments are only allowed on completed appointments');
END;

CREATE TRIGGER trg_payment_not_before_treatment
BEFORE INSERT ON payments
WHEN NEW.payment_date < (
    SELECT date(a.appointment_datetime) FROM treatments t
    JOIN appointments a ON a.appointment_id = t.appointment_id
    WHERE t.treatment_id = NEW.treatment_id)
BEGIN
    SELECT RAISE(ABORT, 'payment_date cannot precede the treatment date');
END;

CREATE TRIGGER trg_payments_not_exceed_net_fee
BEFORE INSERT ON payments
WHEN (SELECT COALESCE(SUM(amount_paise), 0) FROM payments WHERE treatment_id = NEW.treatment_id)
     + NEW.amount_paise > (SELECT net_fee_paise FROM treatments WHERE treatment_id = NEW.treatment_id)
BEGIN
    SELECT RAISE(ABORT, 'total payments cannot exceed the treatment net fee');
END;
"""

TABLE_ORDER = ("patients", "dentists", "appointments", "treatments", "payments")

# Columns we INSERT (generated *_inr columns are computed by SQLite).
INSERT_COLUMNS: dict[str, tuple[str, ...]] = {
    "patients": ("patient_id", "birth_year", "gender", "locality", "registration_date"),
    "dentists": ("dentist_id", "fictional_display_name", "specialty"),
    "appointments": ("appointment_id", "patient_id", "dentist_id", "appointment_datetime",
                     "status", "visit_reason"),
    "treatments": ("treatment_id", "appointment_id", "procedure_name", "tooth_number",
                   "listed_fee_paise", "discount_paise", "net_fee_paise"),
    "payments": ("payment_id", "treatment_id", "payment_date", "amount_paise", "payment_method"),
}


def create_schema(conn: sqlite3.Connection, with_triggers: bool = True) -> None:
    """Create all tables (and, by default, the cross-table safety triggers)."""
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(TABLES_DDL)
    if with_triggers:
        conn.executescript(TRIGGERS_DDL)


def insert_rows(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    """Insert dict rows with a parameterized statement (no string-built SQL values)."""
    cols = INSERT_COLUMNS[table]
    placeholders = ", ".join("?" for _ in cols)
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
        [tuple(row[c] for c in cols) for row in rows],
    )
