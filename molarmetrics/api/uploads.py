"""Upload batches: files waiting on the review screen, and importing them.

* Files are stored under ``runtime/staging/<random batch id>/<random file id>.csv``.
  The user's filename is kept only as a display label; it never becomes a path.
* Size, count, type and content are checked before anything is stored.
* Importing re-validates on the server, builds the dataset atomically, then
  registers and activates it in one registry transaction. On any failure the
  new files are removed and the previously active dataset is unchanged.
"""

from __future__ import annotations

import re
import shutil
import time
import uuid
from collections import OrderedDict
from pathlib import Path

from molarmetrics.analytics.export import csv_safe_text, write_csv
from molarmetrics.api.retention import Retention
from molarmetrics.api.schemas import TypeSuggestion, UploadBatchOut, UploadedFileOut, UploadRejection
from molarmetrics.api.settings import WebSettings
from molarmetrics.api.store import BatchRow, DatasetRow, Store
from molarmetrics.ingest.build import atomic_import
from molarmetrics.ingest.fields import RECORD_ORDER, RECORD_SPECS
from molarmetrics.ingest.parsing import ParsedFile, UploadRejected, parse_csv, suggest_mapping
from molarmetrics.ingest.validate import (
    ImportConfig,
    Issue,
    ValidationReport,
    initial_config,
    suggested_statuses,
    validate_batch,
)

PREVIEW_ROWS = 5
_SEVERITY_LABEL = {"blocking": "Must fix", "review": "Needs review", "warning": "Check", "info": "Note"}


class UploadError(ValueError):
    def __init__(self, rejections: list[UploadRejection]):
        super().__init__("upload rejected")
        self.rejections = rejections


class NotReady(ValueError):
    def __init__(self, report: ValidationReport):
        super().__init__("not ready")
        self.report = report


def display_filename(name: str) -> str:
    """A safe label from a user-supplied filename (never used as a path)."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return base[:120] or "upload.csv"


def clean_dataset_name(name: str) -> str:
    return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", name or "").split())[:80]


class UploadService:
    def __init__(self, store: Store, settings: WebSettings, retention: Retention):
        self.store = store
        self.settings = settings
        self.retention = retention
        self._cache: OrderedDict[tuple[str, str], ParsedFile] = OrderedDict()

    # --- creating ---------------------------------------------------------------------
    def create(self, session_id: str, files: list[tuple[str, bytes]]) -> UploadBatchOut:
        if not files:
            raise UploadError([UploadRejection(filename="", message="Choose at least one CSV file.")])
        if len(files) > self.settings.max_files:
            raise UploadError([UploadRejection(filename="", message=(
                f"Upload up to {self.settings.max_files} files at a time."))])
        rejections, parsed = [], []
        for name, data in files:
            label = display_filename(name)
            if not label.lower().endswith(".csv"):
                rejections.append(UploadRejection(filename=label, message="Only .csv files can be uploaded."))
                continue
            if len(data) > self.settings.max_file_bytes:
                rejections.append(UploadRejection(filename=label, message=(
                    f"This file is larger than {self.settings.max_file_mb} MB.")))
                continue
            try:
                parsed.append((parse_csv(uuid.uuid4().hex[:12], label, data), data))
            except UploadRejected as exc:
                rejections.append(UploadRejection(filename=label, message=str(exc)))
        if rejections:
            raise UploadError(rejections)
        batch_id = uuid.uuid4().hex
        folder = self.settings.staging_dir / batch_id
        folder.mkdir(parents=True)
        try:
            for pf, data in parsed:
                (folder / f"{pf.file_id}.csv").write_bytes(data)
            meta = [{"file_id": pf.file_id, "filename": pf.filename, "size": pf.size} for pf, _ in parsed]
            config = initial_config([pf for pf, _ in parsed], name=_default_name())
            now = time.time()
            self.store.add_batch(BatchRow(id=batch_id, session_id=session_id, created_at=now, last_used_at=now,
                                          files=meta, config=config.model_dump()))
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        for pf, _ in parsed:
            self._remember(batch_id, pf)
        return self.describe(self.store.get_batch(batch_id))

    # --- reading -----------------------------------------------------------------------
    def _remember(self, batch_id: str, pf: ParsedFile) -> None:
        self._cache[(batch_id, pf.file_id)] = pf
        while len(self._cache) > 12:
            self._cache.popitem(last=False)

    def parsed_files(self, batch: BatchRow) -> list[ParsedFile]:
        out = []
        for meta in batch.files:
            key = (batch.id, meta["file_id"])
            pf = self._cache.get(key)
            if pf is None:
                data = (self.settings.staging_dir / batch.id / f"{meta['file_id']}.csv").read_bytes()
                pf = parse_csv(meta["file_id"], meta["filename"], data)
                self._remember(batch.id, pf)
            out.append(pf)
        return out

    def describe(self, batch: BatchRow, config: ImportConfig | None = None) -> UploadBatchOut:
        files = self.parsed_files(batch)
        config = config or ImportConfig.model_validate(batch.config)
        report, _, _ = validate_batch(files, config)
        return UploadBatchOut(
            batch_id=batch.id,
            files=[UploadedFileOut(file_id=pf.file_id, filename=pf.filename, size=pf.size, rows=len(pf.rows),
                                   columns=pf.columns, preview=[cells for _, cells in pf.rows[:PREVIEW_ROWS]])
                   for pf in files],
            config=config, report=report, suggestions={pf.file_id: _type_suggestions(pf) for pf in files})

    # --- review actions ---------------------------------------------------------------
    def validate(self, batch: BatchRow, config: ImportConfig) -> ValidationReport:
        config = self._own_files_only(batch, config)
        report, _, _ = validate_batch(self.parsed_files(batch), config)
        self.store.update_batch(batch.id, config=config.model_dump())
        return report

    def remove_file(self, batch: BatchRow, file_id: str) -> UploadBatchOut | None:
        remaining = [f for f in batch.files if f["file_id"] != file_id]
        if len(remaining) == len(batch.files):
            return None
        (self.settings.staging_dir / batch.id / f"{file_id}.csv").unlink(missing_ok=True)
        self._cache.pop((batch.id, file_id), None)
        config = ImportConfig.model_validate(batch.config)
        config.files = [c for c in config.files if c.file_id != file_id]
        self.store.update_batch(batch.id, files=remaining, config=config.model_dump())
        return self.describe(self.store.get_batch(batch.id))

    def issues_csv(self, batch: BatchRow) -> bytes:
        _, issues, _ = validate_batch(self.parsed_files(batch), ImportConfig.model_validate(batch.config))
        return write_csv([_issue_row(i) for i in issues] or [_issue_row(None)])

    def cancel(self, batch: BatchRow) -> None:
        for meta in batch.files:
            self._cache.pop((batch.id, meta["file_id"]), None)
        self.retention.remove_batch(batch)

    # --- import ------------------------------------------------------------------------
    def import_batch(self, batch: BatchRow, config: ImportConfig, session_id: str) -> DatasetRow:
        config = self._own_files_only(batch, config)
        files = self.parsed_files(batch)
        report, _, data = validate_batch(files, config)  # always re-validated here, never trusted
        if not report.ready or data is None:
            raise NotReady(report)
        name = clean_dataset_name(config.name) or _default_name()
        dataset_id = uuid.uuid4().hex
        db_path, meta = atomic_import(data, name, self.settings.datasets_dir, dataset_id)
        now = time.time()
        row = DatasetRow(id=dataset_id, session_id=session_id, kind="uploaded", name=name, db_path=str(db_path),
                         created_at=now, last_used_at=now,
                         meta={k: meta[k] for k in ("coverage_start", "coverage_end", "capabilities", "counts",
                                                    "import_notes")})
        try:
            self.store.add_dataset(row, activate=True)
        except Exception:
            shutil.rmtree(Path(db_path).parent, ignore_errors=True)
            raise
        self.cancel(batch)  # staged raw files are no longer needed
        return row

    @staticmethod
    def _own_files_only(batch: BatchRow, config: ImportConfig) -> ImportConfig:
        ids = {f["file_id"] for f in batch.files}
        config = config.model_copy(deep=True)
        config.files = [c for c in config.files if c.file_id in ids]
        return config


def _type_suggestions(pf: ParsedFile) -> dict[str, TypeSuggestion]:
    out = {}
    for rtype in RECORD_ORDER:
        mapping = suggest_mapping(RECORD_SPECS[rtype], pf.columns)
        statuses = suggested_statuses(pf, mapping["status"]) if rtype == "appointments" and "status" in mapping else {}
        out[rtype] = TypeSuggestion(mapping=mapping, status_map=statuses)
    return out


def _default_name() -> str:
    return f"Clinic data uploaded {time.strftime('%d %b %Y')}"


def _issue_row(issue: Issue | None) -> dict:
    if issue is None:
        return {"file": "", "row": "", "field": "", "severity": "", "problem": "No issues found.",
                "suggested_fix": "", "value": ""}
    return {"file": csv_safe_text(issue.file or ""), "row": issue.row if issue.row is not None else "",
            "field": csv_safe_text(issue.field or ""), "severity": _SEVERITY_LABEL[issue.severity],
            "problem": csv_safe_text(issue.message), "suggested_fix": csv_safe_text(issue.suggestion),
            "value": csv_safe_text(issue.value or "")}
