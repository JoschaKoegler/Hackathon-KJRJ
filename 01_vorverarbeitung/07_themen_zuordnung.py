"""07. Kuratierte Themen-Zuordnung — Regex rund um die Projekterwähnung.

Liest ``00_data/posts.json`` und ``themen/<projekt>.json``.
Schreibt ``00_data/themes.json`` für ``02_laufzeit/kuratierte_themen.py``.

Der Token-Fallback (Präfixe und Claims) steht in ``08_token_fallback.py``.
Ein Beitrag zählt pro Thema höchstens einmal, kann aber mehrere Themen haben.
Gesucht wird nur rund um die Projekterwähnung, nicht im ganzen Artikel.
"""
from __future__ import annotations

import argparse
import html
import importlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT = BASE_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_config = importlib.import_module("02_laufzeit.config")
POSTS_FILE = _config.POSTS_FILE
THEMES_FILE = _config.THEMES_FILE

THEMEN_DIR = BASE_DIR / "themen"
DEFAULT_INPUT = POSTS_FILE

TOPIC_REGEX = r"seilbahn|gondel"
WINDOW = 400               # Zeichen links/rechts einer Seilbahn-Erwähnung
SHORT_POST = 700           # kürzere Beiträge (Kommentare, Posts) werden ganz gelesen
HAUPTTHEMA_MIN = 3         # so oft muss Heilbronn/IPAI im Text stehen, damit alle Seilbahn-Stellen zählen
BELEG_CHARS = 140          # Länge des Belegausschnitts links/rechts vom Treffer
KATEGORIEN = ("themen", "hopes", "fears")


# ------------------------------------------------------------------
# Text vorbereiten
# ------------------------------------------------------------------
def clean(text) -> str:
    text = html.unescape(str(text or ""))
    text = re.sub(r"<br\s*/?>|<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def merge(spans):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def passages(post: dict, kontext_regex: str, topic_regex: str = TOPIC_REGEX) -> list[str]:
    """Textstellen, in denen nach Themen gesucht wird."""
    title = clean(post.get("title"))
    text = f"{title} . {clean(post.get('content'))}"
    low = text.lower()
    if len(low) <= SHORT_POST:
        return [low]

    windows = merge(
        (max(0, m.start() - WINDOW), m.end() + WINDOW) for m in re.finditer(topic_regex, low)
    )
    if not windows:
        return []
    # Heilbronn ist Hauptthema, wenn im Titel genannt oder mindestens HAUPTTHEMA_MIN-mal im Text -> alle
    # Stellen zählen; sonst (z. B. Artikel über Fulda mit Heilbronn als Randvergleich) nur Stellen mit Bezug
    hauptthema = re.search(kontext_regex, title.lower()) or len(re.findall(kontext_regex, low)) >= HAUPTTHEMA_MIN
    stellen = [low[a:b] for a, b in windows]
    if not hauptthema:
        stellen = [s for s in stellen if re.search(kontext_regex, s)]
    return stellen


# ------------------------------------------------------------------
# Zuordnung
# ------------------------------------------------------------------
def first_match(stellen: list[str], muster: list[str]) -> str | None:
    for s in stellen:
        for p in muster:
            m = re.search(p, s)
            if m:
                a, b = max(0, m.start() - BELEG_CHARS), min(len(s), m.end() + BELEG_CHARS)
                return ("…" if a else "") + s[a:b].strip() + ("…" if b < len(s) else "")
    return None


def parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(ts).replace("Z", "+00:00")))
    except ValueError:
        return None


def analysiere(posts: list[dict], regeln: dict) -> list[dict]:
    zuordnungen = []
    kategorien = [(kat, eintrag) for kat in KATEGORIEN for eintrag in regeln[kat]]
    for post in posts:
        ts = parse_ts(post.get("published_at"))
        if ts is None:
            continue
        stellen = passages(post, regeln["kontext_regex"], regeln.get("topic_regex") or TOPIC_REGEX)
        if not stellen:
            continue
        for kat, eintrag in kategorien:
            beleg = first_match(stellen, eintrag["muster"])
            if beleg is None:
                continue
            zuordnungen.append({
                "kategorie": kat[:-1] if kat != "themen" else "thema",   # thema / hope / fear
                "id": eintrag["id"],
                "label": eintrag["label"],
                "mention_id": post.get("mention_id"),
                "published_at": post.get("published_at"),
                "datum": ts.astimezone(timezone.utc).strftime("%Y-%m-%d"),
                "titel": clean(post.get("title"))[:200],
                "url": post.get("url"),
                "medientyp": post.get("media_type_name"),
                "beleg": beleg,
            })
    zuordnungen.sort(key=lambda z: (z["published_at"], z["kategorie"], z["id"]))
    return zuordnungen


def zaehle(zuordnungen: list[dict], von: str | None = None, bis: str | None = None) -> dict:
    """Anzahl Beiträge je Thema/Hope/Fear im Zeitraum [von, bis] (YYYY-MM-DD, beide inklusive)."""
    gefiltert = [z for z in zuordnungen if (not von or z["datum"] >= von) and (not bis or z["datum"] <= bis)]
    ergebnis = {}
    for kat in ("thema", "hope", "fear"):
        c = Counter((z["id"], z["label"]) for z in gefiltert if z["kategorie"] == kat)
        ergebnis[kat] = [{"id": i, "label": l, "anzahl": n} for (i, l), n in c.most_common()]
    return ergebnis


def uebersicht(zuordnungen: list[dict], regeln: dict, kat_key: str, kat_name: str) -> list[dict]:
    per_id = defaultdict(list)
    for z in zuordnungen:
        if z["kategorie"] == kat_name:
            per_id[z["id"]].append(z)
    liste = []
    for eintrag in regeln[kat_key]:
        zs = per_id.get(eintrag["id"], [])
        liste.append({
            "id": eintrag["id"],
            "label": eintrag["label"],
            "beschreibung": eintrag.get("beschreibung", ""),
            "anzahl": len(zs),
            "anzahl_pro_monat": dict(sorted(Counter(z["datum"][:7] for z in zs).items())),
            "erstes_datum": min((z["datum"] for z in zs), default=None),
            "letztes_datum": max((z["datum"] for z in zs), default=None),
        })
    return sorted(liste, key=lambda e: -e["anzahl"])


# ------------------------------------------------------------------
# Hauptprogramm
# ------------------------------------------------------------------
def _bundle_for(project: str, posts: list[dict], regeln: dict, quelle: str) -> dict:
    zuordnungen = analysiere(posts, regeln)
    daten = sorted(z["datum"] for z in zuordnungen)
    mit_treffer = {z["mention_id"] for z in zuordnungen}
    return {
        "meta": {
            "projekt": project,
            "quelle": quelle,
            "erstellt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "beitraege_gesamt": len(posts),
            "beitraege_mit_zuordnung": len(mit_treffer),
            "zeitraum": {"von": daten[0] if daten else None, "bis": daten[-1] if daten else None},
            "topic_regex": regeln.get("topic_regex") or TOPIC_REGEX,
            "kontext_regex": regeln.get("kontext_regex"),
            "zaehlweise": "Anzahl Beiträge; ein Beitrag zählt pro Thema/Hope/Fear höchstens einmal, kann aber mehreren zugeordnet sein",
            "filterhinweis": "Für einen Zeitraum 'zuordnungen' nach 'datum' (YYYY-MM-DD) filtern und je 'kategorie' + 'id' zählen",
        },
        "themen": uebersicht(zuordnungen, regeln, "themen", "thema"),
        "hopes": uebersicht(zuordnungen, regeln, "hopes", "hope"),
        "fears": uebersicht(zuordnungen, regeln, "fears", "fear"),
        "zuordnungen": zuordnungen,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("eingabe", nargs="?", default=str(DEFAULT_INPUT))
    ap.add_argument("--projekt", help="Nur dieses Projekt; sonst alle Dateien in themen/")
    ap.add_argument("--von", help="Zeitraum-Beginn YYYY-MM-DD (nur für die Konsolenausgabe)")
    ap.add_argument("--bis", help="Zeitraum-Ende YYYY-MM-DD (nur für die Konsolenausgabe)")
    args = ap.parse_args()

    regel_dateien = sorted(THEMEN_DIR.glob("*.json"))
    if args.projekt:
        regel_dateien = [THEMEN_DIR / f"{args.projekt}.json"]
    missing = [path for path in regel_dateien if not path.exists()]
    if missing:
        print(f"FEHLER: Keine Themenregeln ({missing[0]}).")
        sys.exit(1)
    if not regel_dateien:
        print(f"FEHLER: Keine Themenregeln in {THEMEN_DIR}.")
        sys.exit(1)

    with open(args.eingabe, "r", encoding="utf-8") as f:
        alle = json.load(f)

    bundle = {}
    if THEMES_FILE.is_file() and args.projekt:
        existing = json.loads(THEMES_FILE.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            bundle = existing

    for regel_datei in regel_dateien:
        project = regel_datei.stem
        with open(regel_datei, "r", encoding="utf-8") as f:
            regeln = json.load(f)
        posts = [p for p in alle if project in (p.get("matched_projects") or [])]
        if not posts:
            print(f"Keine Beiträge für '{project}' in '{args.eingabe}'.")
            continue
        ausgabe = _bundle_for(project, posts, regeln, Path(args.eingabe).name)
        bundle[project] = ausgabe
        meta = ausgabe["meta"]
        print(
            f"{project}: {meta['beitraege_gesamt']} Beiträge, "
            f"{meta['beitraege_mit_zuordnung']} mit Zuordnung, "
            f"{len(ausgabe['zuordnungen'])} Zuordnungen"
        )
        daten = [
            row["datum"] for row in ausgabe["zuordnungen"]
        ]
        zeitraum = f"{args.von or (daten[0] if daten else '?')} bis {args.bis or (daten[-1] if daten else '?')}"
        for kat, rows in zaehle(ausgabe["zuordnungen"], args.von, args.bis).items():
            print(f"  {kat.upper()} ({zeitraum})")
            for r in rows[:5]:
                print(f"    {r['anzahl']:>4}  {r['label']}")

    if not bundle:
        sys.exit(1)
    THEMES_FILE.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nGespeichert: {THEMES_FILE}  →  02_laufzeit/kuratierte_themen.py")


if __name__ == "__main__":
    main()
