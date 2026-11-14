"""1. Prepare.

Reads the filtered posts, cuts the subscription notice, and sets date,
project, city, and channel. Stance and terms come afterwards from
``stance.py`` and ``terms.py``.
"""

from __future__ import annotations

import json

import pandas as pd

from . import stance, terms
from .config import (
    CHANNEL_BY_SOURCE,
    CITY_BY_PROJECT,
    POSTS_FILE,
    PROJECT_LABEL,
    ROOT,
    TEXT_CHARS,
)

SOCIAL_PLATFORMS = frozenset({
    "YouTube", "Instagram", "Facebook", "Mastodon", "Flickr", "Reddit", "LinkedIn", "TikTok", "X",
})
PLATFORM_DOMAINS = (
    ("YouTube", ("youtube.com", "youtu.be")),
    ("Instagram", ("instagram.com",)),
    ("Facebook", ("facebook.com",)),
    ("Reddit", ("reddit.com",)),
    ("LinkedIn", ("linkedin.com",)),
    ("TikTok", ("tiktok.com",)),
    ("Telegram", ("t.me", "telegram.me", "telegram.org")),
    ("Flickr", ("flickr.com",)),
    ("Pinterest", ("pinterest.com",)),
    ("Tumblr", ("tumblr.com",)),
    ("Bluesky", ("bsky.app",)),
    ("Vimeo", ("vimeo.com",)),
    ("X", ("twitter.com", "x.com")),
)
REGIONAL_HOST_MARKS = (
    "meinbezirk", "anzeiger", "rundblick", "24hamburg", "bw24", "sauerlandkurier",
    "salzkammergut", "rheingau", "az-online", "krone.at", "kurier.at", "vol.at",
)

# The Heilbronner Stimme paywall notice often sits in front of the article.
PAYWALL_MARKERS = (
    "jetzt den vollen zugang freischalten",
    "artikel merken und auf allen",
    "sie haben kein abonnement",
)

_CACHE: pd.DataFrame | None = None


def host_of(source) -> str:
    host = str(source or "").strip().lower()
    return host[4:] if host.startswith("www.") else host


def host_is(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def raw_platform(source, media_type):
    host = host_of(source)
    for name, domains in PLATFORM_DOMAINS:
        if any(host_is(host, domain) for domain in domains):
            return name
    if media_type == "Microblog":
        return "Mastodon"
    if media_type in {"YouTube Video", "YouTube Comments"}:
        return "YouTube"
    return None


def platform_of(source, media_type):
    name = raw_platform(source, media_type)
    return name if name in SOCIAL_PLATFORMS else None


def channel_of(media_type, platform, host) -> str:
    if isinstance(platform, str) and platform:
        return "Social"
    if media_type == "News" or any(mark in host for mark in REGIONAL_HOST_MARKS):
        return "News"
    return "Other web"


def text_without_paywall(text: str) -> str:
    raw = str(text or "")
    lowered = raw.lower()
    cut = len(raw)
    for marker in PAYWALL_MARKERS:
        position = lowered.find(marker)
        if position != -1:
            cut = min(cut, position)
    return raw[:cut].strip()


def _project_key(value) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str) and value:
        return value
    return ""


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    """Date, text, city, and channel. Stance and terms come later."""
    timestamps = pd.to_datetime(frame["published_at"], utc=True, errors="coerce")
    frame["date"] = timestamps.dt.tz_convert(None).dt.normalize()
    frame["text"] = (
        frame["title"].fillna("").astype(str)
        + "\n"
        + frame["content"].fillna("").astype(str).map(text_without_paywall)
    ).str.slice(0, TEXT_CHARS)
    frame["project"] = frame["matched_projects"].map(_project_key)
    frame["project_label"] = frame["project"].map(lambda key: PROJECT_LABEL.get(key, key))
    frame["city"] = frame["project"].map(CITY_BY_PROJECT)
    frame["platform"] = [
        platform_of(source, media_type)
        for source, media_type in zip(frame["source_name"], frame["media_type_name"])
    ]
    frame["source_channel"] = [
        channel_of(media_type, platform, host_of(source))
        for media_type, platform, source in zip(
            frame["media_type_name"], frame["platform"], frame["source_name"]
        )
    ]
    frame["channel"] = frame["source_channel"].map(CHANNEL_BY_SOURCE)
    frame["snippet"] = (
        frame["content"].fillna("").astype(str).map(text_without_paywall)
        .str.replace(r"\s+", " ", regex=True).str.strip().str.slice(0, 280)
    )
    return frame


def load_posts(refresh: bool = False) -> pd.DataFrame:
    """Filtered posts with city, channel, circle, and terms."""
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE

    path = ROOT / POSTS_FILE
    if not path.is_file():
        raise FileNotFoundError(
            f"{POSTS_FILE.as_posix()} is missing. From the repository root, run: "
            "python pipeline/01_filter_posts.py"
        )
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    frame = prepare(pd.DataFrame(raw))
    frame = stance.assign(frame)
    frame = terms.attach(frame)
    frame = frame.dropna(subset=["date"]).copy()
    _CACHE = frame
    return frame
