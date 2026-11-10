"""Reproducible synthetic dataset generator for MolarMetrics.

Usage (from the project root, with the virtual environment active):

    python -m molarmetrics.data.generate              # refuses to overwrite existing data
    python -m molarmetrics.data.generate --overwrite  # regenerate in place

The same seed + settings always produce byte-identical CSV files.

How it works (beginner summary)
-------------------------------
1. Create 1,000 fictional patients (birth year, gender, invented locality).
2. For each patient, plan "care episodes" (check-up, fillings, a root canal
   course, braces, ...). Each episode is a sequence of planned visits.
3. Book every visit into a real 30-minute slot on a day that dentist works.
4. Each booked appointment may be completed, cancelled or a no-show.
   Missed visits are often rebooked a few days later.
5. Completed visits get treatment records (fees in integer paise), and each
   treatment gets 0..3 payments (full, instalments, partial, or unpaid).
6. Write CSVs + SQLite, then independently validate the database.

All patterns come from the documented assumptions in ``catalog.py``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from molarmetrics import APP_NAME, DATA_NOTICE
from molarmetrics.data import catalog as C
from molarmetrics.data.schema import TABLE_ORDER, create_schema, insert_rows
from molarmetrics.money import paise_to_plain, rupees_to_paise

GENERATOR_VERSION = "1.0"

# Calibrated (by trial runs) so the default settings give roughly 6,000
# appointments with only modest month-to-month variation.
RETURN_PROB_AFTER_EPISODE = 0.87
RETURN_PROB_AFTER_DROPOUT = 0.40
RETURN_GAP_DAYS = (30, 200)
MAX_REBOOKS_PER_VISIT = 2


@dataclass(frozen=True)
class GeneratorSettings:
    seed: int = 42
    n_patients: int = 1000
    period_start: date = C.PERIOD_START
    period_end: date = C.PERIOD_END

    def as_json(self) -> dict:
        d = asdict(self)
        d["period_start"] = self.period_start.isoformat()
        d["period_end"] = self.period_end.isoformat()
        return d


@dataclass
class Dataset:
    settings: GeneratorSettings
    tables: dict[str, list[dict]]


@dataclass
class _Visit:
    """One planned visit inside a care episode."""

    gap: tuple[int, int]  # days after the previous completed visit (min, max)
    dentist_id: str
    reason: str
    procedures: list[tuple[str, str | None]] = field(default_factory=list)  # (name, tooth rule)


# Tooth groups (FDI) used when choosing plausible teeth.
_PRIMARY_MOLARS = (54, 55, 64, 65, 74, 75, 84, 85)
_PRIMARY_ANTERIORS = (51, 52, 53, 61, 62, 63, 71, 72, 73, 81, 82, 83)
_FIRST_MOLARS = (16, 26, 36, 46)
_SECOND_MOLARS = (17, 27, 37, 47)
_MOLARS = _FIRST_MOLARS + _SECOND_MOLARS
_PREMOLARS = (14, 15, 24, 25, 34, 35, 44, 45)
_ANTERIORS = (11, 12, 13, 21, 22, 23, 31, 32, 33, 41, 42, 43)
_EARLY_PERMANENT_INCISORS = (11, 21, 31, 41, 12, 22, 32, 42)
_ORTHO_PREMOLARS = (14, 24, 34, 44)
_IMPLANT_SITES = (36, 46, 16, 26, 35, 45, 15, 25, 11, 21)

_GENERAL = ("D01", "D02")
_ENDO, _ORTHO, _PERIO, _PROSTHO, _SURGERY, _PAEDO = "D03", "D04", "D05", "D06", "D07", "D08"


class _Generator:
    def __init__(self, settings: GeneratorSettings):
        self.s = settings
        self.rng = np.random.default_rng(settings.seed)
        self.dentist_busy: dict[tuple[str, date], set[int]] = defaultdict(set)
        self.patient_busy: dict[tuple[int, date], set[int]] = defaultdict(set)
        self.patients: list[dict] = []
        self.appointments: list[dict] = []

    # --- small random helpers (always convert numpy types to plain Python) ----
    def randint(self, lo: int, hi: int) -> int:
        """Random integer in [lo, hi], inclusive."""
        return int(self.rng.integers(lo, hi + 1))

    def chance(self, p: float) -> bool:
        return bool(self.rng.random() < p)

    def pick(self, options, weights=None):
        if weights is None:
            return options[int(self.rng.integers(0, len(options)))]
        w = np.asarray(weights, dtype=float)
        return options[int(self.rng.choice(len(options), p=w / w.sum()))]

    # --- calendar --------------------------------------------------------------
    def is_open(self, d: date, dentist_id: str) -> bool:
        return (d.weekday() in C.DENTIST_BY_ID[dentist_id].working_weekdays
                and (d.month, d.day) not in C.FIXED_HOLIDAYS)

    def book(self, dentist_id: str, pidx: int, earliest: date) -> tuple[date, int] | None:
        """Find the first open day (from ``earliest``) with a free slot for both
        the dentist and the patient. Returns (date, slot index) or None."""
        d = max(earliest, self.s.period_start)
        for _ in range(60):
            if d > self.s.period_end:
                return None
            if self.is_open(d, dentist_id):
                used_d = self.dentist_busy[(dentist_id, d)]
                used_p = self.patient_busy[(pidx, d)]
                free = [i for i in range(len(C.SLOT_TIMES)) if i not in used_d and i not in used_p]
                if free:
                    slot = free[self.randint(0, len(free) - 1)]
                    used_d.add(slot)
                    used_p.add(slot)
                    return d, slot
            d += timedelta(days=1)
        return None

    def draw_status(self, d: date) -> str:
        p_no_show = C.NO_SHOW_PROB_BY_MONTH[d.month - 1]
        p_cancel = C.CANCEL_PROB_NOVEMBER if d.month == 11 else C.CANCEL_PROB
        r = self.rng.random()
        if r < p_no_show:
            return "no_show"
        if r < p_no_show + p_cancel:
            return "cancelled"
        return "completed"

    # --- patients ---------------------------------------------------------------
    def make_patients(self) -> None:
        months = []
        y, m = self.s.period_start.year, self.s.period_start.month
        while date(y, m, 1) <= self.s.period_end:
            months.append((y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        month_w = [C.NEW_PATIENT_MONTH_WEIGHTS[mm - 1] * C.NEW_PATIENT_YEAR_WEIGHTS.get(yy, 1.0)
                   for yy, mm in months]
        latest_first_visit = self.s.period_end - timedelta(days=10)

        for i in range(self.s.n_patients):
            lo, hi, _ = self.pick(C.AGE_BANDS, [b[2] for b in C.AGE_BANDS])
            age_2024 = self.randint(lo, hi)
            if self.chance(C.ESTABLISHED_PATIENT_SHARE):  # already known to the clinic
                # Exponential spread: many come back soon after records start, fewer later.
                offset = int(self.rng.exponential(C.ESTABLISHED_FIRST_VISIT_MEAN_DAYS))
                first = self.s.period_start + timedelta(
                    days=min(offset, C.ESTABLISHED_FIRST_VISIT_WINDOW_DAYS - 1))
            else:  # genuinely new patient, arriving any time in the period
                yy, mm = self.pick(months, month_w)
                next_month = date(yy + (mm == 12), mm % 12 + 1, 1)
                first = date(yy, mm, self.randint(1, (next_month - date(yy, mm, 1)).days))
            self.patients.append({
                "_idx": i,
                "birth_year": 2024 - age_2024,
                "gender": self.pick(C.GENDERS, C.GENDER_WEIGHTS),
                "locality": self.pick(C.LOCALITIES, C.LOCALITY_WEIGHTS),
                "_home_gp": self.pick(_GENERAL),
                "_first_visit_target": min(first, latest_first_visit),
                "_unavailable_teeth": [],  # extracted teeth and implant sites
                "_implant_sites": [],
                "_flags": {"ortho": False, "denture": False, "implants": 0},
                "registration_date": None,
            })

    # --- episodes ----------------------------------------------------------------
    def episode_weights(self, age: int, patient: dict) -> dict[str, float]:
        flags = patient["_flags"]
        wisdom_left = any(t not in patient["_unavailable_teeth"] for t in C.THIRD_MOLARS)
        return {
            "checkup": 3.0,
            "scaling": 2.0 if age >= 13 else 0.0,
            "filling": 2.4 if age >= 3 else 0.0,
            "rct": 1.5 if age >= 12 else 0.0,
            "extraction": 0.9,
            "wisdom": 0.9 if (17 <= age <= 40 and wisdom_left) else 0.0,
            "crown": 0.45 if age >= 20 else 0.0,
            "denture": 0.0 if flags["denture"] else (1.0 if age >= 60 else (0.25 if age >= 45 else 0.0)),
            "implant": 0.0 if flags["implants"] >= 2 else (0.35 if 30 <= age <= 75 else (0.1 if 25 <= age < 30 else 0.0)),
            "ortho": 0.0 if flags["ortho"] else (2.0 if 10 <= age <= 17 else (0.4 if 18 <= age <= 30 else 0.0)),
            "child_preventive": 2.4 if age <= 12 else 0.0,
            "perio": 0.8 if age >= 30 else 0.0,
        }

    def plan_episode(self, kind: str, patient: dict, age: int) -> list[_Visit]:
        gp = patient["_home_gp"]
        V = _Visit
        if kind == "checkup":
            dentist = _PAEDO if (age <= 12 and self.chance(0.8)) else (gp if self.chance(0.85) else _PERIO)
            procs = [("Consultation", None)]
            if age >= 13 and self.chance(0.4):
                procs.append(("Scaling", None))
            return [V((0, 0), dentist, "Routine check-up", procs)]
        if kind == "scaling":
            dentist = _PERIO if self.chance(0.3) else gp
            procs = ([("Consultation", None)] if self.chance(0.3) else []) + [("Scaling", None)]
            return [V((0, 0), dentist, "Teeth cleaning", procs)]
        if kind == "filling":
            dentist = _PAEDO if age <= 12 else (gp if self.chance(0.8) else _ENDO)
            visits = [V((0, 0), dentist, "Tooth decay / cavity",
                        [("Consultation", None)] + [("Composite filling", "filling")] * self.randint(1, 2))]
            if self.chance(0.3):
                visits.append(V((7, 21), dentist, "Filling - next appointment",
                                [("Composite filling", "filling")] * self.randint(1, 2)))
            return visits
        if kind == "rct":
            endo = _ENDO if self.chance(0.7) else gp
            sessions = self.pick((1, 2, 3), (0.25, 0.45, 0.30))
            visits = [V((0, 0), endo, "Toothache",
                        [("Consultation", None), ("Root canal treatment (session)", "rct")])]
            visits += [V((3, 10), endo, "Root canal treatment - continuing",
                         [("Root canal treatment (session)", "rct_same")]) for _ in range(sessions - 1)]
            if age >= 18 and self.chance(0.55):
                crown_dentist = _PROSTHO if self.chance(0.6) else gp
                visits.append(V((7, 21), crown_dentist, "Crown preparation", []))
                visits.append(V((5, 10), crown_dentist, "Crown fitting", [("Crown placement", "rct_same")]))
            return visits
        if kind == "extraction":
            if age <= 12:
                dentist, reason = _PAEDO, "Loose or decayed baby tooth"
            else:
                dentist, reason = (_SURGERY if self.chance(0.45) else gp), "Tooth extraction"
            visits = [V((0, 0), dentist, reason, [("Consultation", None), ("Extraction", "extraction")])]
            if self.chance(0.35):
                visits.append(V((6, 10), dentist, "Post-extraction review", []))
            return visits
        if kind == "wisdom":
            dentist = _SURGERY if self.chance(0.85) else gp
            visits = [V((0, 0), dentist, "Wisdom tooth pain", [("Consultation", None)]),
                      V((3, 14), dentist, "Wisdom tooth removal", [("Extraction", "wisdom")])]
            if self.chance(0.6):
                visits.append(V((6, 10), dentist, "Post-extraction review", []))
            return visits
        if kind == "crown":
            dentist = _PROSTHO if self.chance(0.65) else gp
            return [V((0, 0), dentist, "Broken or weak tooth", [("Consultation", None)]),
                    V((3, 10), dentist, "Crown preparation", []),
                    V((5, 10), dentist, "Crown fitting", [("Crown placement", "crown")])]
        if kind == "denture":
            patient["_flags"]["denture"] = True
            visits = [V((0, 0), _PROSTHO, "Missing teeth - denture consultation", [("Consultation", None)]),
                      V((5, 12), _PROSTHO, "Denture impressions", []),
                      V((5, 12), _PROSTHO, "Denture try-in", []),
                      V((5, 12), _PROSTHO, "Denture delivery", [("Denture provision", None)])]
            if self.chance(0.6):
                visits.append(V((5, 14), _PROSTHO, "Denture adjustment", []))
            return visits
        if kind == "implant":
            patient["_flags"]["implants"] += 1
            dentist = self.pick((_SURGERY, _PROSTHO, _PERIO), (0.5, 0.3, 0.2))
            return [V((0, 0), dentist, "Missing tooth - implant consultation", [("Consultation", None)]),
                    V((7, 21), dentist, "Implant surgery", [("Implant placement", "implant")]),
                    V((7, 14), dentist, "Implant review", [])]
        if kind == "ortho":
            patient["_flags"]["ortho"] = True
            visits = [V((0, 0), _ORTHO, "Braces consultation", [("Consultation", None)])]
            visits += [V((25, 40), _ORTHO, "Orthodontic adjustment", [("Orthodontic review", None)])
                       for _ in range(self.randint(6, 18))]
            return visits
        if kind == "child_preventive":
            return [V((0, 0), _PAEDO, "Child dental check-up",
                      [("Consultation", None), ("Fluoride application", None)])]
        if kind == "perio":
            return [V((0, 0), _PERIO, "Bleeding gums", [("Consultation", None), ("Scaling", None)]),
                    V((14, 35), _PERIO, "Gum treatment review", [("Scaling", None)])]
        raise ValueError(f"unknown episode kind {kind!r}")

    # --- teeth -------------------------------------------------------------------------
    def pick_tooth(self, rule: str, age: int, patient: dict, ctx: dict, exclude: list[int]) -> int:
        if rule == "rct_same":
            return ctx["rct_tooth"]
        blocked = set(patient["_unavailable_teeth"]) | set(exclude)

        def from_groups(groups, weights):
            group = self.pick(groups, weights)
            options = [t for t in group if t not in blocked]
            if not options:  # fall back to any allowed tooth in all groups
                options = [t for g in groups for t in g if t not in blocked] or list(group)
            return self.pick(options)

        if rule == "filling":
            if age <= 5:
                return from_groups((_PRIMARY_MOLARS, _PRIMARY_ANTERIORS), (0.8, 0.2))
            if age <= 11:
                return from_groups((_PRIMARY_MOLARS, _FIRST_MOLARS, _EARLY_PERMANENT_INCISORS), (0.55, 0.35, 0.10))
            return from_groups((_MOLARS, _PREMOLARS, _ANTERIORS), (0.55, 0.30, 0.15))
        if rule == "extraction":
            if age <= 11:
                tooth = from_groups((_PRIMARY_MOLARS, _PRIMARY_ANTERIORS), (0.6, 0.4))
            elif age <= 16:
                tooth = from_groups((_ORTHO_PREMOLARS, _FIRST_MOLARS), (0.7, 0.3))
            else:
                tooth = from_groups((_MOLARS, _PREMOLARS, _ANTERIORS, C.THIRD_MOLARS), (0.5, 0.25, 0.15, 0.10))
            patient["_unavailable_teeth"].append(tooth)
            return tooth
        if rule == "wisdom":
            tooth = from_groups((C.THIRD_MOLARS,), (1.0,))
            patient["_unavailable_teeth"].append(tooth)
            return tooth
        if rule == "rct":
            tooth = from_groups((_FIRST_MOLARS, _SECOND_MOLARS, _PREMOLARS, _ANTERIORS), (0.45, 0.20, 0.25, 0.10))
            ctx["rct_tooth"] = tooth
            return tooth
        if rule == "crown":
            return from_groups((_MOLARS, _PREMOLARS, _ANTERIORS), (0.6, 0.3, 0.1))
        if rule == "implant":
            # Prefer a site where this patient had a permanent tooth extracted earlier.
            extracted = [t for t in patient["_unavailable_teeth"]
                         if t in C.PERMANENT_TEETH and t not in C.THIRD_MOLARS
                         and t not in patient["_implant_sites"]]
            tooth = self.pick(extracted) if extracted else from_groups((_IMPLANT_SITES,), (1.0,))
            patient["_implant_sites"].append(tooth)
            if tooth not in patient["_unavailable_teeth"]:
                patient["_unavailable_teeth"].append(tooth)
            return tooth
        raise ValueError(f"unknown tooth rule {rule!r}")

    # --- money ----------------------------------------------------------------------
    def listed_fee_paise(self, name: str, rule: str | None) -> int:
        proc = C.PROCEDURES[name]
        lo, hi = proc.fee_min_inr, proc.fee_max_inr
        if name == "Extraction":  # surgical wisdom-tooth removal costs more
            lo, hi = (3000, 6000) if rule == "wisdom" else (800, 2500)
        steps = (hi - lo) // proc.fee_step_inr
        return rupees_to_paise(lo + proc.fee_step_inr * self.randint(0, steps))

    def discount_paise(self, name: str, listed: int, age: int) -> int:
        if name == "Consultation" and self.chance(C.CONSULTATION_WAIVER_PROB):
            return listed  # fee waived -> net fee 0
        senior = age >= 60
        if self.chance(C.DISCOUNT_PROB_SENIOR if senior else C.DISCOUNT_PROB_OTHER):
            pct = 10 if senior else self.pick(C.DISCOUNT_PERCENTS)
            return (listed * pct // 100) // 1000 * 1000  # round down to a whole Rs 10
        return 0

    def payment_schedule(self, treatment_date: date, net: int) -> list[tuple[date, int]]:
        """Return planned (date, amount_paise) instalments; totals never exceed ``net``."""
        if net <= 0:
            return []
        high = net >= rupees_to_paise(C.HIGH_FEE_THRESHOLD_INR)
        step = 10_000 if high else 1_000  # round instalments to Rs 100 / Rs 10
        if high:
            plan = self.pick(("full_same_day", "split", "partial", "full_later", "unpaid"),
                             (0.35, 0.45, 0.12, 0.04, 0.04))
        else:
            plan = self.pick(("full_same_day", "full_later", "split", "partial", "unpaid"),
                             (0.86, 0.05, 0.04, 0.03, 0.02))

        def portion(lo: float, hi: float) -> int:
            amount = int(net * self.rng.uniform(lo, hi)) // step * step
            return min(max(amount, step), net - step) if net > 2 * step else net // 2

        if plan == "full_same_day":
            return [(treatment_date, net)]
        if plan == "full_later":
            return [(treatment_date + timedelta(days=self.randint(1, 30)), net)]
        if plan == "unpaid":
            return []
        if plan == "partial":
            when = treatment_date if self.chance(0.8) else treatment_date + timedelta(days=self.randint(1, 20))
            return [(when, portion(0.3, 0.7))]
        # split: 2 (or, for high fees, sometimes 3) instalments summing exactly to net
        n = 3 if (high and self.chance(0.4)) else 2
        first = portion(0.3, 0.6)
        rest = net - first
        amounts = [first] + ([rest] if n == 2 else [rest // 2 // step * step, rest - rest // 2 // step * step])
        amounts = [a for a in amounts if a > 0]
        dates, d = [], treatment_date
        for k in range(len(amounts)):
            if k > 0:
                d = d + timedelta(days=self.randint(7, 30))
            dates.append(d)
        return list(zip(dates, amounts))

    # --- main loop ---------------------------------------------------------------------
    def run_episode(self, patient: dict, start: date, visits: list[_Visit]) -> tuple[date | None, bool]:
        """Book and resolve one episode. Returns (last appointment date, finished?)."""
        ctx: dict = {}  # per-episode memory, e.g. which tooth the root canal is on
        prev: date | None = None
        last_seen: date | None = None
        for k, visit in enumerate(visits):
            target = start if k == 0 else prev + timedelta(days=self.randint(*visit.gap))
            if k == 0 and self.chance(C.POSTPONE_PROB_BY_MONTH[target.month - 1]):
                target += timedelta(days=self.randint(7, 28))  # seasonal postponement
            for attempt in range(MAX_REBOOKS_PER_VISIT + 1):
                booking = self.book(visit.dentist_id, patient["_idx"], target)
                if booking is None:
                    return last_seen, False  # ran past the observation period
                appt_date, slot = booking
                if patient["registration_date"] is None:  # first ever appointment
                    reg = appt_date - timedelta(days=self.randint(0, 14))
                    patient["registration_date"] = max(reg, self.s.period_start)
                status = self.draw_status(appt_date)
                appt = {"_pidx": patient["_idx"], "dentist_id": visit.dentist_id, "_date": appt_date,
                        "_slot": slot, "status": status, "visit_reason": visit.reason, "_treatments": []}
                self.appointments.append(appt)
                last_seen = appt_date
                if status == "completed":
                    self.add_treatments(appt, patient, visit, ctx)
                    prev = appt_date
                    break
                if attempt == MAX_REBOOKS_PER_VISIT or not self.chance(C.REBOOK_PROB):
                    return last_seen, False  # patient dropped out of this episode
                target = appt_date + timedelta(days=self.randint(2, 14))
        return last_seen, True

    def add_treatments(self, appt: dict, patient: dict, visit: _Visit, ctx: dict) -> None:
        age = appt["_date"].year - patient["birth_year"]
        teeth_this_visit: list[int] = []
        for name, rule in visit.procedures:
            tooth = None
            if C.PROCEDURES[name].tooth_specific:
                tooth = self.pick_tooth(rule, age, patient, ctx, teeth_this_visit)
                teeth_this_visit.append(tooth)
            # Repeat procedures in one episode (e.g. monthly orthodontic reviews,
            # root canal sessions) keep the same listed fee, as a clinic would.
            fee_key = (name, "wisdom" if rule == "wisdom" else None)
            fees = ctx.setdefault("fees", {})
            if fee_key not in fees:
                fees[fee_key] = self.listed_fee_paise(name, rule)
            listed = fees[fee_key]
            discount = self.discount_paise(name, listed, age)
            net = listed - discount
            payments = [(d, amt, self.pick(C.PAYMENT_METHODS, C.PAYMENT_METHOD_WEIGHTS))
                        for d, amt in self.payment_schedule(appt["_date"], net)
                        if d <= self.s.period_end]  # later instalments fall outside the data
            appt["_treatments"].append({
                "procedure_name": name, "tooth_number": tooth, "listed_fee_paise": listed,
                "discount_paise": discount, "net_fee_paise": net, "_payments": payments,
            })

    def run_patient(self, patient: dict) -> None:
        start = patient["_first_visit_target"]
        while start <= self.s.period_end:
            age = start.year - patient["birth_year"]
            weights = self.episode_weights(age, patient)
            kinds = [k for k, w in weights.items() if w > 0]
            kind = self.pick(kinds, [weights[k] for k in kinds])
            last, finished = self.run_episode(patient, start, self.plan_episode(kind, patient, age))
            if last is None:
                break
            p_return = RETURN_PROB_AFTER_EPISODE if finished else RETURN_PROB_AFTER_DROPOUT
            if not self.chance(p_return):
                break
            start = last + timedelta(days=self.randint(*RETURN_GAP_DAYS))

    def build(self) -> Dataset:
        self.make_patients()
        for patient in self.patients:
            self.run_patient(patient)
        return self._finalise()

    # --- assign readable, chronological IDs -------------------------------------------
    def _finalise(self) -> Dataset:
        first_appt: dict[int, tuple] = {}
        for a in self.appointments:
            key = (a["_date"], a["_slot"])
            if a["_pidx"] not in first_appt or key < first_appt[a["_pidx"]]:
                first_appt[a["_pidx"]] = key
        for p in self.patients:  # a patient never booked keeps their intended date
            if p["registration_date"] is None:
                p["registration_date"] = p["_first_visit_target"]
        far = (date.max, 99)
        ordered = sorted(self.patients, key=lambda p: (p["registration_date"],
                                                       first_appt.get(p["_idx"], far), p["_idx"]))
        pid = {p["_idx"]: f"P{n:04d}" for n, p in enumerate(ordered, start=1)}
        patients = [{"patient_id": pid[p["_idx"]], "birth_year": p["birth_year"], "gender": p["gender"],
                     "locality": p["locality"], "registration_date": p["registration_date"].isoformat()}
                    for p in ordered]
        dentists = [{"dentist_id": d.dentist_id, "fictional_display_name": d.fictional_display_name,
                     "specialty": d.specialty} for d in C.DENTISTS]

        appts_sorted = sorted(self.appointments, key=lambda a: (a["_date"], a["_slot"], a["dentist_id"]))
        appointments, treatments, raw_payments = [], [], []
        for n, a in enumerate(appts_sorted, start=1):
            appt_id = f"A{n:05d}"
            appointments.append({
                "appointment_id": appt_id, "patient_id": pid[a["_pidx"]], "dentist_id": a["dentist_id"],
                "appointment_datetime": f"{a['_date'].isoformat()} {C.SLOT_TIMES[a['_slot']]}",
                "status": a["status"], "visit_reason": a["visit_reason"],
            })
            for t in a["_treatments"]:
                treat_id = f"T{len(treatments) + 1:05d}"
                treatments.append({"treatment_id": treat_id, "appointment_id": appt_id,
                                   **{k: v for k, v in t.items() if not k.startswith("_")}})
                for seq, (pay_date, amount, method) in enumerate(t["_payments"]):
                    raw_payments.append((pay_date, treat_id, seq, amount, method))
        raw_payments.sort(key=lambda r: (r[0], r[1], r[2]))
        payments = [{"payment_id": f"PM{n:05d}", "treatment_id": tid, "payment_date": d.isoformat(),
                     "amount_paise": amt, "payment_method": method}
                    for n, (d, tid, _seq, amt, method) in enumerate(raw_payments, start=1)]
        return Dataset(self.s, {"patients": patients, "dentists": dentists, "appointments": appointments,
                                "treatments": treatments, "payments": payments})


def generate_dataset(settings: GeneratorSettings | None = None) -> Dataset:
    """Generate the dataset in memory (no files written)."""
    return _Generator(settings or GeneratorSettings()).build()


# --- writing outputs ------------------------------------------------------------------------
CSV_COLUMNS: dict[str, tuple[str, ...]] = {
    "patients": ("patient_id", "birth_year", "gender", "locality", "registration_date"),
    "dentists": ("dentist_id", "fictional_display_name", "specialty"),
    "appointments": ("appointment_id", "patient_id", "dentist_id", "appointment_datetime", "status",
                     "visit_reason"),
    "treatments": ("treatment_id", "appointment_id", "procedure_name", "tooth_number", "listed_fee_inr",
                   "discount_inr", "net_fee_inr", "listed_fee_paise", "discount_paise", "net_fee_paise"),
    "payments": ("payment_id", "treatment_id", "payment_date", "amount_inr", "payment_method",
                 "amount_paise"),
}


def output_paths(out_dir: Path) -> dict[str, Path]:
    paths = {"db": out_dir / "molarmetrics.db",
             "dictionary_md": out_dir / "molarmetrics_data_dictionary.md",
             "dictionary_csv": out_dir / "molarmetrics_data_dictionary.csv",
             "validation_report": out_dir / "molarmetrics_validation_report.json"}
    for table in TABLE_ORDER:
        paths[f"csv_{table}"] = out_dir / "csv" / f"molarmetrics_{table}.csv"
    return paths


def _csv_value(row: dict, col: str) -> str:
    if col.endswith("_inr"):
        return paise_to_plain(row[col[:-4] + "_paise"])
    value = row[col]
    return "" if value is None else str(value)


def write_csvs(dataset: Dataset, csv_dir: Path) -> None:
    csv_dir.mkdir(parents=True, exist_ok=True)
    for table in TABLE_ORDER:
        with open(csv_dir / f"molarmetrics_{table}.csv", "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(CSV_COLUMNS[table])
            for row in dataset.tables[table]:
                writer.writerow([_csv_value(row, c) for c in CSV_COLUMNS[table]])


def write_sqlite(dataset: Dataset, db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        create_schema(conn, with_triggers=True)
        with conn:
            for table in TABLE_ORDER:  # parents first, so foreign keys are satisfied
                insert_rows(conn, table, dataset.tables[table])
        conn.execute("VACUUM")
    finally:
        conn.close()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_all(dataset: Dataset, out_dir: Path, overwrite: bool = False) -> dict[str, Path]:
    """Write CSVs, SQLite, data dictionary and validation report into ``out_dir``.

    Files are built in a temporary folder first and moved into place only after
    everything succeeded, so a failed run never leaves half-written data.
    """
    from molarmetrics.data.dictionary import write_data_dictionary
    from molarmetrics.data.validate import validate_database

    out_dir = Path(out_dir)
    final = output_paths(out_dir)
    existing = [p for p in final.values() if p.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "Generated data already exists (e.g. " + str(existing[0]) + "). "
            "Re-run with --overwrite to replace it."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".molarmetrics_build_", dir=out_dir) as tmp:
        staged = output_paths(Path(tmp))
        write_csvs(dataset, staged["csv_patients"].parent)
        write_sqlite(dataset, staged["db"])
        write_data_dictionary(staged["dictionary_md"], staged["dictionary_csv"])
        report = validate_database(staged["db"])
        report["dataset"] = {
            "app": APP_NAME,
            "notice": DATA_NOTICE,
            "generator_version": GENERATOR_VERSION,
            "settings": dataset.settings.as_json(),
            "row_counts": {t: len(dataset.tables[t]) for t in TABLE_ORDER},
            "csv_sha256": {t: sha256_file(staged[f"csv_{t}"]) for t in TABLE_ORDER},
        }
        report["generated_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        staged["validation_report"].write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        for key, src in staged.items():
            final[key].parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(final[key]))
    return final


def main(argv: list[str] | None = None) -> int:
    from molarmetrics.config import get_settings

    parser = argparse.ArgumentParser(description=f"Generate the {APP_NAME} synthetic dental clinic dataset.")
    parser.add_argument("--out-dir", type=Path, default=get_settings().data_dir,
                        help="output folder (default: ./data)")
    parser.add_argument("--seed", type=int, default=42, help="random seed (default: 42)")
    parser.add_argument("--patients", type=int, default=1000, help="number of patients (default: 1000)")
    parser.add_argument("--overwrite", action="store_true", help="replace existing generated files")
    args = parser.parse_args(argv)

    settings = GeneratorSettings(seed=args.seed, n_patients=args.patients)
    existing = [p for p in output_paths(args.out_dir).values() if p.exists()]
    if existing and not args.overwrite:  # check first, before doing any work
        print(f"Not overwriting: generated data already exists (e.g. {existing[0]}).\n"
              "Re-run with --overwrite to replace it.", file=sys.stderr)
        return 1
    print(f"{APP_NAME}: generating {DATA_NOTICE} (seed={settings.seed}, patients={settings.n_patients}) ...")
    dataset = generate_dataset(settings)
    try:
        paths = write_all(dataset, args.out_dir, overwrite=args.overwrite)
    except FileExistsError as exc:
        print(f"Not overwriting: {exc}", file=sys.stderr)
        return 1
    report = json.loads(paths["validation_report"].read_text(encoding="utf-8"))
    for table, n in report["dataset"]["row_counts"].items():
        print(f"  {table:<13} {n:>6,} rows")
    s = report["summary"]
    print(f"Validation: {s['status']} ({s['checks_passed']}/{s['checks_total']} checks passed)")
    print(f"Database:   {paths['db']}")
    print(f"Report:     {paths['validation_report']}")
    return 0 if s["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
