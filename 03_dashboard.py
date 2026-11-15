#!/usr/bin/env python3
"""03 — HTTP page. Numbers come from files written by ``01_vorverarbeitung``.

``00_data`` is written before this process starts:

1. ``beitraege.load_posts`` — ``00_data/posts.json``
2. ``auswertung.summarize`` — window shares, trend, circles from the stored scores
                           ``00_data/context.json`` ← ``06_peak_kontext.py``
                           ``00_data/themes.json``  ← ``07_themen_zuordnung.py``
                           ``00_data/facts.json``   (hand-authored)

Routes: ``/``, ``/assets/*``, ``GET /api/summary``, ``GET /api/posts``.

    python 03_dashboard.py
    http://127.0.0.1:8765
"""

from __future__ import annotations

import importlib
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ASSETS = ROOT / "00_logo"
ASSET_MIME = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".pdf": "application/pdf",
}

config = importlib.import_module("02_laufzeit.config")
posts = importlib.import_module("02_laufzeit.beitraege")
page = importlib.import_module("02_laufzeit.auswertung")
DEFAULT_CHANNEL = config.DEFAULT_CHANNEL
DEFAULT_CITY = config.DEFAULT_CITY
HOST = config.HOST
PORT = config.PORT
STANCE_SOURCE = config.STANCE_SOURCE
load_posts = posts.load_posts
date_iso = page.date_iso
date_span = page.date_span
list_posts = page.list_posts
select_posts = page.select_posts
summarize = page.summarize


# ===========================================================================
# Oberfläche
# ===========================================================================

SEITE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cäble</title>
<link rel="icon" href="/assets/transparent-logo.png" type="image/png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;500;600;700;900&display=swap" rel="stylesheet">
<style>
  :root {
    --papier: #042a55;
    --karte: #ffffff;
    --tinte: #16181d;
    --leise: #6a707a;
    --linie: rgba(22, 24, 29, 0.08);
    --akzent: #0c4a8a;
    --akzent-hell: #4d8fd6;
    --hn-rot: var(--akzent-hell);
    --hn-blau: var(--akzent);
    --support: #0f6b3a;
    --neutral: #eceae6;
    --neutral-tinte: #3a3d44;
    --opposition: #b42318;
    --schatten: 0 1px 2px rgba(16, 24, 40, 0.04), 0 10px 28px rgba(16, 24, 40, 0.05);
    --glas: #ffffff;
    --zahl: "Source Sans 3", "Source Sans Pro", "Segoe UI", sans-serif;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; overflow: hidden; }
  body {
    background-color: var(--papier);
    background-image: none;
    color: #e8eef5;
    font-family: "Source Sans 3", "Source Sans Pro", "Segoe UI", sans-serif;
    font-feature-settings: "kern" on;
  }
  ::selection { background: rgba(12, 74, 138, 0.45); color: #ffffff; }
  button, input { font: inherit; color: inherit; }
  button:focus-visible, input:focus-visible {
    outline: 2px solid var(--akzent);
    outline-offset: 2px;
  }
  .seite {
    position: relative;
    z-index: 1;
    height: 100%;
    min-height: 0;
    display: grid;
    --spalte-trend: 240px;
    --spalte-posts: 180px;
    --spalte-kontext: 360px;
    --zeile-oben: 1fr;
    --zeile-unten: 2fr;
    grid-template-columns: minmax(180px, 1fr) var(--spalte-trend) var(--spalte-posts) minmax(220px, var(--spalte-kontext));
    grid-template-rows: auto minmax(160px, var(--zeile-oben)) minmax(180px, var(--zeile-unten));
    align-content: stretch;
    grid-template-areas:
      "kopf kopf kopf kopf"
      "buehne trend zahl kontext"
      "zeit zeit zeit kontext";
    gap: 14px;
    padding: 18px;
    overflow: auto;
  }
  .seite > header {
    grid-area: kopf;
    position: relative;
    z-index: 6;
    display: flex;
    flex-direction: row-reverse;
    align-items: center;
    justify-content: space-between;
    gap: 24px;
    background: transparent;
    border: 0;
    border-radius: 0;
    padding: 0 2px 2px;
    box-shadow: none;
  }
  .filter {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-end;
    gap: 14px 22px;
    min-width: 0;
  }
  .filter-gruppe {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .filter-gruppe > span {
    color: rgba(232, 238, 245, 0.7);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    white-space: nowrap;
  }
  .marke { text-align: left; flex: 0 0 auto; }
  .caable-logo {
    display: block;
    width: auto;
    height: 52px;
    margin: 0;
    filter: brightness(0) invert(1);
  }
  #untertitel { display: block; margin-top: 5px; color: rgba(232, 238, 245, 0.78); font-size: 12.5px; letter-spacing: 0.01em; }
  .segment, .staedte, .medien {
    display: flex;
    flex-wrap: wrap;
    gap: 2px;
    padding: 3px;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 12px;
  }
  .segment button, .staedte button, .medien button {
    position: relative;
    z-index: 1;
    border: 0;
    background: transparent;
    color: #f2f6fb;
    border-radius: 9px;
    padding: 6px 11px;
    cursor: pointer;
    pointer-events: auto;
    font-weight: 500;
    transition: background 0.18s ease, color 0.18s ease, box-shadow 0.18s ease;
  }
  .segment button:hover, .staedte button:hover, .medien button:hover {
    background: rgba(255, 255, 255, 0.16);
  }
  .segment button.aktiv, .staedte button.aktiv, .medien button.aktiv {
    background: var(--akzent);
    color: #ffffff;
    box-shadow: 0 4px 12px rgba(26, 31, 43, 0.16);
  }
  .staedte button, .medien button {
    padding: 6px 11px;
    font-size: 13px;
  }
  .buehne, .trend-karte, .zahl-karte, .zeit-karte, .kontext-karte {
    background: var(--karte);
    color: var(--tinte);
    border: 1px solid var(--linie);
    border-radius: 16px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12), 0 16px 40px rgba(0, 0, 0, 0.18);
  }
  .buehne {
    grid-area: buehne;
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 16px 16px 14px;
    min-height: 0;
    height: 100%;
    overflow: hidden;
    background: var(--karte);
  }
  .buehne:has(.themen), .buehne:has(.zwei-bloecke) {
    align-items: stretch;
    justify-content: center;
    overflow: auto;
  }
  .buehne:has(.fakten) {
    align-items: stretch;
    justify-content: stretch;
    overflow: auto;
  }
  .kanal {
    display: block;
    margin-top: 2px;
    color: var(--leise);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.02em;
  }
  .fakten {
    width: 100%;
    height: 100%;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 2px 6px 2px;
  }
  .fakten h2 {
    margin: 0;
    font-size: 18px;
    font-weight: 700;
    letter-spacing: -0.03em;
  }
  .stichpunkte {
    list-style: none;
    margin: 0;
    padding: 0;
    flex: 1 1 auto;
    min-height: 0;
    display: grid;
    grid-template-rows: repeat(3, minmax(min-content, 1fr));
    gap: 8px;
  }
  .stichpunkte li {
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 2px;
    min-height: 0;
    margin: 0;
    padding: 6px 14px;
    border-radius: 12px;
    background: #f4f7fb;
    border-left: 4px solid var(--akzent);
  }
  .stichpunkte strong {
    font-size: clamp(17px, 2.2vh, 26px);
    font-weight: 700;
    letter-spacing: -0.03em;
    line-height: 1.15;
  }
  .stichpunkte span {
    color: var(--leise);
    font-size: clamp(13px, 1.6vh, 16px);
    line-height: 1.25;
  }
  @media (max-width: 1180px) {
    .zwei-bloecke { grid-template-columns: 1fr 1fr; }
  }
  @media (max-width: 720px) {
    .zwei-bloecke { grid-template-columns: 1fr; }
  }
  .kreise {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 22px;
    width: 100%;
    max-width: 100%;
    height: 100%;
    flex: 1 1 auto;
    min-height: 0;
  }
  .kreis {
    border-radius: 50%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    line-height: 1.12;
    flex: 0 0 auto;
  }
  .kreis.Positive, .kreis.Support {
    background: linear-gradient(165deg, #9ed9b3 0%, #6ec492 48%, #4aad73 100%);
    color: #052b18;
    box-shadow: inset 0 0 0 2px rgba(8, 74, 42, 0.42), 0 6px 18px rgba(15, 107, 58, 0.22);
  }
  .kreis.Neutral {
    background: #f3f1ee;
    color: var(--neutral-tinte);
    box-shadow: inset 0 0 0 1px rgba(22, 24, 29, 0.06);
  }
  .kreis.Negative, .kreis.Opposition {
    background: linear-gradient(165deg, #f5b4ad 0%, #e88378 48%, #d85c52 100%);
    color: #4a0e0a;
    box-shadow: inset 0 0 0 2px rgba(120, 28, 22, 0.42), 0 6px 18px rgba(180, 35, 24, 0.2);
  }
  .kreis strong {
    font-family: var(--zahl);
    font-size: 28px;
    font-weight: 700;
    letter-spacing: -0.045em;
    font-variant-numeric: tabular-nums;
  }
  .kreis span { font-size: 12px; letter-spacing: 0.04em; margin-top: 2px; font-weight: 600; }
  .kreis em { font-style: normal; font-size: 12px; opacity: 0.62; margin-top: 3px; font-variant-numeric: tabular-nums; }
  .kreise-block {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    justify-content: flex-start;
    width: 100%;
    height: 100%;
    min-height: 0;
    gap: 6px;
  }
  .buehne-kopf {
    flex: 0 0 auto;
    color: var(--leise);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.16em;
    text-transform: uppercase;
  }
  .kreis-fuss {
    position: static;
    max-width: 720px;
    color: var(--leise);
    font-size: 12px;
    line-height: 1.45;
    text-align: center;
  }
  .themen {
    width: min(820px, 100%);
    min-height: 0;
    max-height: 100%;
    flex: 1 1 auto;
    overflow: auto;
    display: flex;
    flex-direction: column;
    justify-content: safe center;
    gap: 7px;
    margin: 0 auto;
    padding: 4px 8px 2px;
  }
  .thema {
    display: grid;
    grid-template-columns: minmax(168px, 240px) minmax(0, 1fr) 4.2em;
    gap: 12px;
    align-items: center;
  }
  .thema-name {
    font-size: 12.5px;
    font-weight: 550;
    line-height: 1.25;
  }
  .thema .art {
    display: block;
    font-style: normal;
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    margin-bottom: 1px;
  }
  .thema.hope .art { color: var(--support); }
  .thema.fear .art { color: var(--opposition); }
  .thema.hope .balken i { background: var(--support); }
  .thema.fear .balken i { background: var(--opposition); }
  .balken {
    display: block;
    height: 5px;
    background: #e7eaef;
    border-radius: 99px;
    overflow: hidden;
  }
  .balken i {
    display: block;
    height: 100%;
    background: var(--akzent);
    border-radius: 99px;
  }
  .thema-wert, .themen-fuss {
    color: var(--leise);
    font-size: 12px;
  }
  .thema-wert {
    color: var(--tinte);
    font-size: 15px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    text-align: right;
    white-space: nowrap;
  }
  .themen-fuss {
    margin: 10px 0 0;
    text-align: center;
    line-height: 1.4;
  }
  .zwei-bloecke {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
    width: 100%;
    height: 100%;
    min-height: 0;
    padding: 2px;
  }
  .zwei-bloecke > section {
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: auto;
    padding: 16px 18px 14px;
    border: 1px solid var(--linie);
    border-radius: 14px;
    background: #fbfcfd;
  }
  .zwei-bloecke h2 {
    margin: 0 0 14px;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  .zwei-bloecke .hope-block h2 { color: var(--support); }
  .zwei-bloecke .fear-block h2 { color: var(--opposition); }
  .zwei-bloecke .themen {
    width: 100%;
    max-height: none;
    justify-content: flex-start;
    padding: 0;
    margin: 0;
    gap: 12px;
  }
  .zwei-bloecke .thema {
    grid-template-columns: minmax(140px, 1fr) minmax(0, 1.2fr) 4.6em;
    gap: 14px;
  }
  .zwei-bloecke .thema-name {
    font-size: 14px;
    font-weight: 600;
    line-height: 1.3;
  }
  .zwei-bloecke .thema-wert { font-size: 16px; }
  .zwei-bloecke .balken { height: 8px; }
  .trend-karte, .zahl-karte {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    justify-content: flex-start;
    text-align: left;
    padding: 14px 16px 12px;
  }
  .trend-karte {
    grid-area: trend;
    min-width: 0;
  }
  .trend-kopf, .zahl-kopf, .zeit-kopf > span:first-child, .kontext-kopf > span {
    color: var(--leise);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.16em;
    text-transform: uppercase;
  }
  .trend-inhalt {
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
  }
  .zahl-karte {
    grid-area: zahl;
    width: 100%;
    border-radius: 16px;
    cursor: pointer;
    font-weight: 500;
    container-type: inline-size;
    transition: border-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
  }
  .pfeil {
    width: clamp(64px, 72%, 104px);
    height: clamp(64px, 72%, 104px);
    padding: 16px;
    box-sizing: border-box;
    border-radius: 50%;
    background: #eef1f5;
  }
  .pfeil.up { color: var(--support); background: #e7f3ec; }
  .pfeil.down { color: var(--opposition); background: #f8ecea; }
  .pfeil.flat, .pfeil.unknown { color: var(--leise); }
  .zahl-hinweis, .leer {
    color: var(--leise);
    font-size: 12.5px;
    line-height: 1.45;
    margin: 8px 0 0;
  }
  .zahl-karte strong {
    flex: 1 1 auto;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: var(--zahl);
    font-size: clamp(32px, 42cqi, 84px);
    font-weight: 700;
    letter-spacing: -0.055em;
    line-height: 0.82;
    color: var(--tinte);
    font-variant-numeric: tabular-nums;
    text-align: center;
  }
  .zahl-hinweis { text-align: center; }
  .zahl-karte:hover {
    border-color: rgba(12, 74, 138, 0.35);
    transform: translateY(-1px);
    box-shadow: 0 12px 28px rgba(16, 24, 40, 0.08);
  }
  .zeit-karte {
    grid-area: zeit;
    padding: 10px 16px 6px;
    min-width: 0;
    min-height: 0;
    height: 100%;
    display: flex;
    flex-direction: column;
  }
  .kontext-karte {
    position: relative;
    grid-area: kontext;
    min-width: 0;
    min-height: 0;
    height: 100%;
    display: flex;
    flex-direction: column;
    padding: 16px 18px 14px;
    overflow: hidden;
    box-shadow: var(--schatten);
  }
  .kontext-karte::before {
    content: "";
    position: absolute;
    left: 0;
    top: 16px;
    bottom: 16px;
    width: 4px;
    border-radius: 0 2px 2px 0;
    background: linear-gradient(180deg, var(--hn-rot), var(--hn-blau));
  }
  .kontext-kopf {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
  }
  .kontext-kopf button, .blatt header button {
    border: 1px solid var(--linie);
    background: #ffffff;
    border-radius: 999px;
    padding: 5px 11px;
    font-size: 12px;
    letter-spacing: 0;
    text-transform: none;
    cursor: pointer;
    transition: border-color 0.18s ease, background 0.18s ease;
  }
  .kontext-kopf button:hover, .blatt header button:hover {
    border-color: var(--akzent);
    background: #f4f8fc;
  }
  .kontext-kicker {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin-top: 12px;
  }
  .kontext-karte h2, .blatt header strong, .liste h3 {
    font-family: "Source Sans 3", "Source Sans Pro", "Segoe UI", sans-serif;
    font-weight: 700;
    letter-spacing: -0.03em;
  }
  .kontext-karte h2 {
    font-size: 24px;
    line-height: 1.18;
    margin: 8px 0 0;
  }
  .kontext-meta, .kontext-leer, .konfidenz-why {
    color: var(--leise);
    font-size: 13.5px;
    line-height: 1.5;
    margin: 8px 0 0;
  }
  .kontext-karte .lead {
    color: var(--tinte);
    font-size: 15.5px;
    line-height: 1.55;
    margin: 14px 0 0;
  }
  .konfidenz {
    display: inline-block;
    border-radius: 999px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .konfidenz.high { background: #e5f2eb; color: var(--support); }
  .konfidenz.medium { background: #e8f1fa; color: var(--akzent); }
  .konfidenz.low { background: #eef0f3; color: var(--leise); }
  .kontext-scroll, .themen, .liste {
    scrollbar-width: thin;
    scrollbar-color: #d5dae2 transparent;
  }
  .kontext-scroll {
    overflow: auto;
    min-height: 0;
    flex: 1 1 auto;
    margin-top: 6px;
    padding-right: 4px;
  }
  .kontext-block { margin-top: 18px; }
  .kontext-block h3 {
    margin: 0 0 8px;
    font-size: 10px;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--leise);
    font-weight: 600;
  }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chips span {
    background: #eef1f5;
    border: 0;
    border-radius: 999px;
    padding: 4px 10px;
    font-size: 12.5px;
  }
  .kontext-karte ul { list-style: none; margin: 0; padding: 0; }
  .kontext-karte li {
    position: relative;
    font-size: 14.5px;
    line-height: 1.45;
    margin: 0 0 8px;
    padding-left: 12px;
  }
  .kontext-karte li::before {
    content: "";
    position: absolute;
    left: 0;
    top: 0.62em;
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--akzent);
  }
  .kontext-karte a, .liste a { color: inherit; text-decoration-thickness: 1px; text-underline-offset: 2px; }
  .kontext-karte a:hover, .liste a:hover { color: var(--akzent); }
  svg.chart .peak-marke { cursor: pointer; }
  svg.chart text { font-family: "Source Sans 3", "Source Sans Pro", "Segoe UI", sans-serif; }
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
  .doppel { position: relative; height: 18px; margin-top: 2px; padding-left: 42px; }
  .zeit-fuss { padding-left: 42px; }
  .doppel .spur {
    position: absolute;
    left: 0; right: 0; top: 9px;
    height: 3px;
    border-radius: 99px;
    background: #e4e7ec;
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
  .doppel input[type="range"]::-webkit-slider-runnable-track { height: 3px; background: transparent; }
  .doppel input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    pointer-events: auto;
    width: 14px; height: 14px;
    margin-top: -6px;
    border-radius: 50%;
    background: var(--tinte);
    border: 2px solid #ffffff;
    box-shadow: 0 2px 6px rgba(22, 24, 29, 0.18);
    cursor: grab;
  }
  .doppel input[type="range"]::-moz-range-track { height: 3px; background: transparent; border: none; }
  .doppel input[type="range"]::-moz-range-thumb {
    pointer-events: auto;
    width: 14px; height: 14px;
    border-radius: 50%;
    background: var(--tinte);
    border: 2px solid #ffffff;
    box-shadow: 0 2px 6px rgba(26, 31, 43, 0.2);
    cursor: grab;
  }
  .staedte, .medien, .segment {
    display: flex;
    flex-wrap: wrap;
    gap: 2px;
    padding: 3px;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    border: 0;
    box-shadow: none;
  }
  .overlay[hidden] { display: none; }
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 5;
    background: rgba(26, 31, 43, 0.38);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    display: flex;
    justify-content: flex-end;
  }
  .blatt {
    width: min(540px, 100%);
    height: 100%;
    background: var(--karte);
    border-left: 1px solid var(--linie);
    box-shadow: -24px 0 48px rgba(26, 31, 43, 0.14);
    display: flex;
    flex-direction: column;
  }
  .blatt header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
    padding: 18px 18px 12px;
    border: none;
    border-bottom: 1px solid var(--linie);
    border-radius: 0;
    background: transparent;
    box-shadow: none;
    backdrop-filter: none;
  }
  .blatt header strong { font-size: 22px; }
  .blatt header p { margin: 4px 0 0; color: var(--leise); font-size: 13px; }
  .liste { list-style: none; margin: 0; padding: 0; overflow: auto; }
  .liste li {
    padding: 14px 18px 16px;
    border-bottom: 1px solid var(--linie);
  }
  .liste .meta { color: var(--leise); font-size: 12px; }
  .liste h3 { margin: 5px 0; font-size: 17px; line-height: 1.28; }
  .liste .snippet { margin: 0; color: #3e463f; font-size: 13.5px; line-height: 1.5; }
  .plakette {
    display: inline-block;
    border-radius: 999px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
    margin: 0 6px 4px 0;
  }
  .plakette.Positive, .plakette.Support { background: #e5f2eb; color: var(--support); }
  .plakette.Neutral { background: #eceae6; color: var(--neutral-tinte); }
  .plakette.Negative, .plakette.Opposition { background: #f8eeed; color: var(--opposition); }
  .plakette.offen, .plakette.thema { background: #eef1f5; color: var(--leise); }
  .plakette.thema { color: var(--tinte); }
  .plakette.argument { background: #e8f1fa; color: var(--akzent); }
  .plakette.hope { background: #e5f2eb; color: var(--support); }
  .plakette.fear { background: #f8e8e6; color: var(--opposition); }
  .griff {
    position: absolute;
    z-index: 3;
    top: 0;
    left: -120px;
    width: 14px;
    height: 14px;
    margin: 0;
    padding: 0;
    border: 0;
    border-radius: 8px;
    background: transparent;
    touch-action: none;
    pointer-events: none;
  }
  .griff span {
    position: absolute;
    pointer-events: auto;
  }
  .griff-v span { left: 0; right: 0; top: 18px; bottom: 18px; }
  .griff-h span { top: 0; bottom: 0; left: 18px; right: 18px; }
  .griff-v { cursor: col-resize; }
  .griff-h { cursor: row-resize; }
  .griff::before {
    content: "";
    position: absolute;
    border-radius: 99px;
    background: rgba(12, 74, 138, 0.22);
    transition: background 0.15s ease;
  }
  .griff-v::before {
    left: 50%;
    top: 16px;
    bottom: 16px;
    width: 3px;
    transform: translateX(-50%);
  }
  .griff-h::before {
    top: 50%;
    left: 16px;
    right: 16px;
    height: 3px;
    transform: translateY(-50%);
  }
  .griff:hover::before, .griff:focus-visible::before, .griff.aktiv::before {
    background: var(--akzent);
  }
  body.groesse-spalte, body.groesse-spalte * { cursor: col-resize !important; user-select: none; }
  body.groesse-zeile, body.groesse-zeile * { cursor: row-resize !important; user-select: none; }
  @media (max-width: 1100px) {
    .seite {
      grid-template-columns: minmax(0, 1fr) minmax(250px, 320px);
      grid-template-areas:
        "kopf kopf"
        "buehne buehne"
        "trend zahl"
        "zeit kontext";
      grid-template-rows: auto minmax(140px, 1fr) auto minmax(200px, 2fr);
    }
    .buehne { min-height: 0; }
    .griff { display: none; }
  }
  @media (max-width: 720px) {
    .seite {
      grid-template-columns: minmax(0, 1fr) minmax(210px, 260px);
      grid-template-areas:
        "kopf kopf"
        "buehne buehne"
        "trend zahl"
        "zeit kontext";
      grid-template-rows: auto minmax(140px, 1fr) auto minmax(180px, 2fr);
    }
  }
</style>
</head>
<body>
<div class="seite">
  <button type="button" class="griff griff-v" data-kante="trend" aria-label="Resize Trends" title="Drag to resize Trends. Double-click to reset."><span></span></button>
  <button type="button" class="griff griff-v" data-kante="posts" aria-label="Resize Posts" title="Drag to resize Posts. Double-click to reset."><span></span></button>
  <button type="button" class="griff griff-v" data-kante="kontext" aria-label="Resize Peak context" title="Drag to resize Peak context. Double-click to reset."><span></span></button>
  <button type="button" class="griff griff-h" data-kante="zeit" aria-label="Resize Timeline" title="Drag to resize the Timeline. Double-click to reset."><span></span></button>
  <header>
    <div class="filter">
      <div class="filter-gruppe">
        <span>Project</span>
        <div class="staedte" id="staedte"></div>
      </div>
      <div class="filter-gruppe">
        <span>Channel</span>
        <div class="medien" id="medien"></div>
      </div>
      <div class="filter-gruppe">
        <span>View</span>
        <div class="segment" id="ansicht">
          <button type="button" data-ansicht="circles" class="aktiv" title="Tone is how the text sounds. Stance is whether it wants the project.">Tone</button>
          <button type="button" data-ansicht="arguments" title="Expectations and fears. A post can count in more than one.">Hopes &amp; fears</button>
          <button type="button" data-ansicht="facts" title="What comments assume, next to the official figures.">Misunderstandings</button>
        </div>
      </div>
    </div>
    <div class="marke">
      <img class="caable-logo" src="/assets/transparent-logo.svg" width="134" height="52" alt="Cäble">
      <span id="untertitel">Powered by HuNgover</span>
    </div>
  </header>
  <section class="buehne" id="buehne"></section>
  <section class="trend-karte" aria-label="Trend">
    <div class="trend-inhalt" id="trend-inhalt"></div>
  </section>
  <button class="zahl-karte" id="zahl-karte" type="button">
    <span class="zahl-kopf">Posts</span>
    <strong id="zahl">–</strong>
    <span class="zahl-hinweis">Show the posts in this selection</span>
  </button>
  <section class="zeit-karte">
    <div class="zeit-kopf">
      <span>Timeline</span>
      <span id="zeit-spanne"></span>
    </div>
    <svg class="chart" id="chart" role="img" aria-label="Posts per day"></svg>
    <div class="doppel">
      <div class="spur" id="spur"></div>
      <input id="von" type="range" min="0" max="1" value="0" aria-label="Start of the window">
      <input id="bis" type="range" min="0" max="1" value="1" aria-label="End of the window">
    </div>
    <div class="zeit-fuss"><span id="von-label"></span><span id="bis-label"></span></div>
  </section>
  <aside class="kontext-karte" id="kontext">
    <div class="kontext-kopf">
      <span>Peak context</span>
      <button type="button" id="kontext-reset" hidden>Show all</button>
    </div>
    <p class="kontext-leer" id="kontext-leer">Click a peak on the timeline to set the window and read the context for those days.</p>
    <div id="kontext-inhalt" hidden>
      <div class="kontext-kicker">
        <span class="konfidenz" id="kontext-konfidenz"></span>
      </div>
      <h2 id="kontext-titel"></h2>
      <p class="kontext-meta" id="kontext-meta"></p>
      <p class="konfidenz-why" id="kontext-why"></p>
      <div class="kontext-scroll">
        <p class="lead" id="kontext-summary"></p>
        <div id="kontext-bloecke"></div>
      </div>
    </div>
  </aside>
</div>
<div class="overlay" id="overlay" hidden>
  <div class="blatt">
    <header>
      <div>
        <strong id="liste-titel">Posts</strong>
        <p id="liste-text"></p>
      </div>
      <button type="button" id="schliessen">Close</button>
    </header>
    <ul class="liste" id="liste"></ul>
  </div>
</div>
<script>
const ansichtEl = document.getElementById("ansicht");
const buehne = document.getElementById("buehne");
const trendEl = document.getElementById("trend-inhalt");
const zahlEl = document.getElementById("zahl");
const staedteEl = document.getElementById("staedte");
const medienEl = document.getElementById("medien");
const chart = document.getElementById("chart");
const vonInput = document.getElementById("von");
const bisInput = document.getElementById("bis");
const spur = document.getElementById("spur");
const overlay = document.getElementById("overlay");
const liste = document.getElementById("liste");
const kontextLeer = document.getElementById("kontext-leer");
const kontextInhalt = document.getElementById("kontext-inhalt");
const kontextReset = document.getElementById("kontext-reset");

const zustand = {
  ansicht: "circles",
  stadt: "All",
  medium: "All",
  von: null,
  bis: null,
  peak: null,
  serie: [],
  yAchsenMax: 1,
  letzter: null,
  ziehen: null,
};

function esc(wert) {
  return String(wert ?? "").replace(/[&<>"']/g, (zeichen) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[zeichen]);
}
function datumKurz(iso) {
  const monate = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
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
  suche.set("city", zustand.stadt);
  suche.set("channel", zustand.medium);
  if (zustand.von) suche.set("date_from", zustand.von);
  if (zustand.bis) suche.set("date_to", zustand.bis);
  return suche;
}

function schalter(eltern, eintraege, schluessel) {
  const signatur = (eintraege || []).map((eintrag) => eintrag.id + "\n" + eintrag.label).join("\n");
  if (eltern.dataset.signatur !== signatur) {
    eltern.dataset.signatur = signatur;
    eltern.replaceChildren(...(eintraege || []).map((eintrag) => {
      const knopf = document.createElement("button");
      knopf.type = "button";
      knopf.dataset.id = eintrag.id;
      knopf.textContent = eintrag.label;
      if (eintrag.hint) knopf.title = eintrag.hint;
      return knopf;
    }));
  }
  [...eltern.querySelectorAll("button")].forEach((knopf) => {
    knopf.classList.toggle("aktiv", knopf.dataset.id === zustand[schluessel]);
  });
}

function bindeSchalter(eltern, schluessel) {
  eltern.addEventListener("click", (ereignis) => {
    const knopf = ereignis.target.closest("button");
    if (!knopf || !eltern.contains(knopf) || !knopf.dataset.id) return;
    zustand[schluessel] = knopf.dataset.id;
    zustand.von = null;
    zustand.bis = null;
    zustand.peak = null;
    [...eltern.querySelectorAll("button")].forEach((eintrag) => {
      eintrag.classList.toggle("aktiv", eintrag === knopf);
    });
    laden();
  });
}

function pfeil(richtung) {
  const strecke = {
    up: "M32 50 V16 M18 30 L32 14 L46 30",
    down: "M32 14 V48 M18 34 L32 50 L46 34",
    flat: "M16 32 H48",
    unknown: "M18 32 H46",
  }[richtung] || "M18 32 H46";
  return `<svg class="pfeil ${richtung}" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="${strecke}"/></svg>`;
}

function zeichneKreise(daten) {
  const kreis = daten.circles;
  const anzahl = kreis.counts;
  const maximum = Math.max(...Object.values(anzahl), 1);
  const abstand = 18;
  const innenBreite = Math.max((buehne.clientWidth || 360) - 28, 180);
  const innenHoehe = Math.max((buehne.clientHeight || 200) - 20, 88);
  const roh = BLASEN_REIHENFOLGE.map((name) => 118 + Math.sqrt(anzahl[name] / maximum) * 132);
  const summe = roh.reduce((summe, wert) => summe + wert, 0) + abstand * (roh.length - 1);
  const faktor = Math.min(1, innenBreite / summe, innenHoehe / Math.max(...roh));
  const knoten = BLASEN_REIHENFOLGE.map((name, index) => {
    const groesse = Math.max(82, Math.round(roh[index] * faktor));
    const schrift = groesse < 100 ? 22 : groesse < 150 ? 32 : 42;
    const label = groesse < 100 ? 10 : 13;
    const anteil = kreis.shares[name] || 0;
    const tip = `${name} ${prozent(anteil)}.`;
    return `<div class="kreis ${name}" style="width:${groesse}px;height:${groesse}px" title="${esc(tip)}">
      <strong style="font-size:${schrift}px">${prozent(anteil)}</strong>
      <span style="font-size:${label}px">${name}</span>
      <em>${anzahl[name]}</em>
    </div>`;
  }).join("");
  buehne.innerHTML = `<div class="kreise-block"><span class="buehne-kopf">Stance</span><div class="kreise">${knoten}</div></div>`;
}

function kanalZeile(eintrag) {
  const kanal = eintrag.by_channel;
  if (!kanal) return "";
  const teile = ["News", "Social", "Other web"].filter((name) => kanal[name]).map((name) => `${name} ${kanal[name]}`);
  return teile.length ? `<span class="kanal">${esc(teile.join(" · "))}</span>` : "";
}

const BLASEN_REIHENFOLGE = ["Positive", "Neutral", "Negative"];

function balkenZeilen(zeilenQuelle, maximum) {
  return zeilenQuelle.map((eintrag) => {
    const breite = Math.round(((eintrag.share || 0) / maximum) * 100);
    const hinweis = [eintrag.description, ...(eintrag.terms || [])].filter(Boolean).join(" — ");
    const klasse = eintrag.polarity === "hope" || eintrag.polarity === "fear" ? ` ${eintrag.polarity}` : "";
    return `<div class="thema${klasse}" title="${esc(hinweis)}">
      <span class="thema-name">${esc(eintrag.label)}</span>
      <span class="balken"><i style="width:${breite}%"></i></span>
      <span class="thema-wert">${(eintrag.count > 0 && Math.round((eintrag.share || 0) * 100) === 0) ? "&lt;1 %" : prozent(eintrag.share || 0)}</span>
    </div>`;
  }).join("");
}

function zeichneHoffnungenAengste(daten) {
  const zeilen = (daten.arguments || []).filter((eintrag) => eintrag.count > 0);
  const hopes = zeilen.filter((eintrag) => eintrag.polarity === "hope");
  const fears = zeilen.filter((eintrag) => eintrag.polarity === "fear");
  const rest = zeilen.filter((eintrag) => eintrag.polarity !== "hope" && eintrag.polarity !== "fear");
  const alle = hopes.concat(fears, rest);
  if (!alle.length) {
    buehne.innerHTML = `<p class="leer">Nothing in this selection.</p>`;
    return;
  }
  const maximum = Math.max(...alle.map((eintrag) => eintrag.share || 0), 0.001);
  const leer = `<p class="leer">None in this selection.</p>`;
  buehne.innerHTML = `<div class="zwei-bloecke">
    <section class="hope-block">
      <h2>Hopes</h2>
      <div class="themen">${hopes.length ? balkenZeilen(hopes, maximum) : leer}</div>
    </section>
    <section class="fear-block">
      <h2>Fears</h2>
      <div class="themen">${fears.length ? balkenZeilen(fears, maximum) : leer}</div>
    </section>
  </div>`;
}

function zeichneFakten(daten) {
  const punkte = (((daten.facts || {}).stichpunkte) || []).slice(0, 3);
  if (!punkte.length) {
    buehne.innerHTML = `<p class="leer">No fact sheet for this project.</p>`;
    return;
  }
  const zeilen = punkte.map((eintrag) => `<li>
      <strong>${esc(eintrag.titel || "")}</strong>
      <span>${esc(eintrag.text || "")}</span>
    </li>`).join("");
  buehne.innerHTML = `<div class="fakten">
    <h2>Misunderstandings</h2>
    <ol class="stichpunkte">${zeilen}</ol>
  </div>`;
}

function zeichneAnsicht(daten) {
  if (zustand.ansicht === "facts") {
    zeichneFakten(daten);
  } else if (zustand.ansicht === "arguments") {
    zeichneHoffnungenAengste(daten);
  } else {
    zeichneKreise(daten);
  }
}

function zeichneTrend(trend) {
  const richtung = trend.direction === "up" || trend.direction === "down" ? trend.direction : "flat";
  const von = trend.previous_from ? datumKurz(trend.previous_from) : "";
  const bis = trend.previous_to ? datumKurz(trend.previous_to) : "";
  const zeit = von && bis ? von + " – " + bis : "";
  trendEl.innerHTML = pfeil(richtung);
  const svg = trendEl.querySelector(".pfeil");
  if (!svg) return;
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", zeit || "Vorheriger Zeitraum");
  if (zeit) svg.setAttribute("title", zeit);
}

function indexBei(iso) {
  const stelle = zustand.serie.findIndex((punkt) => punkt.date === iso);
  return stelle < 0 ? 0 : stelle;
}

const Y_ACHSE = 42;

function achsenMaximum(rohMax) {
  const basis = Math.max(rohMax, 1);
  return Math.max(1, Math.ceil(basis * 1.1));
}

function serieMaximum(serie) {
  if (!serie.length) return 1;
  return Math.max(...serie.map((punkt) => punkt.count), 1);
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
  const oben = 8;
  const unten = 8;
  const plotHoehe = Math.max(hoehe - oben - unten, 16);
  const plotBreite = Math.max(breite - Y_ACHSE - 8, 40);
  const schritt = serie.length === 1 ? 0 : plotBreite / (serie.length - 1);
  const vonIndex = indexBei(zustand.von);
  const bisIndex = indexBei(zustand.bis);
  const links = Math.min(vonIndex, bisIndex);
  const rechts = Math.max(vonIndex, bisIndex);
  const maximum = zustand.yAchsenMax;
  const punkte = serie.map((punkt, index) => {
    const x = Y_ACHSE + index * schritt;
    const y = hoehe - unten - (punkt.count / maximum) * plotHoehe;
    return [x, y];
  });
  const linie = punkte.map((punkt, index) => `${index ? "L" : "M"}${punkt[0].toFixed(1)},${punkt[1].toFixed(1)}`).join(" ");
  const flaeche = `${linie} L${(Y_ACHSE + plotBreite).toFixed(1)},${hoehe} L${Y_ACHSE},${hoehe} Z`;
  const x0 = punkte[links][0];
  const x1 = punkte[rechts][0];
  const ticks = [0, maximum / 2, maximum].map((wert, i, alle) => {
    const gerundet = i === alle.length - 1 ? maximum : Math.round(wert);
    const y = hoehe - unten - (gerundet / maximum) * plotHoehe;
    return `<line x1="${Y_ACHSE - 3}" y1="${y.toFixed(1)}" x2="${Y_ACHSE}" y2="${y.toFixed(1)}" stroke="#d5dae2" stroke-width="1"></line>
      <text x="${Y_ACHSE - 6}" y="${(y + 3.5).toFixed(1)}" text-anchor="end" fill="#3a3f48" font-size="12" font-weight="700">${gerundet}</text>`;
  }).join("");
  const versatz = {};
  const peaks = (zustand.peaks || []).map((peak) => {
    const index = serie.findIndex((punkt) => punkt.date === peak.date);
    if (index < 0) return "";
    const n = versatz[peak.date] || 0;
    versatz[peak.date] = n + 1;
    const x = (Y_ACHSE + index * schritt + (n ? (n % 2 ? 6 : -6) : 0)).toFixed(1);
    const y = punkte[index][1].toFixed(1);
    const aktiv = zustand.peak === peak.id;
    const major = peak.tier !== "minor";
    const familie = (zustand.familien || []).find((eintrag) => eintrag.id === peak.family);
    const farbe = familie ? familie.color : "#0c4a8a";
    const radius = aktiv ? 6.2 : major ? 4.5 : 3.2;
    const dicke = aktiv ? 2.4 : major ? 1.6 : 1;
    const deckkraft = aktiv ? 1 : major ? 0.9 : 0.45;
    const fenster = (peak.window_from && peak.window_to)
      ? `${datumKurz(peak.window_from)} – ${datumKurz(peak.window_to)}`
      : datumKurz(peak.date);
    const folge = peak.follow === "faded" ? " · volume fell back" : peak.follow === "stayed" ? " · volume stayed high" : "";
    const label = `${peak.label} · ${fenster} · ${peak.post_count} posts`
      + (peak.event_type ? ` · ${peak.event_type}` : "")
      + folge
      + (peak.headline ? `. ${peak.headline}` : "");
    const kern = peak.follow === "faded"
      ? `<circle cx="${x}" cy="${y}" r="${radius}" fill="#ffffff" stroke="${farbe}" stroke-width="1.8"></circle>`
      : peak.follow === "stayed"
        ? `<circle cx="${x}" cy="${y}" r="${radius + 3.2}" fill="none" stroke="${farbe}" stroke-width="1.3"></circle><circle cx="${x}" cy="${y}" r="${radius}" fill="${farbe}"></circle>`
        : `<circle cx="${x}" cy="${y}" r="${radius}" fill="${farbe}" opacity="${deckkraft}"></circle>`;
    const summe = "";
    const rand = aktiv ? `<circle cx="${x}" cy="${y}" r="${radius + 5}" fill="none" stroke="#16181d" stroke-width="1.2"></circle>` : "";
    return `<g class="peak-marke" data-peak="${esc(peak.id)}">
      <title>${esc(label)}</title>
      <line x1="${x}" y1="0" x2="${x}" y2="${hoehe}" stroke="${farbe}" stroke-width="14" opacity="0"></line>
      <line x1="${x}" y1="${y}" x2="${x}" y2="${hoehe}" stroke="${farbe}" stroke-width="${dicke}" opacity="${deckkraft * 0.55}"></line>
      <circle cx="${x}" cy="${y}" r="${radius + 2.2}" fill="#ffffff" opacity="${deckkraft}"></circle>
      ${kern}
      ${rand}
      ${summe}
    </g>`;
  }).join("");
  chart.innerHTML = `
    <defs>
      <linearGradient id="flaeche-licht" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#0c4a8a" stop-opacity="0.18"></stop>
        <stop offset="100%" stop-color="#0c4a8a" stop-opacity="0.02"></stop>
      </linearGradient>
    </defs>
    <text transform="translate(12, ${(hoehe / 2).toFixed(1)}) rotate(-90)" text-anchor="middle" fill="#6a707a" font-size="10" font-weight="600" letter-spacing="0.08em">POSTS / DAY</text>
    <line x1="${Y_ACHSE}" y1="${oben}" x2="${Y_ACHSE}" y2="${hoehe - unten}" stroke="#d5dae2" stroke-width="1"></line>
    ${ticks}
    <path d="${flaeche}" fill="url(#flaeche-licht)"></path>
    <path d="${linie}" fill="none" stroke="#0c4a8a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
    <rect x="${Y_ACHSE}" y="0" width="${Math.max(x0 - Y_ACHSE, 0)}" height="${hoehe}" fill="#ffffff" opacity="0.62" pointer-events="none"></rect>
    <rect x="${x1}" y="0" width="${Math.max(breite - x1, 0)}" height="${hoehe}" fill="#ffffff" opacity="0.62" pointer-events="none"></rect>
    ${peaks}
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
  spur.style.background = `linear-gradient(90deg, #e4e7ec ${links}%, #0c4a8a ${links}%, #0c4a8a ${rechts}%, #e4e7ec ${rechts}%)`;
  document.getElementById("von-label").textContent = datumKurz(zustand.von);
  document.getElementById("bis-label").textContent = datumKurz(zustand.bis);
  const gewaehlt = Math.abs(bis - von) + 1;
  const fenster = gewaehlt === 1 ? "1 day selected" : gewaehlt + " days selected";
  document.getElementById("zeit-spanne").textContent = zustand.peak ? "Peak window · " + fenster : fenster;
}

function gewaehlterPeak() {
  return (zustand.peaks || []).find((peak) => peak.id === zustand.peak) || null;
}

function zeichneKontext() {
  const peak = gewaehlterPeak();
  kontextReset.hidden = !peak;
  if (!peak) {
    kontextLeer.hidden = false;
    kontextInhalt.hidden = true;
    return;
  }
  kontextLeer.hidden = true;
  kontextInhalt.hidden = false;
  const level = peak.confidence || "low";
  const stufen = { high: "high", medium: "medium", low: "low", hoch: "high", mittel: "medium", niedrig: "low" };
  const badge = document.getElementById("kontext-konfidenz");
  badge.className = "konfidenz " + (stufen[level] || "low");
  badge.textContent = "Confidence " + (stufen[level] || level);
  document.getElementById("kontext-titel").textContent = peak.event_type || peak.label;
  document.getElementById("kontext-meta").textContent = [
    peak.label,
    datumKurz(peak.window_from || peak.date) + " – " + datumKurz(peak.window_to || peak.date),
    peak.post_count + " posts at peak",
    peak.follow === "faded" ? "volume fell back afterwards" : peak.follow === "stayed" ? "volume stayed high afterwards" : "",
    peak.sources || "",
  ].filter(Boolean).join(" · ");
  const why = document.getElementById("kontext-why");
  why.textContent = peak.confidence_why || "";
  why.hidden = !peak.confidence_why;
  const summary = document.getElementById("kontext-summary");
  summary.textContent = peak.summary || "";
  summary.hidden = !peak.summary;
  const bloecke = [];
  if ((peak.terms || []).length) {
    bloecke.push(`<div class="kontext-block"><h3>Terms</h3><div class="chips">${
      peak.terms.map((term) => `<span>${esc(term)}</span>`).join("")
    }</div></div>`);
  }
  if ((peak.headlines || []).length) {
    bloecke.push(`<div class="kontext-block"><h3>Headlines & sources</h3><ul>${
      peak.headlines.map((punkt) => {
        const text = typeof punkt === "string" ? punkt : (punkt.text || "");
        const url = sichereUrl(punkt && punkt.url);
        const source = typeof punkt === "object" && punkt ? (punkt.source || "") : "";
        const inhalt = url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(text)}</a>` : esc(text);
        const quelle = source ? ` <span class="meta">${esc(source)}</span>` : "";
        return `<li>${inhalt}${quelle}</li>`;
      }).join("")
    }</ul></div>`);
  }
  if ((peak.effects || []).length) {
    bloecke.push(`<div class="kontext-block"><h3>Follow-up</h3><ul>${
      peak.effects.map((zeile) => `<li>${esc(zeile)}</li>`).join("")
    }</ul></div>`);
  }
  document.getElementById("kontext-bloecke").innerHTML = bloecke.join("");
}

function waehlePeak(id) {
  if (zustand.peak === id) {
    zustand.peak = null;
    zustand.von = null;
    zustand.bis = null;
    laden();
    return;
  }
  const peak = (zustand.peaks || []).find((eintrag) => eintrag.id === id);
  if (!peak) return;
  zustand.peak = id;
  zustand.von = peak.window_from || peak.date;
  zustand.bis = peak.window_to || peak.date;
  laden();
}

function zeichne(daten) {
  zustand.letzter = daten;
  zustand.serie = daten.timeline;
  zustand.yAchsenMax = achsenMaximum(serieMaximum(daten.timeline));
  zustand.peaks = daten.peaks || [];
  zustand.familien = daten.families || [];
  if (zustand.peak && !zustand.peaks.some((peak) => peak.id === zustand.peak)) {
    zustand.peak = null;
  }
  zustand.von = daten.date_from;
  zustand.bis = daten.date_to;
  schalter(staedteEl, daten.cities, "stadt");
  schalter(medienEl, daten.channels, "medium");
  zeichneAnsicht(daten);
  zeichneTrend(daten.trend);
  zahlEl.textContent = String(daten.post_count);
  zeichneChart();
  schieberZeichnen();
  zeichneKontext();
  requestAnimationFrame(zeichneChart);
}

let lauf = 0;
async function laden() {
  const nummer = ++lauf;
  try {
    const antwort = await fetch("/api/summary?" + parameter());
    if (!antwort.ok) return;
    const daten = await antwort.json();
    if (nummer !== lauf) return;
    zeichne(daten);
  } catch (fehler) {}
}
bindeSchalter(staedteEl, "stadt");
bindeSchalter(medienEl, "medium");

let warte = 0;
function schieberLos() {
  if (!zustand.serie.length) return;
  const max = Math.max(zustand.serie.length - 1, 0);
  let von = Number(vonInput.value);
  let bis = Number(bisInput.value);
  if (von > bis) [von, bis] = [bis, von];
  von = Math.max(0, Math.min(max, von));
  bis = Math.max(0, Math.min(max, bis));
  zustand.von = zustand.serie[von].date;
  zustand.bis = zustand.serie[bis].date;
  zustand.peak = null;
  schieberZeichnen();
  zeichneChart();
  zeichneKontext();
  window.clearTimeout(warte);
  warte = window.setTimeout(laden, 90);
}

vonInput.addEventListener("input", schieberLos);
bisInput.addEventListener("input", schieberLos);

function indexAusMaus(ereignis) {
  const kasten = chart.getBoundingClientRect();
  const plot = Math.max((kasten.width || 1) - Y_ACHSE, 1);
  const x = Math.min(Math.max(ereignis.clientX - kasten.left - Y_ACHSE, 0), plot);
  const max = Math.max(zustand.serie.length - 1, 1);
  return Math.round(x / plot * max);
}
chart.style.cursor = "ew-resize";
chart.addEventListener("pointerdown", (ereignis) => {
  const marke = ereignis.target.closest("[data-peak]");
  if (marke) {
    ereignis.preventDefault();
    waehlePeak(marke.getAttribute("data-peak"));
    return;
  }
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
  zeichneAnsicht(zustand.letzter);
  if (zustand.serie.length) zeichneChart();
});
kontextReset.addEventListener("click", () => {
  zustand.peak = null;
  zustand.von = null;
  zustand.bis = null;
  laden();
});

ansichtEl.addEventListener("click", (ereignis) => {
  const knopf = ereignis.target.closest("button");
  if (!knopf) return;
  zustand.ansicht = knopf.dataset.ansicht;
  [...ansichtEl.children].forEach((eintrag) => eintrag.classList.toggle("aktiv", eintrag === knopf));
  if (zustand.letzter) {
    zeichneAnsicht(zustand.letzter);
  }
});

function plakette(name, cue) {
  const klasse = name || "offen";
  const text = name || "unclassified";
  const titel = cue ? ` title="${esc(cue)}"` : "";
  return `<span class="plakette ${klasse}"${titel}>${esc(text)}</span>`;
}
function chips(klasse, namen, evidence) {
  return (namen || []).map((name) => {
    const tip = (evidence || {})[name];
    const titel = tip ? ` title="${esc(tip)}"` : "";
    return `<span class="plakette ${klasse}"${titel}>${esc(name)}</span>`;
  }).join(" ");
}

document.getElementById("zahl-karte").addEventListener("click", async () => {
  overlay.hidden = false;
  liste.innerHTML = `<li class="meta">Loading posts …</li>`;
  const antwort = await fetch("/api/posts?" + parameter());
  const daten = await antwort.json();
  document.getElementById("liste-titel").textContent = daten.post_count + " posts";
  document.getElementById("liste-text").textContent =
    daten.city + " · " + daten.channel + " · " + datumKurz(daten.date_from) + " – " + datumKurz(daten.date_to);
  if (!daten.posts.length) {
    liste.innerHTML = `<li>No posts in this selection.</li>`;
    return;
  }
  liste.innerHTML = daten.posts.map((beitrag) => {
    const url = sichereUrl(beitrag.url);
    const titel = url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(beitrag.title)}</a>` : esc(beitrag.title);
    return `<li>
      <div class="meta">${datumKurz(beitrag.date)} · ${esc(beitrag.project)} · ${esc(beitrag.channel)}</div>
      <h3>${titel}</h3>
      <div class="meta">${plakette(beitrag.circle, beitrag.tone_cue)} ${beitrag.tone_cue ? esc(beitrag.tone_cue) : ""} ${beitrag.mockery ? `<span class="plakette fear" title="Ridicule wording in this post, not a separate series">${esc(beitrag.mockery)}</span>` : ""} ${chips("thema", beitrag.categories, beitrag.evidence)} ${beitrag.curated ? `${chips("hope", beitrag.hopes, beitrag.evidence)} ${chips("fear", beitrag.fears, beitrag.evidence)}` : chips("argument", beitrag.arguments, beitrag.evidence)} ${esc(beitrag.source)} · text stance ${esc(beitrag.stance)}</div>
      <p class="snippet">${esc(beitrag.snippet)}</p>
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

const seite = document.querySelector(".seite");
const GROESSEN_KEY = "hungover-blockgroesse";
const SPALTEN = {
  trend: ["--spalte-trend", 150, 480],
  posts: ["--spalte-posts", 130, 380],
  kontext: ["--spalte-kontext", 240, 680],
};

function klemme(wert, min, max) {
  return Math.min(max, Math.max(min, Math.round(wert)));
}
function maxOben() {
  const stil = getComputedStyle(seite);
  const polster = parseFloat(stil.paddingTop) + parseFloat(stil.paddingBottom);
  const kopf = seite.querySelector("header").getBoundingClientRect().height;
  const innen = seite.clientHeight - polster - kopf - 28;
  return Math.max(160, innen - 180);
}
function setzeSpalte(name, px) {
  const [variable, min, max] = SPALTEN[name];
  seite.style.setProperty(variable, klemme(px, min, max) + "px");
}
function setzeOben(px) {
  seite.style.setProperty("--zeile-oben", klemme(px, 160, maxOben()) + "px");
  seite.style.setProperty("--zeile-unten", "1fr");
}
function speichereGroesse() {
  const stil = seite.style;
  const daten = {
    trend: stil.getPropertyValue("--spalte-trend").trim(),
    posts: stil.getPropertyValue("--spalte-posts").trim(),
    kontext: stil.getPropertyValue("--spalte-kontext").trim(),
    oben: stil.getPropertyValue("--zeile-oben").trim(),
    unten: stil.getPropertyValue("--zeile-unten").trim(),
  };
  try {
    if (Object.values(daten).some(Boolean)) localStorage.setItem(GROESSEN_KEY, JSON.stringify(daten));
    else localStorage.removeItem(GROESSEN_KEY);
  } catch (fehler) {}
}
function leseGroesse() {
  try {
    const daten = JSON.parse(localStorage.getItem(GROESSEN_KEY) || "{}");
    if (daten.trend) seite.style.setProperty("--spalte-trend", daten.trend);
    if (daten.posts) seite.style.setProperty("--spalte-posts", daten.posts);
    if (daten.kontext) seite.style.setProperty("--spalte-kontext", daten.kontext);
    if (daten.oben) seite.style.setProperty("--zeile-oben", daten.oben);
    if (daten.unten) seite.style.setProperty("--zeile-unten", daten.unten);
  } catch (fehler) {}
}
function griffeSetzen() {
  const eng = window.matchMedia("(max-width: 1100px)").matches;
  const basis = seite.getBoundingClientRect();
  const kopfEnde = seite.querySelector("header").getBoundingClientRect().bottom;
  const setzen = (griff, rect) => {
    griff.hidden = eng;
    if (eng) return;
    let top = rect.top;
    let height = rect.height;
    if (top < kopfEnde) {
      height -= kopfEnde - top;
      top = kopfEnde;
    }
    if (height < 8 || rect.width < 8) {
      griff.hidden = true;
      return;
    }
    griff.style.left = (rect.left - basis.left + seite.scrollLeft) + "px";
    griff.style.top = (top - basis.top + seite.scrollTop) + "px";
    griff.style.width = rect.width + "px";
    griff.style.height = height + "px";
  };
  const trend = document.querySelector(".trend-karte").getBoundingClientRect();
  const posts = document.querySelector(".zahl-karte").getBoundingClientRect();
  const kontext = document.querySelector(".kontext-karte").getBoundingClientRect();
  const zeit = document.querySelector(".zeit-karte").getBoundingClientRect();
  const luecke = 14;
  setzen(document.querySelector('.griff[data-kante="trend"]'), { left: trend.left - luecke, top: trend.top, width: luecke, height: trend.height });
  setzen(document.querySelector('.griff[data-kante="posts"]'), { left: posts.left - luecke, top: posts.top, width: luecke, height: posts.height });
  setzen(document.querySelector('.griff[data-kante="kontext"]'), { left: kontext.left - luecke, top: kontext.top, width: luecke, height: kontext.height });
  setzen(document.querySelector('.griff[data-kante="zeit"]'), { left: zeit.left, top: zeit.top - luecke, width: zeit.width, height: luecke });
}
function kanteAusRichtung(kante, breite, taste, schritt) {
  if (kante === "kontext") return breite + (taste === "ArrowLeft" ? schritt : -schritt);
  return breite + (taste === "ArrowRight" ? schritt : -schritt);
}
document.querySelectorAll(".griff").forEach((griff) => {
  griff.addEventListener("pointerdown", (ereignis) => {
    if (ereignis.button !== 0 || window.matchMedia("(max-width: 1100px)").matches) return;
    ereignis.preventDefault();
    const kante = griff.dataset.kante;
    const startX = ereignis.clientX;
    const startY = ereignis.clientY;
    const start = {
      trend: document.querySelector(".trend-karte").getBoundingClientRect().width,
      posts: document.querySelector(".zahl-karte").getBoundingClientRect().width,
      kontext: document.querySelector(".kontext-karte").getBoundingClientRect().width,
      oben: buehne.getBoundingClientRect().height,
    };
    griff.classList.add("aktiv");
    document.body.classList.add(kante === "zeit" ? "groesse-zeile" : "groesse-spalte");
    const bewegen = (ev) => {
      if (kante === "zeit") setzeOben(start.oben + (ev.clientY - startY));
      else if (kante === "kontext") setzeSpalte("kontext", start.kontext - (ev.clientX - startX));
      else setzeSpalte(kante, start[kante] + (ev.clientX - startX));
    };
    const ende = () => {
      window.removeEventListener("pointermove", bewegen);
      window.removeEventListener("pointerup", ende);
      window.removeEventListener("pointercancel", ende);
      griff.classList.remove("aktiv");
      document.body.classList.remove("groesse-zeile", "groesse-spalte");
      speichereGroesse();
      griffeSetzen();
    };
    window.addEventListener("pointermove", bewegen);
    window.addEventListener("pointerup", ende);
    window.addEventListener("pointercancel", ende);
    try { griff.setPointerCapture(ereignis.pointerId); } catch (fehler) {}
  });
  griff.addEventListener("dblclick", () => {
    const kante = griff.dataset.kante;
    if (kante === "zeit") {
      seite.style.removeProperty("--zeile-oben");
      seite.style.removeProperty("--zeile-unten");
    } else {
      seite.style.removeProperty(SPALTEN[kante][0]);
    }
    speichereGroesse();
    griffeSetzen();
  });
  griff.addEventListener("keydown", (ereignis) => {
    if (window.matchMedia("(max-width: 1100px)").matches) return;
    const kante = griff.dataset.kante;
    const schritt = ereignis.shiftKey ? 48 : 16;
    if (kante === "zeit") {
      if (ereignis.key !== "ArrowUp" && ereignis.key !== "ArrowDown") return;
      ereignis.preventDefault();
      const oben = buehne.getBoundingClientRect().height;
      setzeOben(oben + (ereignis.key === "ArrowDown" ? schritt : -schritt));
    } else {
      if (ereignis.key !== "ArrowLeft" && ereignis.key !== "ArrowRight") return;
      ereignis.preventDefault();
      const ziel = kante === "trend"
        ? document.querySelector(".trend-karte")
        : kante === "posts"
          ? document.querySelector(".zahl-karte")
          : document.querySelector(".kontext-karte");
      setzeSpalte(kante, kanteAusRichtung(kante, ziel.getBoundingClientRect().width, ereignis.key, schritt));
    }
    speichereGroesse();
  });
});
leseGroesse();
let letzteMasse = "";
function nachGroesse() {
  griffeSetzen();
  const masse = `${buehne.clientWidth}x${buehne.clientHeight}x${chart.clientWidth}x${chart.clientHeight}`;
  if (masse === letzteMasse) return;
  letzteMasse = masse;
  if (zustand.letzter && zustand.ansicht === "circles") zeichneKreise(zustand.letzter);
  if (zustand.serie.length) zeichneChart();
}
new ResizeObserver(nachGroesse).observe(seite);
window.addEventListener("resize", griffeSetzen);

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

    def _asset(self, rel: str):
        if not rel or ".." in rel.split("/"):
            self._sende(b"Forbidden", "text/plain; charset=utf-8", 403)
            return True
        pfad = (ASSETS / rel).resolve()
        if pfad.parent != ASSETS.resolve() or not pfad.is_file():
            return False
        typ = ASSET_MIME.get(pfad.suffix.lower(), "application/octet-stream")
        self._sende(pfad.read_bytes(), typ)
        return True

    def do_GET(self):
        adresse = urlparse(self.path)
        if adresse.path == "/":
            self._sende(SEITE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if adresse.path.startswith("/assets/"):
            if self._asset(adresse.path.removeprefix("/assets/")):
                return
            self._sende(b"Not found", "text/plain; charset=utf-8", 404)
            return
        frage = parse_qs(adresse.query)
        city = (frage.get("city") or [DEFAULT_CITY])[0]
        channel = (frage.get("channel") or [DEFAULT_CHANNEL])[0]
        date_from = (frage.get("date_from") or [None])[0]
        date_to = (frage.get("date_to") or [None])[0]
        try:
            if adresse.path == "/api/summary":
                self._json(summarize(city, channel, date_from, date_to))
                return
            if adresse.path == "/api/posts":
                packet = summarize(city, channel, date_from, date_to)
                frame = load_posts()
                window = select_posts(
                    frame, packet["city"], packet["channel"], packet["date_from"], packet["date_to"]
                )
                self._json({
                    "city": packet["city"],
                    "channel": packet["channel"],
                    "date_from": packet["date_from"],
                    "date_to": packet["date_to"],
                    "post_count": int(len(window)),
                    "posts": list_posts(window, curated_project=packet.get("curated_project")),
                })
                return
        except FileNotFoundError as error:
            self._json({"error": str(error)}, 500)
            return
        self._sende(b"Not found", "text/plain; charset=utf-8", 404)


def main():
    frame = load_posts()
    start, end = date_span(frame)
    print(f"Posts: {len(frame)}")
    print(f"Range: {date_iso(start)} to {date_iso(end)}")
    print("Cities:")
    print(frame["city"].fillna("(no city)").value_counts().to_string())
    print("Channels:")
    print(frame["channel"].fillna("(no channel)").value_counts().to_string())
    print(f"Circles: tone ({STANCE_SOURCE}), separate from text stance")
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    print(f"Dashboard: http://{HOST}:{PORT}")
    print("Stop with Ctrl+C. Restart after a config change.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
