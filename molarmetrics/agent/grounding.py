"""Number grounding check.

After the model answers, every number in its prose is looked up in the tool
results it actually received (and the user's question). Numbers that cannot
be found are flagged in the UI. It is a heuristic safety net, not a proof:
it catches invented or self-calculated numbers, but cannot judge wording.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# Digits with optional Indian/international thousands separators and decimals.
# The look-behind skips identifiers such as P0001 or D02.
_NUMBER = re.compile(r"(?<![A-Za-z0-9.])(\d{1,3}(?:,\d{2,3})+|\d+)(\.\d+)?")
# Markdown list markers ("1. ", "2) ") are formatting, not claims.
_LIST_MARKER = re.compile(r"^(\s*)\d{1,2}[.)](\s+)", re.MULTILINE)


def extract_numbers(text: str) -> list[tuple[str, Decimal]]:
    found = []
    text = _LIST_MARKER.sub(r"\1\2", text or "")
    for m in _NUMBER.finditer(text):
        token = m.group(0)
        try:
            found.append((token, Decimal(token.replace(",", ""))))
        except InvalidOperation:  # pragma: no cover - regex only yields digits
            continue
    return found


@dataclass
class GroundingReport:
    tool_called: bool
    numbers_checked: int
    unverified: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.numbers_checked == 0 or (self.tool_called and not self.unverified)

    @property
    def message(self) -> str:
        if self.numbers_checked == 0:
            return "The answer contains no numbers to check."
        if not self.tool_called:
            return "No tool was called, so the numbers in this answer are unverified."
        if self.unverified:
            return ("Not found in the tool results: " + ", ".join(self.unverified)
                    + ". Rely on the table and chart, which are calculated directly from the data.")
        return f"All {self.numbers_checked} numbers in the answer appear in the tool results."


def check_grounding(answer: str, tool_contents: list[str], question: str = "") -> GroundingReport:
    allowed: set[Decimal] = set()
    for source in [*tool_contents, question]:
        allowed.update(value for _, value in extract_numbers(source))
    numbers = extract_numbers(answer)
    unverified = []
    for token, value in numbers:
        if value not in allowed and token not in unverified:
            unverified.append(token)
    return GroundingReport(tool_called=bool(tool_contents), numbers_checked=len(numbers), unverified=unverified)
