"""Reading uploaded CSV files and interpreting their cells.

Beginner notes
--------------
* Uploaded files are untrusted. They are size-limited, must be text (no NUL
  bytes), and every structural problem is reported, never "fixed" silently.
* Row numbers match what a spreadsheet shows: the header is row 1, so the
  first data row is row 2. Blank lines still count, so numbers stay aligned.
* Dates: some files are ambiguous. "03/04/2025" is 3 April (DD/MM) or 4 March
  (MM/DD). When every value in a column fits both, MolarMetrics asks the user
  instead of guessing.
* Money is parsed with ``Decimal`` (exact) and stored as integer paise.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from molarmetrics.ingest.fields import RECORD_SPECS, STATUS_SYNONYMS, RecordSpec

MAX_COLUMNS = 100
MAX_ROWS = 200_000
MIN_YEAR, MAX_YEAR = 1950, 2100


class UploadRejected(ValueError):
    """The file cannot be read at all (shown to the user as-is: plain language)."""


@dataclass
class StructuralProblem:
    severity: str  # "blocking" | "warning" | "info"
    code: str
    row: int | None
    message: str
    suggestion: str


@dataclass
class ParsedFile:
    file_id: str
    filename: str
    size: int
    encoding: str
    delimiter: str
    columns: list[str]
    # (spreadsheet row number, cells) for every non-blank data row, cells padded to len(columns)
    rows: list[tuple[int, list[str]]]
    problems: list[StructuralProblem] = field(default_factory=list)

    def column_values(self, column: str) -> list[tuple[int, str]]:
        idx = self.columns.index(column)
        return [(n, cells[idx].strip()) for n, cells in self.rows]


# --- reading -------------------------------------------------------------------------------
def _decode(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding), "utf-8" if encoding == "utf-8-sig" else "windows-1252"
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1"), "latin-1"


def _sniff_delimiter(text: str) -> str:
    first = next((line for line in text.splitlines() if line.strip()), "")
    counts = {d: first.count(d) for d in (",", ";", "\t", "|")}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] > 0 else ","


def parse_csv(file_id: str, filename: str, data: bytes) -> ParsedFile:
    """Parse one uploaded CSV. Raises ``UploadRejected`` when the file cannot
    be read as CSV at all; other problems are returned for the review screen."""
    if data[:4] == b"PK\x03\x04":
        raise UploadRejected("This looks like an Excel workbook. Save it as CSV (comma separated) and upload it again.")
    if b"\x00" in data:
        raise UploadRejected("This file doesn't look like a CSV text file. Export it as CSV and upload it again.")
    text, encoding = _decode(data)
    if not text.strip():
        raise UploadRejected("This file is empty.")
    delimiter = _sniff_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    problems: list[StructuralProblem] = []
    try:
        records = list(reader)
    except csv.Error:
        raise UploadRejected("This file couldn't be read as CSV. Check that quotes are balanced, then export it "
                             "as CSV again.") from None
    header_index = next((i for i, r in enumerate(records) if any(c.strip() for c in r)), None)
    if header_index is None:
        raise UploadRejected("This file is empty.")
    raw_header = [c.strip().lstrip("﻿") for c in records[header_index]]
    while raw_header and not raw_header[-1]:
        raw_header.pop()  # trailing empty header cells from spreadsheet exports
    if not raw_header:
        raise UploadRejected("The first row should hold column names, but it is empty.")
    if len(raw_header) > MAX_COLUMNS:
        raise UploadRejected(f"This file has {len(raw_header)} columns; the limit is {MAX_COLUMNS}.")

    columns: list[str] = []
    seen: dict[str, int] = {}
    for i, name in enumerate(raw_header, start=1):
        label = name or f"Column {i}"
        if not name:
            problems.append(StructuralProblem("info", "unnamed_column", 1, f"Column {i} has no name.",
                                              f"It is shown as 'Column {i}'. Name it in the file if you need it."))
        key = label.lower()
        if key in seen:
            new_label = f"{label} (column {i})"
            problems.append(StructuralProblem(
                "warning", "duplicate_column_name", 1,
                f"Two columns are named '{label}' (columns {seen[key]} and {i}).",
                f"The second is shown as '{new_label}'. Check you map the right one."))
            label = new_label
        seen.setdefault(key, i)
        columns.append(label)

    rows: list[tuple[int, list[str]]] = []
    width = len(columns)
    for offset, cells in enumerate(records[header_index + 1:], start=header_index + 2):
        if not any(c.strip() for c in cells):
            continue  # blank line: skipped, but row numbers stay aligned with the spreadsheet
        while len(cells) > width and not cells[-1].strip():
            cells = cells[:-1]  # trailing empty cells are harmless
        if len(cells) > width:
            problems.append(StructuralProblem(
                "blocking", "too_many_values", offset,
                f"Row {offset} has {len(cells)} values but there are {width} column names.",
                "A value probably contains an unquoted comma. Fix the row in the file and upload it again."))
            continue
        rows.append((offset, cells + [""] * (width - len(cells))))
        if len(rows) > MAX_ROWS:
            raise UploadRejected(f"This file has more than {MAX_ROWS:,} rows, which is more than MolarMetrics "
                                 "can import at once. Split it by date range.")
    if not rows:
        problems.append(StructuralProblem("blocking", "no_rows", None, "This file has column names but no data rows.",
                                          "Add records to the file, or remove it from this upload."))
    if encoding != "utf-8":
        problems.append(StructuralProblem("info", "encoding", None,
                                          "This file isn't UTF-8, so it was read as Windows text.",
                                          "Check that names with special characters look right in the preview."))
    return ParsedFile(file_id=file_id, filename=filename, size=len(data), encoding=encoding,
                      delimiter=delimiter, columns=columns, rows=rows, problems=problems)


# --- suggestions --------------------------------------------------------------------------------
def normalise_header(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split())


def suggest_record_type(filename: str, columns: list[str]) -> str | None:
    """Best-guess record type from the filename and the column headers."""
    name = normalise_header(filename.rsplit(".", 1)[0])
    headers = {normalise_header(c) for c in columns}
    best, best_score = None, 0.0
    for spec in RECORD_SPECS.values():
        score = 0.0
        if any(re.search(rf"\b{re.escape(h)}\b", name) for h in spec.filename_hints):
            score += 3
        mapping = suggest_mapping(spec, columns)
        score += sum(2 if spec.field(k).required else 1 for k in mapping)
        # The record's own ID column is strong evidence.
        if spec.id_field in mapping and normalise_header(mapping[spec.id_field]) != "id":
            score += 2
        score -= 0.5 * sum(1 for f in spec.required_fields if f.key not in mapping)
        if headers and score > best_score:
            best, best_score = spec.key, score
    return best if best_score >= 3 else None


_UNIT_WORDS = {"rs", "inr", "rupee", "rupees", "paise", "paisa", "in", "dd", "mm", "yyyy", "yy", "hh", "ss"}


def _core(norm: str) -> str:
    return " ".join(w for w in norm.split() if w not in _UNIT_WORDS)


def suggest_mapping(spec: RecordSpec, columns: list[str]) -> dict[str, str]:
    """field key -> column, using exact header synonyms first, then the field's
    own key. Each column is used once. Only a suggestion: the user confirms."""
    normalised = {c: normalise_header(c) for c in columns}
    used: set[str] = set()
    out: dict[str, str] = {}
    # Pass 1: exact matches, required fields first so they win contested columns.
    for f in sorted(spec.fields, key=lambda f: not f.required):
        candidates = {normalise_header(f.key)} | {normalise_header(s) for s in f.synonyms} | {normalise_header(f.label)}
        for col, norm in normalised.items():
            if col not in used and norm in candidates:
                out[f.key] = col
                used.add(col)
                break
    # Pass 2: the same, ignoring unit and format words ("Amount (Rs)", "Visit date DD/MM/YYYY").
    for f in sorted(spec.fields, key=lambda f: not f.required):
        if f.key in out:
            continue
        candidates = {normalise_header(f.key)} | {normalise_header(s) for s in f.synonyms} | {normalise_header(f.label)}
        for col, norm in normalised.items():
            if col not in used and _core(norm) and _core(norm) in candidates:
                out[f.key] = col
                used.add(col)
                break
    # Pass 3: a header that contains a multi-word synonym ("Date of first visit").
    for f in spec.fields:
        if f.key in out:
            continue
        for col, norm in normalised.items():
            if col in used:
                continue
            if any(" " in s and normalise_header(s) in norm for s in (f.label, *f.synonyms)):
                out[f.key] = col
                used.add(col)
                break
    return out


# --- dates ----------------------------------------------------------------------------------
DATE_FORMATS: dict[str, tuple[str, ...]] = {
    "YYYY-MM-DD": ("%Y-%m-%d",),
    "DD/MM/YYYY": ("%d/%m/%Y",),
    "MM/DD/YYYY": ("%m/%d/%Y",),
    "DD-MM-YYYY": ("%d-%m-%Y",),
    "MM-DD-YYYY": ("%m-%d-%Y",),
    "DD.MM.YYYY": ("%d.%m.%Y",),
    "YYYY/MM/DD": ("%Y/%m/%d",),
    "D MMM YYYY": ("%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%B-%Y"),
    "MMM D, YYYY": ("%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y"),
}
DATE_FORMAT_EXAMPLES = {
    "YYYY-MM-DD": "2025-04-03", "DD/MM/YYYY": "03/04/2025 = 3 April", "MM/DD/YYYY": "04/03/2025 = 3 April",
    "DD-MM-YYYY": "03-04-2025 = 3 April", "MM-DD-YYYY": "04-03-2025 = 3 April", "DD.MM.YYYY": "03.04.2025",
    "YYYY/MM/DD": "2025/04/03", "D MMM YYYY": "3 Apr 2025", "MMM D, YYYY": "Apr 3, 2025",
}
# Pairs that read the same digits in opposite day/month order.
AMBIGUOUS_PAIRS = (("DD/MM/YYYY", "MM/DD/YYYY"), ("DD-MM-YYYY", "MM-DD-YYYY"))
_PREFERENCE = ("YYYY-MM-DD", "DD/MM/YYYY", "DD-MM-YYYY", "DD.MM.YYYY", "D MMM YYYY", "YYYY/MM/DD", "MMM D, YYYY",
               "MM/DD/YYYY", "MM-DD-YYYY")
_DATE_TIME = re.compile(
    r"^(?P<date>.+?)(?:[ T]+(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\s*(?:[AaPp]\.?\s?[Mm]\.?)?)Z?)?$")
_TIME = re.compile(r"^(?P<h>\d{1,2}):(?P<m>\d{2})(?::(?P<s>\d{2})(?:\.\d+)?)?\s*(?P<ampm>[AaPp]\.?\s?[Mm]\.?)?$")


def parse_time(text: str) -> time | None:
    m = _TIME.match(text.strip())
    if not m:
        return None
    h, mi, s = int(m["h"]), int(m["m"]), int(m["s"] or 0)
    if m["ampm"]:
        pm = m["ampm"].lower().startswith("p")
        if not 1 <= h <= 12:
            return None
        h = (h % 12) + (12 if pm else 0)
    if h > 23 or mi > 59 or s > 59:
        return None
    return time(h, mi, s)


def parse_date_value(text: str, fmt: str) -> tuple[date, time | None] | None:
    """Parse one cell with one named format. Returns (date, optional time)."""
    m = _DATE_TIME.match(text.strip())
    if not m:
        return None
    date_part, time_part = m["date"].strip(), m["time"]
    parsed = None
    for pattern in DATE_FORMATS[fmt]:
        try:
            parsed = datetime.strptime(date_part, pattern).date()
            break
        except ValueError:
            continue
    if parsed is None or not MIN_YEAR <= parsed.year <= MAX_YEAR:
        return None
    t = None
    if time_part:
        t = parse_time(time_part)
        if t is None:
            return None
    return parsed, t


@dataclass
class DateDetection:
    candidates: list[str]  # formats that read EVERY value
    detected: str | None  # the format to use without asking (None when ambiguous or unreadable)
    ambiguous: bool
    best_effort: str | None  # the format reading the most values (for error reporting)


def detect_date_format(values: list[str]) -> DateDetection:
    values = [v for v in values if v]
    if not values:
        return DateDetection([], None, False, None)
    sample = values if len(values) <= 5000 else values[:2500] + values[-2500:]
    scores = {fmt: sum(1 for v in sample if parse_date_value(v, fmt)) for fmt in DATE_FORMATS}
    full = [fmt for fmt in _PREFERENCE if scores[fmt] == len(sample)]
    if not full:
        best = max(_PREFERENCE, key=lambda f: (scores[f], -_PREFERENCE.index(f)))
        return DateDetection([], None, False, best if scores[best] else None)
    ambiguous = any(a in full and b in full for a, b in AMBIGUOUS_PAIRS)
    return DateDetection(full, None if ambiguous else full[0], ambiguous, full[0])


# --- money ------------------------------------------------------------------------------------
class MoneyError(ValueError):
    pass


_CURRENCY = re.compile(r"^(?:₹|rs\.?|inr)\s*|\s*(?:₹|rs\.?|inr|/-)$", re.I)


def parse_money(raw: str, unit: str) -> int:
    """Exact amount in integer paise. ``unit`` is "rupees" or "paise".
    Raises MoneyError with a plain-language reason. Blank cells are the
    caller's business (they are missing values, never zero)."""
    text = raw.strip()
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1].strip()
    if text.startswith("-"):
        negative, text = True, text[1:].strip()
    previous = None
    while previous != text:  # strip "Rs.", "₹", "INR", "/-" at either end
        previous, text = text, _CURRENCY.sub("", text).strip()
    if text.startswith("-"):
        negative, text = True, text[1:].strip()
    if "," in text:
        if "." in text and text.rfind(",") > text.rfind("."):
            raise MoneyError("uses a comma for decimals; use a dot, e.g. 1500.50")
        whole = text.split(".", 1)[0]
        # Indian grouping (1,23,456) or Western grouping (123,456) only: anything
        # else ("12,34") might be a decimal comma, so it is rejected, not guessed.
        if not (re.fullmatch(r"\d{1,2}(?:,\d{2})*,\d{3}", whole) or re.fullmatch(r"\d{1,3}(?:,\d{3})+", whole)):
            raise MoneyError("has commas in unexpected places")
        text = text.replace(",", "")
    if not re.fullmatch(r"\d+(?:\.\d+)?", text):
        raise MoneyError("is not a plain amount")
    if negative:
        raise MoneyError("is negative")
    try:
        value = Decimal(text)
    except InvalidOperation:  # pragma: no cover - the regex only allows digits
        raise MoneyError("is not a plain amount") from None
    if unit == "paise":
        if value != value.to_integral_value():
            raise MoneyError("has a fraction of a paisa; paise must be whole numbers")
        return int(value)
    if -value.as_tuple().exponent > 2 and value != value.quantize(Decimal("0.01")):
        raise MoneyError("has more than 2 decimal places")
    return int(value * 100)


def suggest_money_unit(column_names: list[str], values: list[str]) -> str | None:
    headers = " ".join(normalise_header(c) for c in column_names)
    if "paise" in headers or "paisa" in headers:
        return "paise"
    if re.search(r"\b(inr|rs|rupees?)\b", headers) or any("₹" in v or re.search(r"\d\.\d{1,2}\b", v)
                                                          for v in values[:200]):
        return "rupees"
    return None


# --- statuses ---------------------------------------------------------------------------------
def status_key(raw: str) -> str:
    return normalise_header(raw)


_STATUS_LOOKUP = {normalise_header(s): value for value, syns in STATUS_SYNONYMS.items() for s in syns}


def suggest_status(raw: str) -> str | None:
    return _STATUS_LOOKUP.get(status_key(raw))
