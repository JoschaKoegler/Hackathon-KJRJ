"""3. Terms for the word cloud.

Counts terms in the prepared text. Stop words and the token window sit
below. The number of terms on screen sits in ``config.py``.
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
}


def tokens(text, limit=TOKEN_CHARS) -> list[str]:
    words = re.findall(r"[a-zäöüßàâéèêëîïôùûç]{4,}", str(text or "").lower()[:limit])
    return [word for word in words if word not in STOP_WORDS]


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
