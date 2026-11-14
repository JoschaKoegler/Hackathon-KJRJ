import json
import re
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

# ==========================================
# 1. PFADE
# ==========================================
BASE_DIR = Path(__file__).resolve().parent.parent
DATEN_ORDNER = BASE_DIR / "daten"
# Rohdaten liegen eine Ebene über dem Repo. Die Datei ist zu groß für Git.
ROH_ORDNER = BASE_DIR.parent
GEFILTERT_ORDNER = DATEN_ORDNER / "01_gefiltert"
DATEN_NAME = "FSI_Heilbronn_Medienbeiträge (1).json"
OUTPUT_CLEAN_FILE = GEFILTERT_ORDNER / "clean_data.json"
OUTPUT_AUDIT_FILE = GEFILTERT_ORDNER / "filter_audit.json"
INPUT_FILE = ROH_ORDNER / DATEN_NAME

ALLOWED_LANGUAGES = {"de", "fr", "en"}
# Dublette: Beitrag fällt, sobald die Übereinstimmung darüber liegt.
AEHNLICHKEIT_SCHWELLE = 0.95
DEFINITIONEN_DATEI = Path(__file__).resolve().parent / "projekt_definitionen.json"


def lade_projekt_definitionen(pfad: Path) -> dict:
    """Liest skripte/projekt_definitionen.json. Die Listenreihenfolge ist der Gleichstand."""
    with pfad.open(encoding="utf-8") as datei:
        roh = json.load(datei)
    regeln = {}
    for eintrag in roh["projekte"]:
        regeln[eintrag["id"]] = {
            "topic_terms": list(eintrag["topic_terms"]),
            "context_terms": list(eintrag["context_terms"]),
        }
    if not regeln:
        raise ValueError(f"Keine Projekte in {pfad}")
    return regeln


# ==========================================
# 2. PROJEKT- & FILTERREGELN
# ==========================================
PROJECT_RULES = lade_projekt_definitionen(DEFINITIONEN_DATEI)

# Tourismus-, Freizeit- & Spielzeug-Beifang
TOURISM_NOISE_PATTERNS = [
    r"\bwanderung\b", r"\bwandern\b", r"\bskifahren\b", r"\bskipiste\b", r"\bskigebiet\b",
    r"\bgipfelkreuz\b", r"\bberner oberland\b", r"\bjungfraujoch\b", r"\bjennerbahn\b",
    r"\bzugspitze\b", r"\bsommerrodelbahn\b", r"\breiseblog\b", r"\burlaub\b",
    r"\bferienwohnung\b", r"\bplaymobil\b", r"\blego\b", r"\bmodelleisenbahn\b",
    r"\bfoto-wanderung\b", r"\b10 dinge, die ihr\b", r"\bstädte in asien\b"
]

# Reine Polizei-/Feuerwehr-Einsatzmeldungen (wo IPAI nur als Ortsangabe dient)
INCIDENT_NOISE_PATTERNS = [
    r"\bflächenbrand\b", r"\bgartenhausbrand\b", r"\bpolizeibericht\b",
    r"\bverkehrsunfall\b", r"\blöscharbeiten\b", r"\bkleineinsätze\b",
    r"\bhauptversammlung der feuerwehr\b"
]

# Rettungs-Anker für echte ÖPNV-/Stadtentwicklungs-Debatten
URBAN_TRANSIT_ANCHORS = [
    r"\böpnv\b", r"\boepnv\b", r"\bnahverkehr\b", r"\bpendler\w*", r"\bstadtverkehr\b",
    r"\bverkehrsmittel\b", r"\btransport en commun\b", r"\bmobilit[ée] urbaine\b",
    r"\bgemeinderat\b", r"\bmachbarkeitsstudie\b", r"\bplanfeststellung\b"
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


def ein_projekt(text, rules=None) -> list[str]:
    """Genau ein Projekt: das mit den meisten Muster-Treffern. Bei Gleichstand die frühere Regel."""
    rules = PROJECT_RULES if rules is None else rules
    text_lower = str(text or "").lower()
    scored = []
    for index, (name, rule) in enumerate(rules.items()):
        topic_hits = sum(len(re.findall(pattern, text_lower)) for pattern in rule["topic_terms"])
        context_hits = sum(len(re.findall(pattern, text_lower)) for pattern in rule["context_terms"])
        if topic_hits and context_hits:
            scored.append((topic_hits + context_hits, -index, name))
    if not scored:
        return []
    scored.sort(reverse=True)
    return [scored[0][2]]


def simhash64(text: str) -> int:
    """64-Bit-Fingerabdruck über die Wörter. Nur zur Kandidatensuche, nicht als Urteil."""
    counts = [0] * 64
    leer = True
    for token in text.split():
        leer = False
        value = 2166136261
        for zeichen in token:
            value ^= ord(zeichen)
            value = (value * 16777619) & 0xFFFFFFFF
        gedreht = ((value << 16) | (value >> 16)) & 0xFFFFFFFF
        for bit in range(32):
            counts[bit] += 1 if value & (1 << bit) else -1
            counts[bit + 32] += 1 if gedreht & (1 << bit) else -1
    if leer:
        return 0
    out = 0
    for bit, weight in enumerate(counts):
        if weight > 0:
            out |= 1 << bit
    return out


def laengen_koennen_95_erreichen(links: int, rechts: int) -> bool:
    """SequenceMatcher-Ratio über 0,95 ist bei stark unterschiedlicher Länge unmöglich."""
    if links <= 0 or rechts <= 0:
        return False
    kuerzer = min(links, rechts)
    laenger = max(links, rechts)
    return kuerzer / laenger > 0.90


def uebereinstimmung(links: str, rechts: str) -> float:
    """Anteil gemeinsamer Zeichenfolge, 0 bis 1. Über 0,95 ist eine Dublette."""
    if not links or not rechts:
        return 0.0
    vergleich = SequenceMatcher(None, links, rechts)
    if vergleich.quick_ratio() <= AEHNLICHKEIT_SCHWELLE:
        return vergleich.quick_ratio()
    return vergleich.ratio()


class GeseheneBeitraege:
    """Merkmenge nur für Beiträge, die am Ende behalten werden.

    Schritt 3 prüft dagegen drei Dinge: Inhaltsanfang, URL und 95-%-Ähnlichkeit.
    """

    def __init__(self):
        self.fingerprints: set[str] = set()
        self.urls: set[str] = set()
        self._texte: list[str] = []
        self._laengen: list[int] = []
        self._baender: list[dict[int, list[int]]] = [dict() for _ in range(4)]
        self._fenster: dict[str, list[int]] = {}

    def fingerprint_da(self, fingerprint: str) -> bool:
        return fingerprint in self.fingerprints

    def url_da(self, url_key: str) -> bool:
        return bool(url_key) and url_key in self.urls

    def _fensterschluessel(self, text: str) -> list[str]:
        laenge = len(text)
        if laenge <= 80:
            return [text] if text else []
        return [text[start:start + 80] for start in (0, laenge // 3, (2 * laenge) // 3)]

    def zu_aehnlich(self, text: str) -> bool:
        if not text or not self._texte:
            return False
        laenge = len(text)
        signatur = simhash64(text)
        kandidaten: set[int] = set()
        for band, tafel in enumerate(self._baender):
            kandidaten.update(tafel.get((signatur >> (band * 16)) & 0xFFFF, ()))
        for schluessel in self._fensterschluessel(text):
            kandidaten.update(self._fenster.get(schluessel, ()))
        for index in kandidaten:
            if not laengen_koennen_95_erreichen(laenge, self._laengen[index]):
                continue
            if uebereinstimmung(text, self._texte[index]) > AEHNLICHKEIT_SCHWELLE:
                return True
        return False

    def merken(self, fingerprint: str, url_key: str, text: str) -> None:
        self.fingerprints.add(fingerprint)
        if url_key:
            self.urls.add(url_key)
        if not text:
            return
        index = len(self._texte)
        self._texte.append(text)
        self._laengen.append(len(text))
        signatur = simhash64(text)
        for band, tafel in enumerate(self._baender):
            tafel.setdefault((signatur >> (band * 16)) & 0xFFFF, []).append(index)
        for schluessel in self._fensterschluessel(text):
            self._fenster.setdefault(schluessel, []).append(index)


def extract_records(raw_json) -> list[dict]:
    if isinstance(raw_json, list):
        return raw_json
    if isinstance(raw_json, dict):
        for key in ("data", "mentions", "items", "records", "articles"):
            if isinstance(raw_json.get(key), list):
                return raw_json[key]
    raise ValueError("Unbekannte JSON-Struktur: Erwartet wurde eine Liste von Beiträgen.")


def evaluate_post(post: dict, gesehen: GeseheneBeitraege) -> tuple[bool, list[str], str]:
    """Acht Schritte. Der erste Fehlgrund beendet die Prüfung.

    1 Datum
    2 Sprache de/fr/en
    3 Dublette: Inhaltsanfang, gleiche URL oder mehr als 95 % Übereinstimmung
    4 Genau ein Projekt, Definitionen in projekt_definitionen.json
    5 Tourismus ohne ÖPNV-Anker
    6 Einsatzmeldung ohne ÖPNV-Anker
    7 Beiläufig in langem Text
    8 Behalten
    """
    # 1. Datum
    if not is_valid_timestamp(post.get("published_at")):
        return False, [], "invalid_or_missing_date"

    # 2. Sprache. de-DE, fr-FR, en-GB zählen als de, fr, en. Leerer Code bleibt.
    raw_lang = str(post.get("language_code") or "").lower().strip()
    base_lang = raw_lang.split("-")[0] if raw_lang else ""
    if base_lang and base_lang not in ALLOWED_LANGUAGES:
        return False, [], f"unsupported_language ({raw_lang})"

    title = normalize_text(post.get("title"))
    content = normalize_text(post.get("content"))
    full_text = f"{title} {content}".strip()
    text_lower = full_text.lower()
    title_lower = title.lower()

    # 3. Dublette gegen schon behaltene Beiträge.
    #    Fingerprint: Titelanfang 80 Zeichen und Inhaltsanfang 150 Zeichen.
    content_fingerprint = f"{title.lower()[:80]}|{content.lower()[:150]}"
    if gesehen.fingerprint_da(content_fingerprint):
        return False, [], "duplicate_content"

    url_key = normalize_url(post.get("url"))
    if gesehen.url_da(url_key):
        return False, [], "duplicate_url"

    if gesehen.zu_aehnlich(text_lower):
        return False, [], "similar_over_95"

    # 4. Genau ein Projekt. Die Suchwörter stehen in projekt_definitionen.json.
    matched_projects = ein_projekt(text_lower)

    if not matched_projects:
        return False, [], "no_target_project_match"

    has_tourism_noise = any(re.search(p, text_lower) for p in TOURISM_NOISE_PATTERNS)
    has_transit_anchor = any(re.search(p, text_lower) for p in URBAN_TRANSIT_ANCHORS)

    if has_tourism_noise and not has_transit_anchor:
        return False, [], "tourism_or_leisure_noise"

    if any(re.search(p, text_lower) for p in INCIDENT_NOISE_PATTERNS) and not has_transit_anchor:
        return False, [], "emergency_or_incident_report"

    if len(full_text) > 2500:
        all_topic_patterns = [
            p for proj in matched_projects for p in PROJECT_RULES[proj]["topic_terms"]
        ]
        in_title = any(re.search(p, title_lower) for p in all_topic_patterns)
        mention_count = sum(len(re.findall(p, text_lower)) for p in all_topic_patterns)

        if not in_title and mention_count < 2:
            return False, [], "passing_mention_in_long_article"

    gesehen.merken(content_fingerprint, url_key, text_lower)
    return True, matched_projects, "kept"


# ==========================================
# 4. HAUPTPROGRAMM
# ==========================================
def main():
    if not INPUT_FILE.exists():
        print(f"FEHLER: Rohdaten nicht gefunden unter:\n{INPUT_FILE}")
        print(f"Erwartet im Ordner über dem Repo: {ROH_ORDNER}")
        return

    quelle = Path("..") / INPUT_FILE.relative_to(ROH_ORDNER)
    print(f"Lade Rohdaten aus '{quelle}'...")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_posts = extract_records(json.load(f))

    gesehen = GeseheneBeitraege()
    clean_posts = []
    rejected_samples = []
    stats = Counter()
    project_counts = Counter()

    for post in raw_posts:
        is_valid, projects, reason = evaluate_post(post, gesehen)
        stats[reason] += 1

        if is_valid:
            post["matched_projects"] = projects
            clean_posts.append(post)
            for p in projects:
                project_counts[p] += 1
        else:
            if sum(1 for r in rejected_samples if r["drop_reason"] == reason) < 15:
                rejected_samples.append({
                    "mention_id": post.get("mention_id"),
                    "drop_reason": reason,
                    "source_name": post.get("source_name"),
                    "title": post.get("title"),
                    "snippet": normalize_text(post.get("content"))[:180]
                })

    GEFILTERT_ORDNER.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CLEAN_FILE, "w", encoding="utf-8") as f:
        json.dump(clean_posts, f, ensure_ascii=False, indent=2)

    with open(OUTPUT_AUDIT_FILE, "w", encoding="utf-8") as f:
        json.dump(rejected_samples, f, ensure_ascii=False, indent=2)

    total = len(raw_posts)
    kept = len(clean_posts)
    dropped = total - kept

    print("\n" + "=" * 65)
    print("FILTER-ERGEBNIS (DATENBEREINIGUNG)")
    print("=" * 65)
    print(f"Gesamt eingelesen:   {total:>6} Beiträge")
    print(f"Behalten (Clean):    {kept:>6} Beiträge ({(kept / total * 100) if total else 0:.1f}%)")
    print(f"Ausgesiebt (Noise):  {dropped:>6} Beiträge ({(dropped / total * 100) if total else 0:.1f}%)")

    print("\n--- Aufschlüsselung nach Ausschlussgrund ---")
    for reason, count in stats.most_common():
        if reason != "kept":
            print(f"  - {reason:<32}: {count:>6}")

    print("\n--- Treffer pro Projekt (genau ein Projekt je Beitrag) ---")
    for proj, count in project_counts.most_common():
        print(f"  - {proj:<32}: {count:>6}")

    print("\n" + "=" * 65)
    print(f"Gespeichert:\n -> {OUTPUT_CLEAN_FILE.relative_to(BASE_DIR)}\n -> {OUTPUT_AUDIT_FILE.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()