import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.signal import find_peaks

# ==========================================
# 1. PFADE & PARAMETER
# ==========================================
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
INPUT_FILE = DATA_DIR / "01_filtered" / "posts.json"
OUTPUT_FILE = DATA_DIR / "02_peaks" / "peaks.json"

MIN_PEAK_DISTANCE_DAYS = 7    # Mindestabstand zwischen zwei Peaks in Tagen
PROMINENCE_FACTOR = 1.5       # Höher = nur extremere Ausschläge werden erkannt
CHANGEPOINT_PENALTY = 12.0    # Höher = nur sehr deutliche Trendwenden (z.B. 8.0 - 20.0)
SENTIMENT_FEHLWERT = -99      # keine Angabe, geht in keinen Mittelwert ein


# ==========================================
# 2. REINE NUMPY CHANGE-POINT DETECTION (Binary Segmentation)
# ==========================================
def detect_changepoints_binseg(series: np.ndarray, penalty: float = 12.0, min_size: int = 7) -> list[int]:
    """Findet dauerhafte Niveauwechsel (Trendbrüche) ohne externe C-Bibliotheken."""
    def sse(arr: np.ndarray) -> float:
        if len(arr) == 0:
            return 0.0
        return float(np.sum((arr - np.mean(arr)) ** 2))

    changepoints = []

    def split_segment(start: int, end: int):
        if end - start < 2 * min_size:
            return
        total_cost = sse(series[start:end])
        best_gain = 0.0
        best_idx = None

        for idx in range(start + min_size, end - min_size + 1):
            gain = total_cost - (sse(series[start:idx]) + sse(series[idx:end]))
            if gain > best_gain:
                best_gain = gain
                best_idx = idx

        if best_idx is not None and best_gain > penalty:
            changepoints.append(best_idx)
            split_segment(start, best_idx)
            split_segment(best_idx, end)

    split_segment(0, len(series))
    return sorted(changepoints)


# ==========================================
# 3. ZEITREIHEN-ANALYSE PRO PROJEKT
# ==========================================
def analyze_project_timeseries(df_proj: pd.DataFrame, project_name: str) -> dict:
    df_proj = df_proj.copy()
    if "sentiment" in df_proj.columns:
        df_proj["sentiment"] = pd.to_numeric(df_proj["sentiment"], errors="coerce")
        df_proj.loc[df_proj["sentiment"].eq(SENTIMENT_FEHLWERT), "sentiment"] = np.nan

    daily = df_proj.groupby("date").agg(
        count=("mention_id", "count"),
        avg_sentiment=("sentiment", "mean")
    )

    full_idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_idx)
    daily["count"] = daily["count"].fillna(0)

    counts = daily["count"].values
    std_val = np.std(counts)

    if len(counts) < 14 or std_val == 0:
        return {
            "project": project_name,
            "total_posts": int(counts.sum()),
            "date_range": f"{daily.index.min().strftime('%Y-%m-%d')} to {daily.index.max().strftime('%Y-%m-%d')}",
            "peaks": [],
            "change_points": []
        }

    # --- A) Kurzfristige Peaks (scipy.signal.find_peaks) ---
    prominence_threshold = max(2.0, std_val * PROMINENCE_FACTOR)
    peak_indices, properties = find_peaks(
        counts,
        prominence=prominence_threshold,
        distance=MIN_PEAK_DISTANCE_DAYS
    )

    peaks = []
    for i, idx in enumerate(peak_indices):
        peak_date = daily.index[idx]
        sample_titles = df_proj[df_proj["date"] == peak_date]["title"].dropna().unique()[:2].tolist()

        peaks.append({
            "date": peak_date.strftime("%Y-%m-%d"),
            "post_count": int(counts[idx]),
            "prominence": round(float(properties["prominences"][i]), 2),
            "avg_sentiment": round(float(daily["avg_sentiment"].iloc[idx]), 2) if pd.notna(daily["avg_sentiment"].iloc[idx]) else None,
            "crawler_window": {
                "start": (peak_date - pd.Timedelta(days=3)).strftime("%Y-%m-%d"),
                "end": (peak_date + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
            },
            "sample_titles": sample_titles
        })

    # --- B) Dauerhafte Trendwenden ---
    norm_counts = (counts - np.mean(counts)) / std_val
    cp_indices = detect_changepoints_binseg(norm_counts, penalty=CHANGEPOINT_PENALTY, min_size=7)

    change_points = []
    boundaries = [0] + cp_indices + [len(counts)]
    for pos, idx in enumerate(cp_indices):
        cp_date = daily.index[idx]
        prev_start = boundaries[pos]
        next_end = boundaries[pos + 2]

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
        "date_range": f"{daily.index.min().strftime('%Y-%m-%d')} to {daily.index.max().strftime('%Y-%m-%d')}",
        "peaks": peaks,
        "change_points": change_points
    }


# ==========================================
# 4. HAUPTPROGRAMM & KONSOLEN-AUSGABE
# ==========================================
def main():
    if not INPUT_FILE.exists():
        print(f"ERROR: '{INPUT_FILE.relative_to(BASE_DIR)}' is missing. Run 'python pipeline/01_filter_posts.py' first.")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        clean_data = json.load(f)

    if not clean_data:
        print("The filtered file is empty.")
        return

    df = pd.DataFrame(clean_data)
    df["date"] = pd.to_datetime(df["published_at"], utc=True, errors="coerce").dt.tz_localize(None).dt.floor("D")
    df["sentiment"] = pd.to_numeric(df.get("sentiment"), errors="coerce")
    df.loc[df["sentiment"].eq(SENTIMENT_FEHLWERT), "sentiment"] = np.nan
    df = df.dropna(subset=["date"]).copy()

    df_exploded = df.explode("matched_projects").rename(columns={"matched_projects": "project"})

    all_results = []
    print("\n" + "=" * 75)
    print("PEAK AND CHANGE-POINT RESULTS")
    print("=" * 75)

    for project, group in df_exploded.groupby("project"):
        res = analyze_project_timeseries(group, project)
        all_results.append(res)

        print(f"\nPROJECT: {res['project']} ({res['total_posts']} posts | {res['date_range']})")
        print("-" * 75)

        print("  [PEAKS]")
        if not res["peaks"]:
            print("    -> No significant peaks.")
        for p in res["peaks"]:
            print(f"    * {p['date']} | {p['post_count']} posts (prominence: {p['prominence']}, sentiment: {p['avg_sentiment']})")
            print(f"      Crawler window: {p['crawler_window']['start']} to {p['crawler_window']['end']}")
            for title in p["sample_titles"]:
                print(f"      Sample title: \"{title[:80]}\"")

        print("\n  [CHANGE POINTS]")
        if not res["change_points"]:
            print("    -> No lasting level shifts.")
        for cp in res["change_points"]:
            direction = "UP" if cp["avg_posts_after"] > cp["avg_posts_before"] else "DOWN"
            print(f"    * {cp['date']} ({direction}): mean {cp['avg_posts_before']} -> {cp['avg_posts_after']} posts/day "
                  f"| sentiment: {cp['avg_sentiment_before']} -> {cp['avg_sentiment_after']}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 75)
    print(f"Done. Wrote {OUTPUT_FILE.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()