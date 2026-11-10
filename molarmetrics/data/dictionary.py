"""The MolarMetrics data dictionary (single source of truth).

The same definitions feed:
* data/molarmetrics_data_dictionary.md   (human-readable)
* data/molarmetrics_data_dictionary.csv  (shown in the Data Explorer tab)
"""

from __future__ import annotations

import csv
from pathlib import Path

from molarmetrics import APP_NAME, DATA_NOTICE
from molarmetrics.data import catalog as C

TABLE_DESCRIPTIONS: dict[str, str] = {
    "patients": "One row per fictional patient. No names, phone numbers, emails or addresses are generated.",
    "dentists": "One row per fictional dentist (8 in total).",
    "appointments": "One row per booked appointment, whatever its outcome (completed, cancelled or no-show).",
    "treatments": ("One row per billed procedure line item recorded at a COMPLETED appointment. "
                   "A visit can have several rows; some completed visits (reviews, try-ins) have none."),
    "payments": "One row per payment transaction against one treatment. A treatment can have 0-3 payments.",
}

# (table, column, type, description)
COLUMNS: list[tuple[str, str, str, str]] = [
    ("patients", "patient_id", "TEXT (PK)", "Patient identifier, e.g. P0001 (ordered by registration date)."),
    ("patients", "birth_year", "INTEGER", "Year of birth. Age at a visit is approximated as visit year - birth_year."),
    ("patients", "gender", "TEXT", "Female, Male or Other."),
    ("patients", "locality", "TEXT", "Invented locality label (not a real address)."),
    ("patients", "registration_date", "DATE (YYYY-MM-DD)", "Date registered; always on or before the first appointment."),
    ("dentists", "dentist_id", "TEXT (PK)", "Dentist identifier, D01-D08."),
    ("dentists", "fictional_display_name", "TEXT", "Invented display name. Any resemblance to a real person is coincidental."),
    ("dentists", "specialty", "TEXT", "Clinical specialty label used only to make procedure assignment plausible."),
    ("appointments", "appointment_id", "TEXT (PK)", "Appointment identifier, e.g. A00001 (chronological)."),
    ("appointments", "patient_id", "TEXT (FK)", "References patients.patient_id."),
    ("appointments", "dentist_id", "TEXT (FK)", "References dentists.dentist_id."),
    ("appointments", "appointment_datetime", "DATETIME (YYYY-MM-DD HH:MM:SS)",
     "Booked slot (30-minute slots, 10:00-13:30 and 17:00-20:30; closed Sundays and 26 Jan, 15 Aug, 2 Oct)."),
    ("appointments", "status", "TEXT", "completed, cancelled or no_show."),
    ("appointments", "visit_reason", "TEXT", "Reason recorded when booking (free-text style label)."),
    ("treatments", "treatment_id", "TEXT (PK)", "Treatment line-item identifier, e.g. T00001."),
    ("treatments", "appointment_id", "TEXT (FK)", "References a COMPLETED appointment. Treatment date = appointment date."),
    ("treatments", "procedure_name", "TEXT", "Procedure performed; see the procedure table below for what one row means."),
    ("treatments", "tooth_number", "INTEGER or NULL",
     "FDI two-digit tooth code (11-48 permanent, 51-85 primary). NULL for non-tooth-specific procedures."),
    ("treatments", "listed_fee_inr", "DECIMAL (INR)", "Listed fee in rupees (derived from listed_fee_paise)."),
    ("treatments", "discount_inr", "DECIMAL (INR)", "Discount in rupees; never exceeds the listed fee."),
    ("treatments", "net_fee_inr", "DECIMAL (INR)", "Net fee = listed fee - discount. This is the 'billed' amount."),
    ("treatments", "listed_fee_paise", "INTEGER", "Authoritative listed fee in paise (1 INR = 100 paise)."),
    ("treatments", "discount_paise", "INTEGER", "Authoritative discount in paise."),
    ("treatments", "net_fee_paise", "INTEGER", "Authoritative net fee in paise. Analytics sum this column."),
    ("payments", "payment_id", "TEXT (PK)", "Payment identifier, e.g. PM00001 (chronological)."),
    ("payments", "treatment_id", "TEXT (FK)", "References treatments.treatment_id."),
    ("payments", "payment_date", "DATE (YYYY-MM-DD)", "Date received; never before the treatment date."),
    ("payments", "amount_inr", "DECIMAL (INR)", "Amount in rupees (derived from amount_paise)."),
    ("payments", "payment_method", "TEXT", "UPI, Cash, Card or Net banking."),
    ("payments", "amount_paise", "INTEGER", "Authoritative amount in paise. Analytics sum this column."),
]


def dictionary_rows() -> list[dict]:
    return [{"table": t, "column": c, "type": ty, "description": d} for t, c, ty, d in COLUMNS]


def render_markdown() -> str:
    lines = [
        f"# {APP_NAME} data dictionary",
        "",
        f"> **{DATA_NOTICE}.** Every record describes a fictional Indian dental clinic. Fees, patterns and",
        "> names are invented demo assumptions. They are not verified prices or evidence about real clinics.",
        "",
        f"Observation period: **{C.PERIOD_START.isoformat()} to {C.PERIOD_END.isoformat()}**. Currency: **INR**.",
        "Money is stored as integer **paise** (exact arithmetic); `*_inr` columns are derived for display/CSV.",
        "",
    ]
    for table, description in TABLE_DESCRIPTIONS.items():
        lines += [f"## `{table}`", "", description, "", "| Column | Type | Description |", "|---|---|---|"]
        lines += [f"| `{c}` | {ty} | {d} |" for t, c, ty, d in COLUMNS if t == table]
        lines.append("")
    lines += [
        "## Procedures: what ONE treatment record represents",
        "",
        "| Procedure | One record represents | Tooth-specific | Illustrative listed fee (INR) | Plausible age |",
        "|---|---|---|---|---|",
    ]
    for p in C.PROCEDURES.values():
        lines.append(f"| {p.name} | {p.record_represents} | {'yes' if p.tooth_specific else 'no (NULL)'} | "
                     f"{p.fee_min_inr:,}-{p.fee_max_inr:,} | {p.min_age}-{p.max_age} |")
    lines += [
        "",
        "Extraction fees: 800-2,500 for simple extractions, 3,000-6,000 for surgical wisdom-tooth removal.",
        "Counting treatment records counts **line items**, not patients or completed treatment courses.",
        "",
        "## Dentists (fictional)",
        "",
        "| ID | Display name | Specialty | Works (Mon=0 ... Sat=5) |",
        "|---|---|---|---|",
    ]
    days = "Mon Tue Wed Thu Fri Sat".split()
    for d in C.DENTISTS:
        lines.append(f"| {d.dentist_id} | {d.fictional_display_name} | {d.specialty} | "
                     f"{', '.join(days[i] for i in d.working_weekdays)} |")
    lines += [
        "",
        "## Synthetic patterns (invented, modest, documented)",
        "",
        f"* About {C.ESTABLISHED_PATIENT_SHARE:.0%} of patients are *established*: already known to the clinic and registered "
        "at their first visit after records began (mostly early 2024). The rest are new patients spread over both years.",
        "* New-patient first visits are weighted by month (a little busier Jan/May-Jun/Dec), and some elective first "
        "visits are postponed during the monsoon (Jul-Sep) and the November festival season.",
        "* No-show probability is higher in the monsoon months (about 9-10.5%) than in Jan-Feb (6%). Cancellations "
        "are about 8%, rising to 11% in November. About 72% of missed visits are rebooked.",
        "* Seniors (60+) are more often given a 10% discount; ~3% of consultation fees are waived (net fee 0).",
        "* Most low-fee treatments are paid in full on the day. High-fee treatments (5,000+ INR) are often paid in "
        "2-3 instalments. Some are only partially paid, and a few are unpaid. Instalments due after 31 Dec 2025 are "
        "outside the data, so they appear as outstanding.",
        "",
        "## Known limitations",
        "",
        "* No clinical outcome, diagnosis, imaging or quality data exists. The data cannot say which treatment "
        "\"works best\" or which dentist is \"better\".",
        "* Ages are approximate (visit year - birth year). Tooth history is only partly tracked (extracted teeth are "
        "not reused).",
        "* Payments are linked to individual treatments, a simplification of real invoicing.",
    ]
    return "\n".join(lines) + "\n"


def write_data_dictionary(md_path: Path, csv_path: Path) -> None:
    md_path.write_text(render_markdown(), encoding="utf-8")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["table", "column", "type", "description"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(dictionary_rows())
