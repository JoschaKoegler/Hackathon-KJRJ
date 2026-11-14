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
    CONTEXT_FILE,
    DEFAULT_CHANNEL,
    DEFAULT_CITY,
    EVENTS_FILE,
    LEGACY_PEAKS_FILE,
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
    if channel and channel != "All":
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


def _peak_source_path():
    for relative in (CONTEXT_FILE, PEAKS_FILE, EVENTS_FILE, LEGACY_PEAKS_FILE):
        path = ROOT / relative
        if path.is_file():
            return path
    return None


def _peak_window(peak: dict) -> tuple[str, str]:
    window = peak.get("crawler_window") if isinstance(peak.get("crawler_window"), dict) else {}
    day = str(peak.get("date") or "")
    start = str(window.get("start") or day)
    end = str(window.get("end") or day)
    return start, end


GENERIC_EVENT_TYPE = "Medienberichterstattung (kein klarer Auslöser)"


def score_confidence(context: dict, peak: dict | None = None) -> dict:
    """How sure we are that the peak context names a real occasion.

    Points come from independent evidence (event type, sources, external
    corroboration, topic fit), not from a fixed post count. ``hoch`` is
    reachable without a curated event.
    """
    context = context if isinstance(context, dict) else {}
    reasons: list[str] = []
    points = 0

    event_type = str(context.get("event_type") or "")
    typed = bool(event_type) and event_type != GENERIC_EVENT_TYPE
    type_scores = context.get("event_type_scores") if isinstance(context.get("event_type_scores"), dict) else {}
    numeric_scores = [float(value) for value in type_scores.values() if isinstance(value, (int, float))]
    best_score = max(numeric_scores) if numeric_scores else 0.0
    if typed:
        if best_score >= 8:
            points += 2
            reasons.append("clear event type")
        else:
            points += 1
            reasons.append("event type identified")
    else:
        reasons.append("no clear trigger")

    externals = [
        item for item in (context.get("external_candidates") or [])
        if isinstance(item, dict) and item.get("title") and not item.get("error")
    ]
    match = float(externals[0].get("match_score") or 0) if externals else 0.0
    if externals:
        if match >= 3:
            points += 2
            reasons.append("matching external source")
        else:
            points += 1
            reasons.append("external hint")

    profile = context.get("source_profile") if isinstance(context.get("source_profile"), dict) else {}
    n_posts = int(profile.get("n_posts") or 0)
    n_sources = int(profile.get("n_sources") or 0)
    if n_posts:
        share = n_sources / n_posts
        if n_sources >= 3 and share >= 0.45:
            points += 2
            reasons.append(f"{n_sources} independent sources")
        elif n_sources >= 2:
            points += 1
            reasons.append("several sources")
        if profile.get("likely_syndication"):
            points -= 1
            reasons.append("likely syndication")

    topic = context.get("topic_share")
    off_topic = bool(context.get("off_topic_suspect"))
    if off_topic:
        points -= 2
        reasons.append("possibly off-topic")
    elif isinstance(topic, (int, float)) and topic >= 0.75:
        points += 1
        reasons.append("on-topic in the window")

    curated = bool(context.get("curated_events"))
    if curated:
        points += 3
        reasons.append("curated event")

    strong_corroboration = curated or match >= 3 or best_score >= 8
    if off_topic or points < 2:
        level = "niedrig"
    elif typed and strong_corroboration and points >= 5:
        level = "hoch"
    elif points >= 3:
        level = "mittel"
    else:
        level = "niedrig"
    return {
        "level": level,
        "points": points,
        "why": ", ".join(reasons[:4]),
    }


def _peak_headline(peak: dict, context: dict) -> str:
    for headline in context.get("top_headlines") or []:
        if headline:
            return str(headline)
    for title in peak.get("sample_titles") or []:
        if title:
            return str(title)
    crawled = peak.get("crawled_context") or []
    if crawled and isinstance(crawled[0], dict):
        return str(crawled[0].get("title") or "")
    return ""


def _peak_headlines(peak: dict, context: dict) -> list[dict]:
    items: list[dict] = []

    def add(text, url=None):
        value = str(text or "").strip()
        if not value or any(existing["text"] == value for existing in items):
            return
        item = {"text": value}
        if url:
            item["url"] = str(url)
        items.append(item)

    for headline in (context.get("top_headlines") or [])[:3]:
        add(headline)
    added_external = 0
    for extra in context.get("external_candidates") or []:
        if not isinstance(extra, dict) or extra.get("error") or not extra.get("title"):
            continue
        source = extra.get("source") or ""
        add(extra["title"] if not source else f"{extra['title']} ({source})", extra.get("url"))
        added_external += 1
        if added_external >= 2:
            break
    if not items:
        for title in (peak.get("sample_titles") or [])[:3]:
            add(title)
    return items


def _peak_effects(context: dict) -> list[str]:
    lines = []
    effects = context.get("effects") if isinstance(context.get("effects"), dict) else {}
    persistence = effects.get("persistence")
    if persistence:
        decay = effects.get("decay_days")
        extra = f", {decay} days" if decay not in (None, "") else ""
        follow = {"abgeklungen": "faded", "dauerhaft erhöht": "stayed high"}.get(str(persistence), persistence)
        lines.append(f"Follow-up: {follow}{extra}")
    sent_before, sent_after = effects.get("sentiment_14d_before"), effects.get("sentiment_14d_after")
    if sent_before is not None or sent_after is not None:
        lines.append(f"Sentiment over 14 days: {sent_before} → {sent_after}")
    if context.get("off_topic_suspect"):
        lines.append("Note: peak may be off-topic")
    return lines


def _peak_points(peak: dict, context: dict) -> list[dict]:
    """Bullet points for the context panel. Pipeline text stays as written."""
    points: list[dict] = []

    def add(text, url=None):
        value = str(text or "").strip()
        if not value:
            return
        item = {"text": value}
        if url:
            item["url"] = str(url)
        points.append(item)

    terms = [str(term) for term in (context.get("top_terms") or []) if term]
    amounts = [str(amount) for amount in (context.get("amounts_mentioned") or []) if amount]
    profile = context.get("source_profile") if isinstance(context.get("source_profile"), dict) else {}
    n_posts, n_sources = profile.get("n_posts"), profile.get("n_sources")
    if n_posts and n_sources:
        add(f"{n_posts} posts from {n_sources} sources")
    for headline in (context.get("top_headlines") or [])[:3]:
        add(headline)
    added_external = 0
    for extra in context.get("external_candidates") or []:
        if not isinstance(extra, dict) or extra.get("error") or not extra.get("title"):
            continue
        source = extra.get("source") or ""
        add(extra["title"] if not source else f"{extra['title']} ({source})", extra.get("url"))
        added_external += 1
        if added_external >= 2:
            break
    effects = context.get("effects") if isinstance(context.get("effects"), dict) else {}
    persistence = effects.get("persistence")
    if persistence:
        decay = effects.get("decay_days")
        extra = f", {decay} days" if decay not in (None, "") else ""
        follow = {"abgeklungen": "faded", "dauerhaft erhöht": "stayed high"}.get(str(persistence), persistence)
        add(f"Follow-up: {follow}{extra}")
    sent_before, sent_after = effects.get("sentiment_14d_before"), effects.get("sentiment_14d_after")
    if sent_before is not None or sent_after is not None:
        add(f"Sentiment over 14 days: {sent_before} → {sent_after}")
    if context.get("off_topic_suspect"):
        add("Note: peak may be off-topic")
    if not points:
        for title in (peak.get("sample_titles") or [])[:3]:
            add(title)
    return points


def load_peak_markers(city: str) -> list[dict]:
    """Peak windows for the selected city.

    Markers come from the batch pipeline (``projects_with_context.json``),
    counted on every kept post for that project. They are not recomputed
    for the channel switch. Each marker carries the few-day crawler window
    and the context bullets for the panel beside the timeline.
    """
    path = _peak_source_path()
    if path is None:
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    blocks = raw["projects"] if isinstance(raw, dict) else raw
    markers = []
    for block in blocks:
        project = block.get("project")
        if city != "All" and CITY_BY_PROJECT.get(project) != city:
            continue
        for peak in block.get("peaks", []) or []:
            day = peak.get("date")
            if not day:
                continue
            context = peak.get("context") if isinstance(peak.get("context"), dict) else {}
            window_from, window_to = _peak_window(peak)
            headline = _peak_headline(peak, context)
            scored = score_confidence(context, peak)
            profile = context.get("source_profile") if isinstance(context.get("source_profile"), dict) else {}
            secondary = context.get("event_type_secondary")
            event_type = context.get("event_type") or ""
            if secondary:
                event_type = f"{event_type} · {secondary}"
            markers.append({
                "id": f"{project}::{day}",
                "date": day,
                "window_from": window_from,
                "window_to": window_to,
                "project": project,
                "label": PROJECT_LABEL.get(project, project),
                "post_count": int(peak.get("post_count") or 0),
                "prominence": peak.get("prominence"),
                "tier": peak.get("tier") or "major",
                "rank": peak.get("rank"),
                "event_type": event_type,
                "headline": headline,
                "summary": str(context.get("summary") or "").strip(),
                "confidence": scored["level"],
                "confidence_why": scored["why"],
                "terms": [str(term) for term in (context.get("top_terms") or []) if term][:6],
                "amounts": [str(amount) for amount in (context.get("amounts_mentioned") or []) if amount][:4],
                "sources": (
                    f"{profile['n_posts']} posts · {profile['n_sources']} sources"
                    if profile.get("n_posts") and profile.get("n_sources") else ""
                ),
                "headlines": _peak_headlines(peak, context),
                "effects": _peak_effects(context),
                "points": _peak_points(peak, context),
            })
    markers.sort(key=lambda item: (item["date"], item["project"]))
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
