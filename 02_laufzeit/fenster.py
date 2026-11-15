"""Fenster-Statistik — Anteile, Wilson-Intervall, Balance.

Läuft zur Laufzeit auf dem gewählten Datumsfenster und in der Vorverarbeitung
für feste Peak- und Trendbruch-Fenster. Liest gespeicherte ``tone_score``-Werte.
Bewertet den Text nicht neu.
"""
from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_sent = importlib.import_module("01_vorverarbeitung.02_sentiment_analyse")
POSITIVE = _sent.POSITIVE
NEUTRAL = _sent.NEUTRAL
NEGATIVE = _sent.NEGATIVE
LABEL = _sent.LABEL
Z = 1.96


def wilson(successes: int, trials: int, z: float = Z) -> tuple[float, float] | tuple[None, None]:
    """Wilson interval. Stays open when the count is 0 or equal to the trials."""
    if trials <= 0:
        return None, None
    proportion = successes / trials
    z2 = z * z
    denominator = 1 + z2 / trials
    centre = (proportion + z2 / (2 * trials)) / denominator
    half = z * math.sqrt(proportion * (1 - proportion) / trials + z2 / (4 * trials * trials)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def balance_stats(positive: int, neutral: int, negative: int, z: float = Z):
    """Balance ``(positive − negative) / scored``, with an interval that stays open at the edge.

    The point is the raw balance. The standard error adds half a story to each
    class before the delta-method variance, so a window with zero negative
    stories does not report a standard error of 0.
    """
    scored = positive + neutral + negative
    if scored <= 0:
        return None, None, None, None
    point = (positive - negative) / scored
    adjusted = scored + 1.5
    p_pos = (positive + 0.5) / adjusted
    p_neg = (negative + 0.5) / adjusted
    variance = (
        p_pos * (1 - p_pos) + p_neg * (1 - p_neg) + 2 * p_pos * p_neg
    ) / adjusted
    error = math.sqrt(variance)
    low = max(-1.0, point - z * error)
    high = min(1.0, point + z * error)
    return point, low, high, error


def as_score(value):
    """2, 1, 0, or missing. NaN and ``-99`` do not pass."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    number = int(number)
    return number if number in LABEL else None


def collapse_rows(rows: list[dict]) -> list[dict]:
    """One row per story. Disagreeing copies become a missing score."""
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for row in rows:
        key = row.get("story_key") or f"id:{row.get('mention_id')}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    collapsed = []
    for key in order:
        group = groups[key]
        scores = {as_score(row.get("tone_score")) for row in group}
        scores.discard(None)
        kept = dict(group[0])
        kept["copies"] = len(group)
        kept["tone_score"] = next(iter(scores)) if len(scores) == 1 else None
        collapsed.append(kept)
    return collapsed


def describe(rows: list[dict]) -> dict:
    """Shares, Wilson intervals, balance, and the 0–2 mean. ``-99`` never enters."""
    stories = collapse_rows(rows)
    counts = {POSITIVE: 0, NEUTRAL: 0, NEGATIVE: 0}
    for row in stories:
        score = as_score(row.get("tone_score"))
        if score in counts:
            counts[score] += 1
    scored = sum(counts.values())
    missing = len(stories) - scored
    shares = {}
    intervals = {}
    named = {}
    for score, label in LABEL.items():
        named[label] = counts[score]
        shares[label] = round(counts[score] / scored, 4) if scored else 0.0
        low, high = wilson(counts[score], scored)
        intervals[label] = {
            "low": None if low is None else round(low, 4),
            "high": None if high is None else round(high, 4),
        }
    point, low, high, error = balance_stats(counts[POSITIVE], counts[NEUTRAL], counts[NEGATIVE])
    mean = round((POSITIVE * counts[POSITIVE] + NEUTRAL * counts[NEUTRAL]) / scored, 2) if scored else None
    return {
        "counts": named,
        "shares": shares,
        "intervals": intervals,
        "classified": scored,
        "unclassified": missing,
        "stories": len(stories),
        "balance": None if point is None else round(point, 4),
        "balance_low": None if low is None else round(low, 4),
        "balance_high": None if high is None else round(high, 4),
        "balance_se": None if error is None else round(error, 4),
        "mean": mean,
        "n": scored,
        "n_missing": missing,
    }


def rows_from_frame(frame) -> list[dict]:
    rows = []
    for record in frame.itertuples(index=False):
        rows.append({
            "story_key": getattr(record, "story_key", None),
            "mention_id": getattr(record, "mention_id", None),
            "tone_score": as_score(getattr(record, "tone_score", None)),
        })
    return rows


def format_window(stats: dict) -> str:
    """One window: three shares with intervals, balance beside, mean with n and missing."""
    if not stats["n"]:
        return f"no scored stories (n=0, missing={stats['n_missing']})"
    parts = []
    for label in ("Positive", "Neutral", "Negative"):
        share = stats["shares"][label]
        band = stats["intervals"][label]
        low = "–" if band["low"] is None else f"{round(band['low'] * 100)}"
        high = "–" if band["high"] is None else f"{round(band['high'] * 100)}"
        parts.append(f"{label.lower()} {round(share * 100)}% ({low}–{high})")
    balance = stats["balance"]
    balance_text = "–" if balance is None else f"{balance:+.2f}"
    return (
        f"{', '.join(parts)}, balance {balance_text}, "
        f"mean {stats['mean']:.2f} (n={stats['n']}, missing={stats['n_missing']})"
    )
