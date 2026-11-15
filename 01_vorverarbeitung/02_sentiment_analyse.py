"""02. Sentiment-Analyse — Passage 0/1/2, einmal pro Beitrag.

Liest
  ``00_data/posts.json``
  ``00_data/definitions.json``   Topic-Muster, wann der ganze Text zählt

Schreibt auf denselben Beitrag
  ``tone_score``  2 positiv, 1 neutral, 0 negativ, sonst leer
  ``tone_cue``    auslösende Wörter
  ``tone_gap``    leer, wenn ein Score steht
  ``story_key``   gleiche Schlagzeile, eine Story
  ``circle``      Positive / Neutral / Negative

Kurze Texte und beiläufige Erwähnungen bleiben bewertet. Ein negatives Stichwort
reicht und schlägt ein positives. Trifft keine Cue-Liste, ist der Beitrag neutral.
Stance steht in ``03_stance_analyse.py``. Fenster-Anteile stehen in ``02_laufzeit/fenster.py``.
"""
from __future__ import annotations

import importlib
import json
import math
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_config = importlib.import_module("02_laufzeit.config")
DEFINITIONS = _config.DEFINITIONS_FILE
POSTS_FILE = _config.POSTS_FILE

POSITIVE = 2
NEUTRAL = 1
NEGATIVE = 0
LABEL = {POSITIVE: "Positive", NEUTRAL: "Neutral", NEGATIVE: "Negative"}

_TOPIC: dict[str, re.Pattern[str]] | None = None


def clean(text) -> str:
    text = str(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _load_terms() -> None:
    global _TOPIC
    if _TOPIC is not None:
        return
    raw = json.loads(DEFINITIONS.read_text(encoding="utf-8"))
    topics = {}
    never = re.compile(r"a^")
    for project in raw["projects"]:
        topic_parts = [str(term) for term in project.get("topic_terms") or [] if term]
        topics[project["id"]] = re.compile("|".join(topic_parts), re.IGNORECASE) if topic_parts else never
    _TOPIC = topics


def _topics() -> dict[str, re.Pattern[str]]:
    _load_terms()
    return _TOPIC


# Word-sized. A suffix such as the "ne" in "Marne" must not count as French "ne".
# "non" in "non-mixité" is part of the word, not a negation of the cue after it.
_NEGATION = re.compile(r"\b(?:keine[mnr]?|kein|ohne|nicht|kaum|pas|sans|non)\b(?!-)")

# Negative for a stated setback, criticism, rejection, cost, or risk.
# Kosten and Risiko on their own are enough.
_NEGATIVE_CUES = [
    ("Kritik", r"\bkritik|\bkritisch|\bkritisiert|\bkritiker|\bcritiques?\b"),
    ("Rückschlag", r"r[üu]ckschlag"),
    ("Verzögerung", r"verz[öo]ger"),
    ("Sicherheitsbedenken", r"sicherheitsbedenken"),
    ("Ablehnung", r"lehnt\w{0,4}\s+(?:\S+\s+){0,5}ab|\babgelehnt\b|\bdarf nicht\b|d[üu]rfen nicht"),
    ("ungewiss", r"\bungewiss"),
    ("Vorwurf", r"vorw[üu]rf"),
    ("Verwirrung", r"\bverwirrung"),
    ("falscher Schritt", r"falscher schritt"),
    ("Scheitern", r"\bscheitert\b|\bgescheitert"),
    ("ernüchternd", r"ern[üu]chter"),
    ("nicht umsetzbar", r"nicht umsetzbar|nicht weiterverfolgt"),
    # "fermeture du câble de 2,7 km" is the splice of the rope, not a closure.
    ("Stillstand", r"[àa]\s*l['’]arr[êe]t|fermeture(?!\s+du\s+c[âa]ble\s+de\b)|\binterrompu\b|\bsuspendu\b"),
    ("Unsicherheit", r"ins[ée]curit"),
    ("Panne", r"\bpanne\b"),
    ("statt Seilbahn", r"statt seilbahn"),
    ("Geldverschwendung", r"geldverschwend|\bluftnummer\b|(?<!ernst und )\bunsinn(?:ig)?\b"),
    ("Bemängelung", r"bem[äa]ngel"),
    ("Gegner", r"\bgegner\b|\bwiderstand\b"),
    ("nicht sinnvoll", r"nicht sinnvoll(?!er)|unwirtschaftlich"),
    ("Protest", r"\bprotest"),
    ("Streit", r"\bstreit\b|pol[ée]mique|[ée]chec|s'oppose|controvers"),
    ("Bedenken", r"\bbedenken\b|\bzweifel\b|\bskeptisch|\bumstritten|\bsorge\b|\bbef[üu]rcht"),
    ("Angriff", r"agress|d[ée]savou|non-?mixt"),
    ("Kosten", r"\bteuer\w*|kostspielig|unbezahlbar|kostenexplosion|\bkosten\b|\brisiko\b|\brisiken\b|\bco[uû]ts?\b|\brisques?\b|\bcosts?\b|\brisks?\b"),
    ("Belästigung", r"\blärm\b|nuisanc|gefahr|\bdanger\b|\bskandal"),
    ("Störung", r"\bretard\b|\baccident\b|gr[eè]ve|\bausfall\b|stillgelegt|\bdefekt\b|\bm[äa]ngel"),
    ("dagegen", r"nein zur|gegen die|\bdagegen\b|gegen (?:eine|ein|das)\b"),
]
# Positive only for a stated approval, opening, or step forward.
_POSITIVE_CUES = [
    ("Ja zur", r"ja zur"),
    ("grünes Licht", r"gr[üu]nes licht"),
    ("schreitet voran", r"schreitet voran|geht voran"),
    ("nächste Hürde", r"n[äa]chste h[üu]rde"),
    ("befürwortet", r"bef[üu]rwortet|bef[üu]rworten"),
    ("begrüßt", r"begr[üu][sß]t"),
    ("Pionier", r"\bpionier"),
    ("Einweihung", r"inaugur|er[öo]ffn|ouvre ses portes"),
    ("Erfolg", r"grand succ[eè]s|\berfolg\b|plus agr[ée]able"),
    ("Modellstadt", r"modellstadt"),
    ("hält am Ziel fest", r"h[äa]lt an (?:ihrem|dem) ziel"),
    ("nächste Etappe", r"n[äa]chste[rn]? etappe"),
    ("Premiere", r"\bpremiere\b|tout premier"),
    ("Meilenstein", r"meilenstein|zukunftsweisend|spatenstich|\bfortschritt"),
    ("Auszeichnung", r"auszeichnung|prämiert|ausgezeichnet|r[ée]compens"),
    ("Eröffnung", r"ouverture|\bouvrir\b|\ben service\b|mis en service|in betrieb|baubeginn|lancement"),
    ("Beitritt", r"\bmitglied\b|\bbeitritt\b|schlie[sß]t sich|rejoint|\bpartenaire\b|\bpartnerschaft|wird teil|teil des|teil der|\bvertreten\b"),
    ("Entlastung", r"entlast|klimafreund"),
    ("Zustimmung", r"\bpositiv|\bunterst[üu]tz|\bsoutien\b|chancen?(?!\s+und\s+risiken)"),
    ("Attraktiv", r"attraktiv|vorzeige|\brekord\b|\bbeliebt|bonheur|\bvorblid"),
    ("Aufbau", r"\bentsteht\b|\bbaustelle\b|\bgestartet\b|\bstartet\b|\bgebaut\b|\bfestival\b"),
    ("Erste", r"\bpremier(?:e|s)?\b|\berste[rnms]?\b"),
]

_NEGATIVE = [(name, re.compile(pattern)) for name, pattern in _NEGATIVE_CUES]
_POSITIVE = [(name, re.compile(pattern)) for name, pattern in _POSITIVE_CUES]
# These say the piece is a first, a building site, or an opening. They assign a
# post when nothing harder is present. A question headline, or a setback in the
# same text, does not become positive just because it also says "the first".
_SOFT_POSITIVE = {"Erste", "Aufbau", "Eröffnung", "Premiere", "Meilenstein", "Beitritt"}


def _decide(negative: list[str], positive: list[str], question: bool = False) -> tuple[int, str] | None:
    """One negative cue is enough and beats every positive cue."""
    if negative:
        return NEGATIVE, ", ".join(negative)
    if question:
        positive = [name for name in positive if name not in _SOFT_POSITIVE]
    if positive:
        return POSITIVE, ", ".join(positive)
    return None


def _cue_hits(text: str, cues: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    found = []
    lowered = text.lower()
    # A hypothetical or a drill is not a closure. "ne sera interrompu qu'en cas de vents".
    hypothetical = bool(re.search(r"en cas\b|exercice|pompiers", lowered))
    # "Merz-Kritik" is about the visitor, not about the project he visited.
    about_person = bool(re.search(r"merz-kritik|kritik an merz", lowered))
    for name, pattern in cues:
        if hypothetical and name == "Stillstand":
            continue
        if about_person and name == "Kritik":
            continue
        for match in pattern.finditer(lowered):
            before = lowered[max(0, match.start() - 40):match.start()]
            if _NEGATION.search(before):
                continue
            if name == "Verzögerung" and re.search(
                r"bekannt geworden|bereits im vorfeld",
                lowered[max(0, match.start() - 90):match.end()],
            ):
                continue
            # "löst das Problem" and "Chancen und Risiken" are not a judgement on their own.
            if name == "Zustimmung" and re.search(r"risik", lowered[match.end():match.end() + 24]):
                continue
            if name == "Störung" and re.search(r"\b(?:löst|loest|lösen|loesen|solution)\b", before):
                continue
            found.append(name)
            break
    return found


def _scope(title: str, body: str, topic: re.Pattern[str]) -> str:
    """Title plus the whole text when the headline names the project.

    Otherwise only the stretch around each mention, so a different story in the
    same roundup does not lend its cue.
    """
    if topic.search(title):
        return f"{title} {body}"
    windows = [
        body[max(0, match.start() - 500): match.end() + 500]
        for match in topic.finditer(body)
    ]
    return f"{title} {' '.join(windows)}".strip()


def passage_score(title, content, project) -> tuple[int | None, str]:
    """2, 1, 0. None only when the project key is unknown.

    A short text and a passing mention stay in the scored set. One negative cue
    is enough and beats every positive cue. No cue means neutral. A question
    headline does not become positive from a soft cue such as "the first".
    """
    carried, reason = carries_project(title, content, project)
    if not carried:
        return None, reason
    key = str(project or "")
    topic = _topics().get(key)
    if topic is None:
        return None, "side"
    title_text = clean(title).lower()
    body = clean(content).lower()
    scope = _scope(title_text, body, topic)
    chosen = _decide(
        _cue_hits(scope, _NEGATIVE),
        _cue_hits(scope, _POSITIVE),
        "?" in title_text,
    )
    if chosen is not None:
        return chosen
    return NEUTRAL, ""


def carries_project(title, content, project) -> tuple[bool, str]:
    """Every post with a known project is scored, including short texts and side mentions."""
    del title, content
    if _topics().get(str(project or "")) is None:
        return False, "side"
    return True, ""


def story_key(title, mention_id) -> str:
    """Same headline, one story. Short or empty titles stay on their own id."""
    key = re.sub(r"https?://\S+", " ", clean(title).lower())
    key = re.sub(r"\s+", " ", key).strip()[:80]
    if len(key) < 25:
        return f"id:{mention_id}"
    return key


def circle_label(score):
    try:
        number = float(score)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return LABEL.get(int(number))


def _project_of(value) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str) and value.startswith("["):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(parsed, list) and parsed:
            return str(parsed[0])
    return str(value or "")


def score_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Writes tone_score, tone_cue, tone_gap, story_key, circle from raw title and content."""
    if "project" not in frame.columns:
        frame = frame.copy()
        frame["project"] = frame["matched_projects"].map(_project_of)
    scores = []
    gaps = []
    cues = []
    keys = []
    for record in frame.itertuples(index=False):
        score, cue = passage_score(
            getattr(record, "title", ""),
            getattr(record, "content", ""),
            getattr(record, "project", ""),
        )
        if score is None:
            scores.append(pd.NA)
            gaps.append(cue or "side")
            cues.append("")
        else:
            scores.append(score)
            gaps.append("")
            cues.append(cue)
        keys.append(story_key(getattr(record, "title", ""), getattr(record, "mention_id", "")))
    frame = frame.copy()
    frame["tone_score"] = scores
    frame["tone_gap"] = gaps
    frame["tone_cue"] = cues
    frame["story_key"] = keys
    frame["circle"] = frame["tone_score"].map(circle_label)
    return frame


def apply(posts: list[dict]) -> list[dict]:
    """Scores every post and writes the fields back onto the original dicts."""
    frame = score_frame(pd.DataFrame(posts))
    for post, record in zip(posts, frame.itertuples(index=False)):
        score = record.tone_score
        post["tone_score"] = None if pd.isna(score) else int(score)
        post["tone_cue"] = record.tone_cue or ""
        post["tone_gap"] = record.tone_gap or ""
        post["story_key"] = record.story_key or ""
        post["circle"] = None if record.circle is None or (isinstance(record.circle, float) and math.isnan(record.circle)) else record.circle
    return posts


def main() -> None:
    posts = json.loads(POSTS_FILE.read_text(encoding="utf-8"))
    apply(posts)
    POSTS_FILE.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
    circles = {}
    for post in posts:
        circles[post.get("circle") or "missing"] = circles.get(post.get("circle") or "missing", 0) + 1
    print(f"Sentiment: {POSTS_FILE}  n={len(posts)}  {circles}")


if __name__ == "__main__":
    main()

