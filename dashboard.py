#!/usr/bin/env python3
"""Medienstimmen-Dashboard.

Die Datenauswahl steht oben in KONFIGURATION. Dieselben Funktionen
nutzt das Notebook ``notebooks/dashboard_nachvollziehen.ipynb``.

Start im Ordner Hackathon-KJRJ:

    python dashboard.py

Dann im Browser öffnen: http://127.0.0.1:8765
Nach einer Änderung hier das Skript neu starten und die Seite neu laden.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

# ===========================================================================
# KONFIGURATION  <- hier die Auswahl ändern
# ===========================================================================

# Gefilterte Beiträge aus skripte/1_filter_data.py. Fehlt die Datei, zuerst
# ``python skripte/1_filter_data.py`` ausführen.
DATEN_DATEI = Path("daten") / "01_gefiltert" / "clean_data.json"

HOST = "127.0.0.1"
PORT = 8765

# Schalter unter dem Zeitstrahl, von links nach rechts.
# Ein neuer Eintrag erscheint als Button, sobald ein Projekt unten
# auf diese id zeigt.
STAEDTE_BUTTONS = [
    {"id": "Gesamt", "label": "Gesamt", "hinweis": "Alle Projekte"},
    {"id": "Heilbronn", "label": "Heilbronn", "hinweis": "Seilbahn und IPAI-Campus"},
    {"id": "Bonn", "label": "Bonn", "hinweis": "Seilbahn Bonn"},
    {"id": "Paris", "label": "Paris", "hinweis": "Câble C1"},
]

# Genau ein Projekt je Beitrag, so wie matched_projects in clean_data.json.
# IPAI liegt in Heilbronn. Eine eigene Blase entsteht, wenn hier
# "IPAI" steht und oben ein Button mit derselben id ergänzt wird.
STADT_AUS_PROJEKT = {
    "Heilbronn_Seilbahn": "Heilbronn",
    "IPAI_Campus": "Heilbronn",
    "Bonn_Seilbahn": "Bonn",
    "Paris_Cable_C1": "Paris",
}

PROJEKT_LABEL = {
    "Heilbronn_Seilbahn": "Heilbronn Seilbahn",
    "IPAI_Campus": "IPAI Campus",
    "Bonn_Seilbahn": "Bonn Seilbahn",
    "Paris_Cable_C1": "Paris Câble C1",
}

# Rechter Schalter. Der Kanal kommt aus kanal_bestimmen weiter unten,
# dieselbe Regel wie im Notebook aufteilung_sprache_medien.
MEDIEN_BUTTONS = [
    {"id": "Zeitungen", "label": "Zeitungen"},
    {"id": "Social Media", "label": "Social Media"},
]
MEDIEN_AUS_KANAL = {
    "Nachrichten": "Zeitungen",
    "Social Media": "Social Media",
    # "Andere Webquellen" bleibt ohne Schalter und erscheint in keiner der beiden Ansichten.
}

# Drei Kreise.
# "sentiment": Vendor-Feld sentiment. 1 Zustimmung, 0 Neutral, -1 Ablehnung.
#              -99 und leere Werte bleiben außerhalb der Kreise.
# "haltung":   Textmuster weiter unten. dafür / abwägend / dagegen.
#              "keine erkennbare Haltung" bleibt außerhalb der Kreise.
BLASEN_QUELLE = "sentiment"
BLASEN = ["Zustimmung", "Neutral", "Ablehnung"]

# Trendpfeil: Saldo (Zustimmung - Ablehnung) / eingeordnete Beiträge,
# aktuelles Fenster minus das direkt davor liegende Fenster gleicher Länge.
# Unter dieser Schwelle in Prozentpunkten bleibt der Pfeil waagerecht.
TREND_SCHWELLE_PUNKTE = 2.0
# Darunter wird kein Pfeil ausgegeben, das Fenster ist zu dünn.
MIN_TREND_BASIS = 8

# Wortwolke. "beitraege": ein Wort zählt je Beitrag einmal.
# "vorkommen": jedes Auftreten im Text zählt.
WORT_ANZAHL = 10
WORTHAEUFIGKEIT = "beitraege"
TOKEN_ZEICHEN = 400
TEXT_ZEICHEN = 2500

STANDARD_STADT = "Gesamt"
STANDARD_MEDIUM = "Zeitungen"

# ===========================================================================
# Regeln aus dem Notebook: Medium, Haltung, Wörter
# ===========================================================================

FEHLWERT = -99
TONLAGE_LABEL = {1.0: "positiv", 0.0: "neutral", -1.0: "negativ"}

SOCIAL_RELEVANT = frozenset({
    "YouTube", "Instagram", "Facebook", "Mastodon", "Flickr", "Reddit", "LinkedIn", "TikTok", "X",
})
PLATTFORM_DOMAINS = (
    ("YouTube", ("youtube.com", "youtu.be")),
    ("Instagram", ("instagram.com",)),
    ("Facebook", ("facebook.com",)),
    ("Reddit", ("reddit.com",)),
    ("LinkedIn", ("linkedin.com",)),
    ("TikTok", ("tiktok.com",)),
    ("Telegram", ("t.me", "telegram.me", "telegram.org")),
    ("Flickr", ("flickr.com",)),
    ("Pinterest", ("pinterest.com",)),
    ("Tumblr", ("tumblr.com",)),
    ("Bluesky", ("bsky.app",)),
    ("Vimeo", ("vimeo.com",)),
    ("X", ("twitter.com", "x.com")),
)
REGIONAL_HOST_MARKEN = (
    "meinbezirk", "anzeiger", "rundblick", "24hamburg", "bw24", "sauerlandkurier",
    "salzkammergut", "rheingau", "az-online", "krone.at", "kurier.at", "vol.at",
)

OBJEKT = r"(?:seilbahn\w*|t[ée]l[ée]ph[ée]rique\w*|c[âa]ble\s*c\s*1|gondelbahn\w*|stadtseilbahn\w*)"


def _muster(schablone: str) -> str:
    return schablone.replace("{objekt}", OBJEKT).replace("{nah}", r".{0,60}")


HALTUNG_DAFUER = [
    _muster(r"ja zur {objekt}"),
    _muster(r"gr[üu]nes licht f[üu]r (?:die |eine |konkrete )?(?:vorplanung|{objekt})"),
    _muster(r"bef[üu]rwort\w*(?:\s+\w+){0,4}\s+{objekt}"),
    _muster(r"begr[üu][sß]\w*(?:\s+\w+){0,3}\s+(?:die |das )?{objekt}"),
    _muster(r"(?:sieht|sehen)\s+gro[sß]e chancen{nah}{objekt}|{objekt}{nah}(?:sieht|sehen)\s+gro[sß]e chancen"),
    _muster(r"chancen steigen{nah}{objekt}|{objekt}{nah}chancen steigen"),
    r"positiv\w*\s+machbarkeitsstudie",
]
HALTUNG_DAGEGEN = [
    r"luftnummer",
    _muster(r"prestigeprojekt\w*{nah}(?:geld|k[üu]rzung)|k[üu]rzung{nah}prestigeprojekt"),
    _muster(r"\bnein\b.{0,30}zur {objekt}|sagen\s+[\"“„]?nein.{0,40}{objekt}"),
    _muster(r"\bkeine {objekt} (?:über|ueber|in|nach|durch|für|fuer)\b"),
    _muster(r"gegen die (?:geplante )?{objekt}"),
    _muster(r"{objekt}{nah}abgelehnt|abgelehnt{nah}{objekt}"),
    _muster(r"{objekt}{nah}kritisch|kritisch{nah}{objekt}"),
    _muster(r"unsinnig\w*{nah}{objekt}|{objekt}{nah}unsinn"),
    _muster(r"geldverschwend\w*{nah}{objekt}|{objekt}{nah}geldverschwend"),
    _muster(r"s'oppose\w*{nah}{objekt}|{objekt}{nah}s'oppose\w*"),
]
HALTUNG_ABWAEGEND = [
    _muster(r"pro und contra{nah}{objekt}|{objekt}{nah}pro und contra"),
    _muster(r"vor- und nachteile{nah}{objekt}|{objekt}{nah}vor- und nachteile"),
    _muster(r"chancen und risiken{nah}{objekt}|{objekt}{nah}chancen und risiken"),
    _muster(r"gro[sß]e chancen{nah}risiken|warnt vor risiken{nah}{objekt}"),
]
_DAFUER = [re.compile(eintrag) for eintrag in HALTUNG_DAFUER]
_DAGEGEN = [re.compile(eintrag) for eintrag in HALTUNG_DAGEGEN]
_ABWAEGEND = [re.compile(eintrag) for eintrag in HALTUNG_ABWAEGEND]

STOPPWOERTER = {
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
    # Rest der Stimme-Paywall, falls der Schnitt weiter unten etwas stehen lässt.
    "stimme", "testabo", "freischalten", "zugang", "sichern", "merken",
    "abonnement", "anmeldung", "konto", "geräten", "geraeten",
}

# Abo-Hinweis der Heilbronner Stimme steht oft vor dem Artikeltext.
PAYWALL_SCHNITTE = (
    "jetzt den vollen zugang freischalten",
    "artikel merken und auf allen",
    "sie haben kein abonnement",
)

_CACHE: pd.DataFrame | None = None


def host_aus_quelle(quelle) -> str:
    host = str(quelle or "").strip().lower()
    return host[4:] if host.startswith("www.") else host


def host_ist(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def plattform_roh(quelle, medientyp):
    host = host_aus_quelle(quelle)
    for name, domains in PLATTFORM_DOMAINS:
        if any(host_ist(host, domain) for domain in domains):
            return name
    if medientyp == "Microblog":
        return "Mastodon"
    if medientyp in {"YouTube Video", "YouTube Comments"}:
        return "YouTube"
    return None


def plattform_bestimmen(quelle, medientyp):
    name = plattform_roh(quelle, medientyp)
    return name if name in SOCIAL_RELEVANT else None


def kanal_bestimmen(medientyp, plattform, host) -> str:
    if isinstance(plattform, str) and plattform:
        return "Social Media"
    if medientyp == "News" or any(marke in host for marke in REGIONAL_HOST_MARKEN):
        return "Nachrichten"
    return "Andere Webquellen"


def haltung_aus_text(text) -> str:
    """Haltung zum Projekt aus den Textmustern. Die Vendor-Zahl geht hier nicht ein."""
    text = str(text or "").lower()
    dafuer = any(eintrag.search(text) for eintrag in _DAFUER)
    dagegen = any(eintrag.search(text) for eintrag in _DAGEGEN)
    abwaegend = any(eintrag.search(text) for eintrag in _ABWAEGEND)
    if abwaegend or (dafuer and dagegen):
        return "abwägend"
    if dafuer:
        return "dafür"
    if dagegen:
        return "dagegen"
    return "keine erkennbare Haltung"


def vendor_tonlage(wert) -> str:
    zahl = pd.to_numeric(wert, errors="coerce")
    if pd.isna(zahl) or float(zahl) == FEHLWERT:
        return "keine Angabe"
    return TONLAGE_LABEL.get(float(zahl), "keine Angabe")


def blase_aus_sentiment(wert):
    zahl = pd.to_numeric(wert, errors="coerce")
    if pd.isna(zahl) or float(zahl) == FEHLWERT:
        return None
    return {1.0: "Zustimmung", 0.0: "Neutral", -1.0: "Ablehnung"}.get(float(zahl))


def blase_aus_haltung(haltung):
    return {"dafür": "Zustimmung", "abwägend": "Neutral", "dagegen": "Ablehnung"}.get(haltung)


def text_ohne_paywall(text: str) -> str:
    roh = str(text or "")
    tiefer = roh.lower()
    schnitt = len(roh)
    for marke in PAYWALL_SCHNITTE:
        stelle = tiefer.find(marke)
        if stelle != -1:
            schnitt = min(schnitt, stelle)
    return roh[:schnitt].strip()


def tokens(text, limit=TOKEN_ZEICHEN) -> list[str]:
    woerter = re.findall(r"[a-zäöüßàâéèêëîïôùûç]{4,}", str(text or "").lower()[:limit])
    return [wort for wort in woerter if wort not in STOPPWOERTER]


def _projekt_schluessel(wert) -> str:
    if isinstance(wert, list) and wert:
        return str(wert[0])
    if isinstance(wert, str) and wert:
        return wert
    return ""


def lade_beitraege(neu: bool = False) -> pd.DataFrame:
    """Gefilterte Beiträge mit Stadt, Medium, Blase und Wörtern."""
    global _CACHE
    if _CACHE is not None and not neu:
        return _CACHE

    pfad = Path(__file__).resolve().parent / DATEN_DATEI
    if not pfad.is_file():
        raise FileNotFoundError(
            f"{DATEN_DATEI.as_posix()} fehlt. Zuerst im Projektordner ausführen: python skripte/1_filter_data.py"
        )
    with pfad.open(encoding="utf-8") as datei:
        roh = json.load(datei)
    rahmen = pd.DataFrame(roh)
    zeiten = pd.to_datetime(rahmen["published_at"], utc=True, errors="coerce")
    rahmen["datum"] = zeiten.dt.tz_convert(None).dt.normalize()
    rahmen["text"] = (
        rahmen["title"].fillna("").astype(str) + "\n" + rahmen["content"].fillna("").astype(str).map(text_ohne_paywall)
    ).str.slice(0, TEXT_ZEICHEN)
    rahmen["projekt"] = rahmen["matched_projects"].map(_projekt_schluessel)
    rahmen["projekt_label"] = rahmen["projekt"].map(lambda schluessel: PROJEKT_LABEL.get(schluessel, schluessel))
    rahmen["stadt"] = rahmen["projekt"].map(STADT_AUS_PROJEKT)
    rahmen["plattform"] = [
        plattform_bestimmen(quelle, medientyp)
        for quelle, medientyp in zip(rahmen["source_name"], rahmen["media_type_name"])
    ]
    rahmen["kanal"] = [
        kanal_bestimmen(medientyp, plattform, host_aus_quelle(quelle))
        for medientyp, plattform, quelle in zip(
            rahmen["media_type_name"], rahmen["plattform"], rahmen["source_name"]
        )
    ]
    rahmen["medium"] = rahmen["kanal"].map(MEDIEN_AUS_KANAL)
    rahmen["haltung"] = rahmen["text"].map(haltung_aus_text)
    rahmen["vendor_tonlage"] = rahmen["sentiment"].map(vendor_tonlage)
    if BLASEN_QUELLE == "haltung":
        rahmen["blase"] = rahmen["haltung"].map(blase_aus_haltung)
    else:
        rahmen["blase"] = rahmen["sentiment"].map(blase_aus_sentiment)
    rahmen["woerter"] = rahmen["text"].map(tokens)
    rahmen["ausschnitt"] = (
        rahmen["content"].fillna("").astype(str).map(text_ohne_paywall)
        .str.replace(r"\s+", " ", regex=True).str.strip().str.slice(0, 280)
    )
    rahmen = rahmen.dropna(subset=["datum"]).copy()
    _CACHE = rahmen
    return rahmen


def _als_tag(wert) -> pd.Timestamp | None:
    if wert is None or wert == "":
        return None
    zeit = pd.to_datetime(wert, errors="coerce")
    if pd.isna(zeit):
        return None
    zeit = pd.Timestamp(zeit)
    if zeit.tzinfo is not None:
        zeit = zeit.tz_convert(None)
    return zeit.normalize()


def _iso(zeit) -> str:
    return pd.Timestamp(zeit).strftime("%Y-%m-%d")


def spanne(rahmen: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    return rahmen["datum"].min(), rahmen["datum"].max()


def filtere(
    rahmen: pd.DataFrame,
    stadt: str | None = None,
    medium: str | None = None,
    von=None,
    bis=None,
) -> pd.DataFrame:
    """Stadt, Medium und Zeitraum. None lässt den jeweiligen Schnitt weg."""
    teile = rahmen
    if stadt and stadt != "Gesamt":
        teile = teile[teile["stadt"].eq(stadt)]
    if medium:
        teile = teile[teile["medium"].eq(medium)]
    start = _als_tag(von)
    ende = _als_tag(bis)
    if start is not None:
        teile = teile[teile["datum"] >= start]
    if ende is not None:
        teile = teile[teile["datum"] <= ende]
    return teile


def vorheriges_fenster(von: pd.Timestamp, bis: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Gleich langes Fenster, das am Tag vor ``von`` endet."""
    tage = (bis - von).days + 1
    vorher_bis = von - pd.Timedelta(days=1)
    vorher_von = vorher_bis - pd.Timedelta(days=tage - 1)
    return vorher_von, vorher_bis


def tagesreihe(rahmen: pd.DataFrame, start, ende) -> list[dict]:
    index = pd.date_range(start, ende, freq="D")
    if rahmen.empty:
        zaehlung = pd.Series(0, index=index)
    else:
        zaehlung = rahmen.groupby("datum").size().reindex(index, fill_value=0)
    return [{"datum": _iso(tag), "anzahl": int(wert)} for tag, wert in zaehlung.items()]


def blasen_zaehlen(rahmen: pd.DataFrame) -> dict:
    zaehlung = {name: int(rahmen["blase"].eq(name).sum()) for name in BLASEN}
    eingeordnet = sum(zaehlung.values())
    anteile = {
        name: (round(zaehlung[name] / eingeordnet, 4) if eingeordnet else 0.0)
        for name in BLASEN
    }
    return {
        "anzahl": zaehlung,
        "anteil": anteile,
        "eingeordnet": eingeordnet,
        "ohne_blase": int(rahmen["blase"].isna().sum()),
    }


def _saldo(blasen: dict) -> float | None:
    n = blasen["eingeordnet"]
    if not n:
        return None
    return (blasen["anzahl"]["Zustimmung"] - blasen["anzahl"]["Ablehnung"]) / n


def trend(
    aktuell: pd.DataFrame,
    vorher: pd.DataFrame,
    von,
    bis,
    vorher_von,
    vorher_bis,
    daten_start,
    daten_ende,
) -> dict:
    """Pfeil aus dem Saldo gegenüber dem vorherigen, gleich langen Zeitraum."""
    jetzt = blasen_zaehlen(aktuell)
    zuvor = blasen_zaehlen(vorher)
    saldo_jetzt = _saldo(jetzt)
    saldo_zuvor = _saldo(zuvor)
    grundlage = {
        "von": _iso(von),
        "bis": _iso(bis),
        "vorher_von": _iso(vorher_von),
        "vorher_bis": _iso(vorher_bis),
        "basis_jetzt": jetzt["eingeordnet"],
        "basis_vorher": zuvor["eingeordnet"],
        "saldo_jetzt": None if saldo_jetzt is None else round(saldo_jetzt, 4),
        "saldo_vorher": None if saldo_zuvor is None else round(saldo_zuvor, 4),
    }
    if vorher_bis < daten_start or vorher_von < daten_start or vorher_von > daten_ende:
        return {
            **grundlage,
            "richtung": "unklar",
            "delta_punkte": None,
            "satz": "Der vorherige Zeitraum gleicher Länge liegt vor dem ersten Beitrag dieser Auswahl.",
        }
    if (
        saldo_jetzt is None
        or saldo_zuvor is None
        or jetzt["eingeordnet"] < MIN_TREND_BASIS
        or zuvor["eingeordnet"] < MIN_TREND_BASIS
    ):
        return {
            **grundlage,
            "richtung": "unklar",
            "delta_punkte": None,
            "satz": "Zu wenig eingeordnete Beiträge für einen Vergleich mit dem vorherigen Zeitraum.",
        }
    delta = (saldo_jetzt - saldo_zuvor) * 100
    if delta > TREND_SCHWELLE_PUNKTE:
        richtung = "hoch"
        bewegung = "gestiegen"
    elif delta < -TREND_SCHWELLE_PUNKTE:
        richtung = "runter"
        bewegung = "gesunken"
    else:
        richtung = "gleich"
        bewegung = "nahezu unverändert"
    punkte = f"{delta:+.1f}".replace(".", ",")
    return {
        **grundlage,
        "richtung": richtung,
        "delta_punkte": round(delta, 1),
        "satz": (
            f"Saldo aus Zustimmung und Ablehnung ist {bewegung} ({punkte} Punkte) "
            f"gegenüber {pd.Timestamp(vorher_von).strftime('%d.%m.%Y')} "
            f"bis {pd.Timestamp(vorher_bis).strftime('%d.%m.%Y')}."
        ),
    }


def haeufigste_woerter(rahmen: pd.DataFrame, n: int = WORT_ANZAHL) -> list[dict]:
    zaehler: Counter = Counter()
    for wortliste in rahmen["woerter"]:
        if WORTHAEUFIGKEIT == "vorkommen":
            zaehler.update(wortliste)
        else:
            zaehler.update(set(wortliste))
    return [{"wort": wort, "anzahl": int(zahl)} for wort, zahl in zaehler.most_common(n)]


def beitraege_liste(rahmen: pd.DataFrame) -> list[dict]:
    sicht = rahmen.sort_values("datum", ascending=False)
    zeilen = []
    for zeile in sicht.itertuples(index=False):
        zeilen.append({
            "datum": _iso(zeile.datum),
            "titel": str(zeile.title or "").strip() or "(ohne Titel)",
            "quelle": str(zeile.source_name or ""),
            "url": str(zeile.url or ""),
            "blase": zeile.blase,
            "haltung": zeile.haltung,
            "vendor_tonlage": zeile.vendor_tonlage,
            "stadt": zeile.stadt or "",
            "medium": zeile.medium or "",
            "projekt": zeile.projekt_label or "",
            "ausschnitt": str(zeile.ausschnitt or "").strip(),
        })
    return zeilen


def _klemme(von, bis, start, ende):
    von = start if von is None else max(von, start)
    bis = ende if bis is None else min(bis, ende)
    if von > bis:
        return start, ende
    return von, bis


def auswertung(
    stadt: str = STANDARD_STADT,
    medium: str = STANDARD_MEDIUM,
    von=None,
    bis=None,
    rahmen: pd.DataFrame | None = None,
) -> dict:
    """Alles, was die Oberfläche für eine Schalterstellung zeichnet."""
    rahmen = lade_beitraege() if rahmen is None else rahmen
    gueltige_staedte = {eintrag["id"] for eintrag in STAEDTE_BUTTONS}
    gueltige_medien = {eintrag["id"] for eintrag in MEDIEN_BUTTONS}
    if stadt not in gueltige_staedte:
        stadt = STANDARD_STADT
    if medium not in gueltige_medien:
        medium = STANDARD_MEDIUM

    grundlage = filtere(rahmen, stadt=stadt, medium=medium)
    if grundlage.empty:
        start, ende = spanne(rahmen)
    else:
        start, ende = spanne(grundlage)
    fenster_von, fenster_bis = _klemme(_als_tag(von), _als_tag(bis), start, ende)
    ausschnitt = filtere(grundlage, von=fenster_von, bis=fenster_bis)
    vorher_von, vorher_bis = vorheriges_fenster(fenster_von, fenster_bis)
    vorher = filtere(grundlage, von=vorher_von, bis=vorher_bis)
    blasen = blasen_zaehlen(ausschnitt)
    return {
        "stadt": stadt,
        "medium": medium,
        "blasen_quelle": BLASEN_QUELLE,
        "von": _iso(fenster_von),
        "bis": _iso(fenster_bis),
        "start": _iso(start),
        "ende": _iso(ende),
        "zeitstrahl": tagesreihe(grundlage, start, ende),
        "blasen": blasen,
        "trend": trend(
            ausschnitt, vorher, fenster_von, fenster_bis, vorher_von, vorher_bis, start, ende
        ),
        "datenpunkte": int(len(ausschnitt)),
        "woerter": haeufigste_woerter(ausschnitt),
        "staedte": STAEDTE_BUTTONS,
        "medien": MEDIEN_BUTTONS,
    }


def ueberblick(rahmen: pd.DataFrame | None = None) -> pd.DataFrame:
    """Kleine Tabelle fürs Notebook: Stadt, Medium, Blase."""
    rahmen = lade_beitraege() if rahmen is None else rahmen
    return (
        rahmen.groupby(["stadt", "medium", "blase"], dropna=False)
        .size()
        .rename("beitraege")
        .reset_index()
        .sort_values(["stadt", "medium", "beitraege"], ascending=[True, True, False])
    )


# ===========================================================================
# Oberfläche
# ===========================================================================

SEITE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Medienstimmen</title>
<style>
  :root {
    --papier: #f3efe6;
    --karte: #fbf8f2;
    --tinte: #1e1a16;
    --leise: #6f675e;
    --linie: #e3d9c8;
    --zustimmung: #1c7a4d;
    --neutral: #e7e1d6;
    --neutral-tinte: #3f3a34;
    --ablehnung: #a33b2b;
    --schatten: 0 10px 30px rgba(48, 36, 18, 0.06);
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; overflow: hidden; }
  body {
    background: var(--papier);
    color: var(--tinte);
    font-family: "Avenir Next", "Segoe UI", sans-serif;
  }
  button, input { font: inherit; color: inherit; }
  .seite {
    height: 100%;
    min-height: 0;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 200px 188px;
    grid-template-rows: auto minmax(180px, 1fr) minmax(200px, 2fr);
    align-content: stretch;
    grid-template-areas:
      "kopf kopf kopf"
      "buehne trend zahl"
      "zeit zeit zeit";
    gap: 12px;
    padding: 12px;
    overflow: auto;
  }
  header {
    grid-area: kopf;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
  }
  .marke { text-align: right; }
  .marke strong {
    display: block;
    font-family: Palatino, "Palatino Linotype", Georgia, serif;
    font-size: 22px;
    font-weight: 600;
    letter-spacing: -0.02em;
  }
  .marke span { color: var(--leise); font-size: 13px; }
  .segment, .staedte, .medien {
    display: flex;
    gap: 6px;
    background: transparent;
  }
  .segment button, .staedte button, .medien button, .zahl-karte {
    border: 1px solid var(--linie);
    background: var(--karte);
    border-radius: 999px;
    padding: 8px 14px;
    cursor: pointer;
  }
  .segment button.aktiv, .staedte button.aktiv, .medien button.aktiv {
    background: var(--tinte);
    color: #f7f3ea;
    border-color: var(--tinte);
  }
  .staedte button, .medien button {
    padding: 4px 9px;
    font-size: 13px;
  }
  .buehne, .trend-karte, .zahl-karte, .zeit-karte {
    background: var(--karte);
    border: 1px solid var(--linie);
    border-radius: 18px;
    box-shadow: var(--schatten);
  }
  .buehne {
    grid-area: buehne;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 18px 12px 28px;
    min-height: 0;
    height: 100%;
  }
  .kreise {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    width: 100%;
    max-width: 100%;
    height: 100%;
  }
  .kreis {
    border-radius: 50%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    line-height: 1.15;
    flex: 0 0 auto;
  }
  .kreis.Zustimmung { background: var(--zustimmung); color: #f4fff8; }
  .kreis.Neutral { background: var(--neutral); color: var(--neutral-tinte); border: 1px solid #d9d0c2; }
  .kreis.Ablehnung { background: var(--ablehnung); color: #fff6f3; }
  .kreis strong { font-family: Palatino, Georgia, serif; font-size: 28px; font-weight: 600; }
  .kreis span { font-size: 13px; letter-spacing: 0.02em; margin-top: 2px; }
  .kreis em { font-style: normal; font-size: 12px; opacity: 0.8; margin-top: 4px; }
  .kreis-fuss {
    position: absolute;
    left: 22px; right: 22px; bottom: 12px;
    color: var(--leise);
    font-size: 12px;
    text-align: center;
  }
  .buehne { position: relative; }
  .wolke {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 10px 16px;
    align-content: center;
    width: min(760px, 100%);
    padding-bottom: 18px;
  }
  .wolke b {
    font-family: Palatino, Georgia, serif;
    font-weight: 600;
    line-height: 1;
    color: var(--tinte);
  }
  .wolke b small {
    font-family: "Avenir Next", "Segoe UI", sans-serif;
    font-weight: 500;
    font-size: 12px;
    color: var(--leise);
    margin-left: 5px;
  }
  .trend-karte, .zahl-karte {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 16px 14px;
  }
  .trend-karte { grid-area: trend; }
  .zahl-karte { grid-area: zahl; width: 100%; }
  .pfeil { width: 72px; height: 72px; }
  .pfeil.hoch { color: var(--zustimmung); }
  .pfeil.runter { color: var(--ablehnung); }
  .pfeil.gleich, .pfeil.unklar { color: var(--leise); }
  .trend-karte p, .zahl-hinweis, .leer {
    color: var(--leise);
    font-size: 12.5px;
    line-height: 1.4;
    margin: 8px 0 0;
  }
  .trend-karte strong { font-size: 15px; }
  .zahl-karte strong {
    font-family: Palatino, Georgia, serif;
    font-size: 64px;
    font-weight: 600;
    letter-spacing: -0.04em;
    line-height: 0.9;
  }
  .zahl-label { margin-top: 8px; font-size: 14px; }
  .zahl-karte:hover { border-color: var(--tinte); }
  .zeit-karte {
    grid-area: zeit;
    padding: 10px 14px 8px;
    min-width: 0;
    min-height: 0;
    height: 100%;
    display: flex;
    flex-direction: column;
  }
  .zeit-kopf, .zeit-fuss {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    color: var(--leise);
    font-size: 12px;
  }
  .zeit-kopf { flex-wrap: wrap; }
  .legende {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    align-items: center;
    gap: 4px 8px;
    margin-left: auto;
  }
  svg.chart { width: 100%; flex: 1 1 auto; height: auto; min-height: 0; display: block; }
  .doppel { position: relative; height: 22px; margin-top: 2px; }
  .doppel .spur {
    position: absolute;
    left: 0; right: 0; top: 9px;
    height: 4px;
    border-radius: 99px;
    background: #e6dfd2;
  }
  .doppel input[type="range"] {
    position: absolute;
    left: 0; width: 100%;
    top: 0;
    margin: 0;
    background: none;
    pointer-events: none;
    appearance: none;
    -webkit-appearance: none;
    height: 22px;
  }
  .doppel input[type="range"]::-webkit-slider-runnable-track {
    height: 4px; background: transparent;
  }
  .doppel input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    pointer-events: auto;
    width: 16px; height: 16px;
    margin-top: -6px;
    border-radius: 50%;
    background: var(--tinte);
    border: 2px solid #fbf8f2;
    cursor: grab;
  }
  .doppel input[type="range"]::-moz-range-track {
    height: 4px; background: transparent; border: none;
  }
  .doppel input[type="range"]::-moz-range-thumb {
    pointer-events: auto;
    width: 16px; height: 16px;
    border-radius: 50%;
    background: var(--tinte);
    border: 2px solid #fbf8f2;
    cursor: grab;
  }
  .staedte, .medien {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 4px;
    padding: 0;
    background: none;
    border: 0;
    box-shadow: none;
  }
  .medien {
    padding-left: 8px;
    border-left: 1px solid var(--linie);
  }
  .overlay[hidden] { display: none; }
  .overlay {
    position: fixed;
    inset: 0;
    background: rgba(30, 26, 22, 0.28);
    display: flex;
    justify-content: flex-end;
    z-index: 5;
  }
  .blatt {
    width: min(520px, 100%);
    height: 100%;
    background: var(--karte);
    border-left: 1px solid var(--linie);
    display: flex;
    flex-direction: column;
  }
  .blatt header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
    padding: 16px 16px 10px;
    border-bottom: 1px solid var(--linie);
  }
  .blatt header p { margin: 4px 0 0; color: var(--leise); font-size: 13px; }
  .blatt header button {
    border: 1px solid var(--linie);
    background: transparent;
    border-radius: 999px;
    padding: 6px 12px;
    cursor: pointer;
  }
  .liste { list-style: none; margin: 0; padding: 0; overflow: auto; }
  .liste li {
    padding: 12px 16px 14px;
    border-bottom: 1px solid var(--linie);
  }
  .liste .meta { color: var(--leise); font-size: 12px; }
  .liste h3 { margin: 4px 0; font-size: 16px; font-weight: 600; line-height: 1.3; }
  .liste a { color: inherit; }
  .liste .snippet { margin: 0; color: #3c362f; font-size: 13.5px; line-height: 1.4; }
  .plakette {
    display: inline-block;
    border-radius: 999px;
    padding: 1px 8px;
    font-size: 11px;
    margin-right: 6px;
  }
  .plakette.Zustimmung { background: #e5f5ec; color: var(--zustimmung); }
  .plakette.Neutral { background: #ece7dc; color: var(--neutral-tinte); }
  .plakette.Ablehnung { background: #fde8e4; color: var(--ablehnung); }
  .plakette.offen { background: #f3efe6; color: var(--leise); }
  @media (max-width: 980px) {
    .seite {
      grid-template-columns: 1fr 1fr;
      grid-template-areas:
        "kopf kopf"
        "buehne buehne"
        "trend zahl"
        "zeit zeit";
      align-content: stretch;
      height: 100%;
      grid-template-rows: auto minmax(150px, 1fr) auto minmax(200px, 2fr);
    }
    .buehne { min-height: 0; }
  }
</style>
</head>
<body>
<div class="seite">
  <header>
    <div class="segment" id="ansicht">
      <button type="button" data-ansicht="blasen" class="aktiv">Haltung</button>
      <button type="button" data-ansicht="wolke">Wortwolke</button>
    </div>
    <div class="marke">
      <strong>Medienstimmen</strong>
      <span id="untertitel">Zeitstrahl, Städte, Zeitungen und Social Media</span>
    </div>
  </header>
  <section class="buehne" id="buehne"></section>
  <section class="trend-karte" id="trend"></section>
  <button class="zahl-karte" id="zahl-karte" type="button">
    <strong id="zahl">–</strong>
    <span class="zahl-label">Datenpunkte</span>
    <span class="zahl-hinweis">Beiträge dieser Auswahl anzeigen</span>
  </button>
  <section class="zeit-karte">
    <div class="zeit-kopf">
      <span>Zeitstrahl</span>
      <div class="legende">
        <div class="staedte" id="staedte"></div>
        <div class="medien" id="medien"></div>
      </div>
      <span id="zeit-spanne"></span>
    </div>
    <svg class="chart" id="chart" role="img" aria-label="Beiträge pro Tag"></svg>
    <div class="doppel">
      <div class="spur" id="spur"></div>
      <input id="von" type="range" min="0" max="1" value="0" aria-label="Beginn des Zeitraums">
      <input id="bis" type="range" min="0" max="1" value="1" aria-label="Ende des Zeitraums">
    </div>
    <div class="zeit-fuss"><span id="von-label"></span><span id="bis-label"></span></div>
  </section>
</div>
<div class="overlay" id="overlay" hidden>
  <div class="blatt">
    <header>
      <div>
        <strong id="liste-titel">Datenpunkte</strong>
        <p id="liste-text"></p>
      </div>
      <button type="button" id="schliessen">Schließen</button>
    </header>
    <ul class="liste" id="liste"></ul>
  </div>
</div>
<script>
const ansichtEl = document.getElementById("ansicht");
const buehne = document.getElementById("buehne");
const trendEl = document.getElementById("trend");
const zahlEl = document.getElementById("zahl");
const staedteEl = document.getElementById("staedte");
const medienEl = document.getElementById("medien");
const chart = document.getElementById("chart");
const vonInput = document.getElementById("von");
const bisInput = document.getElementById("bis");
const spur = document.getElementById("spur");
const overlay = document.getElementById("overlay");
const liste = document.getElementById("liste");

const zustand = {
  ansicht: "blasen",
  stadt: "Gesamt",
  medium: "Zeitungen",
  von: null,
  bis: null,
  serie: [],
  letzter: null,
  ziehen: null,
};

function esc(wert) {
  return String(wert ?? "").replace(/[&<>"']/g, (zeichen) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[zeichen]);
}
function datumKurz(iso) {
  const monate = ["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"];
  const [jahr, monat, tag] = iso.split("-");
  return Number(tag) + ". " + monate[Number(monat) - 1] + " " + jahr;
}
function prozent(anteil) {
  return Math.round(anteil * 100) + " %";
}
function sichereUrl(url) {
  try {
    const ziel = new URL(url);
    if (ziel.protocol === "http:" || ziel.protocol === "https:") return ziel.href;
  } catch (fehler) {}
  return "";
}

function parameter() {
  const suche = new URLSearchParams();
  suche.set("stadt", zustand.stadt);
  suche.set("medium", zustand.medium);
  if (zustand.von) suche.set("von", zustand.von);
  if (zustand.bis) suche.set("bis", zustand.bis);
  return suche;
}

function schalter(eltern, eintraege, schluessel) {
  eltern.innerHTML = "";
  eintraege.forEach((eintrag) => {
    const knopf = document.createElement("button");
    knopf.type = "button";
    knopf.textContent = eintrag.label;
    if (eintrag.hinweis) knopf.title = eintrag.hinweis;
    knopf.classList.toggle("aktiv", zustand[schluessel] === eintrag.id);
    knopf.addEventListener("click", () => {
      zustand[schluessel] = eintrag.id;
      zustand.von = null;
      zustand.bis = null;
      laden();
    });
    eltern.appendChild(knopf);
  });
}

function pfeil(richtung) {
  const strecke = {
    hoch: "M32 50 V16 M18 30 L32 14 L46 30",
    runter: "M32 14 V48 M18 34 L32 50 L46 34",
    gleich: "M12 32 H48 M36 20 L50 32 L36 44",
    unklar: "M18 32 H46",
  }[richtung] || "M18 32 H46";
  return `<svg class="pfeil ${richtung}" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="${strecke}"/></svg>`;
}

function zeichneKreise(daten) {
  const anzahl = daten.blasen.anzahl;
  const maximum = Math.max(...Object.values(anzahl), 1);
  const abstand = 16;
  const innenBreite = Math.max((buehne.clientWidth || 360) - 40, 180);
  const innenHoehe = Math.max((buehne.clientHeight || 200) - 56, 72);
  const roh = BLASEN_REIHENFOLGE.map((name) => 96 + Math.sqrt(anzahl[name] / maximum) * 110);
  const summe = roh.reduce((summe, wert) => summe + wert, 0) + abstand * (roh.length - 1);
  const faktor = Math.min(1, innenBreite / summe, innenHoehe / Math.max(...roh));
  const knoten = BLASEN_REIHENFOLGE.map((name, index) => {
    const groesse = Math.max(64, Math.round(roh[index] * faktor));
    const schrift = groesse < 100 ? 15 : groesse < 150 ? 22 : 28;
    const label = groesse < 100 ? 10 : 13;
    return `<div class="kreis ${name}" style="width:${groesse}px;height:${groesse}px">
      <strong style="font-size:${schrift}px">${prozent(daten.blasen.anteil[name])}</strong>
      <span style="font-size:${label}px">${name}</span>
      <em>${anzahl[name]}</em>
    </div>`;
  }).join("");
  const fuss = daten.blasen.ohne_blase
    ? `${daten.blasen.ohne_blase} Beiträge ohne Tonlage zählen bei den Datenpunkten mit, in den Kreisen fehlen sie.`
    : "Anteile der eingeordneten Beiträge im gewählten Zeitraum.";
  buehne.innerHTML = `<div class="kreise">${knoten}</div><div class="kreis-fuss">${fuss}</div>`;
}

const BLASEN_REIHENFOLGE = ["Zustimmung", "Neutral", "Ablehnung"];

function zeichneWolke(woerter) {
  if (!woerter.length) {
    buehne.innerHTML = `<p class="leer">Im gewählten Ausschnitt liegen keine Begriffe.</p>`;
    return;
  }
  const maximum = woerter[0].anzahl || 1;
  const knoten = woerter.map((eintrag) => {
    const groesse = 16 + (eintrag.anzahl / maximum) * 38;
    return `<b style="font-size:${groesse}px">${esc(eintrag.wort)}<small>${eintrag.anzahl}</small></b>`;
  }).join("");
  buehne.innerHTML = `<div class="wolke">${knoten}</div>`;
}

function zeichneTrend(trend) {
  const delta = trend.delta_punkte == null ? "" : `<strong>${String(trend.delta_punkte).replace(".", ",")} Punkte</strong>`;
  trendEl.innerHTML = `${pfeil(trend.richtung)}${delta}<p>${esc(trend.satz)}</p>`;
}

function indexBei(iso) {
  const stelle = zustand.serie.findIndex((punkt) => punkt.datum === iso);
  return stelle < 0 ? 0 : stelle;
}

function zeichneChart() {
  const serie = zustand.serie;
  const breite = Math.max(chart.clientWidth, 280);
  const hoehe = Math.max(chart.clientHeight || 78, 48);
  chart.setAttribute("viewBox", `0 0 ${breite} ${hoehe}`);
  if (!serie.length) {
    chart.innerHTML = "";
    return;
  }
  const maximum = Math.max(...serie.map((punkt) => punkt.anzahl), 1);
  const schritt = serie.length === 1 ? 0 : breite / (serie.length - 1);
  const vonIndex = indexBei(zustand.von);
  const bisIndex = indexBei(zustand.bis);
  const links = Math.min(vonIndex, bisIndex);
  const rechts = Math.max(vonIndex, bisIndex);
  const punkte = serie.map((punkt, index) => {
    const x = index * schritt;
    const y = hoehe - 8 - (punkt.anzahl / maximum) * (hoehe - 16);
    return [x, y];
  });
  const linie = punkte.map((punkt, index) => `${index ? "L" : "M"}${punkt[0].toFixed(1)},${punkt[1].toFixed(1)}`).join(" ");
  const flaeche = `${linie} L${breite},${hoehe} L0,${hoehe} Z`;
  const x0 = punkte[links][0];
  const x1 = punkte[rechts][0];
  chart.innerHTML = `
    <path d="${flaeche}" fill="#1e1a16" opacity="0.08"></path>
    <path d="${linie}" fill="none" stroke="#1e1a16" stroke-width="1.4"></path>
    <rect x="0" y="0" width="${x0}" height="${hoehe}" fill="#fbf8f2" opacity="0.62"></rect>
    <rect x="${x1}" y="0" width="${Math.max(breite - x1, 0)}" height="${hoehe}" fill="#fbf8f2" opacity="0.62"></rect>
  `;
}

function schieberZeichnen() {
  const max = Math.max(zustand.serie.length - 1, 1);
  vonInput.max = String(max);
  bisInput.max = String(max);
  const von = indexBei(zustand.von);
  const bis = indexBei(zustand.bis);
  vonInput.value = String(von);
  bisInput.value = String(bis);
  const links = Math.min(von, bis) / max * 100;
  const rechts = Math.max(von, bis) / max * 100;
  spur.style.background = `linear-gradient(90deg, #e6dfd2 ${links}%, #1e1a16 ${links}%, #1e1a16 ${rechts}%, #e6dfd2 ${rechts}%)`;
  document.getElementById("von-label").textContent = datumKurz(zustand.von);
  document.getElementById("bis-label").textContent = datumKurz(zustand.bis);
  const gewaehlt = Math.abs(bis - von) + 1;
  document.getElementById("zeit-spanne").textContent = gewaehlt === 1 ? "1 Tag ausgewählt" : gewaehlt + " Tage ausgewählt";
}

function zeichne(daten) {
  zustand.letzter = daten;
  zustand.serie = daten.zeitstrahl;
  zustand.von = daten.von;
  zustand.bis = daten.bis;
  schalter(staedteEl, daten.staedte, "stadt");
  schalter(medienEl, daten.medien, "medium");
  if (zustand.ansicht === "wolke") zeichneWolke(daten.woerter);
  else zeichneKreise(daten);
  zeichneTrend(daten.trend);
  zahlEl.textContent = String(daten.datenpunkte);
  zeichneChart();
  schieberZeichnen();
  requestAnimationFrame(zeichneChart);
}

let lauf = 0;
async function laden() {
  const nummer = ++lauf;
  const antwort = await fetch("/api/auswertung?" + parameter());
  const daten = await antwort.json();
  if (nummer !== lauf) return;
  zeichne(daten);
}

let warte = 0;
function schieberLos() {
  if (!zustand.serie.length) return;
  const max = Math.max(zustand.serie.length - 1, 0);
  let von = Number(vonInput.value);
  let bis = Number(bisInput.value);
  if (von > bis) [von, bis] = [bis, von];
  von = Math.max(0, Math.min(max, von));
  bis = Math.max(0, Math.min(max, bis));
  zustand.von = zustand.serie[von].datum;
  zustand.bis = zustand.serie[bis].datum;
  schieberZeichnen();
  zeichneChart();
  window.clearTimeout(warte);
  warte = window.setTimeout(laden, 90);
}

vonInput.addEventListener("input", schieberLos);
bisInput.addEventListener("input", schieberLos);

function indexAusMaus(ereignis) {
  const kasten = chart.getBoundingClientRect();
  const x = Math.min(Math.max(ereignis.clientX - kasten.left, 0), kasten.width || 1);
  const max = Math.max(zustand.serie.length - 1, 1);
  return Math.round(x / (kasten.width || 1) * max);
}
chart.style.cursor = "ew-resize";
chart.addEventListener("pointerdown", (ereignis) => {
  if (!zustand.serie.length) return;
  chart.setPointerCapture(ereignis.pointerId);
  zustand.ziehen = indexAusMaus(ereignis);
  vonInput.value = String(zustand.ziehen);
  bisInput.value = String(zustand.ziehen);
  schieberLos();
});
chart.addEventListener("pointermove", (ereignis) => {
  if (zustand.ziehen == null) return;
  const ziel = indexAusMaus(ereignis);
  vonInput.value = String(Math.min(zustand.ziehen, ziel));
  bisInput.value = String(Math.max(zustand.ziehen, ziel));
  schieberLos();
});
function ziehenEnde() { zustand.ziehen = null; }
chart.addEventListener("pointerup", ziehenEnde);
chart.addEventListener("pointercancel", ziehenEnde);
window.addEventListener("resize", () => {
  if (!zustand.letzter) return;
  if (zustand.ansicht === "wolke") zeichneWolke(zustand.letzter.woerter);
  else zeichneKreise(zustand.letzter);
  if (zustand.serie.length) zeichneChart();
});

ansichtEl.addEventListener("click", (ereignis) => {
  const knopf = ereignis.target.closest("button");
  if (!knopf) return;
  zustand.ansicht = knopf.dataset.ansicht;
  [...ansichtEl.children].forEach((eintrag) => eintrag.classList.toggle("aktiv", eintrag === knopf));
  if (zustand.letzter) {
    if (zustand.ansicht === "wolke") zeichneWolke(zustand.letzter.woerter);
    else zeichneKreise(zustand.letzter);
  }
});

function plakette(name) {
  const klasse = name || "offen";
  const text = name || "ohne Einordnung";
  return `<span class="plakette ${klasse}">${esc(text)}</span>`;
}

document.getElementById("zahl-karte").addEventListener("click", async () => {
  overlay.hidden = false;
  liste.innerHTML = `<li class="meta">Beiträge werden geladen …</li>`;
  const antwort = await fetch("/api/beitraege?" + parameter());
  const daten = await antwort.json();
  document.getElementById("liste-titel").textContent = daten.datenpunkte + " Datenpunkte";
  document.getElementById("liste-text").textContent =
    daten.stadt + " · " + daten.medium + " · " + datumKurz(daten.von) + " – " + datumKurz(daten.bis);
  if (!daten.beitraege.length) {
    liste.innerHTML = `<li>Keine Beiträge in diesem Ausschnitt.</li>`;
    return;
  }
  liste.innerHTML = daten.beitraege.map((beitrag) => {
    const url = sichereUrl(beitrag.url);
    const titel = url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(beitrag.titel)}</a>` : esc(beitrag.titel);
    return `<li>
      <div class="meta">${datumKurz(beitrag.datum)} · ${esc(beitrag.projekt)} · ${esc(beitrag.medium)}</div>
      <h3>${titel}</h3>
      <div class="meta">${plakette(beitrag.blase)} ${esc(beitrag.quelle)} · Tonlage ${esc(beitrag.vendor_tonlage)} · Haltung im Text: ${esc(beitrag.haltung)}</div>
      <p class="snippet">${esc(beitrag.ausschnitt)}</p>
    </li>`;
  }).join("");
});

document.getElementById("schliessen").addEventListener("click", () => { overlay.hidden = true; });
overlay.addEventListener("click", (ereignis) => {
  if (ereignis.target === overlay) overlay.hidden = true;
});
document.addEventListener("keydown", (ereignis) => {
  if (ereignis.key === "Escape") overlay.hidden = true;
});

laden();
</script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _sende(self, inhalt: bytes, typ: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(inhalt)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(inhalt)

    def _json(self, nutzlast, status: int = 200):
        roh = json.dumps(nutzlast, ensure_ascii=False).encode("utf-8")
        self._sende(roh, "application/json; charset=utf-8", status)

    def do_GET(self):
        adresse = urlparse(self.path)
        if adresse.path == "/":
            self._sende(SEITE.encode("utf-8"), "text/html; charset=utf-8")
            return
        frage = parse_qs(adresse.query)
        stadt = (frage.get("stadt") or [STANDARD_STADT])[0]
        medium = (frage.get("medium") or [STANDARD_MEDIUM])[0]
        von = (frage.get("von") or [None])[0]
        bis = (frage.get("bis") or [None])[0]
        try:
            if adresse.path == "/api/auswertung":
                self._json(auswertung(stadt, medium, von, bis))
                return
            if adresse.path == "/api/beitraege":
                paket = auswertung(stadt, medium, von, bis)
                rahmen = lade_beitraege()
                ausschnitt = filtere(rahmen, paket["stadt"], paket["medium"], paket["von"], paket["bis"])
                self._json({
                    "stadt": paket["stadt"],
                    "medium": paket["medium"],
                    "von": paket["von"],
                    "bis": paket["bis"],
                    "datenpunkte": int(len(ausschnitt)),
                    "beitraege": beitraege_liste(ausschnitt),
                })
                return
        except FileNotFoundError as fehler:
            self._json({"fehler": str(fehler)}, 500)
            return
        self._sende(b"Nicht gefunden", "text/plain; charset=utf-8", 404)


def main():
    rahmen = lade_beitraege()
    start, ende = spanne(rahmen)
    print(f"Beiträge: {len(rahmen)}")
    print(f"Zeitraum: {_iso(start)} bis {_iso(ende)}")
    print("Städte:")
    print(rahmen["stadt"].fillna("ohne Zuordnung").value_counts().to_string())
    print("Medien:")
    print(rahmen["medium"].fillna("ohne Schalter").value_counts().to_string())
    print(f"Blasen-Quelle: {BLASEN_QUELLE}")
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    print(f"Dashboard: http://{HOST}:{PORT}")
    print("Beenden mit Strg+C. Nach Änderungen an der Auswahl das Skript neu starten.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard beendet.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
