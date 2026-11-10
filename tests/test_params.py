"""Tool argument validation: normalise harmless variations, reject bad input."""

import pytest
from pydantic import ValidationError

from molarmetrics.analytics.params import (
    AppointmentArgs,
    FinanceArgs,
    KpiArgs,
    ProcedureArgs,
    parse_date,
    resolve_procedure_name,
)


def test_defaults_cover_the_full_data_period():
    assert KpiArgs().model_dump() == {"start_date": "2024-01-01", "end_date": "2025-12-31"}


@pytest.mark.parametrize("value, role, expected", [
    ("2025", "start", "2025-01-01"), ("2025", "end", "2025-12-31"), (2025, "start", "2025-01-01"),
    ("2025-02", "end", "2025-02-28"), ("2024-02", "end", "2024-02-29"),  # leap year
    ("31 December 2025", "point", "2025-12-31"), ("31st December 2025", "point", "2025-12-31"),
    ("Dec 31, 2025", "point", "2025-12-31"), ("31/12/2025", "point", "2025-12-31"),
])
def test_lenient_but_unambiguous_date_parsing(value, role, expected):
    assert parse_date(value, role).isoformat() == expected


@pytest.mark.parametrize("bad", ["last year", "2025-13", "1850-01-01", "yesterday", "2025-02-30"])
def test_unparseable_or_out_of_range_dates_are_rejected(bad):
    with pytest.raises(ValueError):
        parse_date(bad, "start")


def test_invalid_date_range_is_rejected():
    with pytest.raises(ValidationError, match="after end_date"):
        KpiArgs(start_date="2025-12-31", end_date="2025-01-01")


def test_null_dates_fall_back_to_defaults():
    assert KpiArgs(start_date=None, end_date="").model_dump() == {"start_date": "2024-01-01",
                                                                  "end_date": "2025-12-31"}


def test_enum_values_are_normalised():
    args = AppointmentArgs(group_by="Dentist", metric="No-show rate")
    assert (args.group_by, args.metric) == ("dentist", "no_show_rate")
    assert FinanceArgs(metric="Outstanding").metric == "outstanding_balance"
    assert ProcedureArgs(metric="count").metric == "treatment_count"


def test_unknown_metrics_and_groupings_are_rejected():
    with pytest.raises(ValidationError):
        AppointmentArgs(metric="revenue")
    with pytest.raises(ValidationError):
        AppointmentArgs(group_by="locality")
    with pytest.raises(ValidationError):
        FinanceArgs(metric="profit")
    with pytest.raises(ValidationError):
        ProcedureArgs(metric="success_rate")


@pytest.mark.parametrize("top_n", [0, -1, 21, 500])
def test_excessive_or_invalid_limits_are_rejected(top_n):
    with pytest.raises(ValidationError):
        ProcedureArgs(top_n=top_n)


def test_top_n_accepts_numeric_strings_and_null():
    assert ProcedureArgs(top_n="5").top_n == 5
    assert ProcedureArgs(top_n=None).top_n == 10


def test_procedure_names_resolve_aliases_and_deduplicate():
    assert ProcedureArgs(procedures=["RCT", "root canal", "Extraction"]).procedures == [
        "Root canal treatment (session)", "Extraction"]
    assert ProcedureArgs(procedures="fillings and crowns").procedures == ["Composite filling", "Crown placement"]
    assert resolve_procedure_name("CONSULTATION") == "Consultation"


def test_unknown_procedure_is_rejected_with_valid_options():
    with pytest.raises(ValidationError, match="Valid procedures"):
        ProcedureArgs(procedures=["teeth whitening"])


def test_extra_keys_from_the_model_are_ignored():
    assert "sql" not in KpiArgs(sql="DROP TABLE patients").model_dump()


def test_schema_offered_to_the_model_uses_simple_types_and_enums():
    schema = AppointmentArgs.model_json_schema()["properties"]
    assert schema["metric"]["enum"] == ["status_counts", "no_show_rate", "completed_visits"]
    assert schema["start_date"]["type"] == "string"
    assert ProcedureArgs.model_json_schema()["properties"]["top_n"]["maximum"] == 20
