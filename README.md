# Riding the Sentiment

Öffentliche Debatte zu Seilbahn Heilbronn im Vergleich mit Bonn, Paris Câble C1 und IPAI-Campus.

Roh-Export (zu groß für Git): `../FSI_Heilbronn_Medienbeiträge (1).json`.

## Stufen

`01_vorverarbeitung/` schreibt `00_data/` (Batch). `02_laufzeit/` liest `00_data/` und bewertet nicht neu. `03_dashboard.py` ist die HTTP-Seite.

```
01_vorverarbeitung/
  01_filtern.py              Roh-Export + 00_data/definitions.json
       └─ projekt_overlay.py assigned/, briefs/
                             → 00_data/posts.json
                             → unused_data.json (alle verworfenen Beiträge)
  02_sentiment_analyse.py    Passage 0/1/2 → tone_score, tone_cue, tone_gap, story_key, circle
  03_stance_analyse.py       support/oppose/mixed → stance
  04_peak_erkennung.py       Tageszählung gegen lokale Baseline → peaks.json
  05_trendbrueche.py         Binary Segmentation → change_points in peaks.json
  06_peak_kontext.py         orchestriert den Kontext → 00_data/context.json
       06_begriffe.py        auffällige Begriffe (Log-Odds)
       06_ereignistyp.py     Ereignistyp aus Mustern
       06_externe_suche.py   Google News / Projektseite
       06_nachwirkung.py     Abklingen und Ton davor/danach
  07_themen_zuordnung.py     kuratierte Regex → 00_data/themes.json
  08_token_fallback.py       Token- und Claim-Listen → terms, categories, arguments

02_laufzeit/
  config.py                  Pfade und Schalter
  beitraege.py               laden, Stadt/Kanal/Datum, gespeicherte Felder
  fenster.py                 Anteile, Wilson, Balance, Story-Kollaps
  kuratierte_themen.py       Anteile aus themes.json, Faktenblatt
  auswertung.py              Fenster, Trend, Peak-Marker, HTTP-Daten

03_dashboard.py              HTTP: /, /assets/*, /api/summary, /api/posts
00_data/                     posts, definitions, context, themes, facts
00_logo/                     Logo, ausgeliefert unter /assets/
```

| Datei | Geschrieben von | Gelesen von |
| --- | --- | --- |
| `00_data/posts.json` | Filter, dann Sentiment, Stance, Token-Fallback | Laufzeit, Peaks, Trendbrüche, Kontext, Themen |
| `00_data/definitions.json` | von Hand | Filter und Sentiment |
| `01_vorverarbeitung/peaks.json` | Peak-Erkennung, dann Trendbrüche | Peak-Kontext |
| `00_data/context.json` | Peak-Kontext | `auswertung.py` |
| `01_vorverarbeitung/themen/<projekt>.json` | von Hand | nur die kuratierte Themen-Zuordnung |
| `00_data/themes.json` | kuratierte Themen-Zuordnung | `kuratierte_themen.py` |
| `00_data/facts.json` | von Hand | `kuratierte_themen.py` |

Pfade stehen einmal in `02_laufzeit/config.py`.

## Start

```bash
pip install -r requirements.txt
python 03_dashboard.py
```

http://127.0.0.1:8765 — nach Änderung an `00_data/` oder `config.py` neu starten.

## Daten neu aufbereiten

```bash
python 01_vorverarbeitung/01_filtern.py
python 01_vorverarbeitung/02_sentiment_analyse.py
python 01_vorverarbeitung/03_stance_analyse.py
python 01_vorverarbeitung/08_token_fallback.py
python 01_vorverarbeitung/04_peak_erkennung.py
python 01_vorverarbeitung/05_trendbrueche.py
python 01_vorverarbeitung/06_peak_kontext.py    # Netzwerk für die externe Suche
python 01_vorverarbeitung/07_themen_zuordnung.py
python 03_dashboard.py
```
