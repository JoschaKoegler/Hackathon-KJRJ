"""Nachwirkung eines Peaks.

Abklingen der Tageszahl und Tonmittel 14 Tage davor und danach, aus dem gespeicherten Score.
Schreibt ``effects``.
Aufgerufen von ``06_peak_kontext.py``. Die Schwellen bleiben dort.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
import importlib as _il
_fenster = _il.import_module('02_laufzeit.fenster')
describe = _fenster.describe

import importlib

def _k():
    return importlib.import_module("01_vorverarbeitung.06_peak_kontext")

def daily_counts(docs: list[dict]) -> Counter:
    return Counter(d["date"] for d in docs)


def mean_sentiment(docs: list[dict], start, end):
    """Tone mean on 0–2. ``-99`` is already dropped. Copies of one title count once.

    The result carries ``n`` and ``n_missing`` next to the mean. A window with
    no scored story has mean ``None`` and still reports how many are missing.
    """
    window = [
        d for d in docs
        if d.get("date") is not None and start <= d["date"] <= end
    ]
    return describe(window)


def effect_analysis(project_docs: list[dict], peak_date, peak_count: int) -> dict:
    """Wie lange dauert der Peak, und bleibt die Debatte danach erhöht? Stimmung davor/danach."""
    daily = daily_counts(project_docs)
    last_date = max(d["date"] for d in project_docs)

    base_days = [peak_date - timedelta(days=k) for k in range(4, 4 + 31)]
    base_mean = sum(daily.get(d, 0) for d in base_days) / len(base_days)
    threshold = base_mean + max(0.5, _k().DECAY_REL * (peak_count - base_mean))

    decay_days = None
    for k in range(1, 29):
        d1 = peak_date + timedelta(days=k)
        d2 = d1 + timedelta(days=1)
        if daily.get(d1, 0) <= threshold and daily.get(d2, 0) <= threshold:
            decay_days = k
            break

    complete = peak_date + timedelta(days=21) <= last_date
    after_mean = sum(daily.get(peak_date + timedelta(days=k), 0) for k in range(7, 22)) / 15
    if not complete:
        persistence = "still open (not enough data after the peak)"
    elif after_mean > max(1.5 * base_mean, base_mean + 0.5):
        persistence = "stayed high"
    else:
        persistence = "faded"

    before = mean_sentiment(project_docs, peak_date - timedelta(days=14), peak_date - timedelta(days=4))
    after = mean_sentiment(project_docs, peak_date + timedelta(days=3), peak_date + timedelta(days=16))

    return {
        "baseline_posts_per_day": round(base_mean, 2),
        "decay_days": decay_days,
        "decay_note": None if decay_days is not None else "no return to baseline within 28 days (or end of data)",
        "persistence": persistence,
        "avg_posts_per_day_days_7_to_21": round(after_mean, 2),
        "sentiment_14d_before": before["mean"],
        "sentiment_14d_after": after["mean"],
        "sentiment_n_before_after": [before["n"], after["n"]],
        "sentiment_missing_before_after": [before["n_missing"], after["n_missing"]],
        "tone_before": before,
        "tone_after": after,
    }

