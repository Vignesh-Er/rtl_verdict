"""Shared color palette for every rtlverdict chart/dashboard surface -
defined once here so matplotlib figures (scripts/make_charts.py) and the
later static dashboard (Phase 5) use identical verdict colors, never two
palettes drifting apart. Values are the dataviz skill's validated status
palette (good/warning/serious/critical - status colors are fixed, not
themed, and clear 3:1 contrast on both light and dark chart surfaces
unchanged) plus its chart chrome/ink roles.

Verdict -> status mapping (semantic, not arbitrary):
  KEEP       = good     - a real, formally-confirmed bug the testbench caught
  SILENT     = critical - a real, formally-confirmed bug the testbench MISSED
  ERROR      = warning  - never reached verification (fidelity guard rejected it)
  QUARANTINE = muted     - not a confirmed bug either way; deliberately NOT a
               status color (this project treats QUARANTINE as a neutral,
               labeled class, never a discard - see FINDINGS.md) - it recedes
               rather than competing with the three real-outcome colors.
"""

from __future__ import annotations

# Status palette (fixed, not themed - same hex on light and dark surfaces).
STATUS = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}

VERDICT_COLORS = {
    "KEEP": STATUS["good"],
    "SILENT": STATUS["critical"],
    "ERROR": STATUS["warning"],
    "QUARANTINE": "#898781",  # muted ink, deliberately not a status color - see module docstring
}

# Verdict draw order for stacked/composition charts - fixed, never re-sorted
# by value (color-by-identity, not color-by-rank, per the dataviz skill).
VERDICT_ORDER = ["KEEP", "SILENT", "QUARANTINE", "ERROR"]

# Chart chrome & ink (light chart surface - these are static report figures,
# not a theme-reactive surface).
CHROME = {
    "surface": "#fcfcfb",
    "primary_ink": "#0b0b0b",
    "secondary_ink": "#52514e",
    "muted_ink": "#898781",
    "gridline": "#e1e0d9",
    "baseline": "#c3c2b7",
}

# First two categorical slots - used only where a chart needs a generic
# two-series contrast that ISN'T a verdict (e.g. Fig 2's coverage points
# against its silent-rate bars). Fixed order, never cycled.
CATEGORICAL = {
    "series_1": "#2a78d6",  # blue
    "series_2": "#eb6834",  # orange
}
