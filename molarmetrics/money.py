"""Exact money handling.

Beginner note
-------------
Computers store decimals like 0.1 inexactly, so adding many rupee amounts
as floats can drift by a paisa. MolarMetrics therefore stores and sums money
as whole numbers of PAISE (1 rupee = 100 paise) and only converts to rupees
for display or CSV export.
"""

from __future__ import annotations

from decimal import Decimal

PAISE_PER_RUPEE = 100


def rupees_to_paise(rupees: int) -> int:
    """Convert a whole-rupee amount to integer paise."""
    if not isinstance(rupees, int):
        raise TypeError("rupees must be an int (use paise for fractional amounts)")
    return rupees * PAISE_PER_RUPEE


def paise_to_decimal(paise: int) -> Decimal:
    """Exact rupee value as a Decimal, e.g. 12345 -> Decimal('123.45')."""
    return Decimal(int(paise)) / PAISE_PER_RUPEE


def paise_to_plain(paise: int) -> str:
    """Plain two-decimal rupees for CSV files: 150050 -> '1500.50'."""
    paise = int(paise)
    sign = "-" if paise < 0 else ""
    rupees, rem = divmod(abs(paise), PAISE_PER_RUPEE)
    return f"{sign}{rupees}.{rem:02d}"


def indian_grouping(n: int) -> str:
    """Group digits the Indian way: 12345678 -> '1,23,45,678'."""
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


def format_inr(paise: int, show_paise: bool = True) -> str:
    """Format paise as INR with Indian digit grouping.

    >>> format_inr(543210050)
    '₹54,32,100.50'
    >>> format_inr(543210000, show_paise=False)
    '₹54,32,100'
    """
    paise = int(paise)
    sign = "-" if paise < 0 else ""
    rupees, rem = divmod(abs(paise), PAISE_PER_RUPEE)
    if show_paise:
        return f"{sign}₹{indian_grouping(rupees)}.{rem:02d}"
    # Round half up to whole rupees for compact display only.
    if rem >= 50:
        rupees += 1
    return f"{sign}₹{indian_grouping(rupees)}"


def format_inr_compact(paise: int) -> str:
    """Short label for KPI cards: ₹54.32 L (lakh) or ₹1.25 Cr (crore)."""
    value = paise_to_decimal(paise)
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= Decimal(10_000_000):
        return f"{sign}₹{(value / Decimal(10_000_000)).quantize(Decimal('0.01'))} Cr"
    if value >= Decimal(100_000):
        return f"{sign}₹{(value / Decimal(100_000)).quantize(Decimal('0.01'))} L"
    return format_inr(int(paise), show_paise=False)
