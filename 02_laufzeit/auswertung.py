"""4. Page — ``summarize()`` / ``list_posts()`` for the HTTP API.

Called by ``03_dashboard.py``:

* ``GET /api/summary``  →  ``summarize(city, channel, date_from, date_to)``
* ``GET /api/posts``    →  ``summarize`` then ``list_posts``

Reads ``00_data/context.json`` (from ``06_peak_kontext.py``) and
``00_data/facts.json`` (hand-authored, via ``kuratierte_themen.sheet_for_city``).
Themes: ``kuratierte_themen.profile`` when a city has a curated file
(from ``07_themen_zuordnung.py``), else shares over the stored token labels
from ``08_token_fallback.py``. Tone and stance are stored columns.
This module only aggregates the selected window.
"""

from __future__ import annotations

import importlib
import json
import math
import re
from collections import Counter

import pandas as pd

from .config import (
    CHANNEL_BUTTONS,
    CITY_BUTTONS,
    CITY_BY_PROJECT,
    CONTEXT_FILE,
    DEFAULT_CHANNEL,
    DEFAULT_CITY,
    EVENT_FAMILIES,
    PROJECT_LABEL,
    STANCE_SOURCE,
    TREND_THRESHOLD_POINTS,
)
from .fenster import describe, format_window, rows_from_frame, wilson
from .beitraege import load_posts
from . import kuratierte_themen as themes

_token = importlib.import_module("01_vorverarbeitung.08_token_fallback")


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
MOCKERY = (
    ("Luftnummer", re.compile(r"luftnummer")),
    ("Schnapsidee", re.compile(r"schnapsidee")),
    ("Schikane", re.compile(r"schikane")),
    ("Traumtänzerei", re.compile(r"(?<!keine )(?<!kein )traumtänzerei")),
)


def stance_block(frame: pd.DataFrame) -> dict:
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
    text = str(event_type or "").lower()
    if "political" in text or "politisch" in text:
        return "decision"
    if any(word in text for word in ("planning", "feasibility", "planung", "machbarkeit", "route")):
        return "planning"
    if any(word in text for word in ("construction", "milestone", "bau", "meilenstein")):
        return "construction"
    if any(word in text for word in ("opening", "start of service", "eröffnung", "eroeffnung", "betriebsstart")):
        return "opening"
    if any(word in text for word in ("disruption", "closure", "safety", "incident", "störung", "stoerung", "sperrung", "sicherheit", "vorfall")):
        return "disruption"
    if "media" in text or "coverage" in text or "medien" in text:
        return "media"
    return "other"


def follow_of(persistence: str) -> str:
    text = str(persistence or "")
    if text in {"faded", "abgeklungen"}:
        return "faded"
    if text in {"stayed high", "dauerhaft erhöht"}:
        return "stayed"
    return ""


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
    """Tone shares on one row per story, with Wilson intervals and the balance beside."""
    stats = describe(rows_from_frame(frame))
    stats["posts"] = int(len(frame))
    stats["collapsed"] = int(len(frame) - stats["stories"])
    return stats


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
    """Arrow from the balance change against the previous window of the same length."""
    now = count_circles(current)
    before = count_circles(previous)
    base = {
        "date_from": date_iso(start),
        "date_to": date_iso(end),
        "previous_from": date_iso(previous_start),
        "previous_to": date_iso(previous_end),
        "base_now": now["classified"],
        "base_previous": before["classified"],
        "balance_now": now["balance"],
        "balance_previous": before["balance"],
        "se_points": None,
        "interval_low": None,
        "interval_high": None,
    }
    span = (
        f"{pd.Timestamp(previous_start).strftime('%Y-%m-%d')} "
        f"to {pd.Timestamp(previous_end).strftime('%Y-%m-%d')}"
    )
    overlaps = previous_end >= data_start and previous_start <= data_end
    if not overlaps or now["balance"] is None or before["balance"] is None:
        return {
            **base,
            "direction": "unknown",
            "delta_points": None,
            "sentence": "The previous window of the same length has no scored stories to compare.",
        }
    delta = now["balance"] - before["balance"]
    error = math.sqrt(now["balance_se"] ** 2 + before["balance_se"] ** 2)
    z = 1.96
    low = max(-2.0, delta - z * error)
    high = min(2.0, delta + z * error)
    se_points = error * 100
    low_points = low * 100
    high_points = high * 100
    delta_points = round(delta * 100, 1)
    band = TREND_THRESHOLD_POINTS
    detail = (
        f"Positive-minus-negative balance moved {delta_points:+.1f} points "
        f"(interval {low_points:+.1f} to {high_points:+.1f}, standard error {se_points:.1f}) "
        f"against {span}."
    )
    if delta_points > band:
        direction = "up"
    elif delta_points < -band:
        direction = "down"
    else:
        direction = "flat"
    return {
        **base,
        "delta_points": delta_points,
        "se_points": round(se_points, 1),
        "interval_low": round(low_points, 1),
        "interval_high": round(high_points, 1),
        "direction": direction,
        "sentence": f"Positive-minus-negative balance is {direction}. {detail}",
    }


def _cell(value) -> str:
    """JSON numbers cannot be NaN. Missing stance fields stay empty strings."""
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value)


def list_posts(frame: pd.DataFrame, curated_project: str | None = None) -> list[dict]:
    notes = {}
    if curated_project and len(frame) and "mention_id" in frame.columns:
        notes = themes.notes_for(curated_project, frame["mention_id"].astype(str).tolist())
    visible = frame.sort_values("date", ascending=False)
    rows = []
    for row in visible.itertuples(index=False):
        mention = str(getattr(row, "mention_id", "") or "")
        note = notes.get(mention) if curated_project else None
        if note is not None:
            categories = note["themes"]
            hopes = note["hopes"]
            fears = note["fears"]
            evidence = note["evidence"]
            arguments: list[str] = []
            is_curated = True
        else:
            categories = [_token.label_for(category) for category in list(row.categories or [])]
            arguments = [_token.argument_label(argument) for argument in list(row.arguments or [])]
            hopes = []
            fears = []
            evidence = {}
            is_curated = False
        rows.append({
            "date": date_iso(row.date),
            "title": str(row.title or "").strip() or "(no title)",
            "source": str(row.source_name or ""),
            "url": str(row.url or ""),
            "circle": _cell(row.circle),
            "tone_cue": _cell(getattr(row, "tone_cue", "")),
            "stance": _cell(row.stance),
            "city": row.city or "",
            "channel": row.channel or "",
            "project": row.project_label or "",
            "snippet": str(row.snippet or "").strip(),
            "mockery": mockery_label(getattr(row, "text", "")),
            "categories": categories,
            "arguments": arguments,
            "hopes": hopes,
            "fears": fears,
            "evidence": evidence,
            "curated": is_curated,
        })
    return rows


def _clamp(start, end, data_start, data_end):
    start = data_start if start is None else max(start, data_start)
    end = data_end if end is None else min(end, data_end)
    if start > end:
        return data_start, data_end
    return start, end


def _peak_source_path():
    return CONTEXT_FILE if CONTEXT_FILE.is_file() else None


def _peak_window(peak: dict) -> tuple[str, str]:
    window = peak.get("crawler_window") if isinstance(peak.get("crawler_window"), dict) else {}
    day = str(peak.get("date") or "")
    start = str(window.get("start") or day)
    end = str(window.get("end") or day)
    return start, end


GENERIC_EVENT_TYPES = {
    "Media coverage (no clear trigger)",
    "Medienberichterstattung (kein klarer Auslöser)",
}


def score_confidence(context: dict, peak: dict | None = None) -> dict:
    """How sure we are that the peak context names a real occasion.

    Points come from independent evidence (event type, sources, external
    corroboration, topic fit), not from a fixed post count. ``high`` is
    reachable without a curated event.
    """
    context = context if isinstance(context, dict) else {}
    reasons: list[str] = []
    points = 0

    event_type = str(context.get("event_type") or "")
    typed = bool(event_type) and event_type not in GENERIC_EVENT_TYPES
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
        level = "low"
    elif typed and strong_corroboration and points >= 5:
        level = "high"
    elif points >= 3:
        level = "medium"
    else:
        level = "low"
    return {
        "level": level,
        "points": points,
        "why": ", ".join(reasons[:4]),
    }


def _norm_title(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "").lower().strip())
    return value[:96]


def _titles_overlap(a: str, b: str) -> bool:
    left, right = _norm_title(a), _norm_title(b)
    if not left or not right:
        return False
    return left == right or left in right or right in left


def _is_template_summary(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        marker in lowered
        for marker in (
            "auffällige begriffe:",
            "genannte beträge:",
            "häufigste schlagzeile:",
            "möglicher externer beleg:",
            " beiträge aus ",
        )
    )


def _peak_lead(context: dict) -> str:
    summary = str(context.get("summary") or "").strip()
    method = str(context.get("method") or "")
    if not summary:
        return ""
    if summary.startswith("Curated:") or summary.startswith("Kuratiert:"):
        return summary
    if method == "llm" and not _is_template_summary(summary):
        return summary
    if _is_template_summary(summary):
        parts = []
        profile = context.get("source_profile") if isinstance(context.get("source_profile"), dict) else {}
        if profile.get("likely_syndication"):
            parts.append("Many posts look like syndicated copies of the same story.")
        if context.get("off_topic_suspect"):
            parts.append("Check: posts may be off-topic for this project.")
        return " ".join(parts)
    return summary


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


def _peak_headlines(
    peak: dict,
    context: dict,
    frame: pd.DataFrame | None = None,
    project: str | None = None,
) -> list[dict]:
    items: list[dict] = []
    title_rows: dict[str, object] = {}
    if frame is not None and len(frame) and project and "project" in frame.columns:
        subset = frame[frame["project"].eq(project)]
        for row in subset.itertuples(index=False):
            title = str(getattr(row, "title", "") or "").strip()
            if not title:
                continue
            title_rows[_norm_title(title)] = row
            title_rows[_norm_title(title[:60])] = row

    def add(text, url=None, source=None):
        value = str(text or "").strip()
        if not value:
            return
        if any(_titles_overlap(value, existing["text"]) for existing in items):
            return
        item = {"text": value}
        if url:
            item["url"] = str(url)
        if source:
            item["source"] = str(source)
        items.append(item)

    for headline in (context.get("top_headlines") or [])[:5]:
        row = title_rows.get(_norm_title(headline)) or title_rows.get(_norm_title(headline[:60]))
        url = str(getattr(row, "url", "") or "") if row is not None else ""
        source = str(getattr(row, "source_name", "") or "") if row is not None else ""
        add(headline, url or None, source or None)

    added_external = 0
    for extra in context.get("external_candidates") or []:
        if not isinstance(extra, dict) or extra.get("error") or not extra.get("title"):
            continue
        title = str(extra["title"]).strip()
        if any(_titles_overlap(title, existing["text"]) for existing in items):
            continue
        add(title, extra.get("url"), extra.get("source") or None)
        added_external += 1
        if added_external >= 2:
            break
    if not items:
        for title in (peak.get("sample_titles") or [])[:3]:
            add(title)
    return items[:6]


def _tone_around(frame: pd.DataFrame, project: str, day: str) -> str:
    """Tone in the 14-day windows the peak file uses, recomputed from the posts."""
    peak = as_day(day)
    if peak is None or frame is None or frame.empty or "project" not in frame.columns:
        return ""
    subset = frame[frame["project"].eq(project)]

    def one(start, end) -> str:
        part = subset[(subset["date"] >= start) & (subset["date"] <= end)]
        return format_window(describe(rows_from_frame(part)))

    before = one(peak - pd.Timedelta(days=14), peak - pd.Timedelta(days=4))
    after = one(peak + pd.Timedelta(days=3), peak + pd.Timedelta(days=16))
    return f"Tone 14 days before: {before}. After: {after}."


def _peak_effects(context: dict, tone_line: str = "") -> list[str]:
    lines = []
    effects = context.get("effects") if isinstance(context.get("effects"), dict) else {}
    persistence = effects.get("persistence")
    if persistence:
        decay = effects.get("decay_days")
        extra = f", {decay} days" if decay not in (None, "") else ""
        follow = {"abgeklungen": "faded", "dauerhaft erhöht": "stayed high", "faded": "faded", "stayed high": "stayed high"}.get(str(persistence), persistence)
        lines.append(f"Follow-up: {follow}{extra}")
    if tone_line:
        lines.append(tone_line)
    if context.get("off_topic_suspect"):
        lines.append("Note: peak may be off-topic")
    return lines


def _peak_points(peak: dict, context: dict, tone_line: str = "") -> list[dict]:
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
        follow = {"abgeklungen": "faded", "dauerhaft erhöht": "stayed high", "faded": "faded", "stayed high": "stayed high"}.get(str(persistence), persistence)
        add(f"Follow-up: {follow}{extra}")
    if tone_line:
        add(tone_line)
    if context.get("off_topic_suspect"):
        add("Note: peak may be off-topic")
    if not points:
        for title in (peak.get("sample_titles") or [])[:3]:
            add(title)
    return points


def load_peak_markers(city: str, frame: pd.DataFrame | None = None) -> list[dict]:
    """Peak windows for the selected city.

    Markers come from ``data/context.json``. They are counted on every kept post of the
    project, not again for the channel switch.
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
            tone_line = _tone_around(frame, project, day) if frame is not None else ""
            profile = context.get("source_profile") if isinstance(context.get("source_profile"), dict) else {}
            secondary = context.get("event_type_secondary")
            raw_type = context.get("event_type") or ""
            event_type = raw_type
            if secondary:
                event_type = f"{event_type} · {secondary}"
            effects = context.get("effects") if isinstance(context.get("effects"), dict) else {}
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
                "family": event_family(raw_type),
                "follow": follow_of(str(effects.get("persistence") or "")),
                "has_amount": False,
                "headline": headline,
                "summary": _peak_lead(context),
                "confidence": scored["level"],
                "confidence_why": scored["why"],
                "terms": [str(term) for term in (context.get("top_terms") or []) if term][:6],
                "sources": (
                    f"{profile['n_posts']} posts · {profile['n_sources']} sources"
                    if profile.get("n_posts") and profile.get("n_sources") else ""
                ),
                "headlines": _peak_headlines(peak, context, frame, project),
                "effects": _peak_effects(context, tone_line),
                "points": _peak_points(peak, context, tone_line),
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
    project = themes.project_for_city(city)
    mentions = (
        window["mention_id"].astype(str).tolist()
        if project and len(window) and "mention_id" in window.columns
        else []
    )
    channels = (
        {str(mention): str(channel_name or "") for mention, channel_name in zip(window["mention_id"], window["channel"])}
        if len(window) and "mention_id" in window.columns
        else {}
    )
    if project:
        terms = themes.profile(project, mentions, "thema", channels)
        arguments = themes.claim_rows(project, mentions, channels)
        terms_note = themes.CURATED_TERMS_NOTE
        arguments_note = themes.CURATED_ARGUMENTS_NOTE
    else:
        terms = _token.category_profile(window)
        arguments = _token.argument_profile(window)
        terms_note = _token.TERMS_NOTE
        arguments_note = _token.ARGUMENTS_NOTE
    all_peaks = load_peak_markers("All", frame)
    peaks = [
        peak for peak in all_peaks
        if city == "All" or CITY_BY_PROJECT.get(peak["project"]) == city
    ]
    return {
        "city": city,
        "channel": channel,
        "stance_source": STANCE_SOURCE,
        "curated_project": project,
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
        "terms": terms,
        "arguments": arguments,
        "terms_note": terms_note,
        "arguments_note": arguments_note,
        "cities": CITY_BUTTONS,
        "channels": CHANNEL_BUTTONS,
        "peaks": peaks,
        "families": EVENT_FAMILIES,
        "stance": stance_block(window),
        "mockery": mockery_block(window),
        "facts": themes.sheet_for_city(city),
    }
