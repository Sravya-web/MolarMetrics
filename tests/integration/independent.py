"""Independent reference calculations for the live integration checks.

These use pandas on the exported CSV files: a completely different code path
from the SQL inside the MolarMetrics tools. Agreement between the two is
meaningful evidence; agreement between two copies of the same SQL would not be.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd


def load(csv_dir: Path) -> dict[str, pd.DataFrame]:
    tables = {}
    for name in ("patients", "dentists", "appointments", "treatments", "payments"):
        tables[name] = pd.read_csv(csv_dir / f"molarmetrics_{name}.csv", dtype={"tooth_number": "Int64"})
    a = tables["appointments"]
    a["day"] = a["appointment_datetime"].str.slice(0, 10)
    a["month"] = a["appointment_datetime"].str.slice(0, 7)
    t = tables["treatments"].merge(a[["appointment_id", "patient_id", "day", "month"]], on="appointment_id",
                                   how="left", validate="many_to_one")
    tables["treatments_dated"] = t
    p = tables["payments"]
    p["month"] = p["payment_date"].str.slice(0, 7)
    return tables


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return float((Decimal(numerator) * 100 / Decimal(denominator)).quantize(Decimal("0.1"), ROUND_HALF_UP))


def billed_paise(T, start, end) -> int:
    t = T["treatments_dated"]
    return int(t.loc[(t["day"] >= start) & (t["day"] <= end), "net_fee_paise"].sum())


def collected_paise(T, start, end) -> int:
    p = T["payments"]
    return int(p.loc[(p["payment_date"] >= start) & (p["payment_date"] <= end), "amount_paise"].sum())


def monthly_billed_collected(T, year: int) -> dict[str, tuple[int, int]]:
    t, p = T["treatments_dated"], T["payments"]
    billed = t[t["month"].str.startswith(str(year))].groupby("month")["net_fee_paise"].sum()
    coll = p[p["month"].str.startswith(str(year))].groupby("month")["amount_paise"].sum()
    months = [f"{year}-{m:02d}" for m in range(1, 13)]
    return {m: (int(billed.get(m, 0)), int(coll.get(m, 0))) for m in months}


def top_procedures_by_billed(T, start, end, n) -> list[tuple[str, int]]:
    t = T["treatments_dated"]
    sums = t[(t["day"] >= start) & (t["day"] <= end)].groupby("procedure_name")["net_fee_paise"].sum()
    ranked = sorted(((name, int(v)) for name, v in sums.items()), key=lambda x: (-x[1], x[0]))
    return ranked[:n]


def top_procedures_combined_share(T, start, end, n) -> float | None:
    """Share of all billed revenue taken by the top-n procedures (independent of the SQL)."""
    top_total = sum(v for _, v in top_procedures_by_billed(T, start, end, n))
    return _pct(top_total, billed_paise(T, start, end))


def no_show_by_month(T, year: int) -> dict[str, float | None]:
    a = T["appointments"]
    a = a[a["month"].str.startswith(str(year))]
    out = {}
    for m in [f"{year}-{k:02d}" for k in range(1, 13)]:
        rows = a[a["month"] == m]
        out[m] = _pct(int((rows["status"] == "no_show").sum()), len(rows))
    return out


def no_show_rate(T, start, end) -> float | None:
    a = T["appointments"]
    rows = a[(a["day"] >= start) & (a["day"] <= end)]
    return _pct(int((rows["status"] == "no_show").sum()), len(rows))


def outstanding_paise(T, as_of: str) -> int:
    t, p = T["treatments_dated"], T["payments"]
    treated = t[t["day"] <= as_of]
    paid = p[(p["payment_date"] <= as_of) & (p["treatment_id"].isin(treated["treatment_id"]))]
    return int(treated["net_fee_paise"].sum()) - int(paid["amount_paise"].sum())


def top_dentists_by_completed(T, start, end) -> tuple[list[str], int]:
    a = T["appointments"]
    done = a[(a["status"] == "completed") & (a["day"] >= start) & (a["day"] <= end)]
    counts = done.groupby("dentist_id").size()
    best = int(counts.max())
    names = T["dentists"].set_index("dentist_id")["fictional_display_name"]
    return [names[d] for d in sorted(counts[counts == best].index)], best


def returning_patients(T, start, end) -> int:
    """Rank each patient's completed visits over ALL history; a visit ranked 2+
    inside the window means that patient was returning."""
    a = T["appointments"]
    done = a[a["status"] == "completed"].sort_values(["patient_id", "appointment_datetime"]).copy()
    done["visit_number"] = done.groupby("patient_id").cumcount() + 1
    in_window = done[(done["day"] >= start) & (done["day"] <= end)]
    return int(in_window.loc[in_window["visit_number"] >= 2, "patient_id"].nunique())


def procedure_patients(T, names: list[str], start, end) -> dict[str, int]:
    t = T["treatments_dated"]
    t = t[(t["day"] >= start) & (t["day"] <= end)]
    return {n: int(t.loc[t["procedure_name"] == n, "patient_id"].nunique()) for n in names}


def procedure_counts(T, names: list[str], start, end) -> dict[str, int]:
    t = T["treatments_dated"]
    t = t[(t["day"] >= start) & (t["day"] <= end)]
    return {n: int((t["procedure_name"] == n).sum()) for n in names}
