"""Externe Suche zu einem Peak.

Google-News-RSS und die offizielle Projektseite, nur bei Volumen-Ausreißern.
Schreibt ``external_candidates``.
Aufgerufen von ``06_peak_kontext.py``. Die Schwellen bleiben dort.
"""
from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import importlib

def _k():
    return importlib.import_module("01_vorverarbeitung.06_peak_kontext")

def clean_html_text(raw_text: str) -> str:
    if not raw_text:
        return ""
    no_tags = re.sub(r"<[^>]+>", " ", raw_text)
    unescaped = html.unescape(no_tags)
    return re.sub(r"\s+", " ", unescaped).strip()


def http_get(url: str, retries: int = 3, timeout: int = 10, backoff: float = 2.0) -> bytes:
    """GET mit Retries und exponentiellem Backoff (bei 429/5xx und Netzwerkfehlern)."""
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=_k().HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code not in (429, 500, 502, 503, 504):
                break
        except Exception as e:
            last_err = e
        time.sleep(backoff ** (attempt + 1))
    raise RuntimeError(str(last_err))


def fetch_google_news_rss(query: str, must_match_regex: str, lang: str = "de",
                          country: str = "DE", max_items: int = 3) -> list[dict]:
    """Fragt Google News RSS ab und filtert themenfremde Treffer streng aus."""
    encoded_q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded_q}&hl={lang}&gl={country}&ceid={country}:{lang}"
    try:
        root = ET.fromstring(http_get(url))
        results, seen_titles = [], set()
        for item in root.findall(".//item"):
            raw_title = clean_html_text(item.findtext("title", default=""))
            source_el = item.find("source")
            source_name = clean_html_text(source_el.text) if source_el is not None else ""
            if source_name and raw_title.endswith(f" - {source_name}"):
                raw_title = raw_title[: -len(f" - {source_name}")].strip()
            if not re.search(must_match_regex, raw_title, flags=re.I):
                continue
            title_key = raw_title.lower()[:60]
            if not raw_title or title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            results.append({
                "title": raw_title,
                "source": source_name or "Google News",
                "published": item.findtext("pubDate", default="").strip(),
                "url": item.findtext("link", default="").strip()
            })
            if len(results) >= max_items:
                break
        return results
    except Exception as e:
        return [{"error": f"RSS fetch failed: {e}"}]


def crawl_official_page_context(url: str, keywords: list[str]) -> dict:
    """Liest Meta-Beschreibung und relevante Überschriften einer Projekt-/Stadtseite aus."""
    try:
        html_text = http_get(url).decode("utf-8", errors="ignore")
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.S | re.I)
        desc_match = re.search(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html_text, flags=re.S | re.I)
        candidates = re.findall(r"<(?:h1|h2|h3|a)[^>]*>(.*?)</(?:h1|h2|h3|a)>", html_text, flags=re.S | re.I)
        headlines = []
        for raw in candidates:
            text = clean_html_text(raw)
            if 25 <= len(text) <= 180 and any(kw.lower() in text.lower() for kw in keywords):
                if text not in headlines:
                    headlines.append(text)
        return {
            "source_url": url,
            "page_title": clean_html_text(title_match.group(1)) if title_match else "",
            "meta_description": clean_html_text(desc_match.group(1)) if desc_match else "",
            "matching_headlines": headlines[:5],
            "status": "ok"
        }
    except Exception as e:
        return {"source_url": url, "status": f"unreachable ({e})", "matching_headlines": []}

def targeted_external_context(cfg: dict, start_str: str, end_str: str,
                              top_terms: list[str], headlines: list[str]) -> list[dict]:
    """
    Baut die Suche aus den Schlagwörtern des Peaks und wählt den RSS-Treffer,
    der inhaltlich am meisten mit den Peak-Beiträgen übereinstimmt (nicht den Erstplatzierten).
    """
    keyword_set = set(top_terms)
    for h in headlines:
        keyword_set |= _k().tokenize(h)

    def pick(articles: list[dict]) -> list[dict]:
        scored = []
        for a in articles:
            if "error" in a:
                continue
            toks = _k().tokenize(a["title"])
            overlap = len(toks & keyword_set) + len(toks & set(top_terms))  # Top-Terme zählen doppelt
            if overlap >= 2:
                scored.append({**a, "match_score": overlap})
        scored.sort(key=lambda x: x["match_score"], reverse=True)
        return scored[:2]

    # 1. Versuch: Projekt-Query + 2 stärkste Schlagwörter im Peak-Fenster
    query = f"{cfg['rss_query']} {' '.join(top_terms[:2])} after:{start_str} before:{end_str}".replace("  ", " ")
    chosen = pick(fetch_google_news_rss(query, cfg["must_match_regex"], cfg["lang"], cfg["country"], max_items=15))
    if chosen:
        return chosen

    # 2. Versuch: nur Projekt-Query, Fenster um +-5 Tage erweitert
    dt_start = datetime.strptime(start_str, "%Y-%m-%d") - timedelta(days=5)
    dt_end = datetime.strptime(end_str, "%Y-%m-%d") + timedelta(days=5)
    wider = f"{cfg['rss_query']} after:{dt_start:%Y-%m-%d} before:{dt_end:%Y-%m-%d}"
    return pick(fetch_google_news_rss(wider, cfg["must_match_regex"], cfg["lang"], cfg["country"], max_items=15))

