"""Colours and small style helpers for the MolarMetrics UI.

The chart palette was checked with a colour-vision-deficiency validator
(OKLab distances) against the white chart surface:
teal / navy-blue / amber -> worst adjacent CVD Delta E 18.4 (target >= 8),
normal-vision Delta E 19.4 (floor 15), every slot >= 3:1 contrast on white.
Dark navy is reserved for text, not data marks (it is too dark to sit in the
same visual "loudness" band as the other series).
"""

from __future__ import annotations

# --- brand / UI ---------------------------------------------------------------------
NAVY_TEXT = "#1b2f4b"  # headings and primary text
TEXT_SECONDARY = "#4a5a70"
TEXT_MUTED = "#7a8799"
TEAL_UI = "#0b7f75"  # buttons and accents (4.9:1 with white text)
SURFACE = "#ffffff"
GRID = "#e6eaef"  # hairline gridlines
BASELINE = "#c5cfda"  # axis / zero line

# --- validated categorical chart slots (fixed order, never cycled) -----------------
TEAL = "#0a9b8e"
BLUE = "#2f5fa8"
AMBER = "#c96a1d"

# Colour follows the ENTITY, so "billed revenue" is the same blue in every chart.
SERIES_COLORS: dict[str, str] = {
    "collected_paise": TEAL,
    "billed_paise": BLUE,
    "completed": TEAL,
    "cancelled": BLUE,
    "no_show": AMBER,
    "no_show_rate_pct": AMBER,
    "treatment_count": TEAL,
    "scheduled": BLUE,
    "outstanding_paise": BLUE,
}
SERIES_LABELS: dict[str, str] = {
    "collected_paise": "Collections",
    "billed_paise": "Billed revenue",
    "completed": "Completed",
    "cancelled": "Cancelled",
    "no_show": "No-show",
    "no_show_rate_pct": "No-show rate",
    "treatment_count": "Treatment records",
    "scheduled": "Scheduled",
    "outstanding_paise": "Outstanding",
}

FONT_FAMILY = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"

APP_CSS = f"""
<style>
h1, h2, h3 {{ color: {NAVY_TEXT}; letter-spacing: -0.01em; }}
.mm-synthetic {{
    display: inline-block; padding: 0.15rem 0.55rem; border-radius: 999px;
    border: 1px solid #e3b98f; background: #fdf4ec; color: #8a4a12;
    font-size: 0.78rem; font-weight: 600; letter-spacing: 0.04em;
}}
.mm-tagline {{ color: {TEXT_SECONDARY}; margin-top: -0.6rem; }}
[data-testid="stMetricValue"] {{ color: {NAVY_TEXT}; }}
</style>
"""

SYNTHETIC_BADGE_HTML = '<span class="mm-synthetic">SYNTHETIC DEMO DATA</span>'
