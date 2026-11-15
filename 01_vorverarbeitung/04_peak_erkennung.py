"""04. Peak-Erkennung — Tageszählung gegen die lokale Baseline.

Liest ``00_data/posts.json`` (gespeicherter ``tone_score``, ``story_key``).
Schreibt ``01_vorverarbeitung/peaks.json`` mit ``peaks``.
Trendbrüche schreibt ``05_trendbrueche.py`` in dieselbe Datei.
``06_peak_kontext.py`` liest sie. Das Dashboard liest erst ``00_data/context.json``.
"""
import importlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import find_peaks, peak_prominences
from scipy.stats import nbinom, poisson

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_config = importlib.import_module("02_laufzeit.config")
_fenster = importlib.import_module("02_laufzeit.fenster")
_sent = importlib.import_module("01_vorverarbeitung.02_sentiment_analyse")
PEAKS_FILE = _config.PEAKS_FILE
POSTS_FILE = _config.POSTS_FILE
collapse_rows = _fenster.collapse_rows
describe = _fenster.describe
as_score = _fenster.as_score
story_key = _sent.story_key

# ==========================================
# 1. PFADE & PARAMETER
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = POSTS_FILE
OUTPUT_FILE = PEAKS_FILE

# ---- Peak-Erkennung: keine festen Post-Zahlen, alles leitet sich aus der Zeitreihe ab ----
# Ein Tag ist ein Peak, wenn seine Postzahl bei der lokalen Normalität (Baseline) und der
# typischen Streuung des Projekts statistisch nicht mehr als Zufall erklärbar ist.
PEAK_FALSE_ALARMS = 0.5       # erwartete Zufalls-Peaks pro Zeitreihe (kleiner = strenger)
BASELINE_HALF_WINDOW = 28     # Tage links/rechts für die lokale Baseline
BASELINE_EXCLUDE = 3          # Tage rund um den Prüftag, die nicht in die Baseline einfließen
BASELINE_TRIM = 0.10          # oberste 10 % im Fenster zählen nicht (Peaks verfälschen die Baseline nicht)
MIN_BASELINE_DAYS = 14        # weniger Tage im Fenster -> globale Baseline
MIN_PEAK_DISTANCE_DAYS = 7    # Mindestabstand zwischen zwei Peaks
MAX_DISPERSION = 3.0          # Obergrenze für die Überdispersion (Negativ-Binomial)

# ---- Auswahl für den Zeitstrahl: "Haupt-Peaks" (major) vs. "weitere Peaks" (minor) ----
# Alle statistisch auffälligen Peaks bleiben erhalten (tier = "minor"), die UI zeigt standardmäßig nur "major".
DAYS_PER_MAJOR_PEAK = 90      # ca. 1 Haupt-Peak pro Quartal der Zeitreihe
MIN_MAJOR_PEAKS = 3
MAX_MAJOR_PEAKS = 10

# ==========================================
# 2. HILFSFUNKTIONEN: BASELINE, STREUUNG, SCHWELLEN
# ==========================================
def trimmed_mean(values, trim: float) -> float:
    """Mittelwert ohne die obersten `trim`-Prozent der Werte (robust gegen Peaks)."""
    v = np.sort(np.asarray(values, dtype=float))
    if len(v) == 0:
        return 0.0
    drop = int(math.ceil(trim * len(v)))
    kept = v[: len(v) - drop] if drop < len(v) else v[:1]
    return float(kept.mean())


def local_baseline(counts: np.ndarray) -> np.ndarray:
    """Lokale Normalität pro Tag: getrimmter Mittelwert im Umfeld (ohne die Tage direkt um den Prüftag)."""
    n = len(counts)
    floor = max(0.5 * float(counts.mean()), 1e-3)  # verhindert Baseline 0 bei sehr dünnen Reihen
    global_base = max(trimmed_mean(counts, BASELINE_TRIM), floor)
    base = np.full(n, global_base)
    for i in range(n):
        lo, hi = max(0, i - BASELINE_HALF_WINDOW), min(n, i + BASELINE_HALF_WINDOW + 1)
        left = counts[lo:max(lo, i - BASELINE_EXCLUDE)]
        right = counts[min(hi, i + BASELINE_EXCLUDE + 1):hi]
        window = np.concatenate([left, right])
        if len(window) >= MIN_BASELINE_DAYS:
            base[i] = max(trimmed_mean(window, BASELINE_TRIM), floor)
    return base


def estimate_dispersion(counts: np.ndarray) -> float:
    """
    Überdispersion der Tageszahlen (Nachrichten kommen in Schüben): alpha = (Var - Mittel) / Mittel^2.
    Geschätzt ohne die obersten 2 % der Tage, damit echte Peaks die Streuung nicht aufblähen.
    alpha = 0 entspricht einer reinen Poisson-Verteilung.
    """
    sub = counts[counts <= np.quantile(counts, 0.98)]
    if len(sub) < 3:
        return 0.0
    m, v = float(sub.mean()), float(sub.var(ddof=1))
    if m <= 0:
        return 0.0
    return float(min(max((v - m) / (m * m), 0.0), MAX_DISPERSION))


def peak_thresholds(base: np.ndarray, dispersion: float, q: float) -> np.ndarray:
    """Kleinste Tageszahl pro Tag, die unter der Normalität höchstens mit Wahrscheinlichkeit q auftritt."""
    if dispersion < 1e-6:
        k = poisson.isf(q, base)
    else:
        n_param = 1.0 / dispersion
        k = nbinom.isf(q, n_param, n_param / (n_param + base))
    return np.floor(k) + 1.0


def significance(count: float, base: float, dispersion: float) -> float:
    """-log10(p): wie unwahrscheinlich ist diese Tageszahl unter der lokalen Normalität? (gedeckelt bei 300)"""
    if dispersion < 1e-6:
        logp = poisson.logsf(count - 1, base)
    else:
        n_param = 1.0 / dispersion
        logp = nbinom.logsf(count - 1, n_param, n_param / (n_param + base))
    value = -float(logp) / math.log(10)
    return float(min(max(value, 0.0), 300.0)) if np.isfinite(value) else 300.0


def detect_peak_days(counts: np.ndarray, base: np.ndarray, dispersion: float) -> np.ndarray:
    """Lokale Maxima über der dynamischen Schwelle (inkl. erstem/letztem Tag durch Padding).

    Keine feste Postzahl. Die Schwelle folgt Baseline und Streuung der jeweiligen Reihe.
    """
    n = len(counts)
    q = PEAK_FALSE_ALARMS / n
    thr = peak_thresholds(base, dispersion, q)
    padded = np.concatenate([[0.0], counts, [0.0]])
    thr_pad = np.concatenate([[np.inf], thr, [np.inf]])
    idx, _ = find_peaks(padded, height=thr_pad, distance=MIN_PEAK_DISTANCE_DAYS)
    return idx - 1


def assign_tiers(peaks: list[dict], n_days: int) -> dict:
    """
    Wählt die wichtigsten Peaks für den Zeitstrahl: Rang nach Überschuss-Posts (Posts über der Baseline
    im Peak-Fenster). Anzahl und Mindestabstand skalieren mit der Länge der Zeitreihe.
    """
    k_max = int(np.clip(round(n_days / DAYS_PER_MAJOR_PEAK), MIN_MAJOR_PEAKS, MAX_MAJOR_PEAKS))
    spacing = max(MIN_PEAK_DISTANCE_DAYS, n_days // (2 * k_max))

    order = sorted(range(len(peaks)), key=lambda i: (-peaks[i]["excess_posts"], -peaks[i]["significance"], peaks[i]["_idx"]))
    for rank, i in enumerate(order, start=1):
        peaks[i]["rank"] = rank
        peaks[i]["tier"] = "minor"

    chosen: list[int] = []
    for i in order:
        if len(chosen) >= k_max:
            break
        if all(abs(peaks[i]["_idx"] - peaks[j]["_idx"]) > spacing for j in chosen):
            chosen.append(i)
            peaks[i]["tier"] = "major"
    return {"max_major_peaks": k_max, "min_spacing_days": int(spacing), "n_major": len(chosen)}


# ==========================================
# 4. ZEITREIHEN-ANALYSE PRO PROJEKT
# ==========================================
def _tone_stories(df_proj: pd.DataFrame) -> pd.DataFrame:
    """One story per stored title key. Score is 2, 1, 0, or missing. -99 never enters."""
    rows = []
    for record in df_proj.to_dict("records"):
        stored_key = record.get("story_key")
        if isinstance(stored_key, str) and stored_key.strip():
            key = stored_key
        else:
            key = story_key(record.get("title"), record.get("mention_id"))
        rows.append({
            "date": record.get("date"),
            "mention_id": record.get("mention_id"),
            "story_key": key,
            "tone_score": as_score(record.get("tone_score")),
        })
    stories = pd.DataFrame(collapse_rows(rows))
    if stories.empty:
        return stories
    stories["tone_score"] = pd.to_numeric(stories["tone_score"], errors="coerce")
    stories["date"] = pd.to_datetime(stories["date"])
    return stories


def analyze_project_timeseries(df_proj: pd.DataFrame, project_name: str) -> dict:
    df_proj = df_proj.copy()
    stories = _tone_stories(df_proj)

    daily = df_proj.groupby("date").agg(count=("published_at", "size"))
    if not stories.empty:
        tone_daily = stories.groupby("date")["tone_score"].agg(avg_sentiment="mean", tone_n="count")
        tone_daily["tone_stories"] = stories.groupby("date").size()
        tone_daily["tone_missing"] = tone_daily["tone_stories"] - tone_daily["tone_n"]
        daily = daily.join(tone_daily[["avg_sentiment", "tone_n", "tone_missing"]], how="left")
    else:
        daily["avg_sentiment"] = np.nan
        daily["tone_n"] = 0
        daily["tone_missing"] = 0

    full_idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_idx)
    daily["count"] = daily["count"].fillna(0)

    counts = daily["count"].values.astype(float)
    n_days = len(counts)
    date_range = f"{daily.index.min().strftime('%Y-%m-%d')} to {daily.index.max().strftime('%Y-%m-%d')}"

    empty = {
        "project": project_name,
        "total_posts": int(counts.sum()),
        "date_range": date_range,
        "peak_selection": None,
        "peaks": [],
        "change_points": []
    }
    if n_days < 14 or np.std(counts) == 0:
        return empty

    # --- A) Peaks ---
    base = local_baseline(counts)
    dispersion = estimate_dispersion(counts)
    peak_idx = detect_peak_days(counts, base, dispersion)

    prominences = np.zeros(len(peak_idx))
    if len(peak_idx):
        padded = np.concatenate([[0.0], counts, [0.0]])
        prominences = peak_prominences(padded, peak_idx + 1)[0]

    peaks = []
    for k, idx in enumerate(peak_idx):
        idx = int(idx)
        peak_date = daily.index[idx]
        if float(counts[idx]) <= float(base[idx]):
            continue
        ws, we = max(0, idx - 3), min(n_days, idx + 3)  # Peak-Tag -3 ... +2 (wie crawler_window)
        excess = max(0.0, float(counts[ws:we].sum() - base[ws:we].sum()))
        sample_titles = df_proj[df_proj["date"] == peak_date]["title"].dropna().unique()[:2].tolist()
        sent = daily["avg_sentiment"].iloc[idx]
        tone_n = daily["tone_n"].iloc[idx] if "tone_n" in daily.columns else 0
        tone_missing = daily["tone_missing"].iloc[idx] if "tone_missing" in daily.columns else 0

        peaks.append({
            "_idx": idx,
            "date": peak_date.strftime("%Y-%m-%d"),
            "post_count": int(counts[idx]),
            "baseline_posts_per_day": round(float(base[idx]), 2),
            "relative_to_baseline": round(float(counts[idx] / base[idx]), 1),
            "significance": round(significance(counts[idx], base[idx], dispersion), 1),
            "excess_posts": round(excess, 1),
            "prominence": round(float(prominences[k]), 2),
            "avg_sentiment": round(float(sent), 2) if pd.notna(sent) else None,
            "tone_n": int(tone_n) if pd.notna(tone_n) else 0,
            "tone_missing": int(tone_missing) if pd.notna(tone_missing) else 0,
            "crawler_window": {
                "start": (peak_date - pd.Timedelta(days=3)).strftime("%Y-%m-%d"),
                "end": (peak_date + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
            },
            "sample_titles": sample_titles
        })

    selection = assign_tiers(peaks, n_days) if peaks else {"max_major_peaks": 0, "min_spacing_days": 0, "n_major": 0}
    selection.update({
        "n_significant_peaks": len(peaks),
        "dispersion": round(dispersion, 3),
        "false_alarm_budget": PEAK_FALSE_ALARMS
    })
    for p in peaks:
        p.pop("_idx", None)

    change_points = []

    return {
        "project": project_name,
        "total_posts": int(counts.sum()),
        "date_range": date_range,
        "peak_selection": selection,
        "peaks": peaks,
        "change_points": change_points
    }


# ==========================================
# 5. HAUPTPROGRAMM & KONSOLEN-AUSGABE
# ==========================================
def main():
    if not INPUT_FILE.exists():
        print(f"FEHLER: '{INPUT_FILE}' nicht gefunden. Bitte zuerst 01_filtern.py, 02_sentiment_analyse.py und 03_stance_analyse.py ausführen.")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        clean_data = json.load(f)

    if clean_data and isinstance(clean_data[0], dict) and "tone_score" not in clean_data[0]:
        print("WARNUNG: tone_score fehlt. Zuerst 02_sentiment_analyse.py. Fehlende Scores zählen als nicht bewertet.")

    if not clean_data:
        print("Die bereinigte Datei ist leer.")
        return

    df = pd.DataFrame(clean_data)
    df["date"] = pd.to_datetime(df["published_at"], utc=True, errors="coerce").dt.tz_localize(None).dt.floor("D")
    df = df.dropna(subset=["date"]).copy()

    df_exploded = df.explode("matched_projects").rename(columns={"matched_projects": "project"})

    all_results = []
    print("\n" + "=" * 75)
    print("ERGEBNISSE DER PEAK-ERKENNUNG")
    print("=" * 75)

    for project, group in df_exploded.groupby("project"):
        res = analyze_project_timeseries(group, project)
        all_results.append(res)

        print(f"\nPROJEKT: {res['project']} ({res['total_posts']} Beiträge | {res['date_range']})")
        print("-" * 75)

        sel = res["peak_selection"]
        if sel:
            print(f"  [PEAKS] {sel['n_significant_peaks']} statistisch auffällig, davon {sel['n_major']} Haupt-Peaks "
                  f"(max. {sel['max_major_peaks']}, Mindestabstand {sel['min_spacing_days']} Tage, "
                  f"Streuung alpha={sel['dispersion']})")
        majors = sorted([p for p in res["peaks"] if p["tier"] == "major"], key=lambda p: p["date"])
        if not majors:
            print("    -> Keine signifikanten Peaks gefunden.")
        for p in majors:
            print(f"    * {p['date']} | {p['post_count']} Posts (Baseline {p['baseline_posts_per_day']}/Tag, "
                  f"{p['relative_to_baseline']}x, Signifikanz {p['significance']}, Überschuss {p['excess_posts']} Posts, "
                  f"Rang {p['rank']}, Ton-Mittel {p['avg_sentiment']} "
                  f"(n={p['tone_n']}, fehlend={p['tone_missing']}, Skala 0–2)")
            for title in p["sample_titles"]:
                print(f"      Beispiel-Titel: \"{title[:80]}\"")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 75)
    print(f"Fertig! Exportiert nach: {OUTPUT_FILE}  →  05_trendbrueche.py")


if __name__ == "__main__":
    main()