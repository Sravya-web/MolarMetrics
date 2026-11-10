"""Independent validation of a MolarMetrics SQLite database.

This module never imports the generator. It re-checks the documented data
rules directly against the finished database with SQL, so a bug in the
generator cannot "grade its own homework".

Each check reports:
    id, description, severity ("error" or "info"), passed, violations, examples

The overall status is PASS only when every "error" check passes.

Run on an existing database:
    python -m molarmetrics.data.validate            # prints a summary
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

from molarmetrics.data import catalog as C

EXPECTED_PATIENT_COLUMNS = ("patient_id", "birth_year", "gender", "locality", "registration_date")
_PK = {"patients": "patient_id", "dentists": "dentist_id", "appointments": "appointment_id",
       "treatments": "treatment_id", "payments": "payment_id"}


def _ids(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list:
    return [row[0] for row in conn.execute(sql, params).fetchall()]


def _in_list(values) -> str:
    return ", ".join("?" for _ in values)


def validate_database(db_path: Path | str) -> dict:
    """Run every check and return a machine-readable report (a dict)."""
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    checks: list[dict] = []

    def add(check_id: str, description: str, offenders: list, severity: str = "error") -> None:
        checks.append({
            "id": check_id, "description": description, "severity": severity,
            "passed": len(offenders) == 0, "violations": len(offenders),
            "examples": [str(x) for x in offenders[:5]],
        })

    def require(check_id: str, description: str, ok: bool, detail: str) -> None:
        checks.append({"id": check_id, "description": description, "severity": "error",
                       "passed": bool(ok), "violations": 0 if ok else 1, "examples": [] if ok else [detail],
                       "detail": detail})

    try:
        start, end = C.PERIOD_START.isoformat(), C.PERIOD_END.isoformat()

        # --- keys ------------------------------------------------------------------
        for table, pk in _PK.items():
            add(f"pk_unique_{table}", f"{table}.{pk} values are unique and not null",
                _ids(conn, f"SELECT {pk} FROM {table} GROUP BY {pk} HAVING COUNT(*) > 1")
                + _ids(conn, f"SELECT rowid FROM {table} WHERE {pk} IS NULL"))
        add("fk_integrity", "Every foreign key points at an existing parent row",
            [f"{r[0]} rowid {r[1]} -> {r[2]}" for r in conn.execute("PRAGMA foreign_key_check")])

        # --- patients & appointments ------------------------------------------------
        add("registration_on_or_before_first_appointment",
            "Each patient's registration_date is on or before their first appointment",
            _ids(conn, """SELECT p.patient_id FROM patients p
                          JOIN (SELECT patient_id, MIN(date(appointment_datetime)) AS first_day
                                FROM appointments GROUP BY patient_id) f USING (patient_id)
                          WHERE p.registration_date > f.first_day"""))
        add("patients_without_appointments", "Patients registered but never booked (informational)",
            _ids(conn, """SELECT patient_id FROM patients WHERE patient_id NOT IN
                          (SELECT patient_id FROM appointments)"""), severity="info")
        add("status_values_valid", "Appointment status is completed, cancelled or no_show",
            _ids(conn, f"SELECT appointment_id FROM appointments WHERE status NOT IN ({_in_list(C.ALLOWED_STATUSES)})",
                 C.ALLOWED_STATUSES))
        add("no_dentist_double_booking", "A dentist never has two appointments at the same date-time",
            _ids(conn, """SELECT dentist_id || ' @ ' || appointment_datetime FROM appointments
                          GROUP BY dentist_id, appointment_datetime HAVING COUNT(*) > 1"""))
        add("no_patient_double_booking", "A patient never has two appointments at the same date-time",
            _ids(conn, """SELECT patient_id || ' @ ' || appointment_datetime FROM appointments
                          GROUP BY patient_id, appointment_datetime HAVING COUNT(*) > 1"""))
        rows = conn.execute("SELECT appointment_id, dentist_id, date(appointment_datetime), "
                            "time(appointment_datetime) FROM appointments").fetchall()
        bad_day, bad_time = [], []
        for appt_id, dentist_id, day, clock in rows:
            y, m, d = (int(x) for x in day.split("-"))
            weekday = date(y, m, d).weekday()
            dentist = C.DENTIST_BY_ID.get(dentist_id)
            if dentist is None or weekday not in dentist.working_weekdays or (m, d) in C.FIXED_HOLIDAYS:
                bad_day.append(appt_id)
            if clock not in C.SLOT_TIMES:
                bad_time.append(appt_id)
        add("appointments_on_working_days", "Appointments fall on the dentist's working days (never Sundays/holidays)", bad_day)
        add("appointments_in_clinic_hours", "Appointment times are valid 30-minute clinic slots", bad_time)

        # --- dates within the observation period -------------------------------------
        add("dates_within_observation_period",
            f"All registration, appointment and payment dates are within {start}..{end}",
            _ids(conn, "SELECT patient_id FROM patients WHERE registration_date NOT BETWEEN ? AND ?", (start, end))
            + _ids(conn, "SELECT appointment_id FROM appointments WHERE date(appointment_datetime) NOT BETWEEN ? AND ?",
                   (start, end))
            + _ids(conn, "SELECT payment_id FROM payments WHERE payment_date NOT BETWEEN ? AND ?", (start, end)))

        # --- treatments ----------------------------------------------------------------
        add("treatments_only_on_completed_appointments", "Only completed appointments have treatment records",
            _ids(conn, """SELECT t.treatment_id FROM treatments t JOIN appointments a USING (appointment_id)
                          WHERE a.status <> 'completed'"""))
        add("procedure_names_in_catalog", "procedure_name is one of the documented procedures",
            _ids(conn, f"SELECT treatment_id FROM treatments WHERE procedure_name NOT IN ({_in_list(C.PROCEDURE_NAMES)})",
                 C.PROCEDURE_NAMES))
        add("money_is_integer_paise", "Fees and payments are stored as integer paise",
            _ids(conn, """SELECT treatment_id FROM treatments WHERE typeof(listed_fee_paise) <> 'integer'
                          OR typeof(discount_paise) <> 'integer' OR typeof(net_fee_paise) <> 'integer'""")
            + _ids(conn, "SELECT payment_id FROM payments WHERE typeof(amount_paise) <> 'integer'"))
        add("fees_non_negative", "Listed fee, discount and net fee are never negative",
            _ids(conn, """SELECT treatment_id FROM treatments
                          WHERE listed_fee_paise < 0 OR discount_paise < 0 OR net_fee_paise < 0"""))
        add("discount_not_above_listed_fee", "Discount never exceeds the listed fee",
            _ids(conn, "SELECT treatment_id FROM treatments WHERE discount_paise > listed_fee_paise"))
        add("net_fee_equals_listed_minus_discount", "net_fee = listed_fee - discount (exact, in paise)",
            _ids(conn, "SELECT treatment_id FROM treatments WHERE net_fee_paise <> listed_fee_paise - discount_paise"))
        out_of_range = []
        for name, proc in C.PROCEDURES.items():
            out_of_range += _ids(conn, """SELECT treatment_id FROM treatments WHERE procedure_name = ?
                                          AND listed_fee_paise NOT BETWEEN ? AND ?""",
                                 (name, proc.fee_min_inr * 100, proc.fee_max_inr * 100))
        add("listed_fees_within_documented_ranges", "Listed fees lie within the documented illustrative ranges",
            out_of_range)

        # --- teeth -------------------------------------------------------------------------
        add("tooth_numbers_valid_fdi", "Non-null tooth numbers are valid FDI codes (11-48, 51-85)",
            [r[0] for r in conn.execute("SELECT treatment_id, tooth_number FROM treatments WHERE tooth_number IS NOT NULL")
             if r[1] not in C.VALID_FDI_TEETH])
        tooth_specific = tuple(n for n, p in C.PROCEDURES.items() if p.tooth_specific)
        not_specific = tuple(n for n, p in C.PROCEDURES.items() if not p.tooth_specific)
        add("tooth_number_matches_procedure",
            "Tooth-specific procedures have a tooth number; other procedures have NULL",
            _ids(conn, f"""SELECT treatment_id FROM treatments
                           WHERE procedure_name IN ({_in_list(tooth_specific)}) AND tooth_number IS NULL""",
                 tooth_specific)
            + _ids(conn, f"""SELECT treatment_id FROM treatments
                             WHERE procedure_name IN ({_in_list(not_specific)}) AND tooth_number IS NOT NULL""",
                   not_specific))
        age_rows = conn.execute("""SELECT t.treatment_id, t.procedure_name, t.tooth_number,
                                          CAST(strftime('%Y', a.appointment_datetime) AS INTEGER) - p.birth_year
                                   FROM treatments t JOIN appointments a USING (appointment_id)
                                   JOIN patients p USING (patient_id)""").fetchall()
        bad_dentition, bad_proc_age = [], []
        for treat_id, name, tooth, age in age_rows:
            if tooth is not None:
                primary = tooth // 10 >= 5
                if (primary and age > C.MAX_AGE_PRIMARY_TEETH) or (not primary and age < C.MIN_AGE_PERMANENT_TEETH) \
                        or (tooth in C.THIRD_MOLARS and age < C.MIN_AGE_THIRD_MOLARS):
                    bad_dentition.append(treat_id)
            proc = C.PROCEDURES.get(name)
            if proc and not (proc.min_age <= age <= proc.max_age):
                bad_proc_age.append(treat_id)
        add("dentition_plausible_for_age",
            f"Primary teeth only up to age {C.MAX_AGE_PRIMARY_TEETH}; permanent teeth from age "
            f"{C.MIN_AGE_PERMANENT_TEETH}; third molars from age {C.MIN_AGE_THIRD_MOLARS}", bad_dentition)
        add("procedure_plausible_for_age", "Each procedure is within its documented plausible age range", bad_proc_age)

        # --- payments --------------------------------------------------------------------
        add("payment_amounts_positive", "Every payment amount is greater than zero",
            _ids(conn, "SELECT payment_id FROM payments WHERE amount_paise <= 0"))
        add("payment_methods_valid", "payment_method is one of the documented methods",
            _ids(conn, f"SELECT payment_id FROM payments WHERE payment_method NOT IN ({_in_list(C.PAYMENT_METHODS)})",
                 C.PAYMENT_METHODS))
        add("payments_not_exceeding_net_fee", "Total payments per treatment never exceed its net fee",
            _ids(conn, """SELECT t.treatment_id FROM treatments t
                          JOIN (SELECT treatment_id, SUM(amount_paise) AS paid FROM payments GROUP BY treatment_id) p
                          USING (treatment_id) WHERE p.paid > t.net_fee_paise"""))
        add("payment_not_before_treatment_date", "No payment is dated before its treatment's appointment date",
            _ids(conn, """SELECT p.payment_id FROM payments p JOIN treatments t USING (treatment_id)
                          JOIN appointments a USING (appointment_id)
                          WHERE p.payment_date < date(a.appointment_datetime)"""))

        # --- privacy -------------------------------------------------------------------------
        cols = tuple(r[1] for r in conn.execute("PRAGMA table_info(patients)"))
        add("no_direct_patient_identifiers",
            "patients table has only the documented non-identifying columns (no names, phones, emails, addresses)",
            [c for c in cols if c not in EXPECTED_PATIENT_COLUMNS])

        # --- required synthetic patterns are present -------------------------------------
        def scalar(sql: str) -> int:
            return int(conn.execute(sql).fetchone()[0] or 0)

        n_appts = scalar("SELECT COUNT(*) FROM appointments")
        require("pattern_appointment_volume", "Roughly 6,000 appointments (5,500-6,500)",
                5500 <= n_appts <= 6500, f"{n_appts} appointments")
        n_cancel = scalar("SELECT COUNT(*) FROM appointments WHERE status = 'cancelled'")
        n_noshow = scalar("SELECT COUNT(*) FROM appointments WHERE status = 'no_show'")
        require("pattern_cancellations_and_no_shows", "Some cancellations and no-shows exist",
                n_cancel > 0 and n_noshow > 0, f"{n_cancel} cancelled, {n_noshow} no-shows")
        n_repeat = scalar("""SELECT COUNT(*) FROM (SELECT patient_id FROM appointments WHERE status = 'completed'
                             GROUP BY patient_id HAVING COUNT(*) > 1)""")
        require("pattern_repeat_visits", "Some patients have more than one completed visit",
                n_repeat > 0, f"{n_repeat} patients with repeat completed visits")
        n_multi = scalar("""SELECT COUNT(*) FROM (SELECT appointment_id FROM treatments
                            GROUP BY appointment_id HAVING COUNT(*) > 1)""")
        require("pattern_multiple_treatments_per_visit", "Some completed appointments have several treatment records",
                n_multi > 0, f"{n_multi} appointments with 2+ treatments")
        n_split = scalar("""SELECT COUNT(*) FROM (SELECT treatment_id FROM payments
                            GROUP BY treatment_id HAVING COUNT(*) > 1)""")
        require("pattern_split_payments", "Some treatments are paid in several transactions",
                n_split > 0, f"{n_split} treatments with 2+ payments")
        n_partial = scalar("""SELECT COUNT(*) FROM treatments t
                              JOIN (SELECT treatment_id, SUM(amount_paise) AS paid FROM payments GROUP BY treatment_id) p
                              USING (treatment_id) WHERE p.paid < t.net_fee_paise""")
        require("pattern_partially_paid_treatments", "Some treatments are only partially paid",
                n_partial > 0, f"{n_partial} partially paid treatments")
        n_null_tooth = scalar("SELECT COUNT(*) FROM treatments WHERE tooth_number IS NULL")
        require("pattern_null_tooth_numbers", "Non-tooth-specific procedures have NULL tooth numbers",
                n_null_tooth > 0, f"{n_null_tooth} treatments with NULL tooth_number")

        stats = {
            "appointments_by_status": dict(conn.execute(
                "SELECT status, COUNT(*) FROM appointments GROUP BY status ORDER BY status").fetchall()),
            "completed_visits_without_treatment_records": scalar(
                """SELECT COUNT(*) FROM appointments WHERE status = 'completed'
                   AND appointment_id NOT IN (SELECT appointment_id FROM treatments)"""),
            "appointments_with_multiple_treatments": n_multi,
            "treatments_with_split_payments": n_split,
            "treatments_partially_paid": n_partial,
            "treatments_unpaid": scalar("""SELECT COUNT(*) FROM treatments WHERE net_fee_paise > 0
                                           AND treatment_id NOT IN (SELECT treatment_id FROM payments)"""),
            "treatments_with_zero_net_fee": scalar("SELECT COUNT(*) FROM treatments WHERE net_fee_paise = 0"),
            "total_net_fees_paise": scalar("SELECT SUM(net_fee_paise) FROM treatments"),
            "total_payments_paise": scalar("SELECT SUM(amount_paise) FROM payments"),
        }
    finally:
        conn.close()

    errors = [c for c in checks if c["severity"] == "error"]
    failed = [c for c in errors if not c["passed"]]
    return {
        "summary": {
            "status": "PASS" if not failed else "FAIL",
            "checks_total": len(errors),
            "checks_passed": len(errors) - len(failed),
            "checks_failed": len(failed),
            "failed_check_ids": [c["id"] for c in failed],
            "informational_checks": len(checks) - len(errors),
        },
        "observation_period": {"start": C.PERIOD_START.isoformat(), "end": C.PERIOD_END.isoformat()},
        "statistics": stats,
        "checks": checks,
    }


def main() -> int:
    from molarmetrics.config import get_settings

    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else get_settings().db_path
    if not db_path.exists():
        print(f"Database not found: {db_path}. Generate it with: python -m molarmetrics.data.generate")
        return 1
    report = validate_database(db_path)
    for check in report["checks"]:
        mark = "PASS" if check["passed"] else ("INFO" if check["severity"] == "info" else "FAIL")
        print(f"[{mark}] {check['id']}: {check['violations']} violation(s)")
    print(json.dumps(report["summary"], indent=2))
    return 0 if report["summary"]["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
