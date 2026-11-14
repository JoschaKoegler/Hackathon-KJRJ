"""Stance, monthly counts, and timeline helpers for the dashboard.

Every number is a post count. A post can match more than one theme.
Shares use a Wilson interval. A line or a sentence that needs a minimum
says which minimum it used.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

import pandas as pd

from . import curated
from .config import MONTHLY_MIN
from .terms import category_profile, label_for
from .tone import wilson

STANCE_ORDER = ("support", "oppose", "mixed", "no clear stance")
STANCE_LABEL = {
    "support": "Supportive",
    "oppose": "Critical",
    "mixed": "Mixed",
    "no clear stance": "Undecided",
}
STANCE_NOTE = (
    "Stance is a phrase about the project: supportive, critical, mixed, or undecided. "
    "Undecided means no such phrase. It is not the neutral tone. "
    "One count per post. The interval is a Wilson interval for that share."
)
CHANNEL_NAMES = ("News", "Social", "Other web")
MOCKERY = (
    ("Luftnummer", re.compile(r"luftnummer")),
    ("Schnapsidee", re.compile(r"schnapsidee")),
    ("Schikane", re.compile(r"schikane")),
    ("Traumtänzerei", re.compile(r"(?<!keine )(?<!kein )traumtänzerei")),
)
SERIES_COLORS = {
    "hope": ("#1b6b45", "#3d8f68", "#7dba9a"),
    "fear": ("#9a3b38", "#c46a4a", "#6e2a28"),
    "theme": ("#0c4a8a", "#4d79ad", "#8aa4c8"),
    "support": ("#1b6b45",),
    "oppose": ("#9a3b38",),
}


def stance_block(frame: pd.DataFrame) -> dict:
    """Four stance counts for the posts in this frame."""
    counts = {key: 0 for key in STANCE_ORDER}
    if len(frame) and "stance" in frame.columns:
        for value in frame["stance"]:
            key = str(value or "no clear stance")
            if key not in counts:
                key = "no clear stance"
            counts[key] += 1
    total = int(len(frame))
    classes = []
    for key in STANCE_ORDER:
        count = counts[key]
        low, high = wilson(count, total) if total else (None, None)
        classes.append({
            "id": key,
            "label": STANCE_LABEL[key],
            "count": count,
            "share": (count / total) if total else 0.0,
            "low": low,
            "high": high,
        })
    return {"posts": total, "classes": classes, "note": STANCE_NOTE}


def mockery_label(text) -> str:
    """Ridicule of this project. A negated word, or the same word about Fulda, does not count."""
    low = str(text or "").lower()
    hits = []
    for label, pattern in MOCKERY:
        match = pattern.search(low)
        if not match:
            continue
        window = low[max(0, match.start() - 240): match.end() + 40]
        if "fulda" in window:
            continue
        hits.append(label)
    return ", ".join(hits)


def mockery_block(frame: pd.DataFrame) -> dict:
    labels: Counter = Counter()
    if len(frame) and "text" in frame.columns:
        for text in frame["text"]:
            for label in mockery_label(text).split(", "):
                if label:
                    labels[label] += 1
    detail = ", ".join(f"{label} {count}" for label, count in labels.most_common())
    return {"count": int(sum(labels.values())), "detail": detail, "labels": dict(labels)}


def event_family(event_type: str) -> str:
    """Map the pipeline's event type onto one timeline colour."""
    text = str(event_type or "").lower()
    if "politisch" in text:
        return "decision"
    if "planung" in text or "machbarkeit" in text or "route" in text:
        return "planning"
    if "bau" in text or "meilenstein" in text:
        return "construction"
    if "eröffnung" in text or "eroeffnung" in text or "betriebsstart" in text:
        return "opening"
    if any(word in text for word in ("störung", "stoerung", "sperrung", "sicherheit", "vorfall")):
        return "disruption"
    if "medien" in text:
        return "media"
    return "other"


def follow_of(persistence: str) -> str:
    return {"abgeklungen": "faded", "dauerhaft erhöht": "stayed"}.get(str(persistence or ""), "")


def _month_index(frame: pd.DataFrame) -> list[str]:
    if frame.empty:
        return []
    start = frame["date"].min().to_period("M").to_timestamp()
    end = frame["date"].max().to_period("M").to_timestamp()
    return [stamp.strftime("%Y-%m") for stamp in pd.date_range(start, end, freq="MS")]


def _empty_months(months: list[str]) -> dict:
    return {
        "note": (
            f"Posts per month. A line needs at least {MONTHLY_MIN} posts in this selection. "
            "A post can sit on more than one line. Support and opposition are stance phrases, "
            "not the tone. The lines cover the whole project and channel, not only the shaded dates."
        ),
        "min_posts": MONTHLY_MIN,
        "months": months,
        "posts": [0] * len(months),
        "series": [],
    }


def monthly_block(frame: pd.DataFrame, project: str | None) -> dict:
    months = _month_index(frame)
    if not months:
        return _empty_months([])
    index = {month: position for position, month in enumerate(months)}
    posts = [0] * len(months)
    for stamp in frame["date"]:
        posts[index[pd.Timestamp(stamp).strftime("%Y-%m")]] += 1

    buckets: dict[str, dict] = {}

    def add(kind: str, item_id: str, label: str, month: str) -> None:
        if month not in index:
            return
        key = f"{kind}:{item_id}"
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {"id": item_id, "label": label, "kind": kind, "counts": [0] * len(months)}
            buckets[key] = bucket
        bucket["counts"][index[month]] += 1

    if project and curated.has_project(project) and len(frame):
        mentions = set(frame["mention_id"].astype(str))
        for row in curated.assigned_rows(project, mentions):
            kind = {"thema": "theme", "hope": "hope", "fear": "fear"}.get(row.get("kategorie"), "")
            if kind == "theme":
                continue
            add(kind, str(row.get("id")), str(row.get("label") or row.get("id")), str(row.get("datum") or "")[:7])
    elif len(frame) and "categories" in frame.columns:
        for stamp, categories in zip(frame["date"], frame["categories"]):
            month = pd.Timestamp(stamp).strftime("%Y-%m")
            for category in list(categories or []):
                add("theme", str(category), label_for(str(category)), month)

    if len(frame) and "stance" in frame.columns:
        for stamp, stance in zip(frame["date"], frame["stance"]):
            if stance in ("support", "oppose"):
                add(stance, stance, STANCE_LABEL[stance], pd.Timestamp(stamp).strftime("%Y-%m"))

    ranked = sorted(buckets.values(), key=lambda item: -sum(item["counts"]))
    def take(kind: str, limit: int) -> list[dict]:
        picked = [item for item in ranked if item["kind"] == kind and sum(item["counts"]) >= MONTHLY_MIN]
        return picked[:limit]

    stance_lines = [item for item in ranked if item["kind"] in {"support", "oppose"} and sum(item["counts"]) >= 1]
    if any(item["kind"] in {"hope", "fear"} for item in ranked):
        chosen = take("hope", 2) + take("fear", 2) + stance_lines
    else:
        chosen = take("theme", 4) + stance_lines
    used = {kind: 0 for kind in SERIES_COLORS}
    series = []
    for item in chosen:
        palette = SERIES_COLORS[item["kind"]]
        color = palette[min(used[item["kind"]], len(palette) - 1)]
        used[item["kind"]] += 1
        series.append({**item, "color": color, "total": int(sum(item["counts"]))})
    return {
        "note": _empty_months(months)["note"],
        "min_posts": MONTHLY_MIN,
        "months": months,
        "posts": posts,
        "series": series,
    }


