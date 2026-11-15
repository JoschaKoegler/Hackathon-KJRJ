"""Auffällige Begriffe im Peak-Fenster.

Log-Odds der Dokumenthäufigkeit gegen die 35 Tage vor dem Peak.
Schreibt ``top_terms`` und genannte Beträge.
Aufgerufen von ``06_peak_kontext.py``. Die Schwellen bleiben dort.
"""
from __future__ import annotations

import math
import re
from collections import Counter

import importlib

def _k():
    return importlib.import_module("01_vorverarbeitung.06_peak_kontext")

def tokenize(text: str, extra_stop=frozenset()) -> set[str]:
    words = re.findall(r"[a-zäöüßéèêàâçîôûù]{%d,}" % _k().TERM_MIN_LEN, str(text).lower())
    return {w for w in words if w not in _k().STOPWORDS and w not in _k().PROJECT_STOP_TERMS and w not in extra_stop}


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
                      extra_stop=frozenset(), top_n: int = _k().TOP_TERMS) -> list[str]:
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
        if n_all >= 50 and global_df.get(term, 0) / n_all > _k().MAX_GLOBAL_DF_RATIO:
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

