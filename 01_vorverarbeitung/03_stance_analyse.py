"""03. Stance-Analyse — Haltung zum Projekt, einmal pro Beitrag.

Liest den gleichen Text wie die Laufzeit: Titel, Zeilenumbruch, Text ohne
Paywall-Hinweis, gekürzt auf TEXT_CHARS.

Schreibt ``stance``: support, oppose, mixed oder no clear stance.
Die Kreise bleiben in ``02_sentiment_analyse.py``.
"""
from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_config = importlib.import_module("02_laufzeit.config")
_posts = importlib.import_module("02_laufzeit.beitraege")
POSTS_FILE = _config.POSTS_FILE


# --- Phrase stance (not the circles) ---------------------------------------

OBJECT = r"(?:seilbahn\w*|t[ée]l[ée]ph[ée]rique\w*|c[âa]ble\s*c\s*1|gondelbahn\w*|stadtseilbahn\w*)"


def _pattern(template: str) -> str:
    return template.replace("{object}", OBJECT).replace("{near}", r".{0,60}")


STANCE_SUPPORT = [
    _pattern(r"ja zur {object}"),
    _pattern(r"gr[üu]nes licht f[üu]r (?:die |eine |konkrete )?(?:vorplanung|{object})"),
    _pattern(r"gr[üu]nes licht{near}{object}|{object}{near}gr[üu]nes licht"),
    _pattern(r"bef[üu]rwort\w*(?:\s+\w+){0,4}\s+{object}"),
    _pattern(r"bef[üu]rwortet\w*{near}{object}|{object}{near}bef[üu]rwortet\w*"),
    _pattern(r"begr[üu][sß]\w*(?:\s+\w+){0,3}\s+(?:die |das )?{object}"),
    _pattern(r"(?:sieht|sehen)\s+gro[sß]e chancen{near}{object}|{object}{near}(?:sieht|sehen)\s+gro[sß]e chancen"),
    _pattern(r"gro[sß]e chance\b{near}{object}|{object}{near}gro[sß]e chance\b"),
    _pattern(r"chancen f[üu]r (?:eine |die )?{object}"),
    _pattern(r"chancen steigen{near}{object}|{object}{near}chancen steigen"),
    _pattern(r"favorable\w*{near}{object}|{object}{near}favorable"),
    _pattern(r"grand succ[eè]s{near}{object}|{object}{near}grand succ[eè]s"),
    _pattern(r"plus agr[ée]able que le (?:bus|voiture|m[ée]tro)"),
    r"positiv\w*\s+machbarkeitsstudie",
]
STANCE_OPPOSE = [
    r"luftnummer",
    r"nid [àa] agressions",
    _pattern(r"prestigeprojekt\w*{near}(?:geld|k[üu]rzung)|k[üu]rzung{near}prestigeprojekt"),
    _pattern(r"\bnein\b.{0,30}zur {object}|sagen\s+[\"“„]?nein.{0,40}{object}"),
    _pattern(r"\bkeine {object} (?:über|ueber|in|nach|durch|für|fuer)\b"),
    _pattern(r"gegen die (?:geplante )?{object}"),
    _pattern(r"{object}{near}abgelehnt|abgelehnt{near}{object}"),
    _pattern(r"{object}{near}kritisch|kritisch{near}{object}"),
    _pattern(r"nicht sinnvoll{near}{object}|{object}{near}nicht sinnvoll"),
    _pattern(r"unwirtschaftlich\w*{near}{object}|{object}{near}unwirtschaftlich"),
    _pattern(r"\bwiderstand\b{near}{object}|{object}{near}\bwiderstand\b"),
    _pattern(r"r[üu]ckschlag\w*{near}{object}|{object}{near}r[üu]ckschlag"),
    _pattern(r"lehnt\w*.{0,50}ab{near}{object}|{object}{near}lehnt\w*.{0,40}ab"),
    _pattern(r"skeptisch\w*{near}{object}|{object}{near}skeptisch"),
    _pattern(r"(?:stoppt|gestoppt).{0,40}{object}|{object}.{0,40}(?:stoppt|gestoppt)"),
    _pattern(r"critiques?\s+sur.{0,50}{object}|{object}.{0,60}critiques"),
    _pattern(r"unsinnig\w*{near}{object}|{object}{near}unsinn"),
    _pattern(r"geldverschwend\w*{near}{object}|{object}{near}geldverschwend"),
    _pattern(r"s'oppose\w*{near}{object}|{object}{near}s'oppose\w*"),
]
STANCE_MIXED = [
    _pattern(r"pro und contra{near}{object}|{object}{near}pro und contra"),
    _pattern(r"vor- und nachteile{near}{object}|{object}{near}vor- und nachteile"),
    _pattern(r"chancen und risiken{near}{object}|{object}{near}chancen und risiken"),
    _pattern(r"gro[sß]e chancen{near}risiken|warnt vor risiken{near}{object}"),
    _pattern(r"{object}{near}daf[üu]r.{0,40}dagegen|daf[üu]r.{0,40}dagegen{near}{object}"),
    _pattern(r"pol[ée]mique\w*{near}{object}|{object}{near}pol[ée]mique"),
]
_SUPPORT = [re.compile(entry) for entry in STANCE_SUPPORT]
_OPPOSE = [re.compile(entry) for entry in STANCE_OPPOSE]
_MIXED = [re.compile(entry) for entry in STANCE_MIXED]


def stance_from_text(text) -> str:
    """Stance toward the project from phrase patterns. Circles stay out."""
    text = str(text or "").lower()
    support = any(entry.search(text) for entry in _SUPPORT)
    oppose = any(entry.search(text) for entry in _OPPOSE)
    mixed = any(entry.search(text) for entry in _MIXED)
    if mixed or (support and oppose):
        return "mixed"
    if support:
        return "support"
    if oppose:
        return "oppose"
    return "no clear stance"


def apply(posts: list[dict]) -> list[dict]:
    """Writes ``stance`` from the paywall-stripped scoring text. Does not touch the circles."""
    for post in posts:
        post["stance"] = stance_from_text(
            _posts.scoring_text(post.get("title"), post.get("content"))
        )
    return posts


def main() -> None:
    posts = json.loads(POSTS_FILE.read_text(encoding="utf-8"))
    apply(posts)
    POSTS_FILE.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = {}
    for post in posts:
        counts[post["stance"]] = counts.get(post["stance"], 0) + 1
    print(f"Stance: {POSTS_FILE}  n={len(posts)}  {counts}")


if __name__ == "__main__":
    main()
