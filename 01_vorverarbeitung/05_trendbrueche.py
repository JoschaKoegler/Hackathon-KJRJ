"""05. Trendbrüche — Binary Segmentation der Tageszählung.

Liest ``00_data/posts.json`` (gespeicherter ``tone_score``) und ``01_vorverarbeitung/peaks.json``.
Schreibt ``change_points`` in dieselbe Peak-Datei. Die Peak-Tage bleiben unangetastet.
"""
from __future__ import annotations

import importlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_config = importlib.import_module("02_laufzeit.config")
_fenster = importlib.import_module("02_laufzeit.fenster")
_peaks = importlib.import_module("01_vorverarbeitung.04_peak_erkennung")
describe = _fenster.describe
POSTS_FILE = _config.POSTS_FILE
PEAKS_FILE = _config.PEAKS_FILE

# Penalty und Mindestlänge wachsen mit der Länge der Zeitreihe.
CP_PENALTY_FACTOR = 3.0
CP_MIN_SEGMENT_SHARE = 0.03
CP_DAYS_PER_POINT = 120

# ==========================================
# 3. CHANGE-POINT DETECTION (Binary Segmentation, reines NumPy)
# ==========================================
def detect_changepoints_binseg(series: np.ndarray, penalty: float, min_size: int, max_points: int) -> list[int]:
    """Findet dauerhafte Niveauwechsel; behält höchstens `max_points` mit dem größten Gewinn."""
    def sse(arr: np.ndarray) -> float:
        if len(arr) == 0:
            return 0.0
        return float(np.sum((arr - np.mean(arr)) ** 2))

    found: list[tuple[int, float]] = []

    def split_segment(start: int, end: int):
        if end - start < 2 * min_size:
            return
        total_cost = sse(series[start:end])
        best_gain, best_idx = 0.0, None
        for idx in range(start + min_size, end - min_size + 1):
            gain = total_cost - (sse(series[start:idx]) + sse(series[idx:end]))
            if gain > best_gain:
                best_gain, best_idx = gain, idx
        if best_idx is not None and best_gain > penalty:
            found.append((best_idx, best_gain))
            split_segment(start, best_idx)
            split_segment(best_idx, end)

    split_segment(0, len(series))
    top = sorted(found, key=lambda t: -t[1])[:max_points]
    return sorted(idx for idx, _ in top)


def prepare_changepoint_series(counts: np.ndarray) -> np.ndarray | None:
    """Einzelne Spikes werden gekappt, damit sie keine 'Trendbrüche' auslösen; danach normiert."""
    cap = max(float(np.quantile(counts, 0.98)), 1.0)
    series = np.minimum(counts, cap)
    if np.std(series) == 0:
        series = counts
    std = np.std(series)
    if std == 0:
        return None
    return (series - np.mean(series)) / std




def change_points_for(df_proj: pd.DataFrame) -> list[dict]:
    """Niveauwechsel der Tageszählung. Der Ton davor und danach kommt aus dem gespeicherten Score."""
    stories = _peaks._tone_stories(df_proj)
    daily = df_proj.groupby("date").agg(count=("published_at", "size"))
    if not stories.empty:
        tone_daily = stories.groupby("date")["tone_score"].agg(avg_sentiment="mean", tone_n="count")
        tone_daily["tone_stories"] = stories.groupby("date").size()
        tone_daily["tone_missing"] = tone_daily["tone_stories"] - tone_daily["tone_n"]
        daily = daily.join(tone_daily[["avg_sentiment", "tone_n", "tone_missing"]], how="left")
    full_idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_idx)
    daily["count"] = daily["count"].fillna(0)
    counts = daily["count"].values.astype(float)
    n_days = len(counts)
    if n_days < 14 or np.std(counts) == 0:
        return []
    norm_counts = prepare_changepoint_series(counts)
    if norm_counts is None:
        return []
    min_size = max(7, int(round(CP_MIN_SEGMENT_SHARE * n_days)))
    max_points = int(np.clip(round(n_days / CP_DAYS_PER_POINT), 2, 6))
    cp_indices = detect_changepoints_binseg(
        norm_counts,
        penalty=CP_PENALTY_FACTOR * math.log(n_days),
        min_size=min_size,
        max_points=max_points,
    )
    boundaries = [0] + cp_indices + [n_days]
    change_points = []
    for pos, idx in enumerate(cp_indices):
        cp_date = daily.index[idx]
        prev_start, next_end = boundaries[pos], boundaries[pos + 2]
        mean_before = float(np.mean(counts[prev_start:idx]))
        mean_after = float(np.mean(counts[idx:next_end]))

        def _segment(start_i, end_i):
            if stories.empty or start_i >= end_i:
                return {"mean": None, "n": 0, "n_missing": 0}
            start_day = daily.index[start_i]
            end_day = daily.index[end_i - 1]
            part = stories[(stories["date"] >= start_day) & (stories["date"] <= end_day)]
            return describe(part.assign(tone_score=part["tone_score"].where(part["tone_score"].notna(), None)).to_dict("records"))

        before_tone = _segment(prev_start, idx)
        after_tone = _segment(idx, next_end)
        sent_before = before_tone["mean"]
        sent_after = after_tone["mean"]
        change_points.append({
            "date": cp_date.strftime("%Y-%m-%d"),
            "avg_posts_before": round(mean_before, 2),
            "avg_posts_after": round(mean_after, 2),
            "avg_sentiment_before": None if sent_before is None else round(float(sent_before), 2),
            "avg_sentiment_after": None if sent_after is None else round(float(sent_after), 2),
            "tone_n_before": before_tone["n"],
            "tone_n_after": after_tone["n"],
            "tone_missing_before": before_tone["n_missing"],
            "tone_missing_after": after_tone["n_missing"],
        })
    return change_points


def main() -> None:
    if not POSTS_FILE.exists():
        print(f"FEHLER: '{POSTS_FILE}' nicht gefunden.")
        return
    posts = json.loads(POSTS_FILE.read_text(encoding="utf-8"))
    frame = pd.DataFrame(posts)
    frame["date"] = pd.to_datetime(frame["published_at"], utc=True, errors="coerce").dt.tz_localize(None).dt.floor("D")
    frame = frame.dropna(subset=["date"])
    exploded = frame.explode("matched_projects").rename(columns={"matched_projects": "project"})
    by_project = {}
    for project, group in exploded.groupby("project"):
        points = change_points_for(group)
        by_project[str(project)] = points
        print(f"{project}: {len(points)} Trendbrüche")
    if PEAKS_FILE.exists():
        stored = json.loads(PEAKS_FILE.read_text(encoding="utf-8"))
    else:
        stored = [{"project": name, "peaks": [], "change_points": []} for name in by_project]
    seen = set()
    for entry in stored:
        name = str(entry.get("project"))
        seen.add(name)
        entry["change_points"] = by_project.get(name, [])
    for name, points in by_project.items():
        if name not in seen:
            stored.append({"project": name, "peaks": [], "change_points": points})
    PEAKS_FILE.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Trendbrüche: {PEAKS_FILE}")


if __name__ == "__main__":
    main()
