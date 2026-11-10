"""The synthetic-data catalog: every invented assumption in one place.

IMPORTANT
---------
Everything in this file is an INVENTED DEMO ASSUMPTION for a fictional
Indian dental clinic. Fee ranges are illustrative, not verified prices.
Seasonal patterns, no-show rates and payment behaviour are made up so the
dashboard has something to show. None of it is evidence about real clinics.

Beginner note: keeping assumptions in plain data structures (instead of
burying numbers inside generator code) makes them easy to document, test,
and change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# --- Observation period ------------------------------------------------------
PERIOD_START = date(2024, 1, 1)
PERIOD_END = date(2025, 12, 31)

ALLOWED_STATUSES = ("completed", "cancelled", "no_show")
GENDERS = ("Female", "Male", "Other")
PAYMENT_METHODS = ("UPI", "Cash", "Card", "Net banking")


# --- Procedures ----------------------------------------------------------------
@dataclass(frozen=True)
class Procedure:
    """One billable procedure type. One treatment record = one line item."""

    name: str
    record_represents: str  # what ONE treatment record means
    tooth_specific: bool  # True -> tooth_number required; False -> NULL
    fee_min_inr: int
    fee_max_inr: int
    fee_step_inr: int  # listed fees are rounded to this step
    min_age: int  # plausible age range at the visit (inclusive)
    max_age: int


PROCEDURES: dict[str, Procedure] = {
    p.name: p
    for p in [
        Procedure("Consultation", "One examination/consultation at a visit.",
                  False, 300, 700, 50, 2, 95),
        Procedure("Scaling", "One full-mouth scaling and polishing session.",
                  False, 1000, 2500, 100, 12, 95),
        Procedure("Composite filling", "One tooth restored with composite at one visit.",
                  True, 1200, 3000, 100, 3, 95),
        Procedure("Root canal treatment (session)",
                  "ONE root canal treatment session on one tooth. A full root canal "
                  "course often spans 1-3 sessions, so counts are sessions, not teeth "
                  "or completed courses.",
                  True, 2000, 4000, 100, 10, 95),
        Procedure("Extraction", "One tooth extracted (simple or surgical).",
                  True, 800, 6000, 100, 3, 95),
        Procedure("Crown placement", "One crown fitted on one tooth. Earlier preparation "
                  "visits are included in this fee.",
                  True, 6000, 14000, 500, 16, 95),
        Procedure("Denture provision", "One complete or partial denture delivered. "
                  "Impression and try-in visits are included in this fee.",
                  False, 12000, 35000, 500, 40, 95),
        Procedure("Orthodontic review", "One orthodontic review/adjustment visit. It is NOT "
                  "the cost of a whole orthodontic course.",
                  False, 1000, 2000, 100, 9, 40),
        Procedure("Implant placement", "Surgical placement of one implant fixture. The "
                  "later implant crown is not modelled.",
                  True, 28000, 45000, 1000, 21, 85),
        Procedure("Fluoride application", "One topical fluoride application for a child.",
                  False, 500, 1000, 50, 2, 16),
    ]
}
PROCEDURE_NAMES = tuple(PROCEDURES)

# Friendly aliases the analytics tools accept (lower-case). Matching is shown
# back to the user as "validated arguments", so nothing is silently guessed.
PROCEDURE_ALIASES: dict[str, str] = {
    "consultation": "Consultation",
    "check-up": "Consultation",
    "checkup": "Consultation",
    "scaling": "Scaling",
    "cleaning": "Scaling",
    "scaling and polishing": "Scaling",
    "filling": "Composite filling",
    "fillings": "Composite filling",
    "composite filling": "Composite filling",
    "composite": "Composite filling",
    "root canal": "Root canal treatment (session)",
    "root canals": "Root canal treatment (session)",
    "root canal treatment": "Root canal treatment (session)",
    "root canal treatment (session)": "Root canal treatment (session)",
    "rct": "Root canal treatment (session)",
    "extraction": "Extraction",
    "extractions": "Extraction",
    "tooth extraction": "Extraction",
    "crown": "Crown placement",
    "crowns": "Crown placement",
    "crown placement": "Crown placement",
    "denture": "Denture provision",
    "dentures": "Denture provision",
    "denture provision": "Denture provision",
    "orthodontic review": "Orthodontic review",
    "orthodontics": "Orthodontic review",
    "ortho": "Orthodontic review",
    "braces": "Orthodontic review",
    "implant": "Implant placement",
    "implants": "Implant placement",
    "implant placement": "Implant placement",
    "fluoride": "Fluoride application",
    "fluoride application": "Fluoride application",
}


# --- FDI two-digit tooth numbering ----------------------------------------------
# Permanent teeth: quadrants 1-4, teeth 1-8 (e.g. 36 = lower-left first molar).
# Primary (baby) teeth: quadrants 5-8, teeth 1-5 (e.g. 85 = lower-right second molar).
PERMANENT_TEETH = tuple(q * 10 + t for q in (1, 2, 3, 4) for t in range(1, 9))
PRIMARY_TEETH = tuple(q * 10 + t for q in (5, 6, 7, 8) for t in range(1, 6))
THIRD_MOLARS = (18, 28, 38, 48)
VALID_FDI_TEETH = frozenset(PERMANENT_TEETH + PRIMARY_TEETH)

# Plausibility rules (age = visit year - birth year, an approximation)
MAX_AGE_PRIMARY_TEETH = 12
MIN_AGE_PERMANENT_TEETH = 6
MIN_AGE_THIRD_MOLARS = 16


# --- Dentists (fictional names; any resemblance to real people is coincidental) ---
@dataclass(frozen=True)
class Dentist:
    dentist_id: str
    fictional_display_name: str
    specialty: str
    working_weekdays: tuple[int, ...]  # Monday = 0 ... Saturday = 5


DENTISTS: tuple[Dentist, ...] = (
    Dentist("D01", "Dr. Kavya M.", "General dentistry", (0, 1, 2, 3, 4, 5)),
    Dentist("D02", "Dr. Arjun B.", "General dentistry", (0, 1, 2, 3, 4, 5)),
    Dentist("D03", "Dr. Nisha K.", "Endodontics", (0, 1, 3, 4, 5)),
    Dentist("D04", "Dr. Rohan I.", "Orthodontics", (1, 3, 5)),
    Dentist("D05", "Dr. Farah S.", "Periodontics", (0, 2, 4)),
    Dentist("D06", "Dr. Vikram T.", "Prosthodontics", (1, 2, 4, 5)),
    Dentist("D07", "Dr. Meera P.", "Oral and maxillofacial surgery", (0, 2, 5)),
    Dentist("D08", "Dr. Sameer J.", "Paediatric dentistry", (1, 3, 4, 5)),
)
DENTIST_BY_ID = {d.dentist_id: d for d in DENTISTS}

# Clinic hours: two sessions, 30-minute slots (10:00-13:30 and 17:00-20:30).
SLOT_TIMES = tuple(
    f"{h:02d}:{m:02d}:00"
    for h, m in [(10, 0), (10, 30), (11, 0), (11, 30), (12, 0), (12, 30), (13, 0),
                 (17, 0), (17, 30), (18, 0), (18, 30), (19, 0), (19, 30), (20, 0)]
)
# Closed on Sundays and three fixed-date national holidays (illustrative).
FIXED_HOLIDAYS = ((1, 26), (8, 15), (10, 2))


# --- Patients ----------------------------------------------------------------------
# Invented locality labels (not real addresses; resemblance is coincidental).
LOCALITIES = (
    "Tamarind Heights", "Jasmine Quarter", "Peacock Lanes", "Monsoon Meadows",
    "Saffron Square", "Lotus Terrace", "Banyan Crossing", "Coral Gardens",
    "Riverbend Colony", "Sandalwood Park",
)
LOCALITY_WEIGHTS = (0.16, 0.14, 0.12, 0.11, 0.10, 0.09, 0.08, 0.08, 0.07, 0.05)
GENDER_WEIGHTS = (0.51, 0.48, 0.01)

# Age on 1 Jan 2024: (min, max, share of patients)
AGE_BANDS = ((3, 12, 0.13), (13, 17, 0.09), (18, 34, 0.30), (35, 54, 0.28), (55, 82, 0.20))


# --- Modest synthetic patterns (documented; NOT real-world evidence) ------------
# Records begin on PERIOD_START (imagine the fictional clinic adopting this
# system then). "Established" patients were already known to the clinic and are
# registered at their first visit after that date, early in 2024. Without
# them, volumes would ramp up from zero, which no running clinic shows.
ESTABLISHED_PATIENT_SHARE = 0.50
ESTABLISHED_FIRST_VISIT_MEAN_DAYS = 90  # exponential spread of their first visit
ESTABLISHED_FIRST_VISIT_WINDOW_DAYS = 365  # capped at one year

# Relative weight of NEW patients' first visits by calendar month (Jan..Dec):
# a little busier in Jan/May-Jun/Dec, quieter in the monsoon months and November.
NEW_PATIENT_MONTH_WEIGHTS = (1.10, 1.00, 1.00, 0.95, 1.10, 1.05, 0.85, 0.85, 0.90, 0.95, 0.90, 1.05)
# Relative weight of new patients by year (slight growth in 2025).
NEW_PATIENT_YEAR_WEIGHTS = {2024: 0.95, 2025: 1.05}

# Chance that an elective FIRST visit of a care episode is postponed by 1-4
# weeks, by month (Jan..Dec): monsoon (Jul-Sep) and festival season (Nov).
POSTPONE_PROB_BY_MONTH = (0.0, 0.0, 0.0, 0.0, 0.0, 0.10, 0.30, 0.30, 0.15, 0.05, 0.20, 0.0)

# Probability that a booked appointment ends as a no-show, by month (Jan..Dec).
NO_SHOW_PROB_BY_MONTH = (0.060, 0.060, 0.065, 0.070, 0.070, 0.090, 0.105, 0.100, 0.090, 0.070, 0.075, 0.080)
CANCEL_PROB = 0.08
CANCEL_PROB_NOVEMBER = 0.11  # festival season
REBOOK_PROB = 0.72  # after a cancellation/no-show, chance the visit is rebooked

# Discounts: chance a chargeable treatment is discounted, and allowed percentages.
DISCOUNT_PROB_SENIOR = 0.35  # age >= 60
DISCOUNT_PROB_OTHER = 0.08
DISCOUNT_PERCENTS = (5, 10, 15, 20)
CONSULTATION_WAIVER_PROB = 0.03  # consultation fee fully waived (net fee = 0)

PAYMENT_METHOD_WEIGHTS = (0.50, 0.22, 0.22, 0.06)
HIGH_FEE_THRESHOLD_INR = 5000  # high-fee treatments are more often paid in instalments
