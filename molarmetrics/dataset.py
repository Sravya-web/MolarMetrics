"""Which dataset an analysis runs on, and what that dataset can support.

Beginner note
-------------
The analytics were first written for one bundled synthetic clinic. Uploaded
clinic data differs in three ways that matter to every calculation:

* its **coverage** (the first and last dates it contains),
* its **capabilities** (an appointments-only upload cannot show revenue), and
* its **procedure names** (a clinic's own names, not the synthetic catalog).

A ``DatasetContext`` carries those facts. Analyses receive it explicitly, so
a result can never silently use the sample dataset's period or procedures.
When no context is given, ``SAMPLE_CONTEXT`` reproduces the original sample
behaviour exactly (the Streamlit app and the original tests rely on that).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Literal

from molarmetrics import DATA_NOTICE
from molarmetrics.data.catalog import PERIOD_END, PERIOD_START, PROCEDURE_NAMES

# Capability names. "outstanding" is derived: it needs treatments AND payments.
APPOINTMENTS = "appointments"
DENTIST_BREAKDOWN = "dentist_breakdown"
TREATMENTS = "treatments"
PAYMENTS = "payments"
ALL_CAPABILITIES = (APPOINTMENTS, DENTIST_BREAKDOWN, TREATMENTS, PAYMENTS)

UPLOADED_NOTICE = "UPLOADED CLINIC DATA"


@dataclass(frozen=True)
class DatasetContext:
    kind: Literal["sample", "uploaded"]
    name: str
    coverage_start: str  # ISO date, inclusive
    coverage_end: str  # ISO date, inclusive
    capabilities: frozenset[str]
    procedure_names: tuple[str, ...]
    notice: str
    # Plain-language notes about inconsistencies the user reviewed at import
    # (e.g. payments dated before their treatment). Shown with every money result.
    import_notes: tuple[str, ...] = field(default=())

    def has(self, capability: str) -> bool:
        if capability == "outstanding":
            return TREATMENTS in self.capabilities and PAYMENTS in self.capabilities
        return capability in self.capabilities

    @property
    def is_sample(self) -> bool:
        return self.kind == "sample"

    @property
    def record_types(self) -> list[str]:
        """Human names of the record types present, e.g. ['appointments', 'treatments']."""
        out = ["appointments"]
        if self.has(TREATMENTS):
            out.append("treatments (procedures and fees)")
        if self.has(PAYMENTS):
            out.append("payments")
        return out

    def years(self) -> list[int]:
        return list(range(int(self.coverage_start[:4]), int(self.coverage_end[:4]) + 1))

    def example_year(self) -> int:
        """The latest calendar year with data, for examples in prompts and suggestions."""
        return int(self.coverage_end[:4])


SAMPLE_CONTEXT = DatasetContext(
    kind="sample",
    name="Sample clinic",
    coverage_start=PERIOD_START.isoformat(),
    coverage_end=PERIOD_END.isoformat(),
    capabilities=frozenset(ALL_CAPABILITIES),
    procedure_names=PROCEDURE_NAMES,
    notice=DATA_NOTICE,
)


def resolve(ctx: DatasetContext | None) -> DatasetContext:
    return ctx if ctx is not None else SAMPLE_CONTEXT


# --- uploaded datasets store their context in a small key/value table ---------------------
META_TABLE_DDL = "CREATE TABLE dataset_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"


def write_meta(conn: sqlite3.Connection, values: dict) -> None:
    conn.executemany("INSERT INTO dataset_meta (key, value) VALUES (?, ?)",
                     [(k, json.dumps(v, ensure_ascii=False)) for k, v in values.items()])


def read_meta(conn: sqlite3.Connection) -> dict:
    return {k: json.loads(v) for k, v in conn.execute("SELECT key, value FROM dataset_meta")}


def context_from_meta(meta: dict) -> DatasetContext:
    return DatasetContext(
        kind="uploaded",
        name=str(meta["name"]),
        coverage_start=str(meta["coverage_start"]),
        coverage_end=str(meta["coverage_end"]),
        capabilities=frozenset(meta["capabilities"]),
        procedure_names=tuple(meta.get("procedure_names", [])),
        notice=UPLOADED_NOTICE,
        import_notes=tuple(meta.get("import_notes", [])),
    )


def context_from_db(conn: sqlite3.Connection, name: str | None = None) -> DatasetContext:
    """Context for an uploaded dataset, read from its own database. ``name``
    overrides the stored name (the user may rename a dataset later)."""
    ctx = context_from_meta(read_meta(conn))
    if name is not None and name != ctx.name:
        ctx = DatasetContext(**{**ctx.__dict__, "name": name})
    return ctx
