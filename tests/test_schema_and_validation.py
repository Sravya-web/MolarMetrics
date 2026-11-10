"""The database rejects bad rows, and the independent validator catches rule breaks."""

import sqlite3

import pytest

from molarmetrics.data.validate import validate_database
from tests.fixtures.mini_clinic import build_mini_clinic


def _conn(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@pytest.mark.parametrize("sql", [
    # foreign keys
    "INSERT INTO appointments VALUES ('AX','P_UNKNOWN','D01','2025-01-02 10:00:00','completed','x')",
    "INSERT INTO treatments (treatment_id, appointment_id, procedure_name, tooth_number, listed_fee_paise, "
    "discount_paise, net_fee_paise) VALUES ('TX','A_UNKNOWN','Consultation',NULL,100,0,100)",
    # primary key
    "INSERT INTO patients VALUES ('P1',1990,'Male','Test','2025-01-01')",
    # allowed values and money rules
    "INSERT INTO appointments VALUES ('AX','P1','D01','2025-01-02 10:00:00','rescheduled','x')",
    "INSERT INTO treatments (treatment_id, appointment_id, procedure_name, tooth_number, listed_fee_paise, "
    "discount_paise, net_fee_paise) VALUES ('TX','A2','Consultation',NULL,-100,0,-100)",
    "INSERT INTO treatments (treatment_id, appointment_id, procedure_name, tooth_number, listed_fee_paise, "
    "discount_paise, net_fee_paise) VALUES ('TX','A2','Consultation',NULL,100,200,-100)",
    "INSERT INTO treatments (treatment_id, appointment_id, procedure_name, tooth_number, listed_fee_paise, "
    "discount_paise, net_fee_paise) VALUES ('TX','A2','Consultation',NULL,100,10,95)",
    "INSERT INTO treatments (treatment_id, appointment_id, procedure_name, tooth_number, listed_fee_paise, "
    "discount_paise, net_fee_paise) VALUES ('TX','A2','Extraction',19,100,0,100)",  # 19 is not FDI
    "INSERT INTO treatments (treatment_id, appointment_id, procedure_name, tooth_number, listed_fee_paise, "
    "discount_paise, net_fee_paise) VALUES ('TX','A2','Teeth whitening',NULL,100,0,100)",
    "INSERT INTO payments (payment_id, treatment_id, payment_date, amount_paise, payment_method) "
    "VALUES ('PX','T9','2025-03-01',0,'Cash')",  # zero payment
    # double booking (unique indexes)
    "INSERT INTO appointments VALUES ('AX','P3','D01','2025-01-06 10:00:00','completed','x')",
    # cross-table rules (triggers)
    "INSERT INTO treatments (treatment_id, appointment_id, procedure_name, tooth_number, listed_fee_paise, "
    "discount_paise, net_fee_paise) VALUES ('TX','A4','Consultation',NULL,100,0,100)",  # A4 is a no-show
    "INSERT INTO payments (payment_id, treatment_id, payment_date, amount_paise, payment_method) "
    "VALUES ('PX','T9','2025-02-27',100,'Cash')",  # before T9's treatment date (2025-02-28)
    "INSERT INTO payments (payment_id, treatment_id, payment_date, amount_paise, payment_method) "
    "VALUES ('PX','T9','2025-03-01',50001,'Cash')",  # more than T9's net fee of 50000
])
def test_database_rejects_invalid_rows(mini_db, sql):
    conn = _conn(mini_db)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql)
    conn.close()


def test_validator_passes_the_clean_fixture(tmp_path):
    report = validate_database(build_mini_clinic(tmp_path / "clean.db"))
    rule_checks = [c for c in report["checks"] if not c["id"].startswith("pattern_")
                   and c["severity"] == "error" and c["id"] != "dates_within_observation_period"]
    assert all(c["passed"] for c in rule_checks), [c["id"] for c in rule_checks if not c["passed"]]


def test_validator_catches_rule_breaks_independently(tmp_path):
    """With triggers disabled, bad rows get in; the validator must still find them."""
    db = build_mini_clinic(tmp_path / "broken.db", with_triggers=False)
    conn = _conn(db)
    with conn:
        conn.execute("INSERT INTO treatments (treatment_id, appointment_id, procedure_name, tooth_number, "
                     "listed_fee_paise, discount_paise, net_fee_paise) "
                     "VALUES ('TBAD','A4','Consultation',NULL,100,0,100)")  # on a no-show
        conn.execute("INSERT INTO payments VALUES ('PBAD1','T9','2025-02-27',100,'Cash')")  # too early
        conn.execute("INSERT INTO payments VALUES ('PBAD2','T6','2025-03-01',400000,'Cash')")  # overpaid
        conn.execute("UPDATE patients SET registration_date = '2025-03-01' WHERE patient_id = 'P2'")
        conn.execute("UPDATE treatments SET tooth_number = 55 WHERE treatment_id = 'T8'")  # baby tooth, adult
    conn.close()
    failed = {c["id"] for c in validate_database(db)["checks"] if not c["passed"]}
    assert {"treatments_only_on_completed_appointments", "payment_not_before_treatment_date",
            "payments_not_exceeding_net_fee", "registration_on_or_before_first_appointment",
            "dentition_plausible_for_age"} <= failed


def test_main_dataset_validation_report_passes(real_db_path):
    report = validate_database(real_db_path)
    assert report["summary"]["status"] == "PASS", report["summary"]["failed_check_ids"]
