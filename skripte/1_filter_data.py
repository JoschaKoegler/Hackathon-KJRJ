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
SKRIPT_ORDNER = Path(__file__).resolve().parent

# Duplicate: title >= 90% and the same 150 content characters, or the whole text >= 95%.
TITEL_SCHWELLE = 0.90
INHALT_ANFANG = 150
AEHNLICHKEIT_SCHWELLE = 0.95
PROJECT_FILE = SKRIPT_ORDNER / "project_definitions.json"
TOURISM_FILE = SKRIPT_ORDNER / "tourism_terms.json"
INCIDENT_FILE = SKRIPT_ORDNER / "incident_terms.json"
ANCHOR_FILE = SKRIPT_ORDNER / "transit_anchors.json"

# One folder per outcome. Duplicates share one folder; the reason stays on the post.
OUTPUT_FOLDERS = {
    "invalid_or_missing_date": DATEN_ORDNER / "rejected" / "invalid-date",
    "duplicate_title_and_start": DATEN_ORDNER / "rejected" / "duplicates",
    "similar_over_95": DATEN_ORDNER / "rejected" / "duplicates",
    "no_target_project_match": DATEN_ORDNER / "rejected" / "no-project-match",
    "tourism_or_leisure_noise": DATEN_ORDNER / "rejected" / "tourism-leisure",
    "emergency_or_incident_report": DATEN_ORDNER / "incident-reports",
}


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as datei:
        return json.load(datei)


def load_project_definitions(path: Path) -> dict:
    """Order in project_definitions.json is the tie-break."""
    raw = load_json(path)
    rules = {}
    for entry in raw["projects"]:
        rules[entry["id"]] = {
            "topic_terms": list(entry["topic_terms"]),
            "context_terms": list(entry["context_terms"]),
        }
    if not rules:
        raise ValueError(f"No projects in {path}")
    return rules


def load_terms(path: Path, key: str) -> list[str]:
    return list(load_json(path)[key])


# ==========================================
# 2. BEREINIGTE PROJEKT- & FILTERREGELN
# ==========================================
PROJECT_RULES = load_project_definitions(PROJECT_FILE)
NOISE_PATTERNS = load_terms(TOURISM_FILE, "terms")
INCIDENT_NOISE_PATTERNS = load_terms(INCIDENT_FILE, "terms")
URBAN_TRANSIT_ANCHORS = load_terms(ANCHOR_FILE, "anchors")


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
    """Merkmenge der behaltenen Beiträge für die Dublettenprüfung."""

    def __init__(self):
        self._titel: list[str] = []
        self._anfaenge: dict[str, list[int]] = {}
        self._texte: list[str] = []
        self._laengen: list[int] = []
        self._baender: list[dict[int, list[int]]] = [dict() for _ in range(4)]
        self._fenster: dict[str, list[int]] = {}

    def titel_und_anfang(self, titel: str, anfang: str) -> bool:
        """Gleicher Inhaltsanfang und Titel zu mindestens 90 Prozent."""
        for index in self._anfaenge.get(anfang, ()):
            if uebereinstimmung(titel, self._titel[index]) >= TITEL_SCHWELLE:
                return True
        return False

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
            if uebereinstimmung(text, self._texte[index]) >= AEHNLICHKEIT_SCHWELLE:
                return True
        return False

    def merken(self, titel: str, anfang: str, text: str) -> None:
        index = len(self._texte)
        self._titel.append(titel)
        self._anfaenge.setdefault(anfang, []).append(index)
        self._texte.append(text)
        self._laengen.append(len(text))
        if not text:
            return
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
    raise ValueError("Unbekannte JSON-Struktur.")


def evaluate_post(post: dict, gesehen: GeseheneBeitraege) -> tuple[bool, list[str], str]:
    """Kette bis zum Behalten. Der erste Fehlgrund beendet die Prüfung.

    1 Valides Datum, sonst aussortiert
    2 Dublette: Titel >= 90 % und gleiche 150 Inhaltszeichen, oder Gesamttext >= 95 %
    3 Projekt über projekt_definitionen.json, sonst aussortiert
    4 Tourismusbegriffe ohne ÖPNV-Anker, sonst aussortiert
    5 Einsatzmeldung ohne Anker: eigener Ordner, nicht der Hauptstrom
    Beiläufige Erwähnung bleibt im Hauptstrom.
    """
    if not is_valid_timestamp(post.get("published_at")):
        return False, [], "invalid_or_missing_date"

    title = normalize_text(post.get("title"))
    content = normalize_text(post.get("content"))
    text_lower = f"{title} {content}".strip().lower()
    titel = title.lower()
    anfang = content.lower()[:INHALT_ANFANG]

    if gesehen.titel_und_anfang(titel, anfang):
        return False, [], "duplicate_title_and_start"
    if gesehen.zu_aehnlich(text_lower):
        return False, [], "similar_over_95"

    matched_projects = ein_projekt(text_lower)
    if not matched_projects:
        return False, [], "no_target_project_match"

    has_noise = any(re.search(muster, text_lower) for muster in NOISE_PATTERNS)
    has_transit_anchor = any(re.search(muster, text_lower) for muster in URBAN_TRANSIT_ANCHORS)
    if has_noise and not has_transit_anchor:
        return False, [], "tourism_or_leisure_noise"

    if any(re.search(muster, text_lower) for muster in INCIDENT_NOISE_PATTERNS) and not has_transit_anchor:
        return False, matched_projects, "emergency_or_incident_report"

    gesehen.merken(titel, anfang, text_lower)
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
    buckets = {reason: [] for reason in OUTPUT_FOLDERS}
    stats = Counter()
    project_counts = Counter()

    for post in raw_posts:
        is_valid, projects, reason = evaluate_post(post, gesehen)
        stats[reason] += 1

        if reason in OUTPUT_FOLDERS:
            post["matched_projects"] = projects
            post["rejection_reason"] = reason
            buckets[reason].append(post)
        elif is_valid:
            post["matched_projects"] = projects
            clean_posts.append(post)
            for p in projects:
                project_counts[p] += 1

    GEFILTERT_ORDNER.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CLEAN_FILE, "w", encoding="utf-8") as f:
        json.dump(clean_posts, f, ensure_ascii=False, indent=2)

    written = {}
    for reason, folder in OUTPUT_FOLDERS.items():
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "posts.json"
        if target in written:
            written[target].extend(buckets[reason])
        else:
            written[target] = list(buckets[reason])
    for target, posts in written.items():
        with target.open("w", encoding="utf-8") as handle:
            json.dump(posts, handle, ensure_ascii=False)

    total = len(raw_posts)
    kept = len(clean_posts)

    print("\n" + "=" * 65)
    print("FILTER RESULT")
    print("=" * 65)
    print(f"Read:                {total:>6}")
    print(f"Kept:                {kept:>6} ({(kept / total * 100) if total else 0:.1f}%)")
    for reason, count in stats.most_common():
        if reason == "kept":
            continue
        folder = OUTPUT_FOLDERS[reason].relative_to(BASE_DIR)
        print(f"  {reason:<28} {count:>6}  {folder}")

    print("\nProjects in the kept set")
    for proj, count in project_counts.most_common():
        print(f"  {proj:<28} {count:>6}")

    print("\nKept file")
    print(f"  {OUTPUT_CLEAN_FILE.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()