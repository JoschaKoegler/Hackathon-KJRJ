"""3. Terms for the word cloud.

Counts terms in the prepared text. Stop words, project names, and the
token window sit below. The number of terms on screen sits in ``config.py``.
"""

from __future__ import annotations

import re
from collections import Counter

import pandas as pd

from .config import TERM_COUNT, TERM_COUNTING, TOKEN_CHARS

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


def _topic_word(word: str) -> bool:
    if word in TOPIC_WORDS:
        return True
    return any(word.startswith(stem) for stem in TOPIC_STEMS)


def tokens(text, limit=TOKEN_CHARS) -> list[str]:
    words = re.findall(r"[a-zäöüßàâéèêëîïôùûç]{4,}", str(text or "").lower()[:limit])
    return [word for word in words if word not in STOP_WORDS and not _topic_word(word)]


def attach(frame: pd.DataFrame) -> pd.DataFrame:
    """Adds the ``terms`` column."""
    frame["terms"] = frame["text"].map(tokens)
    return frame


def top_terms(frame: pd.DataFrame, n: int = TERM_COUNT) -> list[dict]:
    counter: Counter = Counter()
    for word_list in frame["terms"]:
        if TERM_COUNTING == "occurrences":
            counter.update(word_list)
        else:
            counter.update(set(word_list))
    return [{"term": word, "count": int(count)} for word, count in counter.most_common(n)]
