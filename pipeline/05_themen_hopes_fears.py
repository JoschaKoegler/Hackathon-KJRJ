"""
Themen sowie Hopes & Fears pro Beitrag – mit Zeitstempel, damit das Dashboard nach Zeitraum filtern kann.

Eingabe: Beiträge im alten Format (clean_data.json bzw. FSI_..._altes_Format.json).
Regeln:  themen/<project_key>.json (Themen, Hopes, Fears als Suchmuster; aus dem Datensatz abgeleitet).
Ausgabe: themen_hopes_fears_<project_key>.json

Aufruf:
  python 05_themen_hopes_fears.py                                   # clean_data.json, Heilbronn_Seilbahn
  python 05_themen_hopes_fears.py daten.json --projekt Heilbronn_Seilbahn
  python 05_themen_hopes_fears.py --von 2026-07-01 --bis 2026-07-31  # Zählung für einen Zeitraum ausgeben

Gezählt wird pro Beitrag: Ein Beitrag zählt für ein Thema höchstens einmal, kann aber mehrere Themen haben.
Gesucht wird nur in Textstellen rund um die Seilbahn-Erwähnungen (nicht im ganzen Artikel), damit
Nachrichtenticker und Sammelartikel keine fremden Themen einbringen. Bei Beiträgen, die Heilbronn nur
am Rand nennen (z. B. Artikel über Fulda), zählen nur Stellen mit Heilbronn-Bezug.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
THEMEN_DIR = BASE_DIR / "themen"
DEFAULT_INPUT = BASE_DIR / "clean_data.json"

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


def passages(post: dict, kontext_regex: str) -> list[str]:
    """Textstellen, in denen nach Themen gesucht wird."""
    title = clean(post.get("title"))
    text = f"{title} . {clean(post.get('content'))}"
    low = text.lower()
    if len(low) <= SHORT_POST:
        return [low]

    windows = merge((max(0, m.start() - WINDOW), m.end() + WINDOW) for m in re.finditer(TOPIC_REGEX, low))
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
        stellen = passages(post, regeln["kontext_regex"])
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
                "sentiment": post.get("sentiment"),
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
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("eingabe", nargs="?", default=str(DEFAULT_INPUT))
    ap.add_argument("--projekt", default="Heilbronn_Seilbahn")
    ap.add_argument("--von", help="Zeitraum-Beginn YYYY-MM-DD (nur für die Konsolenausgabe)")
    ap.add_argument("--bis", help="Zeitraum-Ende YYYY-MM-DD (nur für die Konsolenausgabe)")
    args = ap.parse_args()

    regel_datei = THEMEN_DIR / f"{args.projekt}.json"
    if not regel_datei.exists():
        print(f"FEHLER: Keine Themenregeln für '{args.projekt}' ({regel_datei}).")
        sys.exit(1)
    with open(regel_datei, "r", encoding="utf-8") as f:
        regeln = json.load(f)
    with open(args.eingabe, "r", encoding="utf-8") as f:
        alle = json.load(f)
    posts = [p for p in alle if args.projekt in (p.get("matched_projects") or [])]
    if not posts:
        print(f"Keine Beiträge für '{args.projekt}' in '{args.eingabe}'.")
        sys.exit(1)

    zuordnungen = analysiere(posts, regeln)
    daten = sorted(z["datum"] for z in zuordnungen)
    mit_treffer = {z["mention_id"] for z in zuordnungen}

    ausgabe = {
        "meta": {
            "projekt": args.projekt,
            "quelle": Path(args.eingabe).name,
            "erstellt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "beitraege_gesamt": len(posts),
            "beitraege_mit_zuordnung": len(mit_treffer),
            "zeitraum": {"von": daten[0] if daten else None, "bis": daten[-1] if daten else None},
            "zaehlweise": "Anzahl Beiträge; ein Beitrag zählt pro Thema/Hope/Fear höchstens einmal, kann aber mehreren zugeordnet sein",
            "filterhinweis": "Für einen Zeitraum 'zuordnungen' nach 'datum' (YYYY-MM-DD) filtern und je 'kategorie' + 'id' zählen",
        },
        "themen": uebersicht(zuordnungen, regeln, "themen", "thema"),
        "hopes": uebersicht(zuordnungen, regeln, "hopes", "hope"),
        "fears": uebersicht(zuordnungen, regeln, "fears", "fear"),
        "zuordnungen": zuordnungen,
    }
    ziel = BASE_DIR / f"themen_hopes_fears_{args.projekt}.json"
    with open(ziel, "w", encoding="utf-8") as f:
        json.dump(ausgabe, f, ensure_ascii=False, indent=2)

    print(f"{len(posts)} Beiträge, {len(mit_treffer)} mit Zuordnung, {len(zuordnungen)} Zuordnungen -> {ziel.name}")
    zeitraum = f"{args.von or daten[0]} bis {args.bis or daten[-1]}"
    for kat, rows in zaehle(zuordnungen, args.von, args.bis).items():
        print(f"\n{kat.upper()} ({zeitraum})")
        for r in rows:
            print(f"  {r['anzahl']:>4}  {r['label']}")


if __name__ == "__main__":
    main()
