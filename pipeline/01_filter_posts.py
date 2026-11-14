from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

# ==========================================
# 1. PFADE
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
DATEN_NAME = "FSI_Heilbronn_Medienbeiträge (1).json"
OUTPUT_CLEAN_FILE = BASE_DIR / "clean_data.json"
OUTPUT_AUDIT_FILE = BASE_DIR / "filter_audit.json"


def suche_datei(dateiname: str) -> Path | None:
    """Sucht die Datei im Arbeitsordner, im Skriptordner und in darüberliegenden Ordnern."""
    startpunkte = [Path.cwd().resolve(), BASE_DIR]
    gesehen = set()
    for start in startpunkte:
        aktuell = start
        for _ in range(6):
            if aktuell in gesehen:
                break
            gesehen.add(aktuell)
            kandidat = aktuell / dateiname
            if kandidat.is_file():
                return kandidat
            if aktuell.parent == aktuell:
                break
            aktuell = aktuell.parent
    return None


INPUT_FILE = suche_datei(DATEN_NAME) or (BASE_DIR / DATEN_NAME)

ALLOWED_LANGUAGES = {"de", "fr", "en"}
MIN_CONTENT_LENGTH = 40

# Topic- und Kontext-Begriff müssen höchstens so viele Zeichen auseinanderliegen,
# damit ein Beitrag als "über das Projekt" zählt (verhindert Zufallstreffer).
PROXIMITY_WINDOW = 300

# "Nur am Rande erwähnt"-Filter: Ab dieser Textlänge muss das Projektthema im Titel, im Anfang des
# Textes (LEAD_CHARS) oder mindestens zweimal vorkommen. Gilt für alle Projekte gleich.
PASSING_MENTION_MIN_LENGTH = 1200
LEAD_CHARS = 400

# Bei Mehrfachtreffern haben Seilbahn-Projekte Vorrang vor dem IPAI-Campus.
SEILBAHN_PROJECTS = {"Heilbronn_Seilbahn", "Bonn_Seilbahn", "Paris_Cable_C1"}

# ==========================================
# 2. BEREINIGTE PROJEKT- & FILTERREGELN
# ==========================================
PROJECT_RULES = {
    "Heilbronn_Seilbahn": {
        "topic_terms": [r"\bseilbahn\w*", r"\burban cable car\b", r"\bgondelbahn\w*"],
        "context_terms": [
            r"\bheilbronn\w*", r"\bipai\b", r"\bneckarbogen\b",
            r"\bwohlgelegen\b", r"\bböckingen\b", r"\bboeckingen\b", r"\bneckargartach\b"
        ]
    },
    "Bonn_Seilbahn": {
        "topic_terms": [r"\bseilbahn\w*", r"\bgondelbahn\w*"],
        "context_terms": [
            r"\bbonn\w*", r"\bvenusberg\b", r"\bbeuel\b", r"\brheinaue\b",
            r"\bun-campus\b", r"\buniklinikum bonn\b", r"\brheinquerung\b"
        ]
    },
    "Paris_Cable_C1": {
        "topic_terms": [r"t[ée]l[ée]ph[ée]rique\w*", r"c[âa]ble\s*c1\b", r"\bcable\s*c1\b", r"t[ée]l[ée]cabine\w*"],
        "context_terms": [
            r"\bcr[ée]teil\b", r"\bval-de-marne\b", r"\bvilleneuve-saint-georges\b",
            r"\blimeil-br[ée]vannes\b", r"\bvalenton\b", r"\b[îi]le-de-france\b", r"\bidfm\b",
            r"\bc1\b",  # FIX: "Câble C1" allein reicht jetzt als Kontext
            r"t[ée]l[ée]ph[ée]rique\s+(?:de\s+paris|francilien)"
        ]
    },
    "IPAI_Campus": {
        "topic_terms": [r"\bipai\b", r"\binnovation park artificial intelligence\b"],
        "context_terms": [
            r"\bheilbronn\w*", r"\bcampus\b", r"\bki-park\b", r"\bki-innovationspark\b",
            r"\bstein[äa]cker\b", r"\bschwarz-gruppe\b", r"\bdieter schwarz\b",
            r"\bkünstliche intelligenz\b", r"\bstart-?up\w*"
        ]
    }
}

# Tourismus-, Spielplatz-, Reiseblog- & Kultur-Beifang (DE & FR)
# FIX: "chine", "japon", "corée" entfernt – zu riskant für legitime Artikel.
NOISE_PATTERNS = [
    r"\bwanderung\b", r"\bwandern\b", r"\bskifahren\b", r"\bskipiste\b", r"\bskigebiet\b",
    r"\bgipfelkreuz\b", r"\bberner oberland\b", r"\bjungfraujoch\b", r"\bjennerbahn\b",
    r"\bzugspitze\b", r"\bsommerrodelbahn\b", r"\breiseblog\b", r"\breisebericht\b",
    r"\bferienwohnung\b", r"\bplaymobil\b", r"\blego\b", r"\bmodelleisenbahn\b",
    r"\bwaldspielplatz\b", r"\bflying fox\b", r"\bhochseil\w*", r"\broblox\b",
    r"\broad\s*trip\b", r"\bqu[ée]bec\b",
    r"\bsavoie\b", r"\bla plagne\b", r"\bsaint-valentin\b", r"\bpiano [àa] quatre mains\b",
    r"\brandonn[ée]e\w*", r"\bmontjuic\b"
]

INCIDENT_NOISE_PATTERNS = [
    r"\bflächenbrand\b", r"\bgartenhausbrand\b", r"\bpolizeibericht\b",
    r"\bverkehrsunfall\b", r"\blöscharbeiten\b", r"\bkleineinsätze\b",
    r"\bhauptversammlung der feuerwehr\b", r"\bflugzeugabsturz\b"
]

URBAN_TRANSIT_ANCHORS = [
    r"\böpnv\b", r"\boepnv\b", r"\bnahverkehr\b", r"\bpendler\w*", r"\bstadtverkehr\b",
    r"\bverkehrsmittel\b", r"\btransport en commun\b", r"\bmobilit[ée] urbaine\b",
    r"\bgemeinderat\b", r"\bmachbarkeitsstudie\b", r"\bplanfeststellung\b", r"\bnavigo\b"
]


# ==========================================
# 3. HILFSFUNKTIONEN
# ==========================================
def normalize_text(text) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def is_valid_timestamp(ts) -> bool:
    if not ts:
        return False
    try:
        clean_ts = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(ts).strip().replace("Z", "+00:00"))
        datetime.fromisoformat(clean_ts)
        return True
    except ValueError:
        return False


def normalize_url(url) -> str:
    url = str(url or "").strip().lower()
    if not url:
        return ""
    return url.split("#", 1)[0].rstrip("/")


def text_hash(text: str) -> str:
    """Kurzer Hash statt Volltext im Dedup-Set (spart Speicher)."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def match_in_proximity(text: str, topic_patterns: list[str], context_patterns: list[str],
                       window: int = PROXIMITY_WINDOW) -> tuple[int, int]:
    """Zählt Topic- und Kontext-Treffer, die jeweils einen Partner innerhalb von `window` Zeichen haben."""
    topic_spans = [m.span() for p in topic_patterns for m in re.finditer(p, text)]
    context_spans = [m.span() for p in context_patterns for m in re.finditer(p, text)]
    if not topic_spans or not context_spans:
        return 0, 0

    def near(span, others) -> bool:
        return any(o[0] - window <= span[1] and span[0] <= o[1] + window for o in others)

    topic_hits = sum(1 for s in topic_spans if near(s, context_spans))
    context_hits = sum(1 for s in context_spans if near(s, topic_spans))
    return topic_hits, context_hits


def ein_projekt(text, rules=None) -> tuple[list[str], list[str]]:
    """
    Gibt (Hauptprojekt, weitere_Projekte) zurück.
    - Topic und Kontext müssen räumlich nah beieinander stehen.
    - Seilbahn-Projekte haben Vorrang vor dem IPAI-Campus.
    - Innerhalb der Gruppe gewinnt die höhere Trefferzahl, bei Gleichstand die frühere Regel.
    """
    rules = PROJECT_RULES if rules is None else rules
    text_lower = str(text or "").lower()
    scored = []
    for index, (name, rule) in enumerate(rules.items()):
        topic_hits, context_hits = match_in_proximity(text_lower, rule["topic_terms"], rule["context_terms"])
        if topic_hits and context_hits:
            scored.append((topic_hits + context_hits, -index, name))
    if not scored:
        return [], []

    seilbahn = [s for s in scored if s[2] in SEILBAHN_PROJECTS]
    pool = sorted(seilbahn or scored, reverse=True)
    primary = pool[0][2]
    others = [s[2] for s in sorted(scored, reverse=True) if s[2] != primary]
    return [primary], others


def extract_records(raw_json) -> list[dict]:
    if isinstance(raw_json, list):
        return raw_json
    if isinstance(raw_json, dict):
        for key in ("data", "mentions", "items", "records", "articles"):
            if isinstance(raw_json.get(key), list):
                return raw_json[key]
    raise ValueError("Unbekannte JSON-Struktur.")


def evaluate_post(post: dict, seen_ids: set, seen_hashes: set) -> tuple[bool, list[str], str, list[str]]:
    """Rückgabe: (behalten?, Hauptprojekt als Liste, Grund, weitere erkannte Projekte)."""
    mention_id = str(post.get("mention_id") or "").strip()
    if mention_id and mention_id in seen_ids:
        return False, [], "duplicate_mention_id", []

    if not is_valid_timestamp(post.get("published_at")):
        return False, [], "invalid_or_missing_date", []

    raw_lang = str(post.get("language_code") or "").lower().strip()
    base_lang = raw_lang.split("-")[0] if raw_lang else ""
    if base_lang and base_lang not in ALLOWED_LANGUAGES:
        return False, [], f"unsupported_language ({raw_lang})", []

    title = normalize_text(post.get("title"))
    content = normalize_text(post.get("content"))
    full_text = f"{title} {content}".strip()

    if len(full_text) < MIN_CONTENT_LENGTH:
        return False, [], "text_too_short", []

    content_fingerprint = f"{title.lower()[:80]}|{content.lower()[:150]}"
    if content_fingerprint in seen_hashes:
        return False, [], "duplicate_content", []

    text_lower = full_text.lower()
    title_lower = title.lower()

    url_key = normalize_url(post.get("url"))
    if url_key and f"url:{url_key}" in seen_hashes:
        return False, [], "duplicate_url", []
    full_text_key = f"text:{text_hash(text_lower)}"
    if full_text_key in seen_hashes:
        return False, [], "duplicate_text", []

    matched_projects, also_mentions = ein_projekt(text_lower)

    if not matched_projects:
        return False, [], "no_target_project_match", []

    has_noise = any(re.search(p, text_lower) for p in NOISE_PATTERNS)
    has_transit_anchor = any(re.search(p, text_lower) for p in URBAN_TRANSIT_ANCHORS)

    if has_noise and not has_transit_anchor:
        return False, [], "tourism_or_leisure_noise", []

    if any(re.search(p, text_lower) for p in INCIDENT_NOISE_PATTERNS) and not has_transit_anchor:
        return False, [], "emergency_or_incident_report", []

    if len(full_text) > PASSING_MENTION_MIN_LENGTH:
        all_topic_patterns = [
            p for proj in matched_projects for p in PROJECT_RULES[proj]["topic_terms"]
        ]
        lead = text_lower[: len(title_lower) + LEAD_CHARS]
        in_lead = any(re.search(p, lead) for p in all_topic_patterns)
        mention_count = sum(len(re.findall(p, text_lower)) for p in all_topic_patterns)

        if not in_lead and mention_count < 2:
            return False, [], "passing_mention_in_long_article", []

    if mention_id:
        seen_ids.add(mention_id)
    seen_hashes.add(content_fingerprint)
    if url_key:
        seen_hashes.add(f"url:{url_key}")
    seen_hashes.add(full_text_key)

    return True, matched_projects, "kept", also_mentions


# ==========================================
# 4. HAUPTPROGRAMM
# ==========================================
def main():
    if not INPUT_FILE.exists():
        print(f"FEHLER: Datei nicht gefunden unter:\n{INPUT_FILE}")
        return

    print(f"Lade Rohdaten aus '{INPUT_FILE.name}'...")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_posts = extract_records(json.load(f))

    seen_ids = set()
    seen_hashes = set()
    clean_posts = []
    rejected_samples = []
    sample_counts = Counter()
    stats = Counter()
    project_counts = Counter()

    for post in raw_posts:
        is_valid, projects, reason, also_mentions = evaluate_post(post, seen_ids, seen_hashes)
        stats[reason] += 1

        if is_valid:
            post["matched_projects"] = projects
            post["also_mentions"] = also_mentions
            clean_posts.append(post)
            for p in projects:
                project_counts[p] += 1
        else:
            if sample_counts[reason] < 15:
                sample_counts[reason] += 1
                rejected_samples.append({
                    "mention_id": post.get("mention_id"),
                    "drop_reason": reason,
                    "source_name": post.get("source_name"),
                    "title": post.get("title"),
                    "snippet": normalize_text(post.get("content"))[:180]
                })

    with open(OUTPUT_CLEAN_FILE, "w", encoding="utf-8") as f:
        json.dump(clean_posts, f, ensure_ascii=False, indent=2)

    # FIX: Verwerfungsstatistik wird jetzt mitgespeichert
    with open(OUTPUT_AUDIT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "reason_counts": dict(stats.most_common()),
            "samples": rejected_samples
        }, f, ensure_ascii=False, indent=2)

    total = len(raw_posts)
    kept = len(clean_posts)
    dropped = total - kept

    print("\n" + "=" * 65)
    print("BEREINIGTES FILTER-ERGEBNIS")
    print("=" * 65)
    print(f"Gesamt eingelesen:   {total:>6} Beiträge")
    print(f"Behalten (Clean):    {kept:>6} Beiträge ({(kept / total * 100) if total else 0:.1f}%)")
    print(f"Ausgesiebt (Noise):  {dropped:>6} Beiträge ({(dropped / total * 100) if total else 0:.1f}%)")

    print("\n--- Entscheidungsgründe ---")
    for reason, count in stats.most_common():
        print(f"  - {reason:<36}: {count:>6}")

    print("\n--- Treffer pro Projekt ---")
    for proj, count in project_counts.most_common():
        print(f"  - {proj:<32}: {count:>6}")

    print("\n" + "=" * 65)
    print(f"Gespeichert: {OUTPUT_CLEAN_FILE.name}, {OUTPUT_AUDIT_FILE.name}")


if __name__ == "__main__":
    main()