"""Shared helpers for the upload/web tests: load the example bundles, make
small CSV files in memory, and apply the choices a user makes on the review
screen. Expected totals are the hand calculations in examples/README.md."""

from __future__ import annotations

import csv
import io
import sqlite3
from pathlib import Path

from molarmetrics.config import PROJECT_ROOT
from molarmetrics.dataset import context_from_db
from molarmetrics.ingest.build import atomic_import
from molarmetrics.ingest.parsing import ParsedFile, parse_csv
from molarmetrics.ingest.validate import ImportConfig, initial_config, validate_batch

EXAMPLES = PROJECT_ROOT / "examples"
DATE_FIELD = {"appointments": "appointment_date", "payments": "payment_date", "patients": "registration_date"}

# Hand-calculated totals (paise) from examples/README.md.
SUNRISE = {"billed": 4_700_000, "collected": 3_720_000, "outstanding": 980_000, "scheduled": 16, "completed": 11,
           "no_show_rate": 18.8, "unique": 8, "returning": 3, "start": "2025-01-06", "end": "2025-03-12"}
LAKEVIEW = {"billed": 4_100_000, "collected": 3_100_000, "outstanding": 1_000_000, "scheduled": 10, "completed": 7,
            "no_show_rate": 20.0, "unique": 6, "returning": 1, "start": "2024-07-02", "end": "2024-09-30"}
LAKEVIEW_DECISIONS = {"payments_before_treatment": "include", "treatments_on_unattended_appointments": "exclude"}


def bundle_files(name: str, only: tuple[str, ...] | None = None) -> list[Path]:
    return [p for p in sorted((EXAMPLES / name).glob("*.csv")) if only is None or p.stem in only]


def load_bundle(name: str, only: tuple[str, ...] | None = None) -> list[ParsedFile]:
    return [parse_csv(f"f{i}", p.name, p.read_bytes()) for i, p in enumerate(bundle_files(name, only))]


def csv_bytes(header: list[str], rows: list[list]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def choices(files: list[ParsedFile], name: str = "Test clinic", *, unit: str | None = None,
            date_format: str | None = None, decisions: dict | None = None) -> ImportConfig:
    """The suggested configuration plus the user's explicit confirmations."""
    cfg = initial_config(files, name)
    for c in cfg.files:
        if unit and c.record_type in ("treatments", "payments"):
            c.money_unit = unit
        if date_format and c.record_type in DATE_FIELD:
            c.date_formats[DATE_FIELD[c.record_type]] = date_format
    cfg.review_decisions = dict(decisions or {})
    return cfg


def sunrise_config(files):
    return choices(files, "Sunrise Dental", unit="rupees", date_format="DD/MM/YYYY")


def lakeview_config(files, decisions=LAKEVIEW_DECISIONS):
    return choices(files, "Lakeview Dental", unit="paise", decisions=decisions)


def import_files(tmp_path: Path, files, cfg, dataset_id: str = "ds1"):
    report, _, data = validate_batch(files, cfg)
    assert report.ready, [i.message for i in report.issues if i.severity in ("blocking", "review")]
    db_path, _ = atomic_import(data, cfg.name, tmp_path / "datasets", dataset_id)
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        ctx = context_from_db(conn)
    finally:
        conn.close()
    return db_path, ctx
