"""Page tone on a 0–2 scale, kept apart from text stance.

The circle reads the passage about the project, not the vendor code.
Vendor ``1/0/-1`` is a poor match for that passage: of every vendor ``-1``,
8 of 44 were actually negative when read by hand, and none of the four
Heilbronn ``-1`` posts were opposition. The working scale is

* ``2`` positive — the passage states approval, progress, or a favourable result
* ``1`` neutral — the project is the subject, without that judgement
* ``0`` negative — the passage states a setback, criticism, rejection, or closure

A score is kept only when the text actually carries the project. An empty
body, or a long piece in which the project is a side sentence, becomes
missing. Shares collapse copies of the same title to one story. If those
copies disagree, the story is missing rather than voted twice.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

DEFINITIONS = Path(__file__).resolve().parent.parent / "pipeline" / "project_definitions.json"

POSITIVE = 2
NEUTRAL = 1
NEGATIVE = 0
LABEL = {POSITIVE: "Positive", NEUTRAL: "Neutral", NEGATIVE: "Negative"}
TONE_NAME = {POSITIVE: "positive", NEUTRAL: "neutral", NEGATIVE: "negative"}

# Vendor export. Never a tone, and never entered into a mean.
MISSING_CODE = -99
EMPTY_BODY = 40
SHORT_TEXT = 700
# A long piece whose title is another story still counts when the project
# opens the text. A later item in a roundup does not.
OPENING = 900
Z = 1.96

_TOPIC: dict[str, re.Pattern[str]] | None = None
_CONTEXT: dict[str, re.Pattern[str]] | None = None


def clean(text) -> str:
    text = str(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _load_terms() -> None:
    global _TOPIC, _CONTEXT
    if _TOPIC is not None:
        return
    raw = json.loads(DEFINITIONS.read_text(encoding="utf-8"))
    topics = {}
    contexts = {}
    never = re.compile(r"a^")
    for project in raw["projects"]:
        topic_parts = [str(term) for term in project.get("topic_terms") or [] if term]
        context_parts = [str(term) for term in project.get("context_terms") or [] if term]
        topics[project["id"]] = re.compile("|".join(topic_parts), re.IGNORECASE) if topic_parts else never
        contexts[project["id"]] = re.compile("|".join(context_parts), re.IGNORECASE) if context_parts else never
    _TOPIC = topics
    _CONTEXT = contexts


def _topics() -> dict[str, re.Pattern[str]]:
    _load_terms()
    return _TOPIC


def _contexts() -> dict[str, re.Pattern[str]]:
    _load_terms()
    return _CONTEXT


# Body clauses split on sentence marks and commas, so a Toulouse opening does
# not lend its verb to the Bonn clause after the comma. Titles split only on
# commas and pipes: a colon still belongs to the same headline.
_BODY_CLAUSE = re.compile(r"[.!?]+|\s+[–—]\s+|\s+-\s+|[,;|]")
_TITLE_PIECE = re.compile(r"\s*\|\s*|,\s+")

# Word-sized. A suffix such as the "ne" in "Marne" must not count as French "ne".
# "non" in "non-mixité" is part of the word, not a negation of the cue after it.
_NEGATION = re.compile(r"\b(?:keine[mnr]?|kein|ohne|nicht|kaum|pas|sans|non)\b(?!-)")

# Negative only for a stated setback, criticism, rejection, or closure.
# A bare worry-word such as "Kosten" or "Risiko" is not enough.
_NEGATIVE_CUES = [
    ("Kritik", r"\bkritik|\bcritiques?\b"),
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
    ("Geldverschwendung", r"geldverschwend|\bluftnummer\b|(?<!ernst und )\bunsinn\b"),
    ("Bemängelung", r"bem[äa]ngel"),
    ("Gegner", r"\bgegner\b|\bwiderstand\b"),
    ("nicht sinnvoll", r"nicht sinnvoll(?!er)|unwirtschaftlich"),
    ("Protest", r"\bprotest"),
    ("Streit", r"\bstreit\b|pol[ée]mique|[ée]chec|s'oppose|controvers"),
    ("Bedenken", r"\bbedenken\b|\bzweifel\b|\bskeptisch|\bumstritten"),
    ("Angriff", r"agress|d[ée]savou|non-?mixt"),
    ("Kosten", r"zu teuer|kostspielig|unbezahlbar|kostenexplosion"),
    ("Belästigung", r"\blärm\b|nuisanc|gefahr|\bdanger\b|\bskandal"),
    ("Störung", r"\bretard\b|\baccident\b|gr[eè]ve|\bausfall\b|stillgelegt|\bdefekt\b|\bm[äa]ngel"),
    ("dagegen", r"nein zur|gegen die"),
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
    """Positive, negative, or None when this side of the text has no cue."""
    if question:
        positive = [name for name in positive if name not in _SOFT_POSITIVE]
    if negative and not positive:
        return NEGATIVE, ", ".join(negative)
    if positive and not negative:
        return POSITIVE, ", ".join(positive)
    if negative and positive:
        hard_positive = [name for name in positive if name not in _SOFT_POSITIVE]
        if not hard_positive or len(negative) >= len(hard_positive):
            return NEGATIVE, ", ".join(negative)
        return POSITIVE, ", ".join(hard_positive)
    return None


def _pieces(text: str, splitter: re.Pattern[str]) -> list[str]:
    return [part.strip() for part in splitter.split(text) if part and len(part.strip()) > 2]


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


def _title_text(title: str, topic: re.Pattern[str], context: re.Pattern[str], opening_has_context: bool) -> str:
    """Headline pieces that name the project. A comma starts a new item.

    The words just beside the project name still count, so "le téléphérique,
    un objet désavoué" is one judgement and not two headlines.
    """
    kept = []
    for piece in _pieces(title, _TITLE_PIECE):
        if not topic.search(piece):
            continue
        if context.search(piece) or opening_has_context:
            kept.append(piece)
    for match in topic.finditer(title):
        start = max(0, match.start() - 36)
        end = min(len(title), match.end() + 36)
        kept.append(title[start:end])
    return " ".join(kept)


def _body_text(body: str, topic: re.Pattern[str], context: re.Pattern[str], title_anchors: bool = False) -> str:
    """Clauses that name the project and its place, plus a short reason after them.

    The following clause catches "Seilbahn neu. Grund sind die Sicherheitsbedenken"
    without pulling in the next story of a roundup.
    """
    clauses = _pieces(body, _BODY_CLAUSE)
    kept = []
    for index, clause in enumerate(clauses):
        # The headline already names the place, so a later sentence may say
        # only "die Seilbahn" and still be about this project.
        names_project = topic.search(clause) and (context.search(clause) or title_anchors)
        # "Heilbronner Luftnummer" names the project by its nickname, without
        # repeating the noun Seilbahn in that sentence.
        nickname = context.search(clause) and re.search(r"\bluftnummer\b", clause)
        if not (names_project or nickname):
            continue
        kept.append(clause)
        if index + 1 < len(clauses) and len(clauses[index + 1]) <= 160 and not topic.search(clauses[index + 1]):
            kept.append(clauses[index + 1])
    return " ".join(kept)


def passage_score(title, content, project) -> tuple[int | None, str]:
    """2, 1, 0 from the project passage. None when the project is not the subject.

    The second value is the cue that decided a positive or negative score,
    or ``empty`` / ``side`` when the score is missing. Neutral has an empty cue:
    the project is the subject and neither list matched.
    A negative cue in the title wins over praise later in the body. A positive
    title wins over a later criticism. An unmarked title follows the passage,
    and a tie there stays neutral.
    """
    carried, reason = carries_project(title, content, project)
    if not carried:
        return None, reason
    key = str(project or "")
    topic = _topics().get(key)
    context = _contexts().get(key)
    if topic is None or context is None:
        return None, "side"
    title_text = clean(title).lower()
    body = clean(content).lower()
    # Paywalled pieces often name the city only in the outlet line. That is
    # enough for a title that already names the project. A body clause still
    # has to name the city itself, so a Fulda or Hamburg example stays out.
    opening_has_context = bool(context.search(f"{title_text} {body[:700]}"))
    title_scope = _title_text(title_text, topic, context, opening_has_context)
    title_anchors = bool(topic.search(title_text) and context.search(title_text))
    body_scope = _body_text(body, topic, context, title_anchors)
    title_negative = _cue_hits(title_scope, _NEGATIVE)
    title_positive = _cue_hits(title_scope, _POSITIVE)
    body_negative = _cue_hits(body_scope, _NEGATIVE)
    body_positive = _cue_hits(body_scope, _POSITIVE)
    question = "?" in title_text
    chosen = _decide(title_negative, title_positive, question)
    if chosen is not None:
        return chosen
    chosen = _decide(body_negative, body_positive, False)
    if chosen is not None:
        return chosen
    return NEUTRAL, ""


def score_from_vendor(value):
    """Map a vendor code onto 2, 1, 0. ``-99`` and anything else are missing.

    Kept for the calibration script. The circles use ``passage_score``.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or number == MISSING_CODE:
        return None
    return {1.0: POSITIVE, 0.0: NEUTRAL, -1.0: NEGATIVE}.get(number)


def carries_project(title, content, project) -> tuple[bool, str]:
    """Whether the body is about this project, not merely mentioning it.

    Returns ``(False, "empty")`` for a body under 40 characters, unless the
    title itself names the project and its place. Returns ``(False, "side")``
    when the project is one sentence inside another story.
    """
    body = clean(content)
    if len(body) < EMPTY_BODY:
        title_text = clean(title)
        topic = _topics().get(str(project or ""))
        context = _contexts().get(str(project or ""))
        if (
            topic is not None
            and context is not None
            and len(title_text) >= 20
            and topic.search(title_text)
            and context.search(title_text)
        ):
            return True, ""
        return False, "empty"
    topic = _topics().get(str(project or ""))
    if topic is None:
        return False, "side"
    title_hit = bool(topic.search(clean(title)))
    sentences = [part for part in re.split(r"(?<=[.!?])\s+", body) if part]
    hits = [part for part in sentences if topic.search(part)]
    share = sum(len(part) for part in hits) / max(len(body), 1)
    if len(body) <= SHORT_TEXT and (title_hit or hits):
        return True, ""
    if title_hit and hits and share >= 0.05:
        return True, ""
    # No project in the title: only when it leads the piece, not when it
    # arrives as a later item in a bulletin about something else.
    if topic.search(body[:OPENING]) and len(hits) >= 2 and share >= 0.12:
        return True, ""
    return False, "side"


def story_key(title, mention_id) -> str:
    """Same headline, one story. Short or empty titles stay on their own id."""
    key = re.sub(r"https?://\S+", " ", clean(title).lower())
    key = re.sub(r"\s+", " ", key).strip()[:80]
    if len(key) < 25:
        return f"id:{mention_id}"
    return key


def tone_label(score) -> str:
    try:
        number = float(score)
    except (TypeError, ValueError):
        return "missing"
    if math.isnan(number):
        return "missing"
    return TONE_NAME.get(int(number), "missing")


def circle_label(score):
    try:
        number = float(score)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return LABEL.get(int(number))


def wilson(successes: int, trials: int, z: float = Z) -> tuple[float, float] | tuple[None, None]:
    """Wilson interval. Stays open when the count is 0 or equal to the trials."""
    if trials <= 0:
        return None, None
    proportion = successes / trials
    z2 = z * z
    denominator = 1 + z2 / trials
    centre = (proportion + z2 / (2 * trials)) / denominator
    half = z * math.sqrt(proportion * (1 - proportion) / trials + z2 / (4 * trials * trials)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def balance_stats(positive: int, neutral: int, negative: int, z: float = Z):
    """Balance ``(positive − negative) / scored``, with an interval that stays open at the edge.

    The point is the raw balance. The standard error adds half a story to each
    class before the delta-method variance, so a window with zero negative
    stories does not report a standard error of 0.
    """
    scored = positive + neutral + negative
    if scored <= 0:
        return None, None, None, None
    point = (positive - negative) / scored
    adjusted = scored + 1.5
    p_pos = (positive + 0.5) / adjusted
    p_neg = (negative + 0.5) / adjusted
    variance = (
        p_pos * (1 - p_pos) + p_neg * (1 - p_neg) + 2 * p_pos * p_neg
    ) / adjusted
    error = math.sqrt(variance)
    low = max(-1.0, point - z * error)
    high = min(1.0, point + z * error)
    return point, low, high, error


def as_score(value):
    """2, 1, 0, or missing. NaN and ``-99`` do not pass."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    number = int(number)
    return number if number in LABEL else None


def collapse_rows(rows: list[dict]) -> list[dict]:
    """One row per story. Disagreeing copies become a missing score."""
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for row in rows:
        key = row.get("story_key") or f"id:{row.get('mention_id')}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    collapsed = []
    for key in order:
        group = groups[key]
        scores = {as_score(row.get("tone_score")) for row in group}
        scores.discard(None)
        kept = dict(group[0])
        kept["copies"] = len(group)
        kept["tone_score"] = next(iter(scores)) if len(scores) == 1 else None
        collapsed.append(kept)
    return collapsed


def describe(rows: list[dict]) -> dict:
    """Shares, Wilson intervals, balance, and the 0–2 mean. ``-99`` never enters."""
    stories = collapse_rows(rows)
    counts = {POSITIVE: 0, NEUTRAL: 0, NEGATIVE: 0}
    for row in stories:
        score = as_score(row.get("tone_score"))
        if score in counts:
            counts[score] += 1
    scored = sum(counts.values())
    missing = len(stories) - scored
    shares = {}
    intervals = {}
    named = {}
    for score, label in LABEL.items():
        named[label] = counts[score]
        shares[label] = round(counts[score] / scored, 4) if scored else 0.0
        low, high = wilson(counts[score], scored)
        intervals[label] = {
            "low": None if low is None else round(low, 4),
            "high": None if high is None else round(high, 4),
        }
    point, low, high, error = balance_stats(counts[POSITIVE], counts[NEUTRAL], counts[NEGATIVE])
    mean = round((POSITIVE * counts[POSITIVE] + NEUTRAL * counts[NEUTRAL]) / scored, 2) if scored else None
    return {
        "counts": named,
        "shares": shares,
        "intervals": intervals,
        "classified": scored,
        "unclassified": missing,
        "stories": len(stories),
        "balance": None if point is None else round(point, 4),
        "balance_low": None if low is None else round(low, 4),
        "balance_high": None if high is None else round(high, 4),
        "balance_se": None if error is None else round(error, 4),
        "mean": mean,
        "n": scored,
        "n_missing": missing,
    }


def rows_from_frame(frame) -> list[dict]:
    rows = []
    for record in frame.itertuples(index=False):
        rows.append({
            "story_key": getattr(record, "story_key", None),
            "mention_id": getattr(record, "mention_id", None),
            "tone_score": as_score(getattr(record, "tone_score", None)),
        })
    return rows


def format_window(stats: dict) -> str:
    """One window: three shares with intervals, balance beside, mean with n and missing."""
    if not stats["n"]:
        return f"no scored stories (n=0, missing={stats['n_missing']})"
    parts = []
    for label in ("Positive", "Neutral", "Negative"):
        share = stats["shares"][label]
        band = stats["intervals"][label]
        low = "–" if band["low"] is None else f"{round(band['low'] * 100)}"
        high = "–" if band["high"] is None else f"{round(band['high'] * 100)}"
        parts.append(f"{label.lower()} {round(share * 100)}% ({low}–{high})")
    balance = stats["balance"]
    balance_text = "–" if balance is None else f"{balance:+.2f}"
    return (
        f"{', '.join(parts)}, balance {balance_text}, "
        f"mean {stats['mean']:.2f} (n={stats['n']}, missing={stats['n_missing']})"
    )
