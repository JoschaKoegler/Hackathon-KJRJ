import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import find_peaks, peak_prominences
from scipy.stats import nbinom, poisson

# ==========================================
# 1. PFADE & PARAMETER
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "clean_data.json"
OUTPUT_FILE = BASE_DIR / "detected_events.json"

SENTIMENT_FEHLWERT = -99      # keine Angabe, geht in keinen Mittelwert ein

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

# ---- Change-Points: Penalty und Mindestlänge wachsen mit der Länge der Zeitreihe ----
CP_PENALTY_FACTOR = 3.0       # Penalty = Faktor * ln(Anzahl Tage)   (höher = nur deutlichere Trendbrüche)
CP_MIN_SEGMENT_SHARE = 0.03   # Mindestlänge eines Segments: 3 % der Zeitreihe (mind. 7 Tage)
CP_DAYS_PER_POINT = 120       # höchstens ~1 Trendbruch je 120 Tage (mind. 2, höchstens 6)


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
    """Lokale Maxima über der dynamischen Schwelle (inkl. erstem/letztem Tag durch Padding)."""
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
# 3. CHANGE-POINT DETECTION (Binary Segmentation, reines NumPy)
# ==========================================
def detect_changepoints_binseg(series: np.ndarray, penalty: float, min_size: int, max_points: int) -> list[int]:
    """Findet dauerhafte Niveauwechsel; behält höchstens `max_points` mit dem größten Gewinn."""
    def sse(arr: np.ndarray) -> float:
        if len(arr) == 0:
            return 0.0
        return float(np.sum((arr - np.mean(arr)) ** 2))

    found: list[tuple[int, float]] = []

    def split_segment(start: int, end: int):
        if end - start < 2 * min_size:
            return
        total_cost = sse(series[start:end])
        best_gain, best_idx = 0.0, None
        for idx in range(start + min_size, end - min_size + 1):
            gain = total_cost - (sse(series[start:idx]) + sse(series[idx:end]))
            if gain > best_gain:
                best_gain, best_idx = gain, idx
        if best_idx is not None and best_gain > penalty:
            found.append((best_idx, best_gain))
            split_segment(start, best_idx)
            split_segment(best_idx, end)

    split_segment(0, len(series))
    top = sorted(found, key=lambda t: -t[1])[:max_points]
    return sorted(idx for idx, _ in top)


def prepare_changepoint_series(counts: np.ndarray) -> np.ndarray | None:
    """Einzelne Spikes werden gekappt, damit sie keine 'Trendbrüche' auslösen; danach normiert."""
    cap = max(float(np.quantile(counts, 0.98)), 1.0)
    series = np.minimum(counts, cap)
    if np.std(series) == 0:
        series = counts
    std = np.std(series)
    if std == 0:
        return None
    return (series - np.mean(series)) / std


# ==========================================
# 4. ZEITREIHEN-ANALYSE PRO PROJEKT
# ==========================================
def analyze_project_timeseries(df_proj: pd.DataFrame, project_name: str) -> dict:
    df_proj = df_proj.copy()
    if "sentiment" in df_proj.columns:
        df_proj["sentiment"] = pd.to_numeric(df_proj["sentiment"], errors="coerce")
        df_proj.loc[df_proj["sentiment"].eq(SENTIMENT_FEHLWERT), "sentiment"] = np.nan
    else:
        df_proj["sentiment"] = np.nan

    daily = df_proj.groupby("date").agg(
        count=("published_at", "size"),
        avg_sentiment=("sentiment", "mean")
    )

    full_idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_idx)
    daily["count"] = daily["count"].fillna(0)

    counts = daily["count"].values.astype(float)
    n_days = len(counts)
    date_range = f"{daily.index.min().strftime('%Y-%m-%d')} bis {daily.index.max().strftime('%Y-%m-%d')}"

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
        ws, we = max(0, idx - 3), min(n_days, idx + 3)  # Peak-Tag -3 ... +2 (wie crawler_window)
        excess = max(0.0, float(counts[ws:we].sum() - base[ws:we].sum()))
        sample_titles = df_proj[df_proj["date"] == peak_date]["title"].dropna().unique()[:2].tolist()
        sent = daily["avg_sentiment"].iloc[idx]

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

    # --- B) Dauerhafte Trendwenden ---
    change_points = []
    norm_counts = prepare_changepoint_series(counts)
    if norm_counts is not None:
        min_size = max(7, int(round(CP_MIN_SEGMENT_SHARE * n_days)))
        max_points = int(np.clip(round(n_days / CP_DAYS_PER_POINT), 2, 6))
        cp_indices = detect_changepoints_binseg(
            norm_counts, penalty=CP_PENALTY_FACTOR * math.log(n_days), min_size=min_size, max_points=max_points)

        boundaries = [0] + cp_indices + [n_days]
        for pos, idx in enumerate(cp_indices):
            cp_date = daily.index[idx]
            prev_start, next_end = boundaries[pos], boundaries[pos + 2]
            mean_before = float(np.mean(counts[prev_start:idx]))
            mean_after = float(np.mean(counts[idx:next_end]))
            sent_before = daily["avg_sentiment"].iloc[prev_start:idx].mean()
            sent_after = daily["avg_sentiment"].iloc[idx:next_end].mean()

            change_points.append({
                "date": cp_date.strftime("%Y-%m-%d"),
                "avg_posts_before": round(mean_before, 2),
                "avg_posts_after": round(mean_after, 2),
                "avg_sentiment_before": round(float(sent_before), 2) if pd.notna(sent_before) else None,
                "avg_sentiment_after": round(float(sent_after), 2) if pd.notna(sent_after) else None
            })

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
        print(f"FEHLER: '{INPUT_FILE.name}' nicht gefunden. Bitte zuerst '1_filter_data.py' ausführen!")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        clean_data = json.load(f)

    if not clean_data:
        print("Die bereinigte Datei ist leer.")
        return

    df = pd.DataFrame(clean_data)
    df["date"] = pd.to_datetime(df["published_at"], utc=True, errors="coerce").dt.tz_localize(None).dt.floor("D")
    if "sentiment" in df.columns:
        df["sentiment"] = pd.to_numeric(df["sentiment"], errors="coerce")
        df.loc[df["sentiment"].eq(SENTIMENT_FEHLWERT), "sentiment"] = np.nan
    else:
        df["sentiment"] = np.nan
    df = df.dropna(subset=["date"]).copy()

    df_exploded = df.explode("matched_projects").rename(columns={"matched_projects": "project"})

    all_results = []
    print("\n" + "=" * 75)
    print("ERGEBNISSE DER PEAK- & CHANGE-POINT-ANALYSE")
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
                  f"Rang {p['rank']}, Sentiment: {p['avg_sentiment']})")
            for title in p["sample_titles"]:
                print(f"      Beispiel-Titel: \"{title[:80]}\"")

        print("\n  [CHANGE-POINTS - Dauerhafte Niveau-/Trendwechsel]")
        if not res["change_points"]:
            print("    -> Keine dauerhaften Trendbrüche gefunden.")
        for cp in res["change_points"]:
            direction = "ANSTIEG" if cp["avg_posts_after"] > cp["avg_posts_before"] else "RÜCKGANG"
            print(f"    * {cp['date']} ({direction}): Schnitt {cp['avg_posts_before']} -> {cp['avg_posts_after']} Posts/Tag "
                  f"| Sentiment: {cp['avg_sentiment_before']} -> {cp['avg_sentiment_after']}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 75)
    print(f"Fertig! Exportiert nach: {OUTPUT_FILE.name}")


if __name__ == "__main__":
    main()