import html
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ==========================================
# 1. PFADE & PROJEKT-KONFIGURATION
# ==========================================
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
EVENTS_INPUT_FILE = DATA_DIR / "02_peaks" / "peaks.json"
OUTPUT_ENRICHED_FILE = DATA_DIR / "02_peaks" / "events.json"

MIN_POSTS_FOR_CRAWL = 4  # Ignoriert Mini-Ausschläge unter 4 Posts

PROJECT_CONFIG = {
    "Heilbronn_Seilbahn": {
        "display_name": "Heilbronn urban cable car (city – IPAI)",
        "city": "Heilbronn",
        "stage": "Planning / feasibility",
        "rss_query": '"Seilbahn" Heilbronn',
        "must_match_regex": r"seilbahn|gondel|ipai|öpnv|nahverkehr|mobilität",
        "lang": "de",
        "country": "DE",
        "official_url": "https://www.heilbronn.de",
        "page_keywords": ["Seilbahn", "IPAI", "Stadtbahn", "Nahverkehr", "Mobilität"]
    },
    "Bonn_Seilbahn": {
        "display_name": "Bonn urban cable car (Venusberg – Beuel)",
        "city": "Bonn",
        "stage": "Planning",
        "rss_query": '"Seilbahn" Bonn',
        "must_match_regex": r"seilbahn|gondel|venusberg|öpnv|nahverkehr|rheinquerung",
        "lang": "de",
        "country": "DE",
        "official_url": "https://www.bonn.de",
        "page_keywords": ["Seilbahn", "Venusberg", "Beuel", "ÖPNV", "Nordbrücke"]
    },
    "Paris_Cable_C1": {
        "display_name": "Câble C1 Île-de-France (Créteil – Villeneuve-Saint-Georges)",
        "city": "Paris / Val-de-Marne",
        "stage": "Construction / operation (reference)",
        "rss_query": '"Câble C1" OR "téléphérique" Créteil',
        "must_match_regex": r"téléphérique|telepherique|câble|cable|créteil|creteil|val-de-marne",
        "lang": "fr",
        "country": "FR",
        "official_url": "https://www.iledefrance-mobilites.fr",
        "page_keywords": ["Câble C1", "téléphérique", "Créteil", "Villeneuve", "inauguration"]
    },
    "IPAI_Campus": {
        "display_name": "IPAI Campus (Innovation Park Artificial Intelligence)",
        "city": "Heilbronn",
        "stage": "Construction / development (comparison)",
        "rss_query": '"IPAI" Heilbronn',
        "must_match_regex": r"ipai|ki-park|ki-zentrum|künstliche intelligenz|schwarz|campus|spatenstich",
        "lang": "de",
        "country": "DE",
        "official_url": "https://ip.ai",
        "page_keywords": ["IPAI", "Campus", "Heilbronn", "KI", "Innovation", "Spatenstich"]
    }
}


# ==========================================
# 2. CRAWLER-HILFSFUNKTIONEN
# ==========================================
def clean_html_text(raw_text: str) -> str:
    if not raw_text:
        return ""
    no_tags = re.sub(r"<[^>]+>", " ", raw_text)
    unescaped = html.unescape(no_tags)
    return re.sub(r"\s+", " ", unescaped).strip()


def fetch_google_news_rss(
    query: str,
    must_match_regex: str,
    lang: str = "de",
    country: str = "DE",
    max_items: int = 3
) -> list[dict]:
    """Fragt Google News RSS ab und filtert themenfremde Treffer streng aus."""
    encoded_q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded_q}&hl={lang}&gl={country}&ceid={country}:{lang}"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Hackathon-Research/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            xml_bytes = resp.read()

        root = ET.fromstring(xml_bytes)
        results = []
        seen_titles = set()

        for item in root.findall(".//item"):
            raw_title = clean_html_text(item.findtext("title", default=""))
            source_el = item.find("source")
            source_name = clean_html_text(source_el.text) if source_el is not None else ""

            if source_name and raw_title.endswith(f" - {source_name}"):
                raw_title = raw_title[: -len(f" - {source_name}")].strip()

            # Relevanz-Check: Schlagzeile muss wirklich zum Thema passen (kein Falafel/Raupen-Beifang)
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
        return [{"error": f"RSS-Abruf fehlgeschlagen: {e}"}]


def get_event_context_with_fallback(cfg: dict, start_str: str, end_str: str) -> list[dict]:
    """Sucht Schlagzeilen im Peak-Zeitfenster; erweitert bei 0 Treffern einmal um +-5 Tage."""
    query = f"{cfg['rss_query']} after:{start_str} before:{end_str}"
    articles = fetch_google_news_rss(
        query, cfg["must_match_regex"], cfg["lang"], cfg["country"], max_items=3
    )

    valid_articles = [a for a in articles if "error" not in a]
    if not valid_articles:
        dt_start = datetime.strptime(start_str, "%Y-%m-%d") - timedelta(days=5)
        dt_end = datetime.strptime(end_str, "%Y-%m-%d") + timedelta(days=5)
        wider_query = f"{cfg['rss_query']} after:{dt_start.strftime('%Y-%m-%d')} before:{dt_end.strftime('%Y-%m-%d')}"
        articles = fetch_google_news_rss(
            wider_query, cfg["must_match_regex"], cfg["lang"], cfg["country"], max_items=3
        )

    return [a for a in articles if "error" not in a]


def crawl_official_page_context(url: str, keywords: list[str]) -> dict:
    """Liest Meta-Beschreibung und relevante aktuelle Überschriften einer Projekt-/Stadtseite aus."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Hackathon-Research/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            html_text = resp.read().decode("utf-8", errors="ignore")

        title_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.S | re.I)
        page_title = clean_html_text(title_match.group(1)) if title_match else ""

        desc_match = re.search(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
            html_text,
            flags=re.S | re.I
        )
        description = clean_html_text(desc_match.group(1)) if desc_match else ""

        candidates = re.findall(r"<(?:h1|h2|h3|a)[^>]*>(.*?)</(?:h1|h2|h3|a)>", html_text, flags=re.S | re.I)
        headlines = []
        for raw in candidates:
            text = clean_html_text(raw)
            if 25 <= len(text) <= 180 and any(kw.lower() in text.lower() for kw in keywords):
                if text not in headlines:
                    headlines.append(text)

        return {
            "source_url": url,
            "page_title": page_title,
            "meta_description": description,
            "matching_headlines": headlines[:5],
            "status": "ok"
        }
    except Exception as e:
        return {
            "source_url": url,
            "status": f"unreachable ({e})",
            "matching_headlines": []
        }


# ==========================================
# 3. HAUPTPROGRAMM
# ==========================================
def main():
    if not EVENTS_INPUT_FILE.exists():
        print(f"ERROR: '{EVENTS_INPUT_FILE.relative_to(BASE_DIR)}' is missing. Run 'python pipeline/02_detect_peaks.py' first.")
        return

    with open(EVENTS_INPUT_FILE, "r", encoding="utf-8") as f:
        events_data = json.load(f)

    enriched_projects = []

    print("=" * 75)
    print("CRAWL PROJECT AND PEAK CONTEXT")
    print("=" * 75)

    for proj_block in events_data:
        proj_key = proj_block["project"]
        cfg = PROJECT_CONFIG.get(proj_key)
        if not cfg:
            enriched_projects.append(proj_block)
            continue

        print(f"\n>>> PROJECT: {cfg['display_name']}")
        print("-" * 75)

        print(f"  [1/3] Official page ({cfg['official_url']})...")
        official_scan = crawl_official_page_context(cfg["official_url"], cfg["page_keywords"])
        for h in official_scan.get("matching_headlines", [])[:3]:
            print(f"        -> Page hit: \"{h}\"")

        print(f"  [2/3] Latest headlines for {cfg['rss_query']}...")
        latest_news = fetch_google_news_rss(
            cfg["rss_query"], cfg["must_match_regex"], cfg["lang"], cfg["country"], max_items=4
        )
        for n in latest_news:
            if "error" not in n:
                print(f"        -> Latest [{n['source']}]: {n['title']}")

        significant_peaks = [p for p in proj_block.get("peaks", []) if p.get("post_count", 0) >= MIN_POSTS_FOR_CRAWL]
        print(f"  [3/3] Explain {len(significant_peaks)} peaks (>= {MIN_POSTS_FOR_CRAWL} posts)...")

        for peak in significant_peaks:
            win = peak["crawler_window"]
            peak_news = get_event_context_with_fallback(cfg, win["start"], win["end"])
            peak["crawled_context"] = peak_news

            print(f"        * Peak {peak['date']} ({peak['post_count']} posts):")
            if peak_news:
                for vn in peak_news[:2]:
                    print(f"          - [External | {vn['source']}] {vn['title']}")
            else:
                for st in peak.get("sample_titles", [])[:2]:
                    print(f"          - [Dataset] {st[:85]}")

            time.sleep(0.2)

        proj_block["peaks"] = significant_peaks

        # Same lookup for change points.
        for cp in proj_block.get("change_points", []):
            cp_dt = datetime.strptime(cp["date"], "%Y-%m-%d")
            cp_start = (cp_dt - timedelta(days=3)).strftime("%Y-%m-%d")
            cp_end = (cp_dt + timedelta(days=3)).strftime("%Y-%m-%d")
            cp["crawled_context"] = get_event_context_with_fallback(cfg, cp_start, cp_end)
            time.sleep(0.2)

        proj_block["project_context"] = {
            "display_name": cfg["display_name"],
            "city": cfg["city"],
            "stage": cfg["stage"],
            "official_site_scan": official_scan,
            "latest_news": [n for n in latest_news if "error" not in n]
        }
        enriched_projects.append(proj_block)

    final_payload = {
        "collection_metadata": {
            "collected_at_utc": datetime.now(timezone.utc).isoformat(),
            "methods": [
                "Google News RSS Search (public XML feeds with date-range operators after:/before: and headline relevance filtering)",
                "Public HTML metadata & headline extraction from official city/project homepages"
            ],
            "compliance_note": "Only publicly accessible pages without login or paywall were queried; no personal user identifiers collected."
        },
        "projects": enriched_projects
    }

    with open(OUTPUT_ENRICHED_FILE, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 75)
    print(f"Done. Wrote {OUTPUT_ENRICHED_FILE.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()