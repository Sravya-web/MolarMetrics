# Example upload bundles

Two small, fictional clinics for trying the upload flow and for tests. Every expected figure below
was calculated by hand from the rows in these files. The automated tests (`tests/web/`) assert these
literal values; they are not outputs of MolarMetrics code.

All people, codes and amounts are invented.

---

## `sunrise-dental/` (5 files)

The downloadable **example bundle** in the app. It shows common real-world formats:

| What | In the files | What you confirm on the review screen |
|---|---|---|
| Dates | `06/01/2025` style, and every day is 12 or less | The date format is ambiguous (6 Jan or 1 Jun?), so you choose **DD/MM/YYYY** for each date column |
| Money | `₹1,800.00`, `1,800.00` and `1800`, headers end in `(Rs)` | You confirm the amounts are in **rupees** |
| Statuses | `Attended`, `Cancelled`, `DNA` | Suggested as completed, cancelled, no-show |
| Headers | `Appt ID`, `Patient Code`, `Visit Date`, `Line ID`, `Receipt No`… | Suggested mappings |

**Coverage:** 6 Jan 2025 to 12 Mar 2025 (first and last appointment or payment date).

### Appointments (16)

| Month | Scheduled | Completed | Cancelled | No-show |
|---|---|---|---|---|
| Jan 2025 | 5 (SA01–SA05) | 4 | 0 | 1 (SA03) |
| Feb 2025 | 5 (SA06–SA10) | 3 | 1 (SA07) | 1 (SA09) |
| Mar 2025 | 6 (SA11–SA16) | 4 | 1 (SA13) | 1 (SA16) |
| **Total** | **16** | **11** | **2** | **3** |

* No-show rate = 3 ÷ 16 = 18.75% → **18.8%** (rounded half up).
* Unique patients seen (at least one completed visit): S-P01…S-P08 = **8**.
* Returning patients (a completed visit after an earlier completed visit): S-P01 (SA10 after SA01),
  S-P02 (SA06 after SA02), S-P04 (SA14 after SA04) = **3**.
* Completed visits by dentist: S-D1 Dr. Meera Nair 5, S-D2 Dr. Karan Shah 4, S-D3 Dr. Leela Pillai 2.

### Treatments (16) — billed revenue = net fee = listed fee − discount

| Month | Lines | Net fees |
|---|---|---|
| Jan | ST01 500 + ST02 1,800 + ST03 (4,500 − 500) 4,000 + ST04 2,200 + ST05 (500 − 500) 0 + ST06 1,500 | **₹10,000.00** |
| Feb | ST07 (4,500 − 500) 4,000 + ST08 (12,000 − 1,000) 11,000 + ST09 1,200 + ST10 1,800 | **₹18,000.00** |
| Mar | ST11 500 + ST12 (2,200 − 200) 2,000 + ST13 1,500 + ST14 12,000 + ST15 1,200 + ST16 1,800 | **₹19,000.00** |

**Billed revenue: ₹47,000.00.** By procedure: Crown 23,000 (11,000 + 12,000); Root canal treatment
8,000; Scaling 5,400; Composite filling 4,200; Extraction 3,000; Orthodontic review 2,400;
Consultation 1,000 (one consultation waived).

### Payments (16) — collections by payment date

| Month | Receipts | Total |
|---|---|---|
| Jan | SR01 500 + SR02 1,800 + SR03 2,000 + SR04 2,200 + SR05 1,500 | **₹8,000.00** |
| Feb | SR06 2,000 (rest of ST03, a January treatment) + SR07 4,000 + SR08 5,000 + SR09 1,200 + SR10 1,800 | **₹14,000.00** |
| Mar | SR11 4,000 + SR12 500 + SR13 2,000 + SR14 1,500 + SR15 6,000 + SR16 1,200 | **₹15,200.00** |

**Collections: ₹37,200.00.** Cumulative billed: 10,000 → 28,000 → 47,000. Cumulative collected:
8,000 → 22,000 → 37,200.

**Outstanding as of 12 Mar 2025: ₹9,800.00** = 47,000 − 37,200, made up of ST08 crown
(11,000 − 9,000 = 2,000), ST14 crown (12,000 − 6,000 = 6,000) and ST16 scaling (1,800 unpaid):
3 treatment records with a balance.

---

## `lakeview-dental/` (3 files: no patients or dentists file)

| What | In the files |
|---|---|
| Dates | ISO date-times, `2024-07-02 09:00:00` (no question needed) |
| Money | Integer **paise** (`net_fee_paise`, `amount_paise`): you confirm **paise** |
| Dentists | Codes only (L-D1, L-D2), so results by dentist show codes |
| Review groups | One treatment on a **cancelled** appointment (LT04, a ₹500 late-cancellation fee, paid by LP04) and one payment dated **before** its treatment (LP06, a ₹5,000 crown advance on 29 Jul 2024 for a 5 Aug 2024 crown) |

The expected figures assume the decisions used in the tests and browser checks:
**include** the early payment, **leave out** the treatment on the cancelled appointment (which also
leaves out its linked payment LP04).

**Coverage:** 2 Jul 2024 to 30 Sep 2024.

### Appointments (10)

* Scheduled 10; completed 7 (LA01, LA02, LA05, LA06, LA07, LA09, LA10); cancelled 1 (LA04);
  no-show 2 (LA03, LA08). No-show rate = 2 ÷ 10 = **20.0%**.
* By month: Jul 4 scheduled (2 completed, 1 cancelled, 1 no-show, 25.0%); Aug 3 (3 completed, 0.0%);
  Sep 3 (2 completed, 1 no-show, 33.3%).
* Unique patients seen: L-P1, L-P2, L-P3, L-P4, L-P5, L-P6 = **6**. Returning: L-P1 (LA05 after
  LA01) = **1**.

### Billed revenue (LT04 left out)

| Month | Lines (paise ÷ 100) | Net fees |
|---|---|---|
| Jul | LT01 600 + LT02 2,000 + LT03 5,500 | ₹8,100.00 |
| Aug | LT05 15,000 + LT06 1,800 + LT07 600 + LT08 8,000 | ₹25,400.00 |
| Sep | LT09 5,500 + LT10 2,000 | ₹7,500.00 |

**Billed revenue: ₹41,000.00** (₹41,500.00 if LT04 is included).

### Collections (LP04 left out with LT04; LP06 included)

| Month | Payments | Total |
|---|---|---|
| Jul | LP01 600 + LP02 2,000 + LP03 3,000 + LP06 5,000 (advance) | ₹10,600.00 |
| Aug | LP05 2,500 + LP07 6,000 + LP08 1,800 + LP09 600 + LP10 4,000 | ₹14,900.00 |
| Sep | LP11 5,500 | ₹5,500.00 |

**Collections: ₹31,000.00** (₹31,500.00 if LT04 and LP04 are included; ₹26,000.00 if the advance
is left out).

**Outstanding as of 30 Sep 2024: ₹10,000.00** = 41,000 − 31,000: LT05 crown (15,000 − 11,000 =
4,000), LT08 whitening (8,000 − 4,000 = 4,000) and LT10 scaling (2,000 unpaid).

### Appointments only

Uploading just `lakeview-dental/appointments.csv` gives the appointment figures above, and the app
explains that billed revenue, collections, procedures and balances need treatment and payment
records. Nothing is shown as ₹0.
