"""Downloadable CSV templates and the example bundle.

Templates are generated from the record specs in ``fields.py``, so a template
can never drift from what the importer expects. Money columns end in ``_inr``
to make the unit obvious (amounts in rupees, e.g. 1500.00).
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

from molarmetrics.config import PROJECT_ROOT
from molarmetrics.ingest.fields import RECORD_ORDER, RECORD_SPECS, STATUS_LABELS

EXAMPLE_BUNDLE_DIR = PROJECT_ROOT / "examples" / "sunrise-dental"


def template_header(rtype: str) -> list[str]:
    spec = RECORD_SPECS[rtype]
    return [f"{f.key}_inr" if f.kind == "money" else f.key for f in spec.fields]


def template_csv(rtype: str) -> bytes:
    spec = RECORD_SPECS[rtype]
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(template_header(rtype))
    writer.writerows(spec.template_rows)
    return buf.getvalue().encode("utf-8")


def templates_readme() -> str:
    lines = ["MolarMetrics CSV templates", "=========================", "",
             "Each file holds one kind of record. Only appointments.csv is required.",
             "Dates: YYYY-MM-DD (other common formats are accepted; you confirm them when uploading).",
             "Money: rupees with up to 2 decimals, e.g. 1500.00. Use 0 for no discount; never leave amounts blank.",
             f"Appointment status: {', '.join(v.lower() for v in STATUS_LABELS.values())} "
             "(other labels can be matched while reviewing).",
             "Do not include patient names or contact details: use patient codes.", ""]
    for rtype in RECORD_ORDER:
        spec = RECORD_SPECS[rtype]
        lines += [f"{rtype}.csv", "-" * (len(rtype) + 4), f"One row = {spec.one_row}", spec.purpose]
        for f, header in zip(spec.fields, template_header(rtype)):
            lines.append(f"  {header:<22} {'required' if f.required else 'optional':<9} {f.description}")
        lines.append("")
    lines.append("Treatments need either net_fee_inr or listed_fee_inr (net fee = listed fee - discount).")
    return "\n".join(lines) + "\n"


def templates_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rtype in RECORD_ORDER:
            zf.writestr(f"molarmetrics-templates/{rtype}.csv", template_csv(rtype))
        zf.writestr("molarmetrics-templates/README.txt", templates_readme())
    return buf.getvalue()


def example_bundle_zip(directory: Path = EXAMPLE_BUNDLE_DIR) -> bytes:
    """The small, coherent example clinic (CSV files only)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(directory.glob("*.csv")):
            zf.write(path, f"{directory.name}/{path.name}")
    return buf.getvalue()


def record_type_catalog() -> list[dict]:
    """What each record type is, its fields, and its template (for the UI)."""
    return [{
        "key": spec.key, "label": spec.label, "one_row": spec.one_row, "purpose": spec.purpose,
        "depends_on": spec.depends_on, "has_money": spec.has_money,
        "fields": [{"key": f.key, "label": f.label, "kind": f.kind, "required": f.required,
                    "description": f.description} for f in spec.fields],
        "template_url": f"/api/templates/{spec.key}.csv",
    } for spec in (RECORD_SPECS[t] for t in RECORD_ORDER)]
