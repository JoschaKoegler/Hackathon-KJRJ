import html
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ==========================================
# 1. PFADE, PARAMETER & PROJEKT-KONFIGURATION
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
CLEAN_DATA_FILE = BASE_DIR / "clean_data.json"
EVENTS_INPUT_FILE = BASE_DIR / "detected_events.json"
OUTPUT_ENRICHED_FILE = BASE_DIR / "projects_with_context.json"

# Optional: manuell recherchierte Ereignisse (haben Vorrang vor allem Automatischen).
# Format: [{"project": "Heilbronn_Seilbahn", "date": "2025-03-12",
#           "title": "...", "type": "Gemeinderatsbeschluss", "source_url": "https://..."}]
CURATED_EVENTS_FILE = BASE_DIR / "curated_events.json"

MIN_POSTS_FOR_CRAWL = 4     # nur Peaks ab dieser Größe bekommen eine externe RSS-Suche
REQUEST_DELAY = 0.5         # Pause zwischen Netzwerk-Anfragen (Sekunden)
BASELINE_DAYS = 35          # Vergleichszeitraum vor dem Peak-Fenster für "was ist neu?"
TOP_TERMS = 6               # Anzahl Schlagwörter pro Peak
TERM_MIN_LEN = 5            # kürzere Wörter werden nicht als Schlagwort gewertet
MAX_GLOBAL_DF_RATIO = 0.15  # Begriffe in >15 % aller Projekt-Beiträge sind zu generisch (nur ab 50 Beiträgen)
OFF_TOPIC_SHARE = 0.4       # <40 % der Peak-Beiträge nennen das Projekt im Titel/Textanfang -> Prüf-Flag
DECAY_REL = 0.1             # "Abgeklungen" = Baseline + max(0.5, 10 % der Peak-Höhe)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Hackathon-Research/1.0"}

# Optional: Kurzzusammenfassung per LLM statt Vorlage.
# Es werden nur Titel + kurze Textausschnitte gesendet (keine Autoren/URLs der Social-Posts).
# Benötigt: pip install anthropic  und Umgebungsvariable ANTHROPIC_API_KEY.
USE_LLM = False
LLM_MODEL = "claude-sonnet-4-6"

# NEUES PROJEKT HINZUFÜGEN: Regeln in 1_filter_data.py (PROJECT_RULES) ergänzen und hier einen Eintrag
# anlegen. Die Analyse selbst ist projekt-unabhängig. Optionale Schlüssel pro Projekt:
#   "topic_regex":           Regex für den Themen-Check (Standard: must_match_regex)
#   "extra_stopwords":       projektspezifische Füllwörter für die Schlagwort-Extraktion
#   "extra_event_types":     {"Typname": {"strong": [regex, ...], "weak": [regex, ...]}}
#   "suppress_event_types":  ["Typname", ...] Typen, die für dieses Projekt nicht passen
# must_match_regex bewusst eng; official_urls gezielt auf Projekt-/Presseseiten setzen,
# sobald geprüft (ip.ai bitte auf Erreichbarkeit prüfen).
PROJECT_CONFIG = {
    "Heilbronn_Seilbahn": {
        "display_name": "Urbane Seilbahn Heilbronn (City – IPAI)",
        "city": "Heilbronn",
        "stage": "Planung / Machbarkeit",
        "rss_query": '"Seilbahn" Heilbronn',
        "must_match_regex": r"seilbahn|gondel|ipai",
        "lang": "de",
        "country": "DE",
        "official_urls": ["https://www.heilbronn.de"],
        "page_keywords": ["Seilbahn", "IPAI", "Stadtbahn", "Nahverkehr", "Mobilität"]
    },
    "Bonn_Seilbahn": {
        "display_name": "Urbane Seilbahn Bonn (Venusberg – Beuel)",
        "city": "Bonn",
        "stage": "Planung",
        "rss_query": '"Seilbahn" Bonn',
        "must_match_regex": r"seilbahn|gondel|venusberg|rheinquerung",
        "lang": "de",
        "country": "DE",
        "official_urls": ["https://www.bonn.de"],
        "page_keywords": ["Seilbahn", "Venusberg", "Beuel", "ÖPNV", "Nordbrücke"]
    },
    "Paris_Cable_C1": {
        "display_name": "Câble C1 Île-de-France (Créteil – Villeneuve-Saint-Georges)",
        "city": "Paris / Val-de-Marne",
        "stage": "Bau / Betrieb (Referenzprojekt)",
        "rss_query": '"Câble C1" OR "téléphérique" Créteil',
        "must_match_regex": r"c[âa]ble\s*c1|\bc1\b|cr[ée]teil|val-de-marne|villeneuve-saint-georges|limeil|valenton",
        "lang": "fr",
        "country": "FR",
        "official_urls": ["https://www.iledefrance-mobilites.fr"],
        "page_keywords": ["Câble C1", "téléphérique", "Créteil", "Villeneuve", "inauguration"]
    },
    "IPAI_Campus": {
        "display_name": "IPAI Campus (Innovation Park Artificial Intelligence)",
        "city": "Heilbronn",
        "stage": "Bau / Entwicklung (Vergleichsprojekt)",
        "rss_query": '"IPAI" Heilbronn',
        "must_match_regex": r"ipai|ki-park|ki-zentrum|spatenstich",
        "lang": "de",
        "country": "DE",
        "official_urls": ["https://ip.ai"],
        "page_keywords": ["IPAI", "Campus", "Heilbronn", "KI", "Innovation", "Spatenstich"]
    }
}

# ---- Regeln für Ereignistyp (strong = eindeutig, weak = nur schwache Hinweise) ----
# Titeltreffer zählen stärker als Texttreffer. Ein Typ gilt nur, wenn mindestens ein Viertel
# der Peak-Beiträge ihn stützt (skaliert mit der Peak-Größe).
EVENT_TYPE_RULES = {
    "Politische Entscheidung": {
        "strong": [r"gemeinderat", r"stadtrat", r"kreistag", r"landtag", r"beschlie[sß]", r"beschluss",
                   r"beschlossen", r"abstimmung", r"bürgerentscheid", r"conseil municipal", r"d[ée]lib[ée]r"],
        "weak": [r"mehrheit", r"ausschuss", r"\bvote\b", r"koalition", r"antrag"],
    },
    "Kosten / Finanzierung": {
        "strong": [r"kosten", r"kostet", r"teurer", r"kostenschätzung", r"finanzierung", r"förderzusage",
                   r"fördermittel", r"co[uû]t", r"subvention", r"\d+(?:[.,]\d+)?\s*(?:mio|millionen|million)"],
        "weak": [r"förder", r"budget", r"haushalt", r"\beuro\b", r"€"],
    },
    "Planung / Route / Machbarkeit": {
        "strong": [r"trasse", r"machbarkeit", r"gutachten", r"planfeststellung", r"variante", r"trac[ée]",
                   r"standort", r"faisabilit[ée]"],
        "weak": [r"planung", r"\broute\b", r"station", r"[ée]tude"],
    },
    "Visualisierung / Entwurf": {
        "strong": [r"visualisierung", r"animation", r"rendering", r"entwurf", r"simulation"],
        "weak": [r"\bvideo\b", r"modell"],
    },
    "Protest / Bürgerbeteiligung": {
        "strong": [r"bürgerinitiative", r"protest", r"widerstand", r"petition", r"p[ée]tition", r"unterschriften",
                   r"anwohner", r"bürgerbeteiligung", r"manifestation", r"riverains"],
        "weak": [r"kritik", r"kritisiert", r"sorgen", r"contestation"],
    },
    "Bau / Meilenstein": {
        "strong": [r"spatenstich", r"baustart", r"richtfest", r"grundstein", r"bauarbeiten", r"baustelle",
                   r"chantier", r"travaux"],
        "weak": [r"fertigstellung"],
    },
    "Eröffnung / Betriebsstart": {
        "strong": [r"inauguration", r"eröffnung", r"eröffnet", r"inbetriebnahme", r"mise en service",
                   r"betriebsstart", r"erste fahrgäste", r"premiers? passagers"],
        "weak": [r"ouverture", r"ouvre", r"\bopens\b"],
    },
    "Betriebsstörung / Sperrung": {
        "strong": [r"störung", r"gesperrt", r"sperrung", r"stillstand", r"außer betrieb", r"ausfall",
                   r"temp[êe]te", r"interrompu", r"interruption", r"\bpanne\b", r"fermeture", r"ferm[ée]\b",
                   r"[ée]vacuation"],
        "weak": [r"arr[êe]t", r"\bvents?\b", r"\bsturm\b", r"wartung", r"maintenance"],
    },
    "Sicherheit / Vorfall": {
        "strong": [r"agression", r"übergriff", r"s[ée]curit[ée]", r"sicherheit", r"accident", r"unfall",
                   r"harc[èe]lement", r"belästigung", r"vandal"],
        "weak": [r"gefahr", r"danger", r"polizei"],
    },
    "Partnerschaft / Mitgliedschaft": {
        "strong": [r"mitgliedschaft", r"\bmitglied\b", r"schließt sich", r"vertragsunterzeichnung",
                   r"kooperation", r"partnerschaft", r"partenariat", r"rejoint", r"beitritt"],
        "weak": [r"partner", r"konsortium"],
    },
    "Personalie": {
        "strong": [r"beruft", r"ernannt", r"berufung", r"chief technology officer", r"\bcto\b", r"\bceo\b",
                   r"nomm[ée]", r"nomination", r"neuer geschäftsführer", r"neue geschäftsführerin"],
        "weak": [r"geschäftsführer", r"vorstand"],
    },
    "Veranstaltung / Gipfel": {
        "strong": [r"gipfel", r"konferenz", r"kongress", r"tag der offenen", r"\bmesse\b", r"summit",
                   r"sprechtag", r"veranstaltung", r"besichtigung", r"für besucher"],
        "weak": [r"\bevent\b", r"besucher", r"workshop"],
    },
}
GENERIC_EVENT_TYPE = "Medienberichterstattung (kein klarer Auslöser)"
MIN_EVENT_SCORE = 3
MIN_TYPE_SUPPORT_SHARE = 0.25   # Anteil der Peak-Beiträge, die einen Typ stützen müssen
SECONDARY_TYPE_RATIO = 0.6      # zweiter Typ wird genannt, wenn sein Score >= 60 % des besten ist

# Begriffe, die in jedem Beitrag vorkommen und daher keine Aussagekraft haben
PROJECT_STOP_TERMS = {
    "seilbahn", "seilbahnen", "seilbahnprojekt", "heilbronn", "heilbronner", "ipai", "bonn", "bonner",
    "paris", "téléphérique", "teleferique", "câble", "cable", "créteil", "creteil", "campus",
    "gondelbahn", "stadt"
}
STOPWORDS = set("""
aber alle allem allen aller alles also auch auf aus bei beim bereits bin bis bist dabei dafür dagegen daher
damit dann darauf das dass dein dem den denn der des die dies diese diesem diesen dieser dieses doch dort durch
eine einem einen einer eines einige einmal für gegen gewesen hab habe haben hat hatte hatten hier hin hinter ich
ihm ihn ihnen ihr ihre ihrem ihren ihrer immer ist jede jedem jeden jeder jedes jetzt kann kein keine können
machen man mehr mein mit muss nach nicht noch nun nur oder ohne sehr sein seine seinem seinen seiner sich sie sind
soll sollen sollte über um und uns unter vom von vor war waren warum was weil wenn werden wie wieder will wir wird
wollen wurde wurden zum zur zwischen dies sowie sowohl diese bereits etwa rund laut sagte
dans des les une que qui pour pas sur avec sont est mais plus par aux ses son leur leurs cette ces ont comme
être avoir fait faire aussi tout tous très sans sous entre dont même
the and for with that this from have has are was were will not but they their about into more than been also
""".split())
STOPWORDS |= set("""
gibt schon ganz später zwei drei vier fünf neue neuer neuen neues viele vielen gestern heute morgen liegen
liegt sehen sieht geht gehen bleibt worden würde wäre wären unsere unseren unserem unserer euch ihnen etwas
montag dienstag mittwoch donnerstag freitag samstag sonntag januar februar märz april juni juli august
september oktober november dezember lundi mardi mercredi jeudi vendredi samedi dimanche janvier février
mars avril juin juillet août septembre octobre novembre décembre
""".split())

# ==========================================
# 2. HTTP- & RSS-HILFSFUNKTIONEN
# ==========================================
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
            req = urllib.request.Request(url, headers=HEADERS)
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
        return [{"error": f"RSS-Abruf fehlgeschlagen: {e}"}]


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


# ==========================================
# 3. DATEN LADEN & TEXT-HILFSFUNKTIONEN
# ==========================================
def parse_date(ts):
    try:
        clean = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(ts).strip().replace("Z", "+00:00"))
        return datetime.fromisoformat(clean).date()
    except (ValueError, TypeError):
        return None


def load_docs(path: Path) -> dict[str, list[dict]]:
    """Gruppiert die bereinigten Beiträge pro Hauptprojekt."""
    with open(path, "r", encoding="utf-8") as f:
        posts = json.load(f)
    by_project: dict[str, list[dict]] = {}
    for p in posts:
        d = parse_date(p.get("published_at"))
        projects = p.get("matched_projects") or []
        if d is None or not projects:
            continue
        sent = p.get("sentiment")
        try:
            sent = float(sent)
            if sent == -99:
                sent = None
        except (TypeError, ValueError):
            sent = None
        doc = {
            "mention_id": p.get("mention_id"),
            "date": d,
            "title": re.sub(r"\s+", " ", str(p.get("title") or "")).strip(),
            "content": re.sub(r"\s+", " ", str(p.get("content") or "")).strip(),
            "source": p.get("source_name") or "unbekannt",
            "media_type": p.get("media_type_name") or "unbekannt",
            "sentiment": sent,
        }
        by_project.setdefault(projects[0], []).append(doc)
    return by_project


def load_curated_events() -> list[dict]:
    if not CURATED_EVENTS_FILE.exists():
        return []
    try:
        with open(CURATED_EVENTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as e:
        print(f"  WARNUNG: '{CURATED_EVENTS_FILE.name}' konnte nicht gelesen werden ({e}).")
        return []


def curated_near(events: list[dict], project: str, date_str: str, days: int = 3) -> list[dict]:
    center = datetime.strptime(date_str, "%Y-%m-%d")
    found = []
    for ev in events:
        if ev.get("project") != project:
            continue
        try:
            ev_dt = datetime.strptime(str(ev.get("date")), "%Y-%m-%d")
        except ValueError:
            continue
        if abs((ev_dt - center).days) <= days:
            found.append(ev)
    return found


def tokenize(text: str, extra_stop=frozenset()) -> set[str]:
    words = re.findall(r"[a-zäöüßéèêàâçîôûù]{%d,}" % TERM_MIN_LEN, str(text).lower())
    return {w for w in words if w not in STOPWORDS and w not in PROJECT_STOP_TERMS and w not in extra_stop}


def doc_terms(doc: dict, extra_stop=frozenset()) -> set[str]:
    return tokenize(f"{doc['title']} {doc['content'][:1500]}", extra_stop)


_GLOBAL_DF_CACHE: dict = {}


def get_global_df(proj_key: str, project_docs: list[dict], extra_stop) -> tuple[Counter, int]:
    """Dokumenthäufigkeit jedes Begriffs über ALLE Beiträge des Projekts (Filter gegen generische Wörter)."""
    key = (proj_key, len(project_docs))
    if key not in _GLOBAL_DF_CACHE:
        df = Counter()
        for d in project_docs:
            df.update(doc_terms(d, extra_stop))
        _GLOBAL_DF_CACHE[key] = df
    return _GLOBAL_DF_CACHE[key], len(project_docs)


# ==========================================
# 4. PEAK-KONTEXT: BAUSTEINE
# ==========================================
def distinctive_terms(window_docs: list[dict], baseline_docs: list[dict], global_df: Counter, n_all: int,
                      extra_stop=frozenset(), top_n: int = TOP_TERMS) -> list[str]:
    """
    Begriffe, die im Peak-Fenster deutlich häufiger vorkommen als in der Baseline (Log-Odds, Dokumentebene).
    Filter: Mindestanteil im Fenster (skaliert mit der Fenstergröße), keine projektweit generischen Begriffe;
    Begriffe, die auch in Titeln vorkommen, werden bevorzugt.
    """
    n_w, n_b = len(window_docs), len(baseline_docs)
    if n_w == 0:
        return []
    df_w, df_b, title_df = Counter(), Counter(), Counter()
    for d in window_docs:
        df_w.update(doc_terms(d, extra_stop))
        title_df.update(tokenize(d["title"], extra_stop))
    for d in baseline_docs:
        df_b.update(doc_terms(d, extra_stop))

    min_df = 1 if n_w <= 2 else max(2, math.ceil(0.2 * n_w))
    scored = []
    for term, dfw in df_w.items():
        if dfw < min_df:
            continue
        if n_all >= 50 and global_df.get(term, 0) / n_all > MAX_GLOBAL_DF_RATIO:
            continue
        score = math.log((dfw + 1) / (n_w + 2)) - math.log((df_b.get(term, 0) + 1) / (n_b + 2))
        score += 0.5 * (title_df.get(term, 0) / n_w)
        if score > 0:
            scored.append((score, dfw, term))
    scored.sort(reverse=True)
    return [t for _, _, t in scored[:top_n]]


AMOUNT_PATTERNS = [
    r"\b\d{1,3}(?:[.,]\d+)?\s*(?:mio\.?|millionen|million|mrd\.?|milliarden)(?:\s*(?:euro|€))?",
    r"\b\d{1,3}(?:[.,]\d+)?\s*millions?\s*d['’]euros?",
    r"\b\d[\d.,]*\s*(?:€|euro)\b",
]


def extract_amounts(docs: list[dict], top_n: int = 3) -> list[str]:
    found = Counter()
    for d in docs:
        text = f"{d['title']} {d['content'][:2000]}"
        for pat in AMOUNT_PATTERNS:
            for m in re.finditer(pat, text, flags=re.I):
                found[re.sub(r"\s+", " ", m.group(0)).strip().lower()] += 1
    return [a for a, _ in found.most_common(top_n)]


def rules_for_project(cfg: dict) -> dict:
    """Globale Ereignistyp-Regeln + projektspezifische Ergänzungen/Streichungen."""
    rules = {k: v for k, v in EVENT_TYPE_RULES.items() if k not in cfg.get("suppress_event_types", [])}
    rules.update(cfg.get("extra_event_types", {}))
    return rules


def classify_event_type(docs: list[dict], rules: dict) -> tuple[str, str | None, dict]:
    """
    Gibt (Haupttyp, Nebentyp oder None, Scores) zurück.
    Starke Muster: Titel 3 Punkte, Text 1. Schwache Muster: Titel 1, Text 0.5.
    Ein Typ braucht Mindestscore UND Unterstützung durch >= 25 % der Beiträge.
    """
    scores, support = Counter(), {}
    for i, d in enumerate(docs):
        title = d["title"].lower()
        body = d["content"][:600].lower()
        for etype, groups in rules.items():
            hit = False
            for pat in groups.get("strong", []):
                if re.search(pat, title):
                    scores[etype] += 3
                    hit = True
                if re.search(pat, body):
                    scores[etype] += 1
                    hit = True
            for pat in groups.get("weak", []):
                if re.search(pat, title):
                    scores[etype] += 1
                if re.search(pat, body):
                    scores[etype] += 0.5
            if hit:
                support.setdefault(etype, set()).add(i)

    need = max(1, math.ceil(MIN_TYPE_SUPPORT_SHARE * len(docs)))
    valid = [(sc, t) for t, sc in scores.items() if sc >= MIN_EVENT_SCORE and len(support.get(t, ())) >= need]
    if not valid:
        return GENERIC_EVENT_TYPE, None, dict(scores)
    valid.sort(reverse=True)
    best_score, best = valid[0]
    secondary = valid[1][1] if len(valid) > 1 and valid[1][0] >= SECONDARY_TYPE_RATIO * best_score else None
    return best, secondary, dict(scores)


def topic_relevance(docs: list[dict], topic_regex: str) -> float:
    """Anteil der Beiträge, die das Projektthema im Titel oder Textanfang nennen (Filter-Leck-Erkennung)."""
    if not docs:
        return 1.0
    hits = sum(1 for d in docs
               if re.search(topic_regex, f"{d['title']} {d['content'][:400]}".lower(), flags=re.I))
    return hits / len(docs)


def source_profile(docs: list[dict]) -> dict:
    sources = Counter(d["source"] for d in docs)
    media = Counter(d["media_type"] for d in docs)
    titles = {d["title"].lower()[:60] for d in docs if d["title"]}
    top_source, top_n = (sources.most_common(1)[0] if sources else ("", 0))
    share = top_n / len(docs) if docs else 0.0
    return {
        "n_posts": len(docs),
        "n_sources": len(sources),
        "n_unique_titles": len(titles),
        "media_types": dict(media),
        "top_source": top_source,
        "top_source_share": round(share, 2),
        # Viele Posts, aber kaum verschiedene Titel/Quellen -> Nachdruck/Agenturmeldung statt Debatte
        "likely_syndication": bool(docs) and (len(titles) <= max(1, len(docs) // 3) or share >= 0.6),
    }


def top_headlines(docs: list[dict], n: int = 3) -> list[str]:
    counts, first = Counter(), {}
    for d in docs:
        key = d["title"].lower()[:60]
        if not key:
            continue
        counts[key] += 1
        first.setdefault(key, d["title"])
    return [first[k] for k, _ in counts.most_common(n)]


def daily_counts(docs: list[dict]) -> Counter:
    return Counter(d["date"] for d in docs)


def mean_sentiment(docs: list[dict], start, end):
    vals = [d["sentiment"] for d in docs if d["sentiment"] is not None and start <= d["date"] <= end]
    return (round(sum(vals) / len(vals), 2), len(vals)) if len(vals) >= 3 else (None, len(vals))


def effect_analysis(project_docs: list[dict], peak_date, peak_count: int) -> dict:
    """Wie lange dauert der Peak, und bleibt die Debatte danach erhöht? Stimmung davor/danach."""
    daily = daily_counts(project_docs)
    last_date = max(d["date"] for d in project_docs)

    base_days = [peak_date - timedelta(days=k) for k in range(4, 4 + 31)]
    base_mean = sum(daily.get(d, 0) for d in base_days) / len(base_days)
    threshold = base_mean + max(0.5, DECAY_REL * (peak_count - base_mean))

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
        persistence = "noch offen (zu wenig Daten nach dem Peak)"
    elif after_mean > max(1.5 * base_mean, base_mean + 0.5):
        persistence = "dauerhaft erhöht"
    else:
        persistence = "abgeklungen"

    sent_before, n_before = mean_sentiment(project_docs, peak_date - timedelta(days=14), peak_date - timedelta(days=4))
    sent_after, n_after = mean_sentiment(project_docs, peak_date + timedelta(days=3), peak_date + timedelta(days=16))

    return {
        "baseline_posts_per_day": round(base_mean, 2),
        "decay_days": decay_days,
        "decay_note": None if decay_days is not None else "kein Rückgang auf Baseline innerhalb von 28 Tagen (oder Datenende)",
        "persistence": persistence,
        "avg_posts_per_day_days_7_to_21": round(after_mean, 2),
        "sentiment_14d_before": sent_before,
        "sentiment_14d_after": sent_after,
        "sentiment_n_before_after": [n_before, n_after],
    }


# ==========================================
# 5. GEZIELTE EXTERNE SUCHE (aus Peak-Inhalt gebaut)
# ==========================================
def targeted_external_context(cfg: dict, start_str: str, end_str: str,
                              top_terms: list[str], headlines: list[str]) -> list[dict]:
    """
    Baut die Suche aus den Schlagwörtern des Peaks und wählt den RSS-Treffer,
    der inhaltlich am meisten mit den Peak-Beiträgen übereinstimmt (nicht den Erstplatzierten).
    """
    keyword_set = set(top_terms)
    for h in headlines:
        keyword_set |= tokenize(h)

    def pick(articles: list[dict]) -> list[dict]:
        scored = []
        for a in articles:
            if "error" in a:
                continue
            toks = tokenize(a["title"])
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


# ==========================================
# 6. ZUSAMMENFASSUNG (Vorlage oder optional LLM)
# ==========================================
def template_summary(event_type: str, secondary: str | None, terms: list[str], headlines: list[str],
                     profile: dict, amounts: list[str], external: list[dict], off_topic: bool) -> str:
    label = f"{event_type} (auch: {secondary})" if secondary else event_type
    parts = [f"{label}: {profile['n_posts']} Beiträge aus {profile['n_sources']} Quellen"]
    if terms:
        parts.append("auffällige Begriffe: " + ", ".join(terms[:5]))
    if amounts:
        parts.append("genannte Beträge: " + ", ".join(amounts))
    if headlines:
        parts.append(f"häufigste Schlagzeile: „{headlines[0][:110]}“")
    if external:
        parts.append(f"möglicher externer Beleg: „{external[0]['title'][:110]}“ ({external[0]['source']})")
    if profile["likely_syndication"]:
        parts.append("Achtung: viele Posts wirken wie Nachdrucke derselben Meldung")
    if off_topic:
        parts.append("PRÜFEN: Beiträge nennen das Projekt kaum im Titel/Textanfang (evtl. thematisch fremd)")
    return "; ".join(parts) + "."


def llm_summarize(cfg: dict, docs: list[dict], terms: list[str], amounts: list[str], external: list[dict]) -> dict | None:
    """Optional. Gibt {summary, event_type, confidence} zurück oder None (dann greift die Vorlage)."""
    try:
        import anthropic
        client = anthropic.Anthropic()
        snippets = [f"- {d['title'][:140]} | {d['content'][:200]}" for d in docs[:10]]
        ext = [f"- {e['title']} ({e['source']})" for e in external]
        prompt = (
            f"Projekt: {cfg['display_name']} (Stand: {cfg['stage']}).\n"
            "Unten stehen Beiträge aus einem Zeitfenster mit auffällig vielen Veröffentlichungen. "
            "Erkläre in 1-2 Sätzen auf Deutsch, was vermutlich der Anlass war. Nutze AUSSCHLIESSLICH die "
            "gelieferten Texte und erfinde nichts. Wenn kein Anlass erkennbar ist, schreibe genau: "
            "'Kein klarer Auslöser erkennbar'.\n"
            f"Auffällige Begriffe: {', '.join(terms)}\nBeträge: {', '.join(amounts) or 'keine'}\n"
            "Beiträge:\n" + "\n".join(snippets) + "\nExterne Treffer:\n" + ("\n".join(ext) or "keine") + "\n\n"
            "Antworte NUR mit JSON: {\"summary\": str, \"event_type\": str, \"confidence\": \"hoch\"|\"mittel\"|\"niedrig\"}"
        )
        msg = client.messages.create(model=LLM_MODEL, max_tokens=400, messages=[{"role": "user", "content": prompt}])
        text = re.sub(r"```(?:json)?", "", msg.content[0].text).strip()
        data = json.loads(text)
        if isinstance(data.get("summary"), str) and data.get("confidence") in {"hoch", "mittel", "niedrig"}:
            return data
    except Exception as e:
        print(f"        (LLM nicht verfügbar, nutze Vorlage: {e})")
    return None


# ==========================================
# 7. KONTEXT PRO PEAK / CHANGE-POINT
# ==========================================
def build_context(proj_key: str, cfg: dict, project_docs: list[dict], start_str: str, end_str: str,
                  ref_date_str: str, ref_count: int | None, curated: list[dict], do_external: bool) -> dict:
    start = datetime.strptime(start_str, "%Y-%m-%d").date()
    end = datetime.strptime(end_str, "%Y-%m-%d").date()
    ref_date = datetime.strptime(ref_date_str, "%Y-%m-%d").date()
    extra_stop = {w.lower() for w in cfg.get("extra_stopwords", [])}

    window_docs = [d for d in project_docs if start <= d["date"] <= end]
    base_start = start - timedelta(days=BASELINE_DAYS)
    baseline_docs = [d for d in project_docs if base_start <= d["date"] < start]
    if len(baseline_docs) < 10:  # zu wenig Vorlauf -> alle Beiträge außerhalb des Fensters
        baseline_docs = [d for d in project_docs if not (start <= d["date"] <= end)]

    global_df, n_all = get_global_df(proj_key, project_docs, extra_stop)
    terms = distinctive_terms(window_docs, baseline_docs, global_df, n_all, extra_stop)
    headlines = top_headlines(window_docs)
    amounts = extract_amounts(window_docs)
    event_type, secondary, type_scores = classify_event_type(window_docs, rules_for_project(cfg))
    profile = source_profile(window_docs)
    topic_share = topic_relevance(window_docs, cfg.get("topic_regex") or cfg["must_match_regex"])
    off_topic = bool(window_docs) and topic_share < OFF_TOPIC_SHARE

    external = []
    if do_external and window_docs:
        external = targeted_external_context(cfg, start_str, end_str, terms, headlines)
        time.sleep(REQUEST_DELAY)

    # Konfidenz über Punkte: klarer Typ, starker externer Beleg, genug verschiedene Quellen; Nachdruck zieht ab.
    points = 0
    if event_type != GENERIC_EVENT_TYPE:
        points += 1
    if external and external[0].get("match_score", 0) >= 3:
        points += 1
    if profile["n_sources"] >= 4 and profile["n_posts"] >= 4:
        points += 1
    if profile["likely_syndication"]:
        points -= 1
    confidence = "mittel" if points >= 2 else "niedrig"
    if off_topic:
        confidence = "niedrig"
    if curated:
        confidence = "hoch"

    summary = template_summary(event_type, secondary, terms, headlines, profile, amounts, external, off_topic)
    method = "regelbasiert"
    if USE_LLM and window_docs and not curated:
        llm = llm_summarize(cfg, window_docs, terms, amounts, external)
        if llm:
            summary, method = llm["summary"], "llm"
            confidence = "niedrig" if off_topic else llm["confidence"]
            if llm.get("event_type"):
                event_type = llm["event_type"]
    if curated:
        c = curated[0]
        event_type = c.get("type") or event_type
        summary = f"Kuratiert: {c.get('title')}. " + summary
        method = "kuratiert+regelbasiert"

    ctx = {
        "event_type": event_type,
        "event_type_secondary": secondary,
        "summary": summary,
        "confidence": confidence,
        "confidence_points": points,
        "method": method,
        "top_terms": terms,
        "amounts_mentioned": amounts,
        "top_headlines": headlines,
        "source_profile": profile,
        "topic_share": round(topic_share, 2),
        "off_topic_suspect": off_topic,
        "event_type_scores": type_scores,
        "curated_events": curated,
        "external_candidates": external,
        "evidence_mention_ids": [d["mention_id"] for d in window_docs[:10] if d["mention_id"]],
    }
    if ref_count is not None and project_docs:
        ctx["effects"] = effect_analysis(project_docs, ref_date, ref_count)
    return ctx


# ==========================================
# 8. HAUPTPROGRAMM
# ==========================================
def main():
    for needed in (EVENTS_INPUT_FILE, CLEAN_DATA_FILE):
        if not needed.exists():
            print(f"FEHLER: '{needed.name}' nicht gefunden. Bitte zuerst die Skripte 1 und 2 ausführen!")
            return

    with open(EVENTS_INPUT_FILE, "r", encoding="utf-8") as f:
        events_data = json.load(f)
    docs_by_project = load_docs(CLEAN_DATA_FILE)
    curated_events = load_curated_events()
    print(f"Kuratierte Ereignisse geladen: {len(curated_events)} | LLM-Zusammenfassung: {'an' if USE_LLM else 'aus'}")

    enriched_projects = []
    print("=" * 75)
    print("PEAK-KONTEXT: SCHLAGWÖRTER, EREIGNISTYP, GEZIELTE SUCHE, NACHWIRKUNG")
    print("=" * 75)

    for proj_block in events_data:
        proj_key = proj_block["project"]
        cfg = PROJECT_CONFIG.get(proj_key)
        if not cfg:
            enriched_projects.append(proj_block)
            continue
        project_docs = docs_by_project.get(proj_key, [])

        print(f"\n>>> PROJEKT: {cfg['display_name']}  ({len(project_docs)} Beiträge)")
        print("-" * 75)

        official_scans = []
        for url in cfg["official_urls"]:
            print(f"  Scanne offizielle Webseite ({url})...")
            official_scans.append(crawl_official_page_context(url, cfg["page_keywords"]))
            time.sleep(REQUEST_DELAY)

        latest_news = fetch_google_news_rss(
            cfg["rss_query"], cfg["must_match_regex"], cfg["lang"], cfg["country"], max_items=4)

        peaks = proj_block.get("peaks", [])
        print(f"  {len(peaks)} Peaks, davon {sum(1 for p in peaks if p.get('post_count', 0) >= MIN_POSTS_FOR_CRAWL)} "
              f"mit externer Suche (>= {MIN_POSTS_FOR_CRAWL} Posts)")

        for peak in peaks:
            win = peak["crawler_window"]
            curated = curated_near(curated_events, proj_key, peak["date"], days=3)
            peak["crawled"] = peak.get("post_count", 0) >= MIN_POSTS_FOR_CRAWL
            peak["context"] = build_context(
                proj_key, cfg, project_docs, win["start"], win["end"],
                peak["date"], peak.get("post_count", 0), curated, do_external=peak["crawled"])

            ctx = peak["context"]
            flag = "  ⚠ evtl. themenfremd" if ctx["off_topic_suspect"] else ""
            print(f"    * {peak['date']} ({peak['post_count']} Posts) [{ctx['event_type']} | Konfidenz: {ctx['confidence']}]{flag}")
            print(f"      Begriffe: {', '.join(ctx['top_terms'][:5]) or '-'}")
            eff = ctx.get("effects")
            if eff:
                print(f"      Nachwirkung: {eff['persistence']}, Abklingzeit: {eff['decay_days']} Tage")
            for ext in ctx["external_candidates"][:1]:
                print(f"      Beleg: {ext['title'][:90]} ({ext['source']})")

        for cp in proj_block.get("change_points", []):
            cp_dt = datetime.strptime(cp["date"], "%Y-%m-%d")
            cp_start = (cp_dt - timedelta(days=3)).strftime("%Y-%m-%d")
            cp_end = (cp_dt + timedelta(days=3)).strftime("%Y-%m-%d")
            cp["context"] = build_context(
                proj_key, cfg, project_docs, cp_start, cp_end, cp["date"], None,
                curated_near(curated_events, proj_key, cp["date"], days=7), do_external=True)

        proj_block["project_context"] = {
            "display_name": cfg["display_name"],
            "city": cfg["city"],
            "stage": cfg["stage"],
            "official_site_scans": official_scans,
            "latest_news": [n for n in latest_news if "error" not in n],
            "curated_events": sorted(
                [e for e in curated_events if e.get("project") == proj_key],
                key=lambda e: str(e.get("date")))
        }
        enriched_projects.append(proj_block)

    final_payload = {
        "collection_metadata": {
            "collected_at_utc": datetime.now(timezone.utc).isoformat(),
            "methods": [
                "Peak context from the project's own posts: distinctive terms vs. baseline (document-level log-odds), "
                "rule-based event typing, amount extraction, source/syndication profile",
                "Targeted Google News RSS search built from the peak's distinctive terms; hits ranked by overlap with the peak's posts",
                "Persistence analysis: decay time to baseline, post volume 7-21 days after, sentiment 14 days before/after",
                "Public HTML metadata & headline extraction from official city/project homepages",
                "Optional: manually curated event list (curated_events.json); optional LLM summary (USE_LLM)"
            ],
            "interpretation_note": "context.summary describes the likely occasion based on the posts and external headlines; "
                                   "confidence 'hoch' only applies to manually curated events.",
            "compliance_note": "Only publicly accessible pages without login or paywall were queried; no personal user identifiers collected."
        },
        "projects": enriched_projects
    }
    with open(OUTPUT_ENRICHED_FILE, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, ensure_ascii=False, indent=2, default=str)

    print("\n" + "=" * 75)
    print(f"FERTIG! Gespeichert in: {OUTPUT_ENRICHED_FILE.name}")


if __name__ == "__main__":
    main()