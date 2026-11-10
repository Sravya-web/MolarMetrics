"""Validate an upload against the user's review choices, and normalise it.

Beginner notes
--------------
* ``validate_batch`` is a pure function: parsed files + the user's choices in,
  a report out. The review screen calls it after every change, and the import
  step calls it AGAIN on the server, so a stale or tampered browser state can
  never import unvalidated data.
* Severities:
    blocking  must be fixed (or the file corrected) before importing
    review    a real-world inconsistency the user must explicitly decide on:
              include the records as recorded, or leave them out
    warning   worth a look, imported as recorded
    info      context only
* Nothing is invented: a blank ID, date or amount is reported, never filled
  in with a made-up value or zero, and no row is dropped without a decision.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, time
from typing import Literal

from pydantic import BaseModel, Field

from molarmetrics.dataset import APPOINTMENTS as CAP_APPOINTMENTS
from molarmetrics.dataset import DENTIST_BREAKDOWN, PAYMENTS, TREATMENTS
from molarmetrics.ingest.fields import RECORD_ORDER, RECORD_SPECS, STATUS_LABELS, RecordType
from molarmetrics.ingest.parsing import (
    DATE_FORMATS,
    MoneyError,
    ParsedFile,
    detect_date_format,
    parse_date_value,
    parse_money,
    parse_time,
    status_key,
    suggest_mapping,
    suggest_money_unit,
    suggest_record_type,
    suggest_status,
)
from molarmetrics.money import format_inr

Severity = Literal["blocking", "review", "warning", "info"]
StatusValue = Literal["completed", "cancelled", "no_show"]
MAX_TEXT = 120
MAX_AMOUNT_PAISE = 10_00_00_000_00  # ₹10 crore for a single line: larger is almost certainly a unit mistake
ISSUES_PER_GROUP_SHOWN = 20
MAX_ISSUES_KEPT = 20_000


# --- the user's choices (sent by the review screen) --------------------------------------
class FileConfig(BaseModel):
    file_id: str
    record_type: RecordType | None = None
    mapping: dict[str, str] = Field(default_factory=dict)  # field key -> column name
    date_formats: dict[str, str] = Field(default_factory=dict)  # field key -> DATE_FORMATS name
    money_unit: Literal["rupees", "paise"] | None = None
    status_map: dict[str, StatusValue] = Field(default_factory=dict)  # normalised label -> status


class ImportConfig(BaseModel):
    name: str = Field(default="", max_length=80)
    files: list[FileConfig] = Field(default_factory=list)
    review_decisions: dict[str, Literal["include", "exclude"]] = Field(default_factory=dict)


# --- the report (shown on the review screen) ----------------------------------------------
class Issue(BaseModel):
    severity: Severity
    code: str
    file_id: str | None = None
    file: str | None = None
    row: int | None = None  # spreadsheet row: the header is row 1
    field: str | None = None
    message: str
    suggestion: str = ""
    value: str | None = None


class DateFieldReport(BaseModel):
    field: str
    label: str
    column: str
    candidates: list[str]
    detected: str | None
    ambiguous: bool
    chosen: str | None
    examples: list[str]


class MoneyExample(BaseModel):
    raw: str
    interpreted: str | None


class MoneyFieldReport(BaseModel):
    field: str
    label: str
    column: str
    examples: list[MoneyExample]


class StatusLabelReport(BaseModel):
    key: str
    label: str
    count: int
    suggested: StatusValue | None
    chosen: StatusValue | None


class FileReport(BaseModel):
    file_id: str
    filename: str
    record_type: RecordType | None
    suggested_record_type: RecordType | None
    rows: int
    columns: list[str]
    mapping: dict[str, str]
    missing_required: list[str]
    date_fields: list[DateFieldReport]
    money_unit: Literal["rupees", "paise"] | None
    money_unit_suggestion: Literal["rupees", "paise"] | None
    money_fields: list[MoneyFieldReport]
    status_labels: list[StatusLabelReport]
    ignored_columns: list[str]
    blocking: int
    warnings: int


class ReviewGroup(BaseModel):
    code: str
    title: str
    description: str
    count: int
    examples: list[str]
    include_effect: str
    exclude_effect: str
    decision: Literal["include", "exclude"] | None


class ValidationReport(BaseModel):
    ready: bool
    blocking: int
    needs_review: int
    warnings: int
    issues: list[Issue]
    issues_total: int
    files: list[FileReport]
    review_groups: list[ReviewGroup]
    counts: dict[str, int]
    coverage: dict[str, str] | None
    capabilities: list[str]
    summary: str


@dataclass
class NormalizedData:
    """Clean records ready for the database, produced only when ``ready``."""

    patients: list[dict] = field(default_factory=list)
    dentists: list[dict] = field(default_factory=list)
    appointments: list[dict] = field(default_factory=list)
    treatments: list[dict] = field(default_factory=list)
    payments: list[dict] = field(default_factory=list)
    coverage: tuple[str, str] | None = None
    capabilities: list[str] = field(default_factory=list)
    import_notes: list[str] = field(default_factory=list)
    procedure_names: list[str] = field(default_factory=list)


# --- helpers ---------------------------------------------------------------------------------
def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n:,} {singular if n == 1 else (plural or singular + 's')}"


def _show(value: str, limit: int = 60) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value)).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _clean_text(value: str) -> str:
    return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", value).split())


def _day(d: date) -> str:
    return f"{d.day} {d.strftime('%b %Y')}"


def initial_config(files: list[ParsedFile], name: str = "") -> ImportConfig:
    """Suggested choices for a fresh upload: record types, column mappings and
    status labels are pre-filled for the user to check; money units are NOT
    (they must be confirmed), and ambiguous date formats are left unset."""
    configs = []
    for pf in files:
        rtype = suggest_record_type(pf.filename, pf.columns)
        cfg = FileConfig(file_id=pf.file_id, record_type=rtype)
        if rtype:
            cfg.mapping = suggest_mapping(RECORD_SPECS[rtype], pf.columns)
            if rtype == "appointments" and "status" in cfg.mapping:
                cfg.status_map = suggested_statuses(pf, cfg.mapping["status"])
        configs.append(cfg)
    return ImportConfig(name=name, files=configs)


def suggested_statuses(pf: ParsedFile, column: str) -> dict[str, StatusValue]:
    out: dict[str, StatusValue] = {}
    for _, raw in pf.column_values(column):
        key = status_key(raw)
        if key and key not in out and (s := suggest_status(raw)):
            out[key] = s
    return out


class _Collector:
    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def add(self, severity: Severity, code: str, message: str, suggestion: str = "", *, pf: ParsedFile | None = None,
            row: int | None = None, field: str | None = None, value: str | None = None) -> None:
        if len(self.issues) >= MAX_ISSUES_KEPT:
            return
        self.issues.append(Issue(severity=severity, code=code, file_id=pf.file_id if pf else None,
                                 file=pf.filename if pf else None, row=row, field=field, message=message,
                                 suggestion=suggestion, value=None if value is None else _show(value)))


def _display_issues(issues: list[Issue]) -> list[Issue]:
    """At most ISSUES_PER_GROUP_SHOWN of each kind, then one summary line."""
    order = {"blocking": 0, "review": 1, "warning": 2, "info": 3}
    groups: dict[tuple, list[Issue]] = defaultdict(list)
    for issue in issues:
        groups[(issue.severity, issue.code, issue.file_id, issue.field)].append(issue)
    shown: list[Issue] = []
    for key in sorted(groups, key=lambda k: (order[k[0]], k[2] or "", k[1], k[3] or "")):
        items = groups[key]
        shown.extend(items[:ISSUES_PER_GROUP_SHOWN])
        if len(items) > ISSUES_PER_GROUP_SHOWN:
            first = items[0]
            extra = len(items) - ISSUES_PER_GROUP_SHOWN
            shown.append(Issue(severity=first.severity, code=first.code, file_id=first.file_id, file=first.file,
                               field=first.field, message=f"…and {_plural(extra, 'more row')} with the same problem.",
                               suggestion="Download the issues report to see every row."))
    return shown


# --- per-file parsing ---------------------------------------------------------------------------
@dataclass
class _Parsed:
    pf: ParsedFile
    rtype: str
    records: list[dict]  # parsed rows that passed their own checks (with "_row")
    usable: bool  # False when the file's setup (mapping, units, formats) is incomplete
    all_ids: set[str] = field(default_factory=set)  # every ID in the file, valid rows or not


def _parse_file(pf: ParsedFile, cfg: FileConfig, out: _Collector) -> tuple[_Parsed | None, FileReport]:
    rtype = cfg.record_type
    report = FileReport(file_id=pf.file_id, filename=pf.filename, record_type=rtype,
                        suggested_record_type=suggest_record_type(pf.filename, pf.columns), rows=len(pf.rows),
                        columns=pf.columns, mapping={}, missing_required=[], date_fields=[], money_unit=cfg.money_unit,
                        money_unit_suggestion=None, money_fields=[], status_labels=[], ignored_columns=[],
                        blocking=0, warnings=0)
    for p in pf.problems:
        out.add(p.severity, p.code, p.message, p.suggestion, pf=pf, row=p.row)
    if rtype is None:
        out.add("blocking", "record_type_missing", "Choose what kind of records this file contains.",
                "Pick Appointments, Treatments, Payments, Patients or Dentists, or remove the file.", pf=pf)
        report.ignored_columns = list(pf.columns)
        return None, report
    spec = RECORD_SPECS[rtype]
    usable = not any(p.severity == "blocking" and p.code == "no_rows" for p in pf.problems)

    # Mapping: only known fields, existing columns, each column once.
    mapping: dict[str, str] = {}
    used: dict[str, str] = {}
    known = {f.key for f in spec.fields}
    for key, column in cfg.mapping.items():
        if key not in known or not column:
            continue
        if column not in pf.columns:
            out.add("blocking", "column_missing", f"The column '{_show(column)}' isn't in this file.",
                    "Choose the column again.", pf=pf, field=spec.field(key).label)
            usable = False
            continue
        if column in used:
            out.add("blocking", "column_used_twice",
                    f"The column '{_show(column)}' is mapped to both {spec.field(used[column]).label} and "
                    f"{spec.field(key).label}.", "Map each column to one field.", pf=pf)
            usable = False
            continue
        used[column] = key
        mapping[key] = column
    report.mapping = mapping
    report.ignored_columns = [c for c in pf.columns if c not in used]
    for f in spec.required_fields:
        if f.key not in mapping:
            report.missing_required.append(f.label)
            out.add("blocking", "required_field_unmapped", f"Map a column to '{f.label}' (required).",
                    f"{f.description} If the file has no such column, add one and upload it again.", pf=pf,
                    field=f.label)
            usable = False
    if rtype == "treatments" and "net_fee" not in mapping and "listed_fee" not in mapping:
        report.missing_required.append("Net fee or Listed fee")
        out.add("blocking", "fee_unmapped", "Map a column to 'Net fee' or 'Listed fee'.",
                "Billed revenue needs the amount charged for each procedure.", pf=pf, field="Net fee")
        usable = False
    if rtype == "treatments" and "net_fee" not in mapping and "listed_fee" in mapping and "discount" not in mapping:
        out.add("info", "net_from_listed", "No net fee or discount column is mapped, so the listed fee is used as "
                "the amount charged.", "Map a discount or net fee column if discounts were given.", pf=pf)
    if report.ignored_columns:
        out.add("info", "columns_ignored", "Not imported: " + ", ".join(_show(c, 40) for c in report.ignored_columns)
                + ". These columns are not stored.", "", pf=pf)

    # Date formats per mapped date field.
    formats: dict[str, str | None] = {}
    for f in spec.fields:
        if f.kind != "date" or f.key not in mapping:
            continue
        col = mapping[f.key]
        values = [v for _, v in pf.column_values(col) if v]
        det = detect_date_format(values)
        chosen = cfg.date_formats.get(f.key)
        if chosen not in DATE_FORMATS:
            chosen = None
        use = chosen or det.detected
        report.date_fields.append(DateFieldReport(field=f.key, label=f.label, column=col, candidates=det.candidates,
                                                  detected=det.detected, ambiguous=det.ambiguous, chosen=chosen,
                                                  examples=[_show(v, 30) for v in values[:3]]))
        if use is None and det.ambiguous:
            out.add("blocking", "date_format_ambiguous",
                    f"'{f.label}' dates could be day/month or month/day (for example '{_show(values[0], 30)}').",
                    "Choose the date format used in this file.", pf=pf, field=f.label)
            usable = False
        formats[f.key] = use or det.best_effort

    # Money unit (must be confirmed explicitly).
    money_fields = [f for f in spec.fields if f.kind == "money" and f.key in mapping]
    if money_fields:
        cols = [mapping[f.key] for f in money_fields]
        sample = [v for c in cols for _, v in pf.column_values(c)[:200] if v]
        report.money_unit_suggestion = suggest_money_unit(cols, sample)
        for f in money_fields:
            raw = [v for _, v in pf.column_values(mapping[f.key]) if v][:3]
            examples = []
            for v in raw:
                try:
                    interpreted = format_inr(parse_money(v, cfg.money_unit)) if cfg.money_unit else None
                except MoneyError:
                    interpreted = None
                examples.append(MoneyExample(raw=_show(v, 30), interpreted=interpreted))
            report.money_fields.append(MoneyFieldReport(field=f.key, label=f.label, column=mapping[f.key],
                                                        examples=examples))
        if cfg.money_unit is None:
            out.add("blocking", "money_unit_unconfirmed", "Confirm whether amounts in this file are in rupees or paise.",
                    "Rupees: 1500.50 means ₹1,500.50. Paise: 150050 means ₹1,500.50.", pf=pf)
            usable = False

    # Status labels.
    if rtype == "appointments" and "status" in mapping:
        counts: Counter[str] = Counter()
        first_label: dict[str, str] = {}
        for _, raw in pf.column_values(mapping["status"]):
            key = status_key(raw)
            if key:
                counts[key] += 1
                first_label.setdefault(key, _show(raw, 40))
        for key, n in counts.most_common():
            report.status_labels.append(StatusLabelReport(key=key, label=first_label[key], count=n,
                                                          suggested=suggest_status(first_label[key]),
                                                          chosen=cfg.status_map.get(key)))
            if key not in cfg.status_map:
                out.add("blocking", "status_unmapped",
                        f"The status '{first_label[key]}' ({_plural(n, 'row')}) isn't matched to completed, "
                        "cancelled or no-show.",
                        "Choose what it means. If these are future bookings, remove those rows from the file.",
                        pf=pf, field="Appointment status", value=first_label[key])
                usable = False

    if not usable:
        return _Parsed(pf, rtype, [], False), report
    records, all_ids = _parse_rows(pf, spec, mapping, formats, cfg, out)
    return _Parsed(pf, rtype, records, True, all_ids), report


def _parse_rows(pf, spec, mapping, formats, cfg, out: _Collector) -> tuple[list[dict], set[str]]:
    idx = {k: pf.columns.index(c) for k, c in mapping.items()}
    fields = {f.key: f for f in spec.fields}
    records: list[dict] = []
    seen_ids: dict[str, int] = {}
    all_ids = {_clean_text(cells[idx[spec.id_field]]) for _, cells in pf.rows} if spec.id_field in idx else set()
    for row_no, cells in pf.rows:
        rec: dict = {"_row": row_no}
        ok = True
        for key, i in idx.items():
            f = fields[key]
            raw = cells[i].strip()
            if not raw:
                if f.required:
                    out.add("blocking", "blank_required", f"Row {row_no}: {f.label} is blank.",
                            "Fill it in, or remove the row from the file.", pf=pf, row=row_no, field=f.label)
                    ok = False
                rec[key] = None
                continue
            if f.kind in ("id", "ref"):
                rec[key] = _clean_text(raw)
            elif f.kind == "text":
                text = _clean_text(raw)
                if len(text) > MAX_TEXT:
                    out.add("warning", "text_shortened", f"Row {row_no}: {f.label} is longer than {MAX_TEXT} "
                            "characters and will be shortened.", "", pf=pf, row=row_no, field=f.label, value=raw)
                    text = text[:MAX_TEXT]
                rec[key] = text
            elif f.kind == "date":
                fmt = formats.get(key)
                parsed = parse_date_value(raw, fmt) if fmt else None
                if parsed is None:
                    hint = f" in the {fmt} format" if fmt else ""
                    out.add("blocking", "invalid_date", f"Row {row_no}: '{_show(raw, 30)}' isn't a valid date{hint}.",
                            "Correct the date in the file, or choose the right date format.", pf=pf, row=row_no,
                            field=f.label, value=raw)
                    ok = False
                else:
                    rec[key], rec[f"{key}__time"] = parsed
            elif f.kind == "time":
                t = parse_time(raw)
                if t is None:
                    out.add("blocking", "invalid_time", f"Row {row_no}: '{_show(raw, 20)}' isn't a valid time.",
                            "Use a time such as 14:30 or 2:30 PM, or clear the cell.", pf=pf, row=row_no,
                            field=f.label, value=raw)
                    ok = False
                else:
                    rec[key] = t
            elif f.kind == "money":
                try:
                    paise = parse_money(raw, cfg.money_unit)
                except MoneyError as exc:
                    out.add("blocking", "invalid_amount", f"Row {row_no}: {f.label} '{_show(raw, 30)}' {exc}.",
                            "Correct the amount in the file.", pf=pf, row=row_no, field=f.label, value=raw)
                    ok = False
                    continue
                if paise > MAX_AMOUNT_PAISE:
                    out.add("blocking", "amount_too_large", f"Row {row_no}: {f.label} {format_inr(paise)} is "
                            "unusually large.", "Check the amount, and whether the file is in rupees or paise.",
                            pf=pf, row=row_no, field=f.label, value=raw)
                    ok = False
                    continue
                rec[key] = paise
            elif f.kind == "status":
                rec[key] = cfg.status_map.get(status_key(raw))
        rid = rec.get(spec.id_field)
        if rid is not None:
            if rid in seen_ids:
                out.add("blocking", "duplicate_id", f"Row {row_no}: {fields[spec.id_field].label} '{_show(rid)}' is "
                        f"already used in row {seen_ids[rid]}.",
                        "Each record needs its own ID. Remove the duplicate row or correct the ID.", pf=pf,
                        row=row_no, field=fields[spec.id_field].label, value=rid)
                ok = False
            else:
                seen_ids[rid] = row_no
        if ok:
            records.append(rec)
    return records, all_ids


# --- whole-batch validation -------------------------------------------------------------------------
def validate_batch(files: list[ParsedFile], config: ImportConfig) -> tuple[ValidationReport, list[Issue],
                                                                           NormalizedData | None]:
    """Returns (report for the screen, every issue for the CSV report,
    normalised data when ready to import)."""
    out = _Collector()
    by_id = {pf.file_id: pf for pf in files}
    cfgs = {c.file_id: c for c in config.files}
    parsed: dict[str, _Parsed] = {}
    reports: list[FileReport] = []
    type_owner: dict[str, str] = {}
    for pf in files:
        cfg = cfgs.get(pf.file_id) or FileConfig(file_id=pf.file_id)
        if cfg.record_type and cfg.record_type in type_owner:
            out.add("blocking", "duplicate_record_type",
                    f"Two files are set as {RECORD_SPECS[cfg.record_type].label} ({type_owner[cfg.record_type]} and "
                    f"{pf.filename}).", "Combine them into one file, or change one file's record type.", pf=pf)
        elif cfg.record_type:
            type_owner[cfg.record_type] = pf.filename
        p, rep = _parse_file(pf, cfg, out)
        reports.append(rep)
        if p is not None and p.rtype not in parsed:
            parsed[p.rtype] = p
    present = set(type_owner)
    if files and "appointments" not in present:
        out.add("blocking", "appointments_missing", "Add an appointments file. Every import needs appointments.",
                "Upload your appointments export together with the other files.")
    if "payments" in present and "treatments" not in present:
        out.add("blocking", "treatments_missing_for_payments",
                "Payments need a treatments file, so each payment can be linked to a treatment.",
                "Upload a treatments file too, or remove the payments file to import appointments only.")
    if "appointments" in present and "patients" not in present:
        out.add("info", "patients_not_checked", "No patients file was included, so patient codes on appointments "
                "aren't checked against a patient list.", "")
    appt_cfg = next((c for c in config.files if c.record_type == "appointments"), None)
    if appt_cfg and "dentist_id" in appt_cfg.mapping and "dentists" not in present:
        out.add("info", "dentists_not_checked", "No dentists file was included, so results by dentist show dentist "
                "codes, and the codes aren't checked against a dentist list.", "")

    review_groups: list[ReviewGroup] = []
    data: NormalizedData | None = None
    all_usable = all(p.usable for p in parsed.values()) and present <= set(parsed)
    if all_usable and "appointments" in parsed:
        data, review_groups = _cross_checks(parsed, config, out)

    for rep in reports:
        rep.blocking = sum(1 for i in out.issues if i.file_id == rep.file_id and i.severity == "blocking")
        rep.warnings = sum(1 for i in out.issues if i.file_id == rep.file_id and i.severity == "warning")
    blocking = sum(1 for i in out.issues if i.severity == "blocking")
    pending = sum(1 for g in review_groups if g.decision is None)
    warnings = sum(1 for i in out.issues if i.severity == "warning")
    ready = bool(files) and blocking == 0 and pending == 0 and data is not None
    if ready:
        summary = "Ready to import."
    elif blocking:
        summary = f"{_plural(blocking, 'problem')} to fix before importing."
    elif pending:
        summary = f"Review {_plural(pending, 'group')} of records before importing."
    else:
        summary = "Not ready to import yet."
    counts = {}
    if data is not None:
        counts = {t: len(getattr(data, t)) for t in RECORD_ORDER if t in present}
    report = ValidationReport(
        ready=ready, blocking=blocking, needs_review=pending, warnings=warnings,
        issues=_display_issues(out.issues), issues_total=len(out.issues), files=reports,
        review_groups=review_groups, counts=counts,
        coverage={"start": data.coverage[0], "end": data.coverage[1]} if data and data.coverage else None,
        capabilities=data.capabilities if data else [], summary=summary)
    return report, out.issues, data if ready else None


def _cross_checks(parsed: dict[str, _Parsed], config: ImportConfig,
                  out: _Collector) -> tuple[NormalizedData | None, list[ReviewGroup]]:
    """Relationships, fee and payment consistency, and the review groups."""
    appts = parsed["appointments"]
    treats = parsed.get("treatments")
    pays = parsed.get("payments")
    pats = parsed.get("patients")
    dents = parsed.get("dentists")

    patient_ids = {r["patient_id"] for r in pats.records} if pats else None
    dentist_ids = {r["dentist_id"] for r in dents.records} if dents else None
    appt_by_id: dict[str, dict] = {}
    for r in appts.records:
        if patient_ids is not None and r["patient_id"] not in patient_ids:
            out.add("blocking", "unknown_patient", f"Row {r['_row']}: Patient ID '{_show(r['patient_id'])}' isn't in "
                    f"{pats.pf.filename}.", "Add the patient to the patients file, or correct the ID.", pf=appts.pf,
                    row=r["_row"], field="Patient ID", value=r["patient_id"])
            continue
        if dentist_ids is not None and r.get("dentist_id") and r["dentist_id"] not in dentist_ids:
            out.add("blocking", "unknown_dentist", f"Row {r['_row']}: Dentist ID '{_show(r['dentist_id'])}' isn't in "
                    f"{dents.pf.filename}.", "Add the dentist to the dentists file, or correct the ID.", pf=appts.pf,
                    row=r["_row"], field="Dentist ID", value=r["dentist_id"])
            continue
        appt_by_id[r["appointment_id"]] = r

    # Possible duplicate appointments: same patient at the same date and time.
    slots: dict[tuple, int] = {}
    for r in appts.records:
        t = r.get("appointment_time") or r.get("appointment_date__time")
        if t is None:
            continue
        key = (r["patient_id"], r["appointment_date"], t)
        if key in slots:
            out.add("warning", "possible_duplicate_appointment", f"Row {r['_row']}: same patient, date and time as "
                    f"row {slots[key]}.", "Check whether this appointment was entered twice.", pf=appts.pf,
                    row=r["_row"])
        else:
            slots[key] = r["_row"]

    # Treatments: parent appointment, fee consistency.
    treat_by_id: dict[str, dict] = {}
    if treats:
        mapped = set(next((c.mapping for c in config.files if c.file_id == treats.pf.file_id), {}))
        dupes: dict[tuple, int] = {}
        for r in treats.records:
            if r["appointment_id"] not in appt_by_id:
                if r["appointment_id"] in appts.all_ids:
                    continue  # that appointment row has its own problem, reported above
                out.add("blocking", "unknown_appointment", f"Row {r['_row']}: Appointment ID "
                        f"'{_show(r['appointment_id'])}' isn't in {appts.pf.filename}.",
                        "Add the appointment, or correct the ID.", pf=treats.pf, row=r["_row"], field="Appointment ID",
                        value=r["appointment_id"])
                continue
            fee = _fees(r, mapped, treats.pf, out)
            if fee is None:
                continue
            r["listed_fee_paise"], r["discount_paise"], r["net_fee_paise"] = fee
            key = (r["appointment_id"], r["procedure"].lower(), fee[2])
            if key in dupes:
                out.add("warning", "possible_duplicate_treatment", f"Row {r['_row']}: same appointment, procedure and "
                        f"fee as row {dupes[key]}.", "Fine if the procedure was done twice at that visit (e.g. two "
                        "teeth); otherwise remove the duplicate.", pf=treats.pf, row=r["_row"])
            else:
                dupes[key] = r["_row"]
            treat_by_id[r["treatment_id"]] = r

    # Payments: parent treatment.
    pay_ok: list[dict] = []
    if pays:
        dupes = {}
        for r in pays.records:
            if r["treatment_id"] not in treat_by_id:
                if treats and r["treatment_id"] in treats.all_ids:
                    continue  # that treatment row has its own problem, reported above
                out.add("blocking", "unknown_treatment", f"Row {r['_row']}: Treatment ID '{_show(r['treatment_id'])}' "
                        f"isn't in {treats.pf.filename if treats else 'the treatments file'}.",
                        "Add the treatment, or correct the ID.", pf=pays.pf, row=r["_row"], field="Treatment ID",
                        value=r["treatment_id"])
                continue
            if r["amount"] == 0:
                out.add("blocking", "zero_payment", f"Row {r['_row']}: the payment amount is zero.",
                        "Remove the row, or enter the amount received.", pf=pays.pf, row=r["_row"], field="Amount paid")
                continue
            key = (r["treatment_id"], r["payment_date"], r["amount"])
            if key in dupes:
                out.add("warning", "possible_duplicate_payment", f"Row {r['_row']}: same treatment, date and amount as "
                        f"row {dupes[key]}.", "Check whether this payment was entered twice.", pf=pays.pf,
                        row=r["_row"])
            else:
                dupes[key] = r["_row"]
            pay_ok.append(r)

    # --- review groups: real inconsistencies the user must decide on ------------------------
    decisions = config.review_decisions
    groups: list[ReviewGroup] = []
    unattended = [r for r in treat_by_id.values()
                  if appt_by_id[r["appointment_id"]]["status"] in ("cancelled", "no_show")]
    excluded_treatments: set[str] = set()
    if unattended:
        n_c = sum(1 for r in unattended if appt_by_id[r["appointment_id"]]["status"] == "cancelled")
        linked = [p for p in pay_ok if p["treatment_id"] in {r["treatment_id"] for r in unattended}]
        decision = decisions.get("treatments_on_unattended_appointments")
        groups.append(ReviewGroup(
            code="treatments_on_unattended_appointments",
            title="Treatments on cancelled or no-show appointments",
            description=(f"{_plural(len(unattended), 'treatment record')} "
                         f"{'belongs' if len(unattended) == 1 else 'belong'} to appointments marked cancelled "
                         f"({n_c:,}) or no-show ({len(unattended) - n_c:,}). A cancellation fee is possible, but this "
                         "is often a status or ID mistake."),
            count=len(unattended),
            examples=[f"Row {r['_row']} in {treats.pf.filename}: {_show(r['procedure'], 40)} on appointment "
                      f"{_show(r['appointment_id'], 20)} "
                      f"({STATUS_LABELS[appt_by_id[r['appointment_id']]['status']].lower()})" for r in unattended[:5]],
            include_effect="Include them as recorded: they count in billed revenue and procedures.",
            exclude_effect="Leave them out: they are not imported" + (
                f", and neither {'is' if len(linked) == 1 else 'are'} the {_plural(len(linked), 'payment')} "
                "linked to them." if linked else "."),
            decision=decision))
        for r in unattended:
            out.add("review", "treatment_on_unattended_appointment",
                    f"Row {r['_row']}: treatment on appointment '{_show(r['appointment_id'])}', which is marked "
                    f"{STATUS_LABELS[appt_by_id[r['appointment_id']]['status']].lower()}.",
                    "Decide whether to include these treatments.", pf=treats.pf, row=r["_row"])
        if decision == "exclude":
            excluded_treatments = {r["treatment_id"] for r in unattended}

    early = [p for p in pay_ok if p["treatment_id"] not in excluded_treatments
             and p["payment_date"] < appt_by_id[treat_by_id[p["treatment_id"]]["appointment_id"]]["appointment_date"]]
    excluded_payments: set[str] = set()
    if early:
        decision = decisions.get("payments_before_treatment")
        groups.append(ReviewGroup(
            code="payments_before_treatment",
            title="Payments dated before their treatment",
            description=(f"{_plural(len(early), 'payment')} {'is' if len(early) == 1 else 'are'} dated before the "
                         "appointment of the treatment paid for. This can be an advance or deposit, or a date "
                         "typed wrongly."),
            count=len(early),
            examples=[f"Row {p['_row']} in {pays.pf.filename}: paid {_day(p['payment_date'])}, treatment on "
                      f"{_day(appt_by_id[treat_by_id[p['treatment_id']]['appointment_id']]['appointment_date'])}"
                      for p in early[:5]],
            include_effect="Include them as recorded: they count in collections on their payment dates.",
            exclude_effect="Leave them out: they are not imported, so they don't count in collections or reduce "
                           "outstanding balances.",
            decision=decision))
        for p in early:
            out.add("review", "payment_before_treatment",
                    f"Row {p['_row']}: payment dated {_day(p['payment_date'])}, before its treatment's appointment.",
                    "Decide whether to include these payments.", pf=pays.pf, row=p["_row"])
        if decision == "exclude":
            excluded_payments = {p["payment_id"] for p in early}

    # Final record sets after the user's decisions.
    final_treatments = [r for r in treat_by_id.values() if r["treatment_id"] not in excluded_treatments]
    final_payments = [p for p in pay_ok if p["treatment_id"] not in excluded_treatments
                      and p["payment_id"] not in excluded_payments]

    # Payments must not exceed the treatment's net fee (on what will actually be imported).
    paid: Counter[str] = Counter()
    for p in final_payments:
        paid[p["treatment_id"]] += p["amount"]
    for tid, total in paid.items():
        net = treat_by_id[tid]["net_fee_paise"]
        if total > net:
            out.add("blocking", "overpaid_treatment", f"Payments for treatment '{_show(tid)}' add up to "
                    f"{format_inr(total)}, more than its net fee of {format_inr(net)}.",
                    "Check for a duplicated payment or a wrong amount.", pf=pays.pf, row=treat_by_id[tid]["_row"],
                    field="Amount paid")

    # Registration after the first visit (warning only).
    if pats and any(r.get("registration_date") for r in pats.records):
        first_visit: dict[str, date] = {}
        for r in appt_by_id.values():
            d = r["appointment_date"]
            if r["patient_id"] not in first_visit or d < first_visit[r["patient_id"]]:
                first_visit[r["patient_id"]] = d
        for r in pats.records:
            reg, first = r.get("registration_date"), first_visit.get(r["patient_id"])
            if reg and first and reg > first:
                out.add("warning", "registered_after_first_visit", f"Row {r['_row']}: patient '{_show(r['patient_id'])}' "
                        f"registered on {_day(reg)}, after their first appointment on {_day(first)}.",
                        "Check the registration date.", pf=pats.pf, row=r["_row"])

    if any(i.severity == "blocking" for i in out.issues):
        return None, groups

    data = NormalizedData()
    data.patients = [{"patient_id": r["patient_id"], "registration_date": _iso(r.get("registration_date"))}
                     for r in (pats.records if pats else [])]
    data.dentists = [{"dentist_id": r["dentist_id"], "display_name": r.get("dentist_name"),
                      "specialty": r.get("specialty")} for r in (dents.records if dents else [])]
    data.appointments = [{"appointment_id": r["appointment_id"], "patient_id": r["patient_id"],
                          "dentist_id": r.get("dentist_id"), "appointment_datetime": _datetime(r),
                          "status": r["status"]} for r in appt_by_id.values()]
    data.treatments = [{"treatment_id": r["treatment_id"], "appointment_id": r["appointment_id"],
                        "procedure_name": r["procedure"], "listed_fee_paise": r["listed_fee_paise"],
                        "discount_paise": r["discount_paise"], "net_fee_paise": r["net_fee_paise"]}
                       for r in final_treatments]
    data.payments = [{"payment_id": p["payment_id"], "treatment_id": p["treatment_id"],
                      "payment_date": p["payment_date"].isoformat(), "amount_paise": p["amount"],
                      "payment_method": p.get("payment_method")} for p in final_payments]
    days = [r["appointment_date"] for r in appt_by_id.values()] + [p["payment_date"] for p in final_payments]
    data.coverage = (min(days).isoformat(), max(days).isoformat()) if days else None
    data.capabilities = [CAP_APPOINTMENTS]
    if any(a["dentist_id"] for a in data.appointments):
        data.capabilities.append(DENTIST_BREAKDOWN)
    if data.treatments:
        data.capabilities.append(TREATMENTS)
    if data.payments:
        data.capabilities.append(PAYMENTS)
    data.procedure_names = sorted({t["procedure_name"] for t in data.treatments}, key=str.lower)
    data.import_notes = _import_notes(groups, unattended, early, pay_ok, excluded_treatments)
    return data, groups


def _fees(r: dict, mapped: set[str], pf: ParsedFile, out: _Collector) -> tuple[int | None, int | None, int] | None:
    """(listed, discount, net) in paise, or None after reporting a problem.
    Missing amounts are never treated as zero."""
    listed, discount, net = r.get("listed_fee"), r.get("discount"), r.get("net_fee")
    row = r["_row"]
    if "discount" in mapped and discount is None and (listed is not None or net is None):
        out.add("blocking", "blank_discount", f"Row {row}: Discount is blank.", "Enter 0 if there was no discount.",
                pf=pf, row=row, field="Discount")
        return None
    if net is None and "net_fee" in mapped:
        out.add("blocking", "blank_net_fee", f"Row {row}: Net fee is blank.", "Enter the amount charged.", pf=pf,
                row=row, field="Net fee")
        return None
    if net is None:
        if listed is None:
            out.add("blocking", "blank_fee", f"Row {row}: the listed fee is blank.", "Enter the fee charged.", pf=pf,
                    row=row, field="Listed fee")
            return None
        if discount is not None and discount > listed:
            out.add("blocking", "discount_exceeds_fee", f"Row {row}: the discount {format_inr(discount)} is more than "
                    f"the listed fee {format_inr(listed)}.", "Correct the discount or the fee.", pf=pf, row=row,
                    field="Discount")
            return None
        return listed, discount, listed - (discount or 0)
    if listed is not None and discount is not None:
        if discount > listed:
            out.add("blocking", "discount_exceeds_fee", f"Row {row}: the discount {format_inr(discount)} is more than "
                    f"the listed fee {format_inr(listed)}.", "Correct the discount or the fee.", pf=pf, row=row,
                    field="Discount")
            return None
        if net != listed - discount:
            out.add("blocking", "fee_mismatch", f"Row {row}: net fee {format_inr(net)} isn't the listed fee "
                    f"{format_inr(listed)} minus the discount {format_inr(discount)}.",
                    "Correct one of the three amounts.", pf=pf, row=row, field="Net fee")
            return None
        return listed, discount, net
    if listed is not None and net > listed:
        out.add("blocking", "net_above_listed", f"Row {row}: net fee {format_inr(net)} is more than the listed fee "
                f"{format_inr(listed)}.", "Correct one of the amounts.", pf=pf, row=row, field="Net fee")
        return None
    if listed is None and discount is not None:
        return net + discount, discount, net
    return listed, None, net


def _import_notes(groups, unattended, early, pay_ok, excluded_treatments) -> list[str]:
    notes = []
    for g in groups:
        if g.code == "treatments_on_unattended_appointments":
            n = len(unattended)
            if g.decision == "include":
                notes.append(f"{_plural(n, 'treatment record')} on cancelled or no-show appointments "
                             f"{'is' if n == 1 else 'are'} included in billed revenue as recorded (reviewed at import).")
            else:
                linked = sum(1 for p in pay_ok if p["treatment_id"] in excluded_treatments)
                extra = f", with {_plural(linked, 'linked payment')}" if linked else ""
                notes.append(f"{_plural(n, 'treatment record')} on cancelled or no-show appointments "
                             f"{'was' if n == 1 else 'were'} left out at import{extra}.")
        elif g.code == "payments_before_treatment":
            n = len(early)
            if g.decision == "include":
                notes.append(f"{_plural(n, 'payment')} dated before {'its' if n == 1 else 'their'} treatment "
                             f"{'is' if n == 1 else 'are'} included as recorded (reviewed at import).")
            else:
                notes.append(f"{_plural(n, 'payment')} dated before {'its' if n == 1 else 'their'} treatment "
                             f"{'was' if n == 1 else 'were'} left out at import, so "
                             f"{'it is' if n == 1 else 'they are'} not in collections or balances.")
    return notes


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _datetime(r: dict) -> str:
    t: time | None = r.get("appointment_time") or r.get("appointment_date__time") or time(0, 0)
    return f"{r['appointment_date'].isoformat()} {t.strftime('%H:%M:%S')}"
