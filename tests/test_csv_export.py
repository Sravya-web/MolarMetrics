"""CSV downloads contain exact INR values (from integer paise) and the synthetic notice."""

import csv
import io

from molarmetrics.analytics import analyses as A
from molarmetrics.analytics.params import FinanceArgs, KpiArgs
from molarmetrics.ui.components import csv_filename, result_csv_bytes


def _rows(result):
    return list(csv.DictReader(io.StringIO(result_csv_bytes(result).decode("utf-8"))))


def test_monthly_csv_uses_exact_inr_from_paise(mini_conn):
    r = A.finances(mini_conn, FinanceArgs(start_date="2025-01-01", end_date="2025-02-28"))
    rows = _rows(r)
    assert [row["month"] for row in rows] == ["2025-01", "2025-02"]
    assert (rows[0]["billed_inr"], rows[0]["collected_inr"]) == ("4850.00", "3850.00")  # hand-calculated
    assert rows[1]["billed_inr"] == "15500.00"
    assert all(row["data_notice"] == "SYNTHETIC DEMO DATA" for row in rows)
    assert csv_filename(r).startswith("molarmetrics_") and csv_filename(r).endswith("_synthetic.csv")


def test_kpi_csv_lists_metrics_with_units(mini_conn):
    r = A.clinic_kpis(mini_conn, KpiArgs(start_date="2025-01-01", end_date="2025-02-28"))
    rows = {row["metric"]: row for row in _rows(r)}
    assert (rows["Billed revenue"]["value"], rows["Billed revenue"]["unit"]) == ("20350.00", "INR")
    assert (rows["No-show rate"]["value"], rows["No-show rate"]["unit"]) == ("22.2", "percent")
    assert rows["No-show rate"]["note"] == "2 no-shows / 9 scheduled appointments"
