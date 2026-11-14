"""4. Summary.

Filters the prepared posts by city, channel, and date window, then builds
the timeline, circles, trend arrow, term list, and peak markers.
"""

from __future__ import annotations

import json

import pandas as pd

from .config import (
    CHANNEL_BUTTONS,
    CIRCLES,
    CITY_BUTTONS,
    CITY_BY_PROJECT,
    DEFAULT_CHANNEL,
    DEFAULT_CITY,
    EVENTS_FILE,
    MIN_TREND_BASE,
    PEAKS_FILE,
    PROJECT_LABEL,
    ROOT,
    STANCE_SOURCE,
    TREND_THRESHOLD_POINTS,
)
from .prepare import load_posts
from .terms import top_terms


def as_day(value) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    stamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(stamp):
        return None
    stamp = pd.Timestamp(stamp)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert(None)
    return stamp.normalize()


def date_iso(stamp) -> str:
    return pd.Timestamp(stamp).strftime("%Y-%m-%d")


def date_span(frame: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    return frame["date"].min(), frame["date"].max()


def select_posts(
    frame: pd.DataFrame,
    city: str | None = None,
    channel: str | None = None,
    date_from=None,
    date_to=None,
) -> pd.DataFrame:
    """City, channel, and date window. None skips that cut."""
    selected = frame
    if city and city != "All":
        selected = selected[selected["city"].eq(city)]
    if channel:
        selected = selected[selected["channel"].eq(channel)]
    start = as_day(date_from)
    end = as_day(date_to)
    if start is not None:
        selected = selected[selected["date"] >= start]
    if end is not None:
        selected = selected[selected["date"] <= end]
    return selected


def previous_window(start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    """A window of the same length that ends the day before ``start``."""
    days = (end - start).days + 1
    previous_end = start - pd.Timedelta(days=1)
    previous_start = previous_end - pd.Timedelta(days=days - 1)
    return previous_start, previous_end


def daily_counts(frame: pd.DataFrame, start, end) -> list[dict]:
    index = pd.date_range(start, end, freq="D")
    if frame.empty:
        counts = pd.Series(0, index=index)
    else:
        counts = frame.groupby("date").size().reindex(index, fill_value=0)
    return [{"date": date_iso(day), "count": int(value)} for day, value in counts.items()]


def count_circles(frame: pd.DataFrame) -> dict:
    counts = {name: int(frame["circle"].eq(name).sum()) for name in CIRCLES}
    classified = sum(counts.values())
    shares = {
        name: (round(counts[name] / classified, 4) if classified else 0.0)
        for name in CIRCLES
    }
    return {
        "counts": counts,
        "shares": shares,
        "classified": classified,
        "unclassified": int(frame["circle"].isna().sum()),
    }


def _balance(circles: dict) -> float | None:
    classified = circles["classified"]
    if not classified:
        return None
    return (circles["counts"]["Support"] - circles["counts"]["Opposition"]) / classified


def trend(
    current: pd.DataFrame,
    previous: pd.DataFrame,
    start,
    end,
    previous_start,
    previous_end,
    data_start,
    data_end,
) -> dict:
    """Arrow from the balance against the previous window of the same length."""
    now = count_circles(current)
    before = count_circles(previous)
    balance_now = _balance(now)
    balance_before = _balance(before)
    base = {
        "date_from": date_iso(start),
        "date_to": date_iso(end),
        "previous_from": date_iso(previous_start),
        "previous_to": date_iso(previous_end),
        "base_now": now["classified"],
        "base_previous": before["classified"],
        "balance_now": None if balance_now is None else round(balance_now, 4),
        "balance_previous": None if balance_before is None else round(balance_before, 4),
    }
    if previous_end < data_start or previous_start < data_start or previous_start > data_end:
        return {
            **base,
            "direction": "unknown",
            "delta_points": None,
            "sentence": "The previous window of the same length starts before the first post in this selection.",
        }
    if (
        balance_now is None
        or balance_before is None
        or now["classified"] < MIN_TREND_BASE
        or before["classified"] < MIN_TREND_BASE
    ):
        return {
            **base,
            "direction": "unknown",
            "delta_points": None,
            "sentence": "Too few classified posts to compare with the previous window.",
        }
    delta = (balance_now - balance_before) * 100
    if delta > TREND_THRESHOLD_POINTS:
        direction = "up"
        movement = "up"
    elif delta < -TREND_THRESHOLD_POINTS:
        direction = "down"
        movement = "down"
    else:
        direction = "flat"
        movement = "nearly unchanged"
    points = f"{delta:+.1f}"
    return {
        **base,
        "direction": direction,
        "delta_points": round(delta, 1),
        "sentence": (
            f"Support-minus-opposition balance is {movement} ({points} points) "
            f"against {pd.Timestamp(previous_start).strftime('%Y-%m-%d')} "
            f"to {pd.Timestamp(previous_end).strftime('%Y-%m-%d')}."
        ),
    }


def list_posts(frame: pd.DataFrame) -> list[dict]:
    visible = frame.sort_values("date", ascending=False)
    rows = []
    for row in visible.itertuples(index=False):
        rows.append({
            "date": date_iso(row.date),
            "title": str(row.title or "").strip() or "(no title)",
            "source": str(row.source_name or ""),
            "url": str(row.url or ""),
            "circle": row.circle,
            "stance": row.stance,
            "vendor_tone": row.vendor_tone,
            "city": row.city or "",
            "channel": row.channel or "",
            "project": row.project_label or "",
            "snippet": str(row.snippet or "").strip(),
        })
    return rows


def _clamp(start, end, data_start, data_end):
    start = data_start if start is None else max(start, data_start)
    end = data_end if end is None else min(end, data_end)
    if start > end:
        return data_start, data_end
    return start, end


def load_peak_markers(city: str) -> list[dict]:
    """Peak dates for the selected city.

    Markers come from the batch pipeline, counted on every kept post for
    that project. They are not recomputed for the channel switch.
    ``events.json`` wins over ``peaks.json`` once the crawler has run.
    """
    events_path = ROOT / EVENTS_FILE
    peaks_path = ROOT / PEAKS_FILE
    path = events_path if events_path.is_file() else peaks_path
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    blocks = raw["projects"] if isinstance(raw, dict) else raw
    markers = []
    for block in blocks:
        project = block.get("project")
        if city != "All" and CITY_BY_PROJECT.get(project) != city:
            continue
        for peak in block.get("peaks", []):
            # Same floor as pipeline/03_attach_events.py. Smaller spikes stay in peaks.json.
            if int(peak.get("post_count") or 0) < 4:
                continue
            context = peak.get("crawled_context") or []
            headline = ""
            if context and isinstance(context[0], dict):
                headline = str(context[0].get("title") or "")
            markers.append({
                "date": peak.get("date"),
                "project": project,
                "label": PROJECT_LABEL.get(project, project),
                "post_count": peak.get("post_count"),
                "prominence": peak.get("prominence"),
                "headline": headline,
            })
    return markers


def summarize(
    city: str = DEFAULT_CITY,
    channel: str = DEFAULT_CHANNEL,
    date_from=None,
    date_to=None,
    frame: pd.DataFrame | None = None,
) -> dict:
    """Everything the page draws for one switch setting."""
    frame = load_posts() if frame is None else frame
    valid_cities = {entry["id"] for entry in CITY_BUTTONS}
    valid_channels = {entry["id"] for entry in CHANNEL_BUTTONS}
    if city not in valid_cities:
        city = DEFAULT_CITY
    if channel not in valid_channels:
        channel = DEFAULT_CHANNEL

    base = select_posts(frame, city=city, channel=channel)
    if base.empty:
        start, end = date_span(frame)
    else:
        start, end = date_span(base)
    window_from, window_to = _clamp(as_day(date_from), as_day(date_to), start, end)
    window = select_posts(base, date_from=window_from, date_to=window_to)
    previous_from, previous_to = previous_window(window_from, window_to)
    previous = select_posts(base, date_from=previous_from, date_to=previous_to)
    circles = count_circles(window)
    return {
        "city": city,
        "channel": channel,
        "stance_source": STANCE_SOURCE,
        "date_from": date_iso(window_from),
        "date_to": date_iso(window_to),
        "start": date_iso(start),
        "end": date_iso(end),
        "timeline": daily_counts(base, start, end),
        "circles": circles,
        "trend": trend(
            window, previous, window_from, window_to, previous_from, previous_to, start, end
        ),
        "post_count": int(len(window)),
        "terms": top_terms(window),
        "cities": CITY_BUTTONS,
        "channels": CHANNEL_BUTTONS,
        "peaks": load_peak_markers(city),
    }


def overview(frame: pd.DataFrame | None = None) -> pd.DataFrame:
    """Small table for the notebook: city, channel, circle."""
    frame = load_posts() if frame is None else frame
    return (
        frame.groupby(["city", "channel", "circle"], dropna=False)
        .size()
        .rename("posts")
        .reset_index()
        .sort_values(["city", "channel", "posts"], ascending=[True, True, False])
    )
