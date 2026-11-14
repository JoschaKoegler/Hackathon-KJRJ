#!/usr/bin/env python3
"""Public-debate dashboard. This file is the page only.

The numbers come from ``analysis/``:

1. ``prepare.py`` reads the filtered posts and sets text, city, and channel.
2. ``stance.py`` sets text stance, vendor tone, and the three circles.
3. ``terms.py`` supplies the word-cloud terms.
4. ``summary.py`` filters, counts the timeline, and reads peak markers.

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
<style>
  :root {
    --papier: #f3efe6;
    --karte: #fbf8f2;
    --tinte: #1e1a16;
    --leise: #6f675e;
    --linie: #e3d9c8;
    --support: #1c7a4d;
    --neutral: #e7e1d6;
    --neutral-tinte: #3f3a34;
    --opposition: #a33b2b;
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
  .kreis.Support { background: var(--support); color: #f4fff8; }
  .kreis.Neutral { background: var(--neutral); color: var(--neutral-tinte); border: 1px solid #d9d0c2; }
  .kreis.Opposition { background: var(--opposition); color: #fff6f3; }
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
  .pfeil.up { color: var(--support); }
  .pfeil.down { color: var(--opposition); }
  .pfeil.flat, .pfeil.unknown { color: var(--leise); }
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
  .plakette.Support { background: #e5f5ec; color: var(--support); }
  .plakette.Neutral { background: #ece7dc; color: var(--neutral-tinte); }
  .plakette.Opposition { background: #fde8e4; color: var(--opposition); }
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
      <button type="button" data-ansicht="circles" class="aktiv">Stance</button>
      <button type="button" data-ansicht="terms">Terms</button>
    </div>
    <div class="marke">
      <strong>Public debate</strong>
      <span id="untertitel">Timeline, cities, news, and social</span>
    </div>
  </header>
  <section class="buehne" id="buehne"></section>
  <section class="trend-karte" id="trend"></section>
  <button class="zahl-karte" id="zahl-karte" type="button">
    <strong id="zahl">–</strong>
    <span class="zahl-label">Posts</span>
    <span class="zahl-hinweis">Show the posts in this selection</span>
  </button>
  <section class="zeit-karte">
    <div class="zeit-kopf">
      <span>Timeline</span>
      <div class="legende">
        <div class="staedte" id="staedte"></div>
        <div class="medien" id="medien"></div>
      </div>
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
  ansicht: "circles",
  stadt: "All",
  medium: "News",
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

function zeichneWolke(woerter) {
  if (!woerter.length) {
    buehne.innerHTML = `<p class="leer">No terms in this selection.</p>`;
    return;
  }
  const maximum = woerter[0].count || 1;
  const knoten = woerter.map((eintrag) => {
    const groesse = 16 + (eintrag.count / maximum) * 38;
    return `<b style="font-size:${groesse}px">${esc(eintrag.term)}<small>${eintrag.count}</small></b>`;
  }).join("");
  buehne.innerHTML = `<div class="wolke">${knoten}</div>`;
}

function zeichneTrend(trend) {
  const delta = trend.delta_points == null ? "" : `<strong>${trend.delta_points} points</strong>`;
  trendEl.innerHTML = `${pfeil(trend.direction)}${delta}<p>${esc(trend.sentence)}</p>`;
}

function indexBei(iso) {
  const stelle = zustand.serie.findIndex((punkt) => punkt.date === iso);
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
  const maximum = Math.max(...serie.map((punkt) => punkt.count), 1);
  const schritt = serie.length === 1 ? 0 : breite / (serie.length - 1);
  const vonIndex = indexBei(zustand.von);
  const bisIndex = indexBei(zustand.bis);
  const links = Math.min(vonIndex, bisIndex);
  const rechts = Math.max(vonIndex, bisIndex);
  const punkte = serie.map((punkt, index) => {
    const x = index * schritt;
    const y = hoehe - 8 - (punkt.count / maximum) * (hoehe - 16);
    return [x, y];
  });
  const linie = punkte.map((punkt, index) => `${index ? "L" : "M"}${punkt[0].toFixed(1)},${punkt[1].toFixed(1)}`).join(" ");
  const flaeche = `${linie} L${breite},${hoehe} L0,${hoehe} Z`;
  const x0 = punkte[links][0];
  const x1 = punkte[rechts][0];
  const peaks = (zustand.peaks || []).map((peak) => {
    const index = serie.findIndex((punkt) => punkt.date === peak.date);
    if (index < 0) return "";
    const x = (index * schritt).toFixed(1);
    const label = `${peak.label} ${peak.date}: ${peak.post_count} posts` + (peak.headline ? `. ${peak.headline}` : "");
    return `<line x1="${x}" y1="2" x2="${x}" y2="${hoehe}" stroke="#a33b2b" stroke-width="1" opacity="0.55"><title>${esc(label)}</title></line>`;
  }).join("");
  chart.innerHTML = `
    <path d="${flaeche}" fill="#1e1a16" opacity="0.08"></path>
    <path d="${linie}" fill="none" stroke="#1e1a16" stroke-width="1.4"></path>
    ${peaks}
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
  document.getElementById("zeit-spanne").textContent = gewaehlt === 1 ? "1 day selected" : gewaehlt + " days selected";
}

function zeichne(daten) {
  zustand.letzter = daten;
  zustand.serie = daten.timeline;
  zustand.peaks = daten.peaks || [];
  zustand.von = daten.date_from;
  zustand.bis = daten.date_to;
  schalter(staedteEl, daten.cities, "stadt");
  schalter(medienEl, daten.channels, "medium");
  if (zustand.ansicht === "terms") zeichneWolke(daten.terms);
  else zeichneKreise(daten);
  zeichneTrend(daten.trend);
  zahlEl.textContent = String(daten.post_count);
  zeichneChart();
  schieberZeichnen();
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
  if (zustand.ansicht === "terms") zeichneWolke(zustand.letzter.terms);
  else zeichneKreise(zustand.letzter);
  if (zustand.serie.length) zeichneChart();
});

ansichtEl.addEventListener("click", (ereignis) => {
  const knopf = ereignis.target.closest("button");
  if (!knopf) return;
  zustand.ansicht = knopf.dataset.ansicht;
  [...ansichtEl.children].forEach((eintrag) => eintrag.classList.toggle("aktiv", eintrag === knopf));
  if (zustand.letzter) {
    if (zustand.ansicht === "terms") zeichneWolke(zustand.letzter.terms);
    else zeichneKreise(zustand.letzter);
  }
});

function plakette(name) {
  const klasse = name || "offen";
  const text = name || "unclassified";
  return `<span class="plakette ${klasse}">${esc(text)}</span>`;
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
      <div class="meta">${plakette(beitrag.circle)} ${esc(beitrag.source)} · vendor tone ${esc(beitrag.vendor_tone)} · text stance ${esc(beitrag.stance)}</div>
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
                    "posts": list_posts(window),
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
