#!/usr/bin/env python3
"""Public-debate dashboard. This file is the page only.

The numbers come from ``analysis/``:

1. ``prepare.py`` reads the filtered posts and sets text, city, and channel.
2. ``stance.py`` sets text stance, vendor tone, and the three circles.
3. ``terms.py`` groups tokens into themes such as Kosten and Nachhaltigkeit.
4. ``curated.py`` replaces those lists for a project with a step-05 file.
5. ``summary.py`` filters, counts the timeline, and reads peak windows
   from ``pipeline/projects_with_context.json``.

City, channel, and stance source live in ``analysis/config.py``.

From the repository root:

    python dashboard.py

Then open http://127.0.0.1:8765
Restart the script after a config change and reload the page.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from analysis.config import (
    CHANNEL_BUTTONS,
    CHANNEL_BY_SOURCE,
    CIRCLES,
    CITY_BUTTONS,
    CITY_BY_PROJECT,
    DEFAULT_CHANNEL,
    DEFAULT_CITY,
    HOST,
    PORT,
    POSTS_FILE,
    STANCE_SOURCE,
)
from analysis.prepare import load_posts
from analysis.summary import date_iso, date_span, list_posts, overview, select_posts, summarize

# notebooks/walk_through_dashboard.ipynb reads these names off this module.


# ===========================================================================
# Oberfläche
# ===========================================================================

SEITE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Public debate</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,500;0,9..144,560;1,9..144,560&family=Outfit:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --papier: #f3eee6;
    --karte: #fffaf4;
    --tinte: #1a1f2b;
    --leise: #746c63;
    --linie: rgba(26, 31, 43, 0.08);
    --akzent: #c56a32;
    --support: #1e6a4a;
    --neutral: #e7e0d4;
    --neutral-tinte: #3c433e;
    --opposition: #8d3d3c;
    --schatten: 0 1px 0 rgba(255, 255, 255, 0.85) inset, 0 16px 36px rgba(72, 44, 18, 0.06);
    --glas: #fffaf4;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; overflow: hidden; }
  body {
    background-color: var(--papier);
    background-image:
      radial-gradient(980px 520px at 6% -12%, rgba(214, 148, 86, 0.28), transparent 58%),
      radial-gradient(760px 480px at 100% 108%, rgba(30, 58, 46, 0.07), transparent 55%),
      repeating-linear-gradient(0deg, transparent, transparent 3px, rgba(26, 31, 43, 0.018) 3px, rgba(26, 31, 43, 0.018) 4px);
    color: var(--tinte);
    font-family: Outfit, "Avenir Next", "Segoe UI", sans-serif;
    font-feature-settings: "ss01" on, "kern" on;
  }
  body::before {
    content: "";
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;
    opacity: 0.22;
    mix-blend-mode: multiply;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.55'/%3E%3C/svg%3E");
  }
  ::selection { background: #f3d3b8; color: var(--tinte); }
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
    grid-template-columns: minmax(0, 1fr) 190px 170px minmax(280px, 360px);
    grid-template-rows: auto minmax(180px, 1fr) minmax(200px, 2fr);
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
    display: flex;
    flex-direction: row-reverse;
    align-items: center;
    justify-content: space-between;
    gap: 24px;
    background: rgba(255, 250, 244, 0.78);
    border: 1px solid rgba(255, 255, 255, 0.7);
    border-radius: 18px;
    padding: 14px 18px;
    box-shadow: var(--schatten);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
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
    color: var(--leise);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    white-space: nowrap;
  }
  .marke { text-align: left; flex: 0 0 auto; }
  .marke strong {
    display: block;
    font-family: Fraunces, Georgia, serif;
    font-style: italic;
    font-weight: 560;
    font-size: 30px;
    letter-spacing: -0.035em;
    line-height: 1;
    color: var(--tinte);
  }
  .marke strong::after {
    content: "";
    display: block;
    width: 32px;
    height: 2px;
    margin-top: 8px;
    border-radius: 2px;
    background: var(--akzent);
  }
  .marke span { display: block; margin-top: 6px; color: var(--leise); font-size: 12.5px; letter-spacing: 0.01em; }
  .segment, .staedte, .medien {
    display: flex;
    flex-wrap: wrap;
    gap: 2px;
    padding: 3px;
    background: #efe6da;
    border-radius: 12px;
  }
  .segment button, .staedte button, .medien button {
    border: 0;
    background: transparent;
    color: var(--tinte);
    border-radius: 9px;
    padding: 6px 11px;
    cursor: pointer;
    font-weight: 500;
    transition: background 0.18s ease, color 0.18s ease, box-shadow 0.18s ease;
  }
  .segment button:hover, .staedte button:hover, .medien button:hover {
    background: rgba(255, 250, 244, 0.7);
  }
  .segment button.aktiv, .staedte button.aktiv, .medien button.aktiv {
    background: var(--tinte);
    color: #fffaf4;
    box-shadow: 0 4px 12px rgba(26, 31, 43, 0.16);
  }
  .staedte button, .medien button {
    padding: 6px 11px;
    font-size: 13px;
  }
  .buehne, .trend-karte, .zahl-karte, .zeit-karte, .kontext-karte {
    background: var(--karte);
    border: 1px solid var(--linie);
    border-radius: 18px;
    box-shadow: var(--schatten);
  }
  .buehne {
    grid-area: buehne;
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 18px 12px 28px;
    min-height: 0;
    height: 100%;
    overflow: hidden;
    background:
      radial-gradient(380px 160px at 50% 42%, rgba(197, 106, 50, 0.09), transparent 72%),
      var(--karte);
  }
  .buehne:has(.themen) {
    align-items: stretch;
    justify-content: center;
  }
  .kreise {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 18px;
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
    line-height: 1.12;
    flex: 0 0 auto;
  }
  .kreis.Support {
    background: radial-gradient(circle at 34% 28%, #4c9a74, #1e6a4a 68%);
    color: #f6fbf8;
    box-shadow: 0 12px 24px rgba(30, 106, 74, 0.2);
  }
  .kreis.Neutral {
    background: radial-gradient(circle at 34% 28%, #f7f3ec, #e4dcd0 72%);
    color: var(--neutral-tinte);
    box-shadow: inset 0 0 0 1px rgba(26, 31, 43, 0.04);
  }
  .kreis.Opposition {
    background: radial-gradient(circle at 34% 28%, #c46a66, #8d3d3c 70%);
    color: #fff8f6;
    box-shadow: 0 12px 24px rgba(141, 61, 60, 0.18);
  }
  .kreis strong {
    font-family: Fraunces, Georgia, serif;
    font-size: 28px;
    font-weight: 560;
    letter-spacing: -0.03em;
  }
  .kreis span { font-size: 12px; letter-spacing: 0.04em; margin-top: 2px; }
  .kreis em { font-style: normal; font-size: 12px; opacity: 0.78; margin-top: 3px; }
  .kreis-fuss {
    position: absolute;
    left: 22px; right: 22px; bottom: 12px;
    color: var(--leise);
    font-size: 12px;
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
    grid-template-columns: minmax(168px, 240px) minmax(0, 1fr) 3.2em;
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
  .thema.hope .balken i { background: linear-gradient(90deg, #4c9a74, #1e6a4a); }
  .thema.fear .balken i { background: linear-gradient(90deg, #c46a66, #8d3d3c); }
  .balken {
    display: block;
    height: 6px;
    background: #efe7dc;
    border-radius: 99px;
    overflow: hidden;
  }
  .balken i {
    display: block;
    height: 100%;
    background: linear-gradient(90deg, #d8894e, var(--akzent));
    border-radius: 99px;
  }
  .thema-wert, .themen-fuss {
    color: var(--leise);
    font-size: 12px;
  }
  .thema-wert {
    font-variant-numeric: tabular-nums;
    text-align: right;
    white-space: nowrap;
  }
  .themen-fuss {
    margin: 10px 0 0;
    text-align: center;
    line-height: 1.4;
  }
  .trend-karte, .zahl-karte {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 16px 14px;
  }
  .trend-karte {
    grid-area: trend;
    align-items: stretch;
    justify-content: flex-start;
    gap: 2px;
  }
  .trend-kopf, .zeit-kopf > span:first-child, .kontext-kopf > span {
    color: var(--leise);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.16em;
    text-transform: uppercase;
  }
  .trend-kopf { text-align: left; }
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
    border-radius: 18px;
    cursor: pointer;
    font-weight: 500;
    transition: border-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
  }
  .pfeil {
    width: 58px;
    height: 58px;
    padding: 12px;
    border-radius: 50%;
    background: #f6efe6;
  }
  .pfeil.up { color: var(--support); background: #e7f3ec; }
  .pfeil.down { color: var(--opposition); background: #f8ecea; }
  .pfeil.flat, .pfeil.unknown { color: var(--leise); }
  .trend-karte p, .zahl-hinweis, .leer {
    color: var(--leise);
    font-size: 12.5px;
    line-height: 1.45;
    margin: 8px 0 0;
  }
  .trend-karte strong {
    display: block;
    margin-top: 8px;
    font-family: Fraunces, Georgia, serif;
    font-size: 18px;
    font-weight: 560;
  }
  .zahl-karte strong {
    font-family: Fraunces, Georgia, serif;
    font-size: 68px;
    font-weight: 560;
    letter-spacing: -0.045em;
    line-height: 0.85;
    color: var(--tinte);
  }
  .zahl-label {
    margin-top: 10px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.16em;
    text-transform: uppercase;
  }
  .zahl-karte:hover {
    border-color: rgba(197, 106, 50, 0.45);
    transform: translateY(-1px);
    box-shadow: 0 1px 0 rgba(255, 255, 255, 0.85) inset, 0 18px 32px rgba(72, 44, 18, 0.1);
  }
  .zeit-karte {
    grid-area: zeit;
    padding: 14px 16px 10px;
    min-width: 0;
    min-height: 0;
    height: 100%;
    display: flex;
    flex-direction: column;
  }
  .kontext-karte {
    grid-area: kontext;
    min-width: 0;
    min-height: 0;
    height: 100%;
    display: flex;
    flex-direction: column;
    padding: 16px 18px 14px;
    overflow: hidden;
    box-shadow: inset 3px 0 0 var(--akzent), 0 1px 0 rgba(255, 255, 255, 0.85) inset, 0 16px 36px rgba(72, 44, 18, 0.06);
  }
  .kontext-kopf {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
  }
  .kontext-kopf button, .blatt header button {
    border: 1px solid var(--linie);
    background: #fffaf4;
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
    background: #fff6ee;
  }
  .kontext-kicker {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin-top: 12px;
  }
  .kontext-karte h2, .blatt header strong, .liste h3 {
    font-family: Fraunces, Georgia, serif;
    font-weight: 560;
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
  .konfidenz.hoch { background: #e5f2eb; color: var(--support); }
  .konfidenz.mittel { background: #f8efe6; color: #8a4b22; }
  .konfidenz.niedrig { background: #efeae2; color: var(--leise); }
  .kontext-scroll, .themen, .liste {
    scrollbar-width: thin;
    scrollbar-color: #ddd3c6 transparent;
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
    background: #f6efe6;
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
  svg.chart text { font-family: Outfit, "Avenir Next", "Segoe UI", sans-serif; }
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
  .doppel { position: relative; height: 22px; margin-top: 4px; padding-left: 42px; }
  .zeit-fuss { padding-left: 42px; }
  .doppel .spur {
    position: absolute;
    left: 0; right: 0; top: 9px;
    height: 3px;
    border-radius: 99px;
    background: #efe6da;
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
    border: 2px solid #fffaf4;
    box-shadow: 0 2px 6px rgba(26, 31, 43, 0.2);
    cursor: grab;
  }
  .doppel input[type="range"]::-moz-range-track { height: 3px; background: transparent; border: none; }
  .doppel input[type="range"]::-moz-range-thumb {
    pointer-events: auto;
    width: 14px; height: 14px;
    border-radius: 50%;
    background: var(--tinte);
    border: 2px solid #fffaf4;
    box-shadow: 0 2px 6px rgba(26, 31, 43, 0.2);
    cursor: grab;
  }
  .staedte, .medien, .segment {
    display: flex;
    flex-wrap: wrap;
    gap: 2px;
    padding: 3px;
    background: #efe6da;
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
    background: #fffaf4;
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
  .plakette.Support { background: #e5f2eb; color: var(--support); }
  .plakette.Neutral { background: #e7e0d4; color: var(--neutral-tinte); }
  .plakette.Opposition { background: #f8e8e6; color: var(--opposition); }
  .plakette.offen, .plakette.thema { background: #f4eee6; color: var(--leise); }
  .plakette.thema { color: var(--tinte); }
  .plakette.argument { background: #f8efe6; color: #8a4b22; }
  .plakette.hope { background: #e5f2eb; color: var(--support); }
  .plakette.fear { background: #f8e8e6; color: var(--opposition); }
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
          <button type="button" data-ansicht="circles" class="aktiv">Stance</button>
          <button type="button" data-ansicht="terms">Themes</button>
          <button type="button" data-ansicht="arguments" title="Expectations, fears, and misunderstandings">Hopes &amp; fears</button>
        </div>
      </div>
    </div>
    <div class="marke">
      <strong>Public debate</strong>
      <span id="untertitel">Timeline, cities, news, and social</span>
    </div>
  </header>
  <section class="buehne" id="buehne"></section>
  <section class="trend-karte">
    <span class="trend-kopf">Trends</span>
    <div class="trend-inhalt" id="trend-inhalt"></div>
  </section>
  <button class="zahl-karte" id="zahl-karte" type="button">
    <strong id="zahl">–</strong>
    <span class="zahl-label">Posts</span>
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
  eltern.innerHTML = "";
  eintraege.forEach((eintrag) => {
    const knopf = document.createElement("button");
    knopf.type = "button";
    knopf.textContent = eintrag.label;
    if (eintrag.hint) knopf.title = eintrag.hint;
    knopf.classList.toggle("aktiv", zustand[schluessel] === eintrag.id);
    knopf.addEventListener("click", () => {
      zustand[schluessel] = eintrag.id;
      zustand.von = null;
      zustand.bis = null;
      zustand.peak = null;
      laden();
    });
    eltern.appendChild(knopf);
  });
}

function pfeil(richtung) {
  const strecke = {
    up: "M32 50 V16 M18 30 L32 14 L46 30",
    down: "M32 14 V48 M18 34 L32 50 L46 34",
    flat: "M12 32 H48 M36 20 L50 32 L36 44",
    unknown: "M18 32 H46",
  }[richtung] || "M18 32 H46";
  return `<svg class="pfeil ${richtung}" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="${strecke}"/></svg>`;
}

function zeichneKreise(daten) {
  const anzahl = daten.circles.counts;
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
      <strong style="font-size:${schrift}px">${prozent(daten.circles.shares[name])}</strong>
      <span style="font-size:${label}px">${name}</span>
      <em>${anzahl[name]}</em>
    </div>`;
  }).join("");
  const fuss = daten.circles.unclassified
    ? `${daten.circles.unclassified} posts have no tone. They count in the total, and they stay out of the circles.`
    : "Shares of the classified posts in the selected window.";
  buehne.innerHTML = `<div class="kreise">${knoten}</div><div class="kreis-fuss">${fuss}</div>`;
}

const BLASEN_REIHENFOLGE = ["Support", "Neutral", "Opposition"];

function zeichneBalken(zeilenQuelle, fuss) {
  if (!zeilenQuelle || !zeilenQuelle.length) {
    buehne.innerHTML = `<p class="leer">Nothing in this selection.</p>`;
    return;
  }
  const maximum = Math.max(...zeilenQuelle.map((eintrag) => eintrag.share || 0), 0.001);
  const zeilen = zeilenQuelle.map((eintrag) => {
    const breite = Math.round(((eintrag.share || 0) / maximum) * 100);
    const hinweis = [eintrag.description, ...(eintrag.terms || [])].filter(Boolean).join(" — ");
    const art = eintrag.polarity === "hope" ? "Hope" : eintrag.polarity === "fear" ? "Fear" : "";
    const klasse = art ? ` ${eintrag.polarity}` : "";
    const name = art ? `<i class="art">${art}</i>${esc(eintrag.label)}` : esc(eintrag.label);
    return `<div class="thema${klasse}" title="${esc(hinweis)}">
      <span class="thema-name">${name}</span>
      <span class="balken"><i style="width:${breite}%"></i></span>
      <span class="thema-wert">${(eintrag.count > 0 && Math.round((eintrag.share || 0) * 100) === 0) ? "&lt;1 %" : prozent(eintrag.share || 0)}</span>
    </div>`;
  }).join("");
  buehne.innerHTML = `<div class="themen">${zeilen}<p class="themen-fuss">${esc(fuss)}</p></div>`;
}

function zeichneAnsicht(daten) {
  if (zustand.ansicht === "terms") {
    zeichneBalken(daten.terms, daten.terms_note || "Share of posts that mention the theme. A post can count in more than one.");
  } else if (zustand.ansicht === "arguments") {
    zeichneBalken(daten.arguments, daten.arguments_note || "Expectations, fears, and misunderstandings. A post can count in more than one.");
  } else {
    zeichneKreise(daten);
  }
}

function zeichneTrend(trend) {
  const delta = trend.delta_points == null ? "" : `<strong>${trend.delta_points} points</strong>`;
  trendEl.innerHTML = `${pfeil(trend.direction)}${delta}<p>${esc(trend.sentence)}</p>`;
}

function indexBei(iso) {
  const stelle = zustand.serie.findIndex((punkt) => punkt.date === iso);
  return stelle < 0 ? 0 : stelle;
}

const Y_ACHSE = 42;

function achsenMaximum(wert) {
  if (wert <= 1) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(wert)));
  const n = wert / mag;
  const schoen = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return schoen * mag;
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
  const rohMax = Math.max(...serie.map((punkt) => punkt.count), 1);
  const maximum = achsenMaximum(rohMax);
  const oben = 8;
  const unten = 8;
  const plotHoehe = Math.max(hoehe - oben - unten, 16);
  const plotBreite = Math.max(breite - Y_ACHSE - 8, 40);
  const schritt = serie.length === 1 ? 0 : plotBreite / (serie.length - 1);
  const vonIndex = indexBei(zustand.von);
  const bisIndex = indexBei(zustand.bis);
  const links = Math.min(vonIndex, bisIndex);
  const rechts = Math.max(vonIndex, bisIndex);
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
    return `<line x1="${Y_ACHSE - 3}" y1="${y.toFixed(1)}" x2="${Y_ACHSE}" y2="${y.toFixed(1)}" stroke="#d9d0c4" stroke-width="1"></line>
      <text x="${Y_ACHSE - 6}" y="${(y + 3).toFixed(1)}" text-anchor="end" fill="#746c63" font-size="10">${gerundet}</text>`;
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
    const farbe = aktiv ? "#2c6b4f" : "#c45c26";
    const radius = aktiv ? 6 : major ? 4.5 : 3;
    const dicke = aktiv ? 2.4 : major ? 1.6 : 1;
    const deckkraft = aktiv ? 1 : major ? 0.9 : 0.45;
    const fenster = (peak.window_from && peak.window_to)
      ? `${datumKurz(peak.window_from)} – ${datumKurz(peak.window_to)}`
      : datumKurz(peak.date);
    const label = `${peak.label} · ${fenster} · ${peak.post_count} posts`
      + (peak.event_type ? ` · ${peak.event_type}` : "")
      + (peak.headline ? `. ${peak.headline}` : "");
    return `<g class="peak-marke" data-peak="${esc(peak.id)}">
      <title>${esc(label)}</title>
      <line x1="${x}" y1="0" x2="${x}" y2="${hoehe}" stroke="${farbe}" stroke-width="14" opacity="0"></line>
      <line x1="${x}" y1="${y}" x2="${x}" y2="${hoehe}" stroke="${farbe}" stroke-width="${dicke}" opacity="${deckkraft * 0.55}"></line>
      <circle cx="${x}" cy="${y}" r="${radius + 2.2}" fill="#fffaf4" opacity="${deckkraft}"></circle>
      <circle cx="${x}" cy="${y}" r="${radius}" fill="${farbe}" opacity="${deckkraft}"></circle>
    </g>`;
  }).join("");
  chart.innerHTML = `
    <defs>
      <linearGradient id="flaeche-licht" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#c56a32" stop-opacity="0.28"></stop>
        <stop offset="100%" stop-color="#c56a32" stop-opacity="0.02"></stop>
      </linearGradient>
    </defs>
    <text transform="translate(12, ${(hoehe / 2).toFixed(1)}) rotate(-90)" text-anchor="middle" fill="#746c63" font-size="10" font-weight="600" letter-spacing="0.08em">POSTS / DAY</text>
    <line x1="${Y_ACHSE}" y1="${oben}" x2="${Y_ACHSE}" y2="${hoehe - unten}" stroke="#d9d0c4" stroke-width="1"></line>
    ${ticks}
    <path d="${flaeche}" fill="url(#flaeche-licht)"></path>
    <path d="${linie}" fill="none" stroke="#c56a32" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"></path>
    <rect x="${Y_ACHSE}" y="0" width="${Math.max(x0 - Y_ACHSE, 0)}" height="${hoehe}" fill="#fffaf4" opacity="0.58" pointer-events="none"></rect>
    <rect x="${x1}" y="0" width="${Math.max(breite - x1, 0)}" height="${hoehe}" fill="#fffaf4" opacity="0.58" pointer-events="none"></rect>
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
  spur.style.background = `linear-gradient(90deg, #efe6da ${links}%, #c56a32 ${links}%, #c56a32 ${rechts}%, #efe6da ${rechts}%)`;
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
  const level = peak.confidence || "niedrig";
  const stufen = { hoch: "high", mittel: "medium", niedrig: "low" };
  const badge = document.getElementById("kontext-konfidenz");
  badge.className = "konfidenz " + level;
  badge.textContent = "Confidence " + (stufen[level] || level);
  document.getElementById("kontext-titel").textContent = peak.event_type || peak.label;
  document.getElementById("kontext-meta").textContent = [
    peak.label,
    datumKurz(peak.window_from || peak.date) + " – " + datumKurz(peak.window_to || peak.date),
    peak.post_count + " posts at peak",
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
  if ((peak.amounts || []).length) {
    bloecke.push(`<div class="kontext-block"><h3>Amounts</h3><div class="chips">${
      peak.amounts.map((amount) => `<span>${esc(amount)}</span>`).join("")
    }</div></div>`);
  }
  if ((peak.headlines || []).length) {
    bloecke.push(`<div class="kontext-block"><h3>Headlines & sources</h3><ul>${
      peak.headlines.map((punkt) => {
        const text = typeof punkt === "string" ? punkt : (punkt.text || "");
        const url = sichereUrl(punkt && punkt.url);
        const inhalt = url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(text)}</a>` : esc(text);
        return `<li>${inhalt}</li>`;
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
  zustand.peaks = daten.peaks || [];
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
  const antwort = await fetch("/api/summary?" + parameter());
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

function plakette(name) {
  const klasse = name || "offen";
  const text = name || "unclassified";
  return `<span class="plakette ${klasse}">${esc(text)}</span>`;
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
      <div class="meta">${plakette(beitrag.circle)} ${chips("thema", beitrag.categories, beitrag.evidence)} ${beitrag.curated ? `${chips("hope", beitrag.hopes, beitrag.evidence)} ${chips("fear", beitrag.fears, beitrag.evidence)}` : chips("argument", beitrag.arguments, beitrag.evidence)} ${esc(beitrag.source)} · vendor tone ${esc(beitrag.vendor_tone)} · text stance ${esc(beitrag.stance)}</div>
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
    print(f"Circle source: {STANCE_SOURCE}")
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
