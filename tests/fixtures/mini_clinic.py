"""A tiny hand-checked clinic for financial and metric tests.

This fixture is SEPARATE from the main synthetic dataset. Every expected value
below was calculated by hand from these rows (not by running MolarMetrics
code), so the tests check the implementation against independent arithmetic.

Appointments (window W = 2025-01-01 .. 2025-02-28 unless stated)
------------------------------------------------------------------
A1  P1 D01 2024-12-10 10:00 completed   <- history BEFORE the window
A2  P1 D01 2025-01-06 10:00 completed   (P1 returning: earlier visit A1)
A3  P2 D02 2025-01-15 11:00 completed   (P2 first-ever completed visit)
A4  P2 D02 2025-01-20 11:00 no_show
A5  P3 D01 2025-01-31 17:00 cancelled
A6  P2 D02 2025-02-03 10:00 completed   (P2 returning: earlier visit A3)
A7  P4 D01 2025-02-10 10:00 no_show
A8  P3 D01 2025-02-14 10:00 completed   (P3 first completed; A5 was cancelled)
A9  P4 D02 2025-02-28 18:00 completed   (P4 first completed; A7 was a no-show)
A10 P1 D02 2025-02-20 10:00 cancelled

W: scheduled 9 = completed 5 + cancelled 2 + no-show 2 -> no-show rate 2/9 = 22.2%
   Jan: 4 scheduled (2 completed, 1 cancelled, 1 no-show) -> 25.0%
   Feb: 5 scheduled (3 completed, 1 cancelled, 1 no-show) -> 20.0%
   unique patients seen 4 (P1-P4); returning patients 2 (P1, P2)
   by dentist: D01 4 scheduled / 2 completed; D02 5 scheduled / 3 completed

Treatments (net = listed - discount, in paise)
-----------------------------------------------
T1 A1 Consultation           listed  50000 disc     0 net  50000  (Dec 2024)
T2 A1 Composite filling #36  listed 200000 disc     0 net 200000  (Dec 2024)
T3 A2 Scaling                listed 150000 disc 15000 net 135000  (Jan)
T4 A3 Consultation (waived)  listed  40000 disc 40000 net      0  (Jan)
T5 A3 Root canal #46         listed 350050 disc    50 net 350000  (Jan) <- paise
T6 A6 Root canal #46         listed 350000 disc     0 net 350000  (Feb)
T7 A6 Crown #46              listed 1000000 disc 100000 net 900000 (Feb), 3 payments
T8 A8 Extraction #48         listed 250000 disc     0 net 250000  (Feb)
T9 A9 Consultation           listed  50000 disc     0 net  50000  (Feb)

Billed W   = 135000+0+350000+350000+900000+250000+50000 = 2,035,000 (Rs 20,350.00)
Billed Jan = 135000+0+350000 = 485,000; Billed Feb = 350000+900000+250000+50000 = 1,550,000

Payments
--------
PM1  T1 2024-12-10  50000     PM6  T5 2025-02-20 100000
PM2  T2 2024-12-10 100000     PM7  T7 2025-02-03 300000
PM3  T2 2025-01-08 100000     PM8  T7 2025-02-25 300000
PM4  T3 2025-01-06 135000     PM9  T7 2025-03-10 300000  <- after the window
PM5  T5 2025-01-15 150000     PM10 T8 2025-02-14 250000
(T4 waived: no payment. T6 and T9 unpaid.)

Collections W   = 100000+135000+150000+100000+300000+300000+250000 = 1,335,000
Collections Jan = 100000+135000+150000 = 385,000 (includes PM3 for a DECEMBER treatment)
Collections Feb = 100000+300000+300000+250000 = 950,000

Outstanding balance
-------------------
as of 2024-12-09: 0 (no treatments yet)
as of 2024-12-10: net 250000 - paid 150000 = 100,000 (T2 half paid)
as of 2025-01-31: net 735000 - paid 535000 = 200,000 (T5: 350000 - 150000); 1 treatment
as of 2025-02-28: net 2285000 - paid 1485000 = 800,000 (T5 100000, T6 350000, T7 300000, T9 50000); 4 treatments
    aging: 0-30 days 700,000 (T6, T7, T9); 31-90 days 100,000 (T5, 44 days)
as of 2025-03-31: net 2285000 - paid 1785000 = 500,000 (T5, T6, T9); 3 treatments
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from molarmetrics.data.schema import create_schema, insert_rows

PATIENTS = [
    {"patient_id": "P1", "birth_year": 1980, "gender": "Female", "locality": "Test Locality", "registration_date": "2024-12-01"},
    {"patient_id": "P2", "birth_year": 1975, "gender": "Male", "locality": "Test Locality", "registration_date": "2025-01-10"},
    {"patient_id": "P3", "birth_year": 1990, "gender": "Female", "locality": "Test Locality", "registration_date": "2025-01-25"},
    {"patient_id": "P4", "birth_year": 2000, "gender": "Other", "locality": "Test Locality", "registration_date": "2025-02-01"},
]
DENTISTS = [
    {"dentist_id": "D01", "fictional_display_name": "Dr. Test A.", "specialty": "General dentistry"},
    {"dentist_id": "D02", "fictional_display_name": "Dr. Test B.", "specialty": "Endodontics"},
]
_A = [
    ("A1", "P1", "D01", "2024-12-10 10:00:00", "completed"),
    ("A2", "P1", "D01", "2025-01-06 10:00:00", "completed"),
    ("A3", "P2", "D02", "2025-01-15 11:00:00", "completed"),
    ("A4", "P2", "D02", "2025-01-20 11:00:00", "no_show"),
    ("A5", "P3", "D01", "2025-01-31 17:00:00", "cancelled"),
    ("A6", "P2", "D02", "2025-02-03 10:00:00", "completed"),
    ("A7", "P4", "D01", "2025-02-10 10:00:00", "no_show"),
    ("A8", "P3", "D01", "2025-02-14 10:00:00", "completed"),
    ("A9", "P4", "D02", "2025-02-28 18:00:00", "completed"),
    ("A10", "P1", "D02", "2025-02-20 10:00:00", "cancelled"),
]
APPOINTMENTS = [{"appointment_id": a, "patient_id": p, "dentist_id": d, "appointment_datetime": dt,
                 "status": s, "visit_reason": "Fixture visit"} for a, p, d, dt, s in _A]
_T = [
    ("T1", "A1", "Consultation", None, 50000, 0),
    ("T2", "A1", "Composite filling", 36, 200000, 0),
    ("T3", "A2", "Scaling", None, 150000, 15000),
    ("T4", "A3", "Consultation", None, 40000, 40000),
    ("T5", "A3", "Root canal treatment (session)", 46, 350050, 50),
    ("T6", "A6", "Root canal treatment (session)", 46, 350000, 0),
    ("T7", "A6", "Crown placement", 46, 1000000, 100000),
    ("T8", "A8", "Extraction", 48, 250000, 0),
    ("T9", "A9", "Consultation", None, 50000, 0),
]
TREATMENTS = [{"treatment_id": t, "appointment_id": a, "procedure_name": n, "tooth_number": tooth,
               "listed_fee_paise": listed, "discount_paise": disc, "net_fee_paise": listed - disc}
              for t, a, n, tooth, listed, disc in _T]
_P = [
    ("PM1", "T1", "2024-12-10", 50000, "Cash"),
    ("PM2", "T2", "2024-12-10", 100000, "UPI"),
    ("PM3", "T2", "2025-01-08", 100000, "UPI"),
    ("PM4", "T3", "2025-01-06", 135000, "Card"),
    ("PM5", "T5", "2025-01-15", 150000, "UPI"),
    ("PM6", "T5", "2025-02-20", 100000, "Cash"),
    ("PM7", "T7", "2025-02-03", 300000, "Card"),
    ("PM8", "T7", "2025-02-25", 300000, "Card"),
    ("PM9", "T7", "2025-03-10", 300000, "UPI"),
    ("PM10", "T8", "2025-02-14", 250000, "Cash"),
]
PAYMENTS = [{"payment_id": p, "treatment_id": t, "payment_date": d, "amount_paise": amt, "payment_method": m}
            for p, t, d, amt, m in _P]


def build_mini_clinic(db_path: Path, with_triggers: bool = True) -> Path:
    conn = sqlite3.connect(db_path)
    try:
        create_schema(conn, with_triggers=with_triggers)
        with conn:
            for table, rows in (("patients", PATIENTS), ("dentists", DENTISTS), ("appointments", APPOINTMENTS),
                                ("treatments", TREATMENTS), ("payments", PAYMENTS)):
                insert_rows(conn, table, rows)
    finally:
        conn.close()
    return db_path
