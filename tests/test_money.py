"""Exact money handling: integer paise, INR formatting, Indian digit grouping."""

from decimal import Decimal

import pytest

from molarmetrics.money import (
    format_inr,
    format_inr_compact,
    indian_grouping,
    paise_to_decimal,
    paise_to_plain,
    rupees_to_paise,
)


def test_rupees_to_paise_is_exact_and_integer_only():
    assert rupees_to_paise(1500) == 150_000
    with pytest.raises(TypeError):
        rupees_to_paise(15.5)


def test_paise_to_decimal_has_no_float_drift():
    # 0.1 + 0.2 != 0.3 in floats; in integer paise the sum is exact.
    assert sum([10, 20]) == 30
    assert paise_to_decimal(30) == Decimal("0.30")
    assert sum(paise_to_decimal(p) for p in [1] * 1000) == Decimal("10.00")


@pytest.mark.parametrize("paise, plain", [(150050, "1500.50"), (5, "0.05"), (0, "0.00"), (-12345, "-123.45")])
def test_paise_to_plain_for_csv(paise, plain):
    assert paise_to_plain(paise) == plain


@pytest.mark.parametrize("n, grouped", [(0, "0"), (999, "999"), (1000, "1,000"), (100000, "1,00,000"),
                                        (12345678, "1,23,45,678"), (1000000000, "1,00,00,00,000")])
def test_indian_grouping(n, grouped):
    assert indian_grouping(n) == grouped


def test_format_inr():
    assert format_inr(543_210_050) == "₹54,32,100.50"
    assert format_inr(543_210_000, show_paise=False) == "₹54,32,100"
    assert format_inr(-150_000) == "-₹1,500.00"


def test_format_inr_compact_uses_lakh_and_crore():
    assert format_inr_compact(68_09_100_00) == "₹68.09 L"
    assert format_inr_compact(1_37_99_880_00) == "₹1.38 Cr"
    assert format_inr_compact(45_000_00) == "₹45,000"
