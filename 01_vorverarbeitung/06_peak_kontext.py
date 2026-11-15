"""06. Peak-Kontext — Peaks und Trendbrüche bekommen ein Ereignis.

Liest ``00_data/posts.json``, ``peaks.json``, optional ``curated_events.json``.
Schreibt ``00_data/context.json`` für die Peak-Marker der Laufzeit.

Begriffe, Ereignistyp, externe Suche und Nachwirkung stehen in den Nachbardateien.
"""
import html
import importlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_config = importlib.import_module("02_laufzeit.config")
_fenster = importlib.import_module("02_laufzeit.fenster")
_sent = importlib.import_module("01_vorverarbeitung.02_sentiment_analyse")
CONTEXT_FILE = _config.CONTEXT_FILE
PEAKS_FILE = _config.PEAKS_FILE
POSTS_FILE = _config.POSTS_FILE
describe = _fenster.describe
as_score = _fenster.as_score
story_key = _sent.story_key

# ==========================================
# 1. PFADE, PARAMETER & PROJEKT-KONFIGURATION
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
CLEAN_DATA_FILE = POSTS_FILE
EVENTS_INPUT_FILE = PEAKS_FILE
OUTPUT_ENRICHED_FILE = CONTEXT_FILE

# Optional: manuell recherchierte Ereignisse (haben Vorrang vor allem Automatischen).
# Format: [{"project": "Heilbronn_Seilbahn", "date": "2025-03-12",
#           "title": "...", "type": "Gemeinderatsbeschluss", "source_url": "https://..."}]
CURATED_EVENTS_FILE = BASE_DIR / "curated_events.json"

# Externe Suche nur für statistische Ausreißer (relativ zur lokalen Baseline, keine feste Postzahl).
OUTLIER_RELATIVE = 2.0
OUTLIER_SIGNIFICANCE = 2.0
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

# Neues Projekt: Steckbrief unter briefs/<id>.json. Muster in 00_data/definitions.json.
# Sobald das Modell gelaufen ist, assigned/<id>.json; sonst gelten
# data/definitions.json über 01_filter_posts.py.
# Hier zusätzlich einen Eintrag anlegen. Die Analyse selbst ist projekt-unabhängig.
# Optionale Schlüssel pro Projekt:
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
        "stage": "Planning / feasibility",
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
        "stage": "Planning",
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
        "stage": "Construction / operation (reference project)",
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
        "stage": "Construction / development (comparison project)",
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
    "Political decision": {
        "strong": [r"gemeinderat", r"stadtrat", r"kreistag", r"landtag", r"beschlie[sß]", r"beschluss",
                   r"beschlossen", r"abstimmung", r"bürgerentscheid", r"conseil municipal", r"d[ée]lib[ée]r"],
        "weak": [r"mehrheit", r"ausschuss", r"\bvote\b", r"koalition", r"antrag"],
    },
    "Cost / funding": {
        "strong": [r"kosten", r"kostet", r"teurer", r"kostenschätzung", r"finanzierung", r"förderzusage",
                   r"fördermittel", r"co[uû]t", r"subvention", r"\d+(?:[.,]\d+)?\s*(?:mio|millionen|million)"],
        "weak": [r"förder", r"budget", r"haushalt", r"\beuro\b", r"€"],
    },
    "Planning / route / feasibility": {
        "strong": [r"trasse", r"machbarkeit", r"gutachten", r"planfeststellung", r"variante", r"trac[ée]",
                   r"standort", r"faisabilit[ée]"],
        "weak": [r"planung", r"\broute\b", r"station", r"[ée]tude"],
    },
    "Visualisation / design": {
        "strong": [r"visualisierung", r"animation", r"rendering", r"entwurf", r"simulation"],
        "weak": [r"\bvideo\b", r"modell"],
    },
    "Protest / public participation": {
        "strong": [r"bürgerinitiative", r"protest", r"widerstand", r"petition", r"p[ée]tition", r"unterschriften",
                   r"anwohner", r"bürgerbeteiligung", r"manifestation", r"riverains"],
        "weak": [r"kritik", r"kritisiert", r"sorgen", r"contestation"],
    },
    "Construction / milestone": {
        "strong": [r"spatenstich", r"baustart", r"richtfest", r"grundstein", r"bauarbeiten", r"baustelle",
                   r"chantier", r"travaux"],
        "weak": [r"fertigstellung"],
    },
    "Opening / start of service": {
        "strong": [r"inauguration", r"eröffnung", r"eröffnet", r"inbetriebnahme", r"mise en service",
                   r"betriebsstart", r"erste fahrgäste", r"premiers? passagers"],
        "weak": [r"ouverture", r"ouvre", r"\bopens\b"],
    },
    "Service disruption / closure": {
        "strong": [r"störung", r"gesperrt", r"sperrung", r"stillstand", r"außer betrieb", r"ausfall",
                   r"temp[êe]te", r"interrompu", r"interruption", r"\bpanne\b", r"fermeture", r"ferm[ée]\b",
                   r"[ée]vacuation"],
        "weak": [r"arr[êe]t", r"\bvents?\b", r"\bsturm\b", r"wartung", r"maintenance"],
    },
    "Safety / incident": {
        "strong": [r"agression", r"übergriff", r"s[ée]curit[ée]", r"sicherheit", r"accident", r"unfall",
                   r"harc[èe]lement", r"belästigung", r"vandal"],
        "weak": [r"gefahr", r"danger", r"polizei"],
    },
    "Partnership / membership": {
        "strong": [r"mitgliedschaft", r"\bmitglied\b", r"schließt sich", r"vertragsunterzeichnung",
                   r"kooperation", r"partnerschaft", r"partenariat", r"rejoint", r"beitritt"],
        "weak": [r"partner", r"konsortium"],
    },
    "Personnel": {
        "strong": [r"beruft", r"ernannt", r"berufung", r"chief technology officer", r"\bcto\b", r"\bceo\b",
                   r"nomm[ée]", r"nomination", r"neuer geschäftsführer", r"neue geschäftsführerin"],
        "weak": [r"geschäftsführer", r"vorstand"],
    },
    "Event / summit": {
        "strong": [r"gipfel", r"konferenz", r"kongress", r"tag der offenen", r"\bmesse\b", r"summit",
                   r"sprechtag", r"veranstaltung", r"besichtigung", r"für besucher"],
        "weak": [r"\bevent\b", r"besucher", r"workshop"],
    },
}
GENERIC_EVENT_TYPE = "Media coverage (no clear trigger)"
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
        title = re.sub(r"\s+", " ", str(p.get("title") or "")).strip()
        content = re.sub(r"\s+", " ", str(p.get("content") or "")).strip()
        tone = as_score(p.get("tone_score"))
        stored_key = p.get("story_key")
        if isinstance(stored_key, str) and stored_key.strip():
            key = stored_key
        else:
            key = story_key(title, p.get("mention_id"))
        doc = {
            "mention_id": p.get("mention_id"),
            "date": d,
            "title": title,
            "content": content,
            "source": p.get("source_name") or "unknown",
            "media_type": p.get("media_type_name") or "unknown",
            "story_key": key,
            "tone_score": tone,
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
        print(f"  WARNING: could not read '{CURATED_EVENTS_FILE.name}' ({e}).")
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


# ==========================================
# 6. ZUSAMMENFASSUNG (Vorlage oder optional LLM)
# ==========================================
def template_notes(profile: dict, off_topic: bool) -> str:
    """Only warnings — terms, amounts, and headlines live in structured peak fields."""
    parts = []
    if profile.get("likely_syndication"):
        parts.append("Note: many posts look like reprints of the same story")
    if off_topic:
        parts.append("Check: posts barely mention the project in the title or opening (possibly off-topic)")
    return " ".join(parts)


def llm_summarize(cfg: dict, docs: list[dict], terms: list[str], amounts: list[str], external: list[dict]) -> dict | None:
    """Optional. Gibt {summary, event_type, confidence} zurück oder None (dann greift die Vorlage)."""
    try:
        import anthropic
        client = anthropic.Anthropic()
        snippets = [f"- {d['title'][:140]} | {d['content'][:200]}" for d in docs[:10]]
        ext = [f"- {e['title']} ({e['source']})" for e in external]
        prompt = (
            f"Project: {cfg['display_name']} (stage: {cfg['stage']}).\n"
            "Below are posts from a window with an unusual number of publications. "
            "Explain in 1-2 sentences in English what the likely occasion was. Use ONLY the "
            "supplied texts and invent nothing. The posts themselves may be German or French; "
            "keep names and quotations as written, but write the summary in English. "
            "If no occasion is identifiable, write exactly: "
            "'No clear trigger identifiable'.\n"
            f"Distinctive terms: {', '.join(terms)}\nAmounts: {', '.join(amounts) or 'none'}\n"
            "Posts:\n" + "\n".join(snippets) + "\nExternal hits:\n" + ("\n".join(ext) or "none") + "\n\n"
            "Reply with JSON only: {\"summary\": str, \"event_type\": str, \"confidence\": \"high\"|\"medium\"|\"low\"}"
        )
        msg = client.messages.create(model=LLM_MODEL, max_tokens=400, messages=[{"role": "user", "content": prompt}])
        text = re.sub(r"```(?:json)?", "", msg.content[0].text).strip()
        data = json.loads(text)
        if isinstance(data.get("summary"), str) and data.get("confidence") in {"high", "medium", "low"}:
            return data
    except Exception as e:
        print(f"        (LLM unavailable, using template: {e})")
    return None


def is_volume_outlier(peak: dict) -> bool:
    """True if the day is an outlier vs its own baseline. No global post floor."""
    baseline = float(peak.get("baseline_posts_per_day") or 0.0)
    count = float(peak.get("post_count") or 0.0)
    relative = float(peak.get("relative_to_baseline") or 0.0)
    significance = float(peak.get("significance") or 0.0)
    if relative >= OUTLIER_RELATIVE or significance >= OUTLIER_SIGNIFICANCE:
        return True
    return count > baseline + max(1.0, 2.0 * math.sqrt(max(baseline, 0.25)))


def score_confidence(event_type: str, type_scores: dict, profile: dict, external: list,
                     off_topic: bool, topic_share: float, terms: list, curated: list,
                     peak: dict | None = None) -> tuple[str, int]:
    """high / medium / low from independent evidence, not a fixed post count.

    ``high`` needs a named event type plus corroboration. A generic media spike
    cannot be high-confidence even if many outlets copy it.
    """
    points = 0
    typed = event_type != GENERIC_EVENT_TYPE
    best_score = max(type_scores.values()) if type_scores else 0
    if typed:
        points += 2 if best_score >= 8 else 1
    hits = [item for item in (external or []) if isinstance(item, dict) and item.get("title") and not item.get("error")]
    match = float(hits[0].get("match_score") or 0) if hits else 0.0
    if hits:
        points += 2 if match >= 3 else 1
    n_posts = int(profile.get("n_posts") or 0)
    n_sources = int(profile.get("n_sources") or 0)
    if n_posts:
        share = n_sources / n_posts
        if n_sources >= 3 and share >= 0.45:
            points += 2
        elif n_sources >= 2:
            points += 1
        if profile.get("likely_syndication"):
            points -= 1
    if off_topic:
        points -= 2
    elif topic_share >= 0.75:
        points += 1
    if curated:
        points += 3
    strong = bool(curated) or match >= 3 or best_score >= 8
    if off_topic or points < 2:
        return "low", points
    if typed and strong and points >= 5:
        return "high", points
    if points >= 3:
        return "medium", points
    return "low", points


# ==========================================
# 7. KONTEXT PRO PEAK / CHANGE-POINT
# ==========================================
def build_context(proj_key: str, cfg: dict, project_docs: list[dict], start_str: str, end_str: str,
                  ref_date_str: str, ref_count: int | None, curated: list[dict], do_external: bool,
                  peak: dict | None = None) -> dict:
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

    confidence, points = score_confidence(
        event_type, type_scores, profile, external, off_topic, topic_share, terms, curated, peak
    )

    summary = template_notes(profile, off_topic)
    method = "rule-based"
    if USE_LLM and window_docs and not curated:
        llm = llm_summarize(cfg, window_docs, terms, amounts, external)
        if llm:
            summary, method = llm["summary"], "llm"
            if off_topic:
                confidence = "low"
            elif llm.get("confidence") in {"high", "medium", "low"}:
                confidence = llm["confidence"]
            if llm.get("event_type"):
                event_type = llm["event_type"]
    if curated:
        c = curated[0]
        event_type = c.get("type") or event_type
        curated_line = f"Curated: {c.get('title')}." if c.get("title") else ""
        notes = template_notes(profile, off_topic)
        summary = " ".join(part for part in (curated_line, notes) if part).strip()
        method = "curated+rule-based"

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
def _bind_methods() -> None:
    global tokenize, doc_terms, get_global_df, distinctive_terms, extract_amounts
    global rules_for_project, classify_event_type
    global clean_html_text, http_get, fetch_google_news_rss, crawl_official_page_context, targeted_external_context
    global daily_counts, mean_sentiment, effect_analysis
    begriffe = importlib.import_module("01_vorverarbeitung.06_begriffe")
    typ = importlib.import_module("01_vorverarbeitung.06_ereignistyp")
    suche = importlib.import_module("01_vorverarbeitung.06_externe_suche")
    nach = importlib.import_module("01_vorverarbeitung.06_nachwirkung")
    tokenize = begriffe.tokenize
    doc_terms = begriffe.doc_terms
    get_global_df = begriffe.get_global_df
    distinctive_terms = begriffe.distinctive_terms
    extract_amounts = begriffe.extract_amounts
    rules_for_project = typ.rules_for_project
    classify_event_type = typ.classify_event_type
    clean_html_text = suche.clean_html_text
    http_get = suche.http_get
    fetch_google_news_rss = suche.fetch_google_news_rss
    crawl_official_page_context = suche.crawl_official_page_context
    targeted_external_context = suche.targeted_external_context
    daily_counts = nach.daily_counts
    mean_sentiment = nach.mean_sentiment
    effect_analysis = nach.effect_analysis

_bind_methods()

def main():
    for needed in (EVENTS_INPUT_FILE, CLEAN_DATA_FILE):
        if not needed.exists():
            print(f"ERROR: '{needed}' not found. Run 04_peak_erkennung.py and 05_trendbrueche.py first.")
            return

    with open(EVENTS_INPUT_FILE, "r", encoding="utf-8") as f:
        events_data = json.load(f)
    docs_by_project = load_docs(CLEAN_DATA_FILE)
    curated_events = load_curated_events()
    print(f"Curated events loaded: {len(curated_events)} | LLM summary: {'on' if USE_LLM else 'off'}")

    enriched_projects = []
    print("=" * 75)
    print("PEAK CONTEXT: TERMS, EVENT TYPE, TARGETED SEARCH, FOLLOW-UP")
    print("=" * 75)

    for proj_block in events_data:
        proj_key = proj_block["project"]
        cfg = PROJECT_CONFIG.get(proj_key)
        if not cfg:
            enriched_projects.append(proj_block)
            continue
        project_docs = docs_by_project.get(proj_key, [])

        print(f"\n>>> PROJECT: {cfg['display_name']}  ({len(project_docs)} posts)")
        print("-" * 75)

        official_scans = []
        for url in cfg["official_urls"]:
            print(f"  Scanning official site ({url})...")
            official_scans.append(crawl_official_page_context(url, cfg["page_keywords"]))
            time.sleep(REQUEST_DELAY)

        latest_news = fetch_google_news_rss(
            cfg["rss_query"], cfg["must_match_regex"], cfg["lang"], cfg["country"], max_items=4)

        peaks = proj_block.get("peaks", [])
        n_outliers = sum(1 for p in peaks if is_volume_outlier(p))
        print(f"  {len(peaks)} peaks, {n_outliers} above the local baseline (external search)")

        for peak in peaks:
            win = peak["crawler_window"]
            curated = curated_near(curated_events, proj_key, peak["date"], days=3)
            peak["crawled"] = is_volume_outlier(peak)
            peak["context"] = build_context(
                proj_key, cfg, project_docs, win["start"], win["end"],
                peak["date"], peak.get("post_count", 0), curated, do_external=peak["crawled"],
                peak=peak)

            ctx = peak["context"]
            flag = "  ⚠ possibly off-topic" if ctx["off_topic_suspect"] else ""
            print(f"    * {peak['date']} ({peak['post_count']} posts) [{ctx['event_type']} | confidence: {ctx['confidence']}]{flag}")
            print(f"      Terms: {', '.join(ctx['top_terms'][:5]) or '-'}")
            eff = ctx.get("effects")
            if eff:
                print(f"      Follow-up: {eff['persistence']}, decay: {eff['decay_days']} days")
            for ext in ctx["external_candidates"][:1]:
                print(f"      Source: {ext['title'][:90]} ({ext['source']})")

        for cp in proj_block.get("change_points", []):
            cp_dt = datetime.strptime(cp["date"], "%Y-%m-%d")
            cp_start = (cp_dt - timedelta(days=3)).strftime("%Y-%m-%d")
            cp_end = (cp_dt + timedelta(days=3)).strftime("%Y-%m-%d")
            cp["context"] = build_context(
                proj_key, cfg, project_docs, cp_start, cp_end, cp["date"], None,
                curated_near(curated_events, proj_key, cp["date"], days=7), do_external=True)

        if isinstance(proj_block.get("date_range"), str):
            proj_block["date_range"] = proj_block["date_range"].replace(" bis ", " to ")
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
                                   "confidence high/medium/low is scored from event type, independent sources, "
                                   "external corroboration and topic fit — not from a fixed post count.",
            "compliance_note": "Only publicly accessible pages without login or paywall were queried; no personal user identifiers collected."
        },
        "projects": enriched_projects
    }
    with open(OUTPUT_ENRICHED_FILE, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, ensure_ascii=False, indent=2, default=str)

    print("\n" + "=" * 75)
    print(f"Done. Saved to: {OUTPUT_ENRICHED_FILE}  →  02_laufzeit/auswertung.py")


if __name__ == "__main__":
    main()