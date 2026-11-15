"""Kuratierte Themen — liest ``00_data/themes.json`` und ``00_data/facts.json``.

Die Zuordnung selbst steht in ``01_vorverarbeitung/07_themen_zuordnung.py``.
Dieses Modul baut nur die Anteile für die gewählte Stadt und das Faktenblatt.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

from .config import CITY_BY_PROJECT, FACTS_FILE, THEMES_FILE

CURATED_TERMS_NOTE = (
    "Share of posts in this window. A theme counts when it appears in the passage "
    "around the cable car, not in the rest of the article. A post can count in more than one."
)
CURATED_ARGUMENTS_NOTE = (
    "Hopes and fears count only when that passage states a judgement. "
    "Naming the topic is not enough. A post can count in more than one."
)

_CACHE: dict[str, dict] | None = None
_EMPTY = {"themes": [], "hopes": [], "fears": [], "evidence": {}}


def _load() -> dict[str, dict]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    found: dict[str, dict] = {}
    if THEMES_FILE.is_file():
        with THEMES_FILE.open(encoding="utf-8") as handle:
            bundle = json.load(handle)
        if not isinstance(bundle, dict):
            bundle = {}
        for project, payload in sorted(bundle.items()):
            if not isinstance(payload, dict):
                continue
            project = str((payload.get("meta") or {}).get("projekt") or project)
            by_mention: dict[str, list[dict]] = defaultdict(list)
            for row in payload.get("zuordnungen") or []:
                mention = str(row.get("mention_id") or "")
                if mention:
                    by_mention[mention].append(row)
            order: dict[tuple[str, str], int] = {}
            sections: dict[str, list[dict]] = {}
            for polarity, section in (("thema", "themen"), ("hope", "hopes"), ("fear", "fears")):
                entries = list(payload.get(section) or [])
                sections[polarity] = entries
                for index, entry in enumerate(entries):
                    order[(polarity, str(entry.get("id")))] = index
            found[project] = {
                "by_mention": by_mention,
                "order": order,
                "sections": sections,
            }
    _CACHE = found
    return found


def project_for_city(city: str | None) -> str | None:
    """Project key when this city button is a single project with a curated file."""
    if not city or city == "All":
        return None
    keys = [key for key, mapped in CITY_BY_PROJECT.items() if mapped == city]
    if len(keys) != 1:
        return None
    key = keys[0]
    return key if key in _load() else None


def notes_for(project: str, mention_ids) -> dict[str, dict]:
    """Theme, hope, and fear labels for each mention, plus one evidence snippet."""
    catalog = _load().get(project)
    if catalog is None:
        return {str(mention): dict(_EMPTY) for mention in mention_ids}
    order = catalog["order"]
    result = {}
    for mention in mention_ids:
        key = str(mention)
        grouped: dict[str, list[tuple[int, str]]] = {"thema": [], "hope": [], "fear": []}
        evidence: dict[str, str] = {}
        for row in catalog["by_mention"].get(key, []):
            polarity = row.get("kategorie")
            if polarity not in grouped:
                continue
            label = str(row.get("label") or row.get("id") or "")
            if not label:
                continue
            grouped[polarity].append((order.get((polarity, str(row.get("id"))), 999), label))
            beleg = str(row.get("beleg") or "").strip()
            if beleg and label not in evidence:
                evidence[label] = beleg

        def labels(polarity: str) -> list[str]:
            seen: set[str] = set()
            names: list[str] = []
            for _, label in sorted(grouped[polarity]):
                if label in seen:
                    continue
                seen.add(label)
                names.append(label)
            return names

        result[key] = {
            "themes": labels("thema"),
            "hopes": labels("hope"),
            "fears": labels("fear"),
            "evidence": evidence,
        }
    return result


def profile(project: str, mention_ids, polarity: str, channels: dict | None = None) -> list[dict]:
    """One row per theme, hope, or fear that appears in the selected posts.

    ``mention_ids`` is one id per post in the window. ``share`` divides the
    count by that number of posts. A post counts once per item.
    """
    catalog = _load().get(project)
    if catalog is None:
        return []
    selected = [str(mention) for mention in mention_ids]
    wanted = set(selected)
    total = len(selected)
    channels = channels or {}
    buckets: dict[str, dict] = {}
    for entry in catalog["sections"].get(polarity, []):
        buckets[str(entry.get("id"))] = {
            "id": entry.get("id"),
            "label": entry.get("label") or entry.get("id"),
            "description": entry.get("beschreibung") or "",
            "posts": set(),
            "evidence": [],
            "channels": defaultdict(int),
        }
    for mention in wanted:
        for row in catalog["by_mention"].get(mention, []):
            if row.get("kategorie") != polarity:
                continue
            bucket = buckets.get(str(row.get("id")))
            if bucket is None or mention in bucket["posts"]:
                continue
            bucket["posts"].add(mention)
            channel = channels.get(mention) or ""
            if channel:
                bucket["channels"][channel] += 1
            beleg = str(row.get("beleg") or "").strip()
            if beleg and len(bucket["evidence"]) < 2 and beleg not in bucket["evidence"]:
                bucket["evidence"].append(beleg)
    kind = {"thema": "theme", "hope": "hope", "fear": "fear"}.get(polarity, polarity)
    rows = []
    for bucket in buckets.values():
        count = len(bucket["posts"])
        if not count:
            continue
        rows.append({
            "id": bucket["id"],
            "label": bucket["label"],
            "count": count,
            "share": (count / total) if total else 0.0,
            "terms": bucket["evidence"],
            "description": bucket["description"],
            "polarity": kind,
            "by_channel": {
                name: int(bucket["channels"].get(name, 0))
                for name in ("News", "Social", "Other web")
            },
        })
    rows.sort(key=lambda row: (-row["count"], str(row["label"])))
    return rows


def claim_rows(project: str, mention_ids, channels: dict | None = None) -> list[dict]:
    """Hopes first, then fears. Both use the same bar list on the page."""
    return profile(project, mention_ids, "hope", channels) + profile(project, mention_ids, "fear", channels)


ALL_SHEET = "Heilbronn_Seilbahn"


def load(project: str) -> dict | None:
    """Sheet for one project key, or nothing when that entry is absent."""
    if not FACTS_FILE.is_file():
        return None
    with FACTS_FILE.open(encoding="utf-8") as handle:
        bundle = json.load(handle)
    if not isinstance(bundle, dict):
        return None
    sheet = bundle.get(project)
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
