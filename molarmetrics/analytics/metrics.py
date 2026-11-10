"""Core metric calculations with parameterized SQL.

Beginner notes
--------------
* Every query passes dates as parameters (``?``), never by pasting text into
  SQL, so inputs cannot change what a query does.
* Double counting is avoided by aggregating each table SEPARATELY (treatments
  per month, payments per month, payments per treatment) and only then
  combining the small results. Joining appointments -> treatments -> payments
  and summing fees would repeat a treatment's fee once per payment.
* Money is summed as integer paise, so totals are exact.
* All functions take ISO date strings ('YYYY-MM-DD'); the end date is inclusive.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from molarmetrics.data.catalog import PROCEDURE_NAMES

STATUS_KEYS = ("scheduled", "completed", "cancelled", "no_show")
_STATUS_SUMS = """
    COUNT(a.appointment_id),
    COALESCE(SUM(a.status = 'completed'), 0),
    COALESCE(SUM(a.status = 'cancelled'), 0),
    COALESCE(SUM(a.status = 'no_show'), 0)
"""
AGING_BUCKETS = (("0-30 days", 0, 30), ("31-90 days", 31, 90), ("91-180 days", 91, 180),
                 ("181+ days", 181, None))


def months_between(start: str, end: str) -> list[str]:
    """Every 'YYYY-MM' from start to end inclusive, in chronological order."""
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    out, y, m = [], s.year, s.month
    while (y, m) <= (e.year, e.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# --- appointments ---------------------------------------------------------------------
def status_counts(conn: sqlite3.Connection, start: str, end: str) -> dict[str, int]:
    row = conn.execute(
        f"SELECT {_STATUS_SUMS} FROM appointments a WHERE date(a.appointment_datetime) BETWEEN ? AND ?",
        (start, end),
    ).fetchone()
    return dict(zip(STATUS_KEYS, (int(v) for v in row)))


def status_counts_by_month(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    found = {
        r[0]: r[1:]
        for r in conn.execute(
            f"""SELECT strftime('%Y-%m', a.appointment_datetime) AS month, {_STATUS_SUMS}
                FROM appointments a WHERE date(a.appointment_datetime) BETWEEN ? AND ?
                GROUP BY month""",
            (start, end),
        )
    }
    # Fill months with no appointments with zeros so charts show the gap.
    return [{"month": m, **dict(zip(STATUS_KEYS, (int(v) for v in found.get(m, (0, 0, 0, 0)))))}
            for m in months_between(start, end)]


# Dentist name column: the sample database uses ``fictional_display_name``,
# uploaded datasets use ``display_name``. Chosen from this fixed whitelist only.
_DENTIST_NAME_COLUMNS = ("display_name", "fictional_display_name")


def _dentist_name_column(conn: sqlite3.Connection) -> str:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dentists)")}
    return next((c for c in _DENTIST_NAME_COLUMNS if c in cols), "NULL")


def _dentist_label(dentist_id: str, name: str | None) -> str:
    return f"{name} ({dentist_id})" if name else str(dentist_id)


def status_counts_by_dentist(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    """Status counts per dentist. Dentists with zero appointments in the range
    are kept. Without a dentists table (an appointments-only upload), dentists
    are the distinct dentist IDs on the appointments. Appointments with no
    dentist recorded get their own row, so per-dentist rows always add up to
    the overall totals."""
    if conn.execute("SELECT EXISTS (SELECT 1 FROM dentists)").fetchone()[0]:
        name_col = _dentist_name_column(conn)
        # LEFT JOIN from dentists keeps dentists with zero appointments in the range.
        rows = conn.execute(
            f"""SELECT d.dentist_id, d.{name_col} AS name, d.specialty, {_STATUS_SUMS}
                FROM dentists d
                LEFT JOIN appointments a
                       ON a.dentist_id = d.dentist_id AND date(a.appointment_datetime) BETWEEN ? AND ?
                GROUP BY d.dentist_id, name, d.specialty
                ORDER BY d.dentist_id""" if name_col != "NULL" else
            f"""SELECT d.dentist_id, NULL, d.specialty, {_STATUS_SUMS}
                FROM dentists d
                LEFT JOIN appointments a
                       ON a.dentist_id = d.dentist_id AND date(a.appointment_datetime) BETWEEN ? AND ?
                GROUP BY d.dentist_id, d.specialty
                ORDER BY d.dentist_id""",
            (start, end),
        ).fetchall()
    else:
        rows = conn.execute(
            f"""SELECT ids.dentist_id, NULL, NULL, {_STATUS_SUMS}
                FROM (SELECT DISTINCT dentist_id FROM appointments WHERE dentist_id IS NOT NULL) ids
                LEFT JOIN appointments a
                       ON a.dentist_id = ids.dentist_id AND date(a.appointment_datetime) BETWEEN ? AND ?
                GROUP BY ids.dentist_id
                ORDER BY ids.dentist_id""",
            (start, end),
        ).fetchall()
    out = [{"dentist_id": r[0], "dentist": _dentist_label(r[0], r[1]), "specialty": r[2],
            **dict(zip(STATUS_KEYS, (int(v) for v in r[3:])))} for r in rows]
    unassigned = conn.execute(
        f"""SELECT {_STATUS_SUMS} FROM appointments a
            WHERE a.dentist_id IS NULL AND date(a.appointment_datetime) BETWEEN ? AND ?""",
        (start, end),
    ).fetchone()
    if int(unassigned[0]):
        out.append({"dentist_id": None, "dentist": "No dentist recorded", "specialty": None,
                    **dict(zip(STATUS_KEYS, (int(v) for v in unassigned)))})
    return out


# --- patients ---------------------------------------------------------------------------
def patient_counts(conn: sqlite3.Connection, start: str, end: str) -> dict[str, int]:
    """Unique patients seen and returning patients in [start, end].

    The window function runs over ALL completed visits (before the date filter),
    so a visit counts as returning when ANY earlier completed visit exists, even
    one before the selected range.
    """
    row = conn.execute(
        """WITH completed AS (
               SELECT patient_id, appointment_datetime,
                      MIN(appointment_datetime) OVER (PARTITION BY patient_id) AS first_completed_at
               FROM appointments WHERE status = 'completed'
           )
           SELECT COUNT(DISTINCT patient_id),
                  COUNT(DISTINCT CASE WHEN appointment_datetime > first_completed_at THEN patient_id END)
           FROM completed
           WHERE date(appointment_datetime) BETWEEN ? AND ?""",
        (start, end),
    ).fetchone()
    return {"unique_patients_seen": int(row[0]), "returning_patients": int(row[1])}


# --- money ----------------------------------------------------------------------------------
def billed_revenue(conn: sqlite3.Connection, start: str, end: str) -> dict[str, int]:
    """Sum of net fees by appointment (treatment) date. treatments -> appointments
    is many-to-one, so this join cannot repeat a fee."""
    row = conn.execute(
        """SELECT COALESCE(SUM(t.net_fee_paise), 0), COUNT(t.treatment_id)
           FROM treatments t JOIN appointments a ON a.appointment_id = t.appointment_id
           WHERE date(a.appointment_datetime) BETWEEN ? AND ?""",
        (start, end),
    ).fetchone()
    return {"billed_paise": int(row[0]), "treatment_count": int(row[1])}


def collections(conn: sqlite3.Connection, start: str, end: str) -> dict[str, int]:
    """Sum of payments by PAYMENT date (no join needed)."""
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_paise), 0), COUNT(*) FROM payments WHERE payment_date BETWEEN ? AND ?",
        (start, end),
    ).fetchone()
    return {"collected_paise": int(row[0]), "payment_count": int(row[1])}


def billed_vs_collected_by_month(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    billed = dict(conn.execute(
        """SELECT strftime('%Y-%m', a.appointment_datetime) AS month, SUM(t.net_fee_paise)
           FROM treatments t JOIN appointments a ON a.appointment_id = t.appointment_id
           WHERE date(a.appointment_datetime) BETWEEN ? AND ? GROUP BY month""",
        (start, end),
    ).fetchall())
    collected = dict(conn.execute(
        """SELECT strftime('%Y-%m', payment_date) AS month, SUM(amount_paise)
           FROM payments WHERE payment_date BETWEEN ? AND ? GROUP BY month""",
        (start, end),
    ).fetchall())
    return [{"month": m, "billed_paise": int(billed.get(m, 0)), "collected_paise": int(collected.get(m, 0))}
            for m in months_between(start, end)]


def procedure_breakdown(conn: sqlite3.Connection, start: str, end: str,
                        names: tuple[str, ...] | None = None) -> list[dict]:
    """Treatment records, distinct patients and billed revenue per procedure.
    Every procedure in ``names`` (default: the sample catalog) is returned, with
    zeros when absent in the range. Procedures found in the data but missing from
    ``names`` are appended, so no billed amount is ever dropped."""
    found = {
        r[0]: r[1:]
        for r in conn.execute(
            """SELECT t.procedure_name, COUNT(*), COUNT(DISTINCT a.patient_id), SUM(t.net_fee_paise)
               FROM treatments t JOIN appointments a ON a.appointment_id = t.appointment_id
               WHERE date(a.appointment_datetime) BETWEEN ? AND ?
               GROUP BY t.procedure_name""",
            (start, end),
        )
    }
    ordered = list(names if names is not None else PROCEDURE_NAMES)
    ordered += sorted(n for n in found if n not in ordered)
    return [{"procedure": name, "treatment_count": int(found.get(name, (0, 0, 0))[0]),
             "patients": int(found.get(name, (0, 0, 0))[1]), "billed_paise": int(found.get(name, (0, 0, 0))[2])}
            for name in ordered]


def outstanding_as_of(conn: sqlite3.Connection, as_of: str) -> dict:
    """Outstanding balance on ``as_of`` (inclusive), with aging buckets.

    Payments are pre-aggregated per treatment in the ``paid`` CTE BEFORE the
    join, so each treatment's net fee is counted exactly once.
    """
    rows = conn.execute(
        """WITH paid AS (
               SELECT treatment_id, SUM(amount_paise) AS paid_paise
               FROM payments WHERE payment_date <= ? GROUP BY treatment_id
           )
           SELECT date(a.appointment_datetime), t.net_fee_paise, COALESCE(p.paid_paise, 0)
           FROM treatments t
           JOIN appointments a ON a.appointment_id = t.appointment_id
           LEFT JOIN paid p ON p.treatment_id = t.treatment_id
           WHERE date(a.appointment_datetime) <= ?""",
        (as_of, as_of),
    ).fetchall()
    as_of_day = date.fromisoformat(as_of)
    buckets = {label: {"bucket": label, "treatments_with_balance": 0, "outstanding_paise": 0}
               for label, _, _ in AGING_BUCKETS}
    billed = paid = with_balance = 0
    for treatment_day, net, paid_paise in rows:
        billed += net
        paid += paid_paise
        balance = net - paid_paise
        age = (as_of_day - date.fromisoformat(treatment_day)).days
        label = next(lbl for lbl, lo, hi in AGING_BUCKETS if age >= lo and (hi is None or age <= hi))
        buckets[label]["outstanding_paise"] += balance
        if balance > 0:
            with_balance += 1
            buckets[label]["treatments_with_balance"] += 1
    return {"billed_to_date_paise": billed, "paid_to_date_paise": paid, "outstanding_paise": billed - paid,
            "treatments_considered": len(rows), "treatments_with_balance": with_balance,
            "aging": list(buckets.values())}
