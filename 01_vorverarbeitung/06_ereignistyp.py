"""Ereignistyp aus Titel- und Textmustern.

Zwölf Regeltypen plus projektspezifische Ergänzungen.
Schreibt ``event_type`` in den Peak-Kontext.
Aufgerufen von ``06_peak_kontext.py``. Die Schwellen bleiben dort.
"""
from __future__ import annotations

import math
import re
from collections import Counter

import importlib

def _k():
    return importlib.import_module("01_vorverarbeitung.06_peak_kontext")

def rules_for_project(cfg: dict) -> dict:
    """Globale Ereignistyp-Regeln + projektspezifische Ergänzungen/Streichungen."""
    rules = {k: v for k, v in _k().EVENT_TYPE_RULES.items() if k not in cfg.get("suppress_event_types", [])}
    rules.update(cfg.get("extra_event_types", {}))
    return rules


def classify_event_type(docs: list[dict], rules: dict) -> tuple[str, str | None, dict]:
    """
    Gibt (Haupttyp, Nebentyp oder None, Scores) zurück.
    Starke Muster: Titel 3 Punkte, Text 1. Schwache Muster: Titel 1, Text 0.5.
    Ein Typ braucht Mindestscore UND Unterstützung durch >= 25 % der Beiträge.
    """
    scores, support = Counter(), {}
    for i, d in enumerate(docs):
        title = d["title"].lower()
        body = d["content"][:600].lower()
        for etype, groups in rules.items():
            hit = False
            for pat in groups.get("strong", []):
                if re.search(pat, title):
                    scores[etype] += 3
                    hit = True
                if re.search(pat, body):
                    scores[etype] += 1
                    hit = True
            for pat in groups.get("weak", []):
                if re.search(pat, title):
                    scores[etype] += 1
                if re.search(pat, body):
                    scores[etype] += 0.5
            if hit:
                support.setdefault(etype, set()).add(i)

    need = max(1, math.ceil(_k().MIN_TYPE_SUPPORT_SHARE * len(docs)))
    valid = [(sc, t) for t, sc in scores.items() if sc >= _k().MIN_EVENT_SCORE and len(support.get(t, ())) >= need]
    if not valid:
        return _k().GENERIC_EVENT_TYPE, None, dict(scores)
    valid.sort(reverse=True)
    best_score, best = valid[0]
    secondary = valid[1][1] if len(valid) > 1 and valid[1][0] >= _k().SECONDARY_TYPE_RATIO * best_score else None
    return best, secondary, dict(scores)

