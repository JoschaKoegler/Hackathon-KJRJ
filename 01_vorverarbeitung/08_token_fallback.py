"""Token-Fallback — Wortlisten und Claim-Muster, wenn kein kuratiertes Thema greift.

Liest den gespeicherten Beitragstext (Titel, Zeilenumbruch, Text ohne Paywall, TEXT_CHARS).

Schreibt auf den Beitrag
  ``terms``        Tokens
  ``categories``   Themen-Ids aus den Präfix-Listen
  ``arguments``    Claim-Ids aus den Mustern

Die Anteile im gewählten Fenster (``category_profile``, ``argument_profile``)
rechnet die Laufzeit. Die kuratierte Regex-Zuordnung steht in ``07_themen_zuordnung.py``.
"""
from __future__ import annotations

import importlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_config = importlib.import_module("02_laufzeit.config")
TEXT_CHARS = _config.TEXT_CHARS
POSTS_FILE = _config.POSTS_FILE

TOKEN_CHARS = TEXT_CHARS

STOP_WORDS = {
    "dass", "daß", "eine", "einer", "einem", "einen", "nicht", "auch", "sich", "sind",
    "wird", "wurde", "werden", "haben", "hat", "nach", "noch", "oder", "aber", "über",
    "unter", "zwischen", "sowie", "beim", "schon", "nur", "wie", "aus", "bei", "mit",
    "von", "für", "und", "der", "die", "das", "den", "dem", "des", "ein", "ist", "auf",
    "als", "zum", "zur", "vom", "im", "in", "am", "an", "zu", "es", "sie", "wir", "man",
    "les", "des", "une", "dans", "pour", "par", "sur", "avec", "plus", "que", "qui",
    "est", "sont", "pas", "aux", "cette", "leur", "leurs", "nous", "vous",
    "the", "and", "for", "with", "this", "that", "from", "https", "http", "www",
    "weiterlesen", "artikel", "diese", "dieser", "diesem", "durch", "allen",
    "sein", "seine", "seinem", "seinen", "seiner", "mehr", "kann", "wurde",
    "jetzt", "ihre", "ihrem", "ihren", "ihrer", "ihres", "dann", "wenn", "weil",
    "doch", "hier", "dort", "dazu", "beim",
    # Leftover Stimme paywall words, if the cut leaves a fragment.
    "stimme", "testabo", "freischalten", "zugang", "sichern", "merken",
    "abonnement", "anmeldung", "konto", "geräten", "geraeten",
    # Place and calendar words that otherwise fill the cloud.
    "heilbronn", "heilbronner", "bonn", "bonner", "paris", "france", "frankreich",
    "marne", "baden", "württemberg", "wuerttemberg", "deutschland", "deutschen",
    "deutsche", "deutscher", "deutsches", "créteil", "creteil", "villeneuve",
    "valenton", "stadt", "städte", "januar", "februar", "märz", "maerz", "april",
    "juni", "juli", "august", "september", "oktober", "november", "dezember",
    "décembre", "janvier", "février", "fevrier", "mars", "avril", "juin",
    "juillet", "août", "aout", "septembre", "octobre", "novembre",
    # Media and function words left after the short stop list.
    "google", "foto", "photo", "photos", "video", "vidéo", "publié", "publie",
    "heute", "gestern", "newsletter", "redaktion", "radio", "neue", "neuer",
    "neues", "neuen", "nouveau", "nouvelle", "nouvelles", "premier", "première",
    "premiere", "soll", "sollte", "sollten", "können", "könnte", "könnten",
    "bereits", "immer", "wieder", "etwa", "sowie", "land", "euro", "euros",
    "saint", "georges", "limeil", "brévannes", "brevannes",
    # Function words that filled the cloud once names were gone.
    "gibt", "geben", "erste", "erster", "ersten", "erstes", "rund", "damit",
    "alle", "allem", "aller", "dabei", "zwei", "drei", "vier", "fünf", "seit",
    "jahren", "jahre", "jahr", "viele", "vielen", "viel", "aussi", "mais",
    "entre", "comme", "dont", "tout", "tous", "toute", "toutes", "très", "tres",
    "bien", "après", "apres", "avant", "selon", "lors", "vers", "chez", "sans",
    "sous", "donc", "alors", "encore", "depuis", "pendant", "elle", "elles",
    "fait", "être", "etre", "keine", "kein", "keinen", "keiner", "keinem",
    "muss", "müssen", "muessen", "sondern", "richtung", "während", "waehrend",
    "anzeige", "blick", "ohne", "weiter", "unsere", "unser", "gemeinsam",
    "jour", "même", "meme", "mêmes", "memes", "projekt", "projets", "service",
    "worden", "sagte", "sagt", "kommen", "kommt", "gehen", "geht", "andere",
    "anderen", "anderer", "anderes", "davon", "darauf", "macht", "machen",
    "personen", "leben", "welt", "zeit", "ganz", "große", "grosse", "großen",
    "grossen", "teil", "teile", "sieht", "sehen", "menschen", "direkt",
    "stehen", "steht", "mise", "sommer", "besonders", "neben",
}

# Project names the filter already required. They crowd out arguments.
TOPIC_STEMS = (
    "seilbahn",
    "gondelbahn",
    "téléphéri",
    "telepheri",
    "télécabin",
    "telecabin",
    "ipai",
)
TOPIC_WORDS = {"cable", "câble", "cables"}

# Themes a post can fall into. Order is the order on the page.
# prefixes: the token starts with this. words: the token is exactly this.
# Longer prefixes win, so "wirtschaftlichkeit" is Kosten and "wirtschaft" is Wirtschaft.
# "kostenlos" is excluded below: it means free, not a cost debate.
CATEGORIES = (
    {
        "id": "mobilitaet",
        "label": "Mobilität",
        "prefixes": (
            "urbain", "urban", "öpnv", "oepnv", "nahverkehr", "mobilit", "mobilité",
            "mobilite", "transport", "verkehrsmittel", "verkehr", "anbindung", "pendler",
            "fahrgast", "voyageur", "usager", "stadtbahn", "bahnhof", "kapazität",
            "kapazitaet", "capacité", "capacite", "fréquentation", "frequentation",
            "radverkehr", "tramway", "ligne", "linie", "entlastung",
        ),
        "words": ("métro", "metro", "tram", "trams", "stau", "staus", "bahn"),
    },
    {
        "id": "kosten",
        "label": "Kosten",
        "prefixes": (
            "planungskosten", "kostenschätz", "kostenschaetz", "kosten", "kostet",
            "teurer", "teuer", "finanz", "haushalt", "budget", "subvention",
            "fördergeld", "fördermittel", "förderzusage", "förderfähig", "förderprogramm",
            "fördertopf", "fördersumme", "förderung",
            "foerdergeld", "foerdermittel", "foerderzusage", "foerderprogramm", "foerderung",
            "million", "investition", "wirtschaftlichkeit", "rentabilit",
            "coût", "coute", "coûte", "financement", "gebühr", "gebuehr", "defizit",
            "zuschuss", "beihilfe",
        ),
        "words": (),
    },
    {
        "id": "nachhaltigkeit",
        "label": "Nachhaltigkeit",
        "prefixes": (
            "nachhalt", "klimaneutral", "klimaschutz", "klima", "emission", "émission",
            "ökolog", "oekolog", "écolog", "ecolog", "umwelt", "energie", "énergie",
            "erneuerbar", "kohlenstoff", "carbone", "environnement", "biodivers",
            "treibhaus", "ressourc", "durable",
        ),
        "words": (),
    },
    {
        "id": "umfeld",
        "label": "Umfeld",
        "prefixes": (
            "stadtbild", "landschaft", "sichtachse", "verschattung", "grünfläche",
            "gruenflaeche", "lärm", "laerm", "bruit", "paysage", "nuisance",
            "artenschutz", "naturschutz", "vogelschutz", "wohnumfeld", "freiraum",
            "baumfäll", "baumfaell",
        ),
        "words": (),
    },
    {
        "id": "akzeptanz",
        "label": "Akzeptanz",
        "prefixes": (
            "bürgerinitiative", "buergerinitiative", "bürgerbeteiligung", "buergerbeteiligung",
            "bürgerdialog", "buergerdialog", "protest", "widerstand", "petition", "pétition",
            "anwohner", "bewohner", "beteiligung", "riverain", "manifestation", "contestation",
            "concertation", "unterschrift", "gegner", "befürworter", "befuerworter",
            "akzeptanz", "kritik", "ablehnung", "umfrage", "skeptisch", "bedenken",
            "bürger", "buerger", "citoyen",
        ),
        "words": (),
    },
    {
        "id": "sicherheit",
        "label": "Sicherheit",
        "prefixes": (
            "sicherheit", "unfall", "unfälle", "unfaelle", "accident", "sécurité",
            "securite", "agression", "aggression", "vandal", "belästigung", "belaestigung",
            "harcèlement", "harcelement", "übergriff", "uebergriff", "évacuation",
            "evacuation", "evakuierung",
        ),
        "words": (),
    },
    {
        "id": "planung",
        "label": "Planung",
        "prefixes": (
            "planfeststellung", "machbarkeit", "faisabilit", "gutachten", "genehmigung",
            "genehmigt", "variante", "planung", "geplant", "vorhaben", "étude", "etude",
            "tracé", "trasse",
        ),
        "words": ("pläne", "plänen", "plaene", "plaenen"),
    },
    {
        "id": "politik",
        "label": "Politik",
        "prefixes": (
            "bürgerentscheid", "buergerentscheid", "gemeinderat", "stadtrat", "kreistag",
            "landtag", "oberbürgermeister", "oberbuergermeister", "bürgermeister",
            "buergermeister", "verkehrsminister", "minister", "beschluss", "beschlossen",
            "beschließt", "beschliesst", "abstimmung", "koalition", "fraktion", "partei",
            "délibération", "deliberation", "conseil", "maire", "gewählt", "gewaehlt",
            "wähler", "waehler", "wahl",
        ),
        "words": ("élu", "élus", "élue", "élues", "elu", "elus", "elue", "elues"),
    },
    {
        "id": "bau",
        "label": "Bau & Betrieb",
        "prefixes": (
            "spatenstich", "baustelle", "baustart", "bauarbeit", "baubeginn", "richtfest",
            "grundstein", "inaugur", "eröffnung", "eroeffnung", "eröffnet", "eroeffnet",
            "inbetriebnahme", "betriebsstart", "haltestelle", "strecke", "cabine",
            "kabine", "gondel", "chantier", "travaux", "ouverture", "fermeture", "sperrung",
            "gesperrt", "störung", "stoerung", "ausfall", "ausfälle", "ausfaelle",
            "panne", "wartung", "maintenance", "verzöger", "verzoeger", "fertigstellung",
            "station", "gebaut", "bauen", "baut",
        ),
        "words": ("bau", "ouvert", "ouverte", "ouverts", "ouvertes"),
    },
    {
        "id": "wirtschaft",
        "label": "Wirtschaft",
        "prefixes": (
            "unternehmen", "wirtschaft", "standort", "arbeitsplatz", "arbeitsplätz",
            "arbeitsplaetz", "industrie", "tourismus", "tourisme", "emploi", "entreprise",
            "investor", "mittelstand", "konzern", "wertschöpfung", "wertschoepfung", "firma",
        ),
        "words": (),
    },
    {
        "id": "technologie",
        "label": "Technologie",
        "prefixes": (
            "künstliche", "kuenstliche", "intelligenz", "intelligence", "artificial",
            "forschung", "innovation", "technologie", "wissenschaft", "ökosystem",
            "oekosystem", "ecosystem", "écosystème", "startup", "robot", "automatis",
            "digitalisierung", "algorithm",
        ),
        "words": (),
    },
)

# A prefix hit that does not mean the theme.
_EXCLUDED_PREFIXES = ("kostenlos", "kostenfrei")

THEME_LABEL = {entry["id"]: entry["label"] for entry in CATEGORIES}


def _matchers() -> list[tuple[str, str, bool]]:
    rows = []
    for entry in CATEGORIES:
        for prefix in entry["prefixes"]:
            rows.append((len(prefix), prefix, entry["id"], True))
        for word in entry["words"]:
            rows.append((len(word), word, entry["id"], False))
    rows.sort(key=lambda item: (-item[0], item[1]))
    return [(prefix, category, is_prefix) for _, prefix, category, is_prefix in rows]


_MATCHERS = _matchers()


def category_of(word: str) -> str | None:
    """Theme id for one token, or None when the token is not a theme word."""
    if word.startswith(_EXCLUDED_PREFIXES):
        return None
    for prefix, category, is_prefix in _MATCHERS:
        if is_prefix and word.startswith(prefix):
            return category
        if not is_prefix and word == prefix:
            return category
    return None


def categories_in(words) -> list[str]:
    """Theme ids mentioned in one post, in page order."""
    found = []
    seen = set()
    for word in words:
        category = category_of(word)
        if category and category not in seen:
            seen.add(category)
            found.append(category)
    order = {entry["id"]: index for index, entry in enumerate(CATEGORIES)}
    found.sort(key=order.get)
    return found


def label_for(category_id: str) -> str:
    return THEME_LABEL.get(category_id, category_id)


def _topic_word(word: str) -> bool:
    if word in TOPIC_WORDS:
        return True
    return any(word.startswith(stem) for stem in TOPIC_STEMS)


def tokens(text, limit=TOKEN_CHARS) -> list[str]:
    words = re.findall(r"[a-zäöüßàâéèêëîïôùûç]{4,}", str(text or "").lower()[:limit])
    return [word for word in words if word not in STOP_WORDS and not _topic_word(word)]


def attach_tokens(frame: pd.DataFrame) -> pd.DataFrame:
    """Adds ``terms`` and ``categories`` (theme ids, one post can have several)."""
    frame["terms"] = frame["text"].map(tokens)
    frame["categories"] = frame["terms"].map(categories_in)
    return frame


def category_profile(frame: pd.DataFrame) -> list[dict]:
    """One row per theme, in page order.

    ``count`` is posts that mention the theme. ``share`` is that count
    divided by the posts in the frame. ``terms`` are the words that
    triggered it, most common first.
    """
    counts = {entry["id"]: 0 for entry in CATEGORIES}
    examples: dict[str, Counter] = {entry["id"]: Counter() for entry in CATEGORIES}
    channel_counts: dict[str, Counter] = {entry["id"]: Counter() for entry in CATEGORIES}
    total = len(frame)
    if total and "terms" in frame.columns:
        channels = frame["channel"] if "channel" in frame.columns else [""] * total
        for word_list, channel in zip(frame["terms"], channels):
            seen_category = set()
            seen_word = set()
            for word in word_list:
                category = category_of(word)
                if category is None:
                    continue
                if word not in seen_word:
                    seen_word.add(word)
                    examples[category][word] += 1
                if category not in seen_category:
                    seen_category.add(category)
                    counts[category] += 1
                    if channel:
                        channel_counts[category][channel] += 1
    rows = []
    for entry in CATEGORIES:
        count = counts[entry["id"]]
        rows.append({
            "id": entry["id"],
            "label": entry["label"],
            "count": count,
            "share": (count / total) if total else 0.0,
            "terms": [word for word, _count in examples[entry["id"]].most_common(3)],
            "by_channel": {
                name: int(channel_counts[entry["id"]].get(name, 0))
                for name in ("News", "Social", "Other web")
            },
        })
    return rows


CLAIMS = (
    {
        "id": "nutzen",
        "label": "Nutzen im Alltag",
        "polarity": "hope",
        "pattern": (
            r"verkehrsentlast|verkehrschaos|verkehrlich\w* nutzen|geringer nutzen|"
            r"wenig nutzen|kein nutzen|ohne nutzen|"
            r"verkehr(?:sprobleme)?.{0,25}entlast|entlast\w*.{0,30}verkehr|"
            r"zeiterspar|zeitgewinn|gain de temps|temps gagn[ée]|fahrtzeit|fahrzeit|"
            r"alltagstaug|weniger umsteigen|direktverbindung|"
            r"alternative zum (?:auto|pkw|stau)|\bstaus?\b|embouteillage"
        ),
    },
    {
        "id": "kosten",
        "label": "Zu hohe Kosten",
        "polarity": "fear",
        "pattern": (
            r"zu teuer|teurer als|wird teurer|kostenexplosion|unbezahlbar|"
            r"geldverschwend|unwirtschaftlich|millionengrab|zu hohe kosten|"
            r"kosten zu hoch|kostensteigerung|kostenrisiko|kostenintensiv|kostspielig|"
            r"lohnt sich nicht|rechnet sich nicht|nicht finanzier|"
            r"trop cher|trop co[uû]teux|co[uû]t trop"
        ),
    },
    {
        "id": "machbarkeit",
        "label": "Machbarkeit",
        "polarity": "fear",
        "pattern": (
            r"machbarkeit|\bmachbar\b|undurchf[üu]hr|nicht realisier|unrealistisch|"
            r"luftnummer|faisabilit|nicht umsetzbar"
        ),
    },
    {
        "id": "klima",
        "label": "Klimaschutz",
        "polarity": "hope",
        "pattern": (
            r"klimaschutz|klimaneutral|klimafreund|emission|"
            r"ökologisch|oekologisch|[ée]colog|ecolog|carbone|treibhaus|"
            r"umweltfreundlich|emissionsfrei|emissionsarm|"
            r"nachhaltig\w* (?:mobilit|verkehr|transport|l[öo]sung)"
        ),
    },
    {
        "id": "laerm",
        "label": "Lärm",
        "polarity": "fear",
        "pattern": r"\bl[äa]rm|\bbruits?\b|ruhest[öo]rung|nuisance sonore",
    },
    {
        "id": "stadtbild",
        "label": "Stadtbild und Ästhetik",
        "polarity": "fear",
        "pattern": (
            r"[äa]sthet|stadtbild|verschandel|h[äa]sslich|sichtachse|verschatt|"
            r"erscheinungsbild|esth[ée]ti"
        ),
    },
    {
        "id": "naturschutz",
        "label": "Naturschutz",
        "polarity": "fear",
        "pattern": (
            r"naturschutz|artenschutz|baumf[äa]ll|landschaftsbild|"
            r"eingriff in (?:die )?(?:natur|landschaft)|biotop"
        ),
    },
    {
        "id": "sicherheit",
        "label": "Sicherheit und Ausfälle",
        "polarity": "fear",
        "pattern": (
            r"\bunf[äa]ll|evakuier|[ée]vacuation|\bagress|\bpanne\b|"
            r"windanf[äa]ll|st[öo]ranf[äa]ll|bei sturm|betriebsst[öo]r|hors service"
        ),
    },
    {
        "id": "barriere",
        "label": "Barrierefreiheit",
        "polarity": "hope",
        "pattern": r"barrierefrei|rollstuhl|accessibilit|\bpmr\b|personen mit eingeschr[äa]nkter",
    },
    {
        "id": "verzoegerung",
        "label": "Verzögerung",
        "polarity": "fear",
        "pattern": (
            r"verz[öo]gert sich|bauverz[öo]g|terminverzug|hinter dem zeitplan|"
            r"projektverz[öo]g|seilbahn\w*.{0,30}verz[öo]ger|verz[öo]ger\w*.{0,30}seilbahn|"
            r"\ben retard\b"
        ),
    },
    {
        "id": "prestige",
        "label": "Prestigeprojekt",
        "polarity": "fear",
        "pattern": (
            r"prestige|leuchtturm|vorzeigeprojekt|symbolpolitik|imageprojekt|"
            r"selbstdarstellung|"
            r"schwarz(?:-|\s)gruppe.{0,50}(?:aufgekauft|gesponsert|sponsor|bestimmt)|"
            r"(?:aufgekauft|gesponsert|m[äa]zen).{0,40}schwarz"
        ),
    },
    {
        "id": "jobs",
        "label": "Neue Arbeitsplätze",
        "polarity": "hope",
        "pattern": (
            r"ansiedlung|standortvorteil|neue arbeitspl|arbeitspl[äa]tze schaff|"
            r"schafft.{0,24}arbeitspl|neue jobs|jobs schaff"
        ),
    },
)

CLAIM_LABEL = {entry["id"]: entry["label"] for entry in CLAIMS}
_PATTERNS = [(entry["id"], re.compile(entry["pattern"])) for entry in CLAIMS]


def claim_label(argument_id: str) -> str:
    return CLAIM_LABEL.get(argument_id, argument_id)


def arguments_in(text) -> list[str]:
    """Claim ids mentioned in one post, in page order."""
    low = str(text or "").lower()
    return [argument_id for argument_id, pattern in _PATTERNS if pattern.search(low)]


def attach_claims(frame: pd.DataFrame) -> pd.DataFrame:
    """Adds ``arguments`` (claim ids, one post can have several)."""
    frame["arguments"] = frame["text"].map(arguments_in)
    return frame


def argument_profile(frame: pd.DataFrame) -> list[dict]:
    """One row per claim, in page order.

    ``count`` is posts that raise the claim. ``share`` divides that by
    the posts in the frame. ``terms`` are short snippets that triggered it.
    """
    counts = {entry["id"]: 0 for entry in CLAIMS}
    examples: dict[str, Counter] = {entry["id"]: Counter() for entry in CLAIMS}
    channel_counts: dict[str, Counter] = {entry["id"]: Counter() for entry in CLAIMS}
    total = len(frame)
    if total and "text" in frame.columns:
        channels = frame["channel"] if "channel" in frame.columns else [""] * total
        pairs = zip(frame["text"], channels)
    else:
        pairs = []
    for text, channel in pairs:
        low = str(text or "").lower()
        for argument_id, pattern in _PATTERNS:
            match = pattern.search(low)
            if not match:
                continue
            counts[argument_id] += 1
            if channel:
                channel_counts[argument_id][channel] += 1
            snippet = re.sub(r"\s+", " ", match.group(0)).strip()[:48]
            if snippet:
                examples[argument_id][snippet] += 1
    rows = []
    for entry in CLAIMS:
        count = counts[entry["id"]]
        rows.append({
            "id": entry["id"],
            "label": entry["label"],
            "count": count,
            "share": (count / total) if total else 0.0,
            "terms": [snippet for snippet, _count in examples[entry["id"]].most_common(2)],
            "polarity": entry.get("polarity") or "",
            "by_channel": {
                name: int(channel_counts[entry["id"]].get(name, 0))
                for name in ("News", "Social", "Other web")
            },
        })
    return rows


def attach(frame: pd.DataFrame) -> pd.DataFrame:
    """Adds ``terms``, ``categories``, ``arguments`` from the token and claim lists."""
    return attach_claims(attach_tokens(frame))


def argument_label(argument_id: str) -> str:
    """Alias used by ``page.list_posts``."""
    return claim_label(argument_id)


TERMS_NOTE = (
    "Share of posts that mention the theme. A post can count in more than one."
)
ARGUMENTS_NOTE = (
    "Expectations, fears, and misunderstandings. A post can count in more than one."
)


def apply(posts: list[dict]) -> list[dict]:
    """Writes terms, categories, and arguments. Leaves stance untouched."""
    beitraege = importlib.import_module("02_laufzeit.beitraege")
    frame = pd.DataFrame(posts)
    frame["text"] = [
        beitraege.scoring_text(title, content)
        for title, content in zip(frame["title"], frame["content"])
    ]
    frame = attach(frame)
    for post, record in zip(posts, frame.itertuples(index=False)):
        post["terms"] = list(record.terms or [])
        post["categories"] = list(record.categories or [])
        post["arguments"] = list(record.arguments or [])
    return posts


def main() -> None:
    posts = json.loads(POSTS_FILE.read_text(encoding="utf-8"))
    apply(posts)
    POSTS_FILE.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Token-Fallback: {POSTS_FILE}  n={len(posts)}")


if __name__ == "__main__":
    main()
