# MolarMetrics data dictionary

> **SYNTHETIC DEMO DATA.** Every record describes a fictional Indian dental clinic. Fees, patterns and
> names are invented demo assumptions. They are not verified prices or evidence about real clinics.

Observation period: **2024-01-01 to 2025-12-31**. Currency: **INR**.
Money is stored as integer **paise** (exact arithmetic); `*_inr` columns are derived for display/CSV.

## `patients`

One row per fictional patient. No names, phone numbers, emails or addresses are generated.

| Column | Type | Description |
|---|---|---|
| `patient_id` | TEXT (PK) | Patient identifier, e.g. P0001 (ordered by registration date). |
| `birth_year` | INTEGER | Year of birth. Age at a visit is approximated as visit year - birth_year. |
| `gender` | TEXT | Female, Male or Other. |
| `locality` | TEXT | Invented locality label (not a real address). |
| `registration_date` | DATE (YYYY-MM-DD) | Date registered; always on or before the first appointment. |

## `dentists`

One row per fictional dentist (8 in total).

| Column | Type | Description |
|---|---|---|
| `dentist_id` | TEXT (PK) | Dentist identifier, D01-D08. |
| `fictional_display_name` | TEXT | Invented display name. Any resemblance to a real person is coincidental. |
| `specialty` | TEXT | Clinical specialty label used only to make procedure assignment plausible. |

## `appointments`

One row per booked appointment, whatever its outcome (completed, cancelled or no-show).

| Column | Type | Description |
|---|---|---|
| `appointment_id` | TEXT (PK) | Appointment identifier, e.g. A00001 (chronological). |
| `patient_id` | TEXT (FK) | References patients.patient_id. |
| `dentist_id` | TEXT (FK) | References dentists.dentist_id. |
| `appointment_datetime` | DATETIME (YYYY-MM-DD HH:MM:SS) | Booked slot (30-minute slots, 10:00-13:30 and 17:00-20:30; closed Sundays and 26 Jan, 15 Aug, 2 Oct). |
| `status` | TEXT | completed, cancelled or no_show. |
| `visit_reason` | TEXT | Reason recorded when booking (free-text style label). |

## `treatments`

One row per billed procedure line item recorded at a COMPLETED appointment. A visit can have several rows; some completed visits (reviews, try-ins) have none.

| Column | Type | Description |
|---|---|---|
| `treatment_id` | TEXT (PK) | Treatment line-item identifier, e.g. T00001. |
| `appointment_id` | TEXT (FK) | References a COMPLETED appointment. Treatment date = appointment date. |
| `procedure_name` | TEXT | Procedure performed; see the procedure table below for what one row means. |
| `tooth_number` | INTEGER or NULL | FDI two-digit tooth code (11-48 permanent, 51-85 primary). NULL for non-tooth-specific procedures. |
| `listed_fee_inr` | DECIMAL (INR) | Listed fee in rupees (derived from listed_fee_paise). |
| `discount_inr` | DECIMAL (INR) | Discount in rupees; never exceeds the listed fee. |
| `net_fee_inr` | DECIMAL (INR) | Net fee = listed fee - discount. This is the 'billed' amount. |
| `listed_fee_paise` | INTEGER | Authoritative listed fee in paise (1 INR = 100 paise). |
| `discount_paise` | INTEGER | Authoritative discount in paise. |
| `net_fee_paise` | INTEGER | Authoritative net fee in paise. Analytics sum this column. |

## `payments`

One row per payment transaction against one treatment. A treatment can have 0-3 payments.

| Column | Type | Description |
|---|---|---|
| `payment_id` | TEXT (PK) | Payment identifier, e.g. PM00001 (chronological). |
| `treatment_id` | TEXT (FK) | References treatments.treatment_id. |
| `payment_date` | DATE (YYYY-MM-DD) | Date received; never before the treatment date. |
| `amount_inr` | DECIMAL (INR) | Amount in rupees (derived from amount_paise). |
| `payment_method` | TEXT | UPI, Cash, Card or Net banking. |
| `amount_paise` | INTEGER | Authoritative amount in paise. Analytics sum this column. |

## Procedures: what ONE treatment record represents

| Procedure | One record represents | Tooth-specific | Illustrative listed fee (INR) | Plausible age |
|---|---|---|---|---|
| Consultation | One examination/consultation at a visit. | no (NULL) | 300-700 | 2-95 |
| Scaling | One full-mouth scaling and polishing session. | no (NULL) | 1,000-2,500 | 12-95 |
| Composite filling | One tooth restored with composite at one visit. | yes | 1,200-3,000 | 3-95 |
| Root canal treatment (session) | ONE root canal treatment session on one tooth. A full root canal course often spans 1-3 sessions, so counts are sessions, not teeth or completed courses. | yes | 2,000-4,000 | 10-95 |
| Extraction | One tooth extracted (simple or surgical). | yes | 800-6,000 | 3-95 |
| Crown placement | One crown fitted on one tooth. Earlier preparation visits are included in this fee. | yes | 6,000-14,000 | 16-95 |
| Denture provision | One complete or partial denture delivered. Impression and try-in visits are included in this fee. | no (NULL) | 12,000-35,000 | 40-95 |
| Orthodontic review | One orthodontic review/adjustment visit. It is NOT the cost of a whole orthodontic course. | no (NULL) | 1,000-2,000 | 9-40 |
| Implant placement | Surgical placement of one implant fixture. The later implant crown is not modelled. | yes | 28,000-45,000 | 21-85 |
| Fluoride application | One topical fluoride application for a child. | no (NULL) | 500-1,000 | 2-16 |

Extraction fees: 800-2,500 for simple extractions, 3,000-6,000 for surgical wisdom-tooth removal.
Counting treatment records counts **line items**, not patients or completed treatment courses.

## Dentists (fictional)

| ID | Display name | Specialty | Works (Mon=0 ... Sat=5) |
|---|---|---|---|
| D01 | Dr. Kavya M. | General dentistry | Mon, Tue, Wed, Thu, Fri, Sat |
| D02 | Dr. Arjun B. | General dentistry | Mon, Tue, Wed, Thu, Fri, Sat |
| D03 | Dr. Nisha K. | Endodontics | Mon, Tue, Thu, Fri, Sat |
| D04 | Dr. Rohan I. | Orthodontics | Tue, Thu, Sat |
| D05 | Dr. Farah S. | Periodontics | Mon, Wed, Fri |
| D06 | Dr. Vikram T. | Prosthodontics | Tue, Wed, Fri, Sat |
| D07 | Dr. Meera P. | Oral and maxillofacial surgery | Mon, Wed, Sat |
| D08 | Dr. Sameer J. | Paediatric dentistry | Tue, Thu, Fri, Sat |

## Synthetic patterns (invented, modest, documented)

* About 50% of patients are *established*: already known to the clinic and registered at their first visit after records began (mostly early 2024). The rest are new patients spread over both years.
* New-patient first visits are weighted by month (a little busier Jan/May-Jun/Dec), and some elective first visits are postponed during the monsoon (Jul-Sep) and the November festival season.
* No-show probability is higher in the monsoon months (about 9-10.5%) than in Jan-Feb (6%). Cancellations are about 8%, rising to 11% in November. About 72% of missed visits are rebooked.
* Seniors (60+) are more often given a 10% discount; ~3% of consultation fees are waived (net fee 0).
* Most low-fee treatments are paid in full on the day. High-fee treatments (5,000+ INR) are often paid in 2-3 instalments. Some are only partially paid, and a few are unpaid. Instalments due after 31 Dec 2025 are outside the data, so they appear as outstanding.

## Known limitations

* No clinical outcome, diagnosis, imaging or quality data exists. The data cannot say which treatment "works best" or which dentist is "better".
* Ages are approximate (visit year - birth year). Tooth history is only partly tracked (extracted teeth are not reused).
* Payments are linked to individual treatments, a simplification of real invoicing.
