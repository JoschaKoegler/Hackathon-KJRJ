"""Official figures next to what a comment assumes.

``pipeline/annahmen_und_fakten_<project>.json`` is the sheet. The page
shows it for that city. All shows the Heilbronn sheet, the only one so far.
The date window does not filter these figures.
"""

from __future__ import annotations

import json

from .config import CITY_BY_PROJECT, ROOT

PIPELINE = ROOT / "pipeline"
ALL_SHEET = "Heilbronn_Seilbahn"


def load(project: str) -> dict | None:
    """Sheet for one project key, or nothing when that file is absent."""
    path = PIPELINE / f"annahmen_und_fakten_{project}.json"
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as handle:
        sheet = json.load(handle)
    if not isinstance(sheet, dict):
        return None
    return sheet


def sheet_for_city(city: str | None) -> dict | None:
    """Sheet behind this city button. Other projects stay empty until a file exists."""
    if not city or city == "All":
        return load(ALL_SHEET)
    keys = [key for key, mapped in CITY_BY_PROJECT.items() if mapped == city]
    if len(keys) != 1:
        return None
    return load(keys[0])
