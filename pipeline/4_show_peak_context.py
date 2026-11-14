"""Zeigt den Kontext der Peaks lesbar an und exportiert ihn als CSV (Excel-tauglich).

Aufruf:
  python 4_show_peak_context.py                      # Top 10 Peaks je Projekt (ab 4 Posts)
  python 4_show_peak_context.py Heilbronn_Seilbahn   # nur ein Projekt
  python 4_show_peak_context.py Heilbronn_Seilbahn 2 # ... ab 2 Posts
"""
import csv
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "projects_with_context.json"
OUTPUT_CSV = BASE_DIR / "peak_context_overview.csv"
TOP_N_PER_PROJECT = 10


def main():
    only_project = sys.argv[1] if len(sys.argv) > 1 else None
    min_posts = int(sys.argv[2]) if len(sys.argv) > 2 else 4

    if not INPUT_FILE.exists():
        print(f"FEHLER: '{INPUT_FILE.name}' nicht gefunden. Bitte zuerst 3_crawl_context.py ausführen.")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        projects = json.load(f)["projects"]

    rows = []
    for block in projects:
        name = block["project"]
        if only_project and name != only_project:
            continue
        peaks = [p for p in block.get("peaks", []) if p.get("post_count", 0) >= min_posts and p.get("context")]
        peaks.sort(key=lambda p: p["post_count"], reverse=True)

        print("\n" + "=" * 80)
        print(f"{name}  ({len(peaks)} Peaks ab {min_posts} Posts)")
        print("=" * 80)

        for i, p in enumerate(peaks):
            ctx = p["context"]
            eff = ctx.get("effects") or {}
            ext = (ctx.get("external_candidates") or [{}])[0]

            rows.append({
                "projekt": name,
                "datum": p["date"],
                "posts": p["post_count"],
                "ereignistyp": ctx["event_type"],
                "konfidenz": ctx["confidence"],
                "nebentyp": ctx.get("event_type_secondary") or "",
                "evtl_themenfremd": "ja" if ctx.get("off_topic_suspect") else "",
                "zusammenfassung": ctx["summary"],
                "begriffe": ", ".join(ctx.get("top_terms", [])),
                "betraege": ", ".join(ctx.get("amounts_mentioned", [])),
                "top_schlagzeile": (ctx.get("top_headlines") or [""])[0],
                "externer_beleg": ext.get("title", ""),
                "externer_beleg_url": ext.get("url", ""),
                "nachwirkung": eff.get("persistence", ""),
                "abklingzeit_tage": eff.get("decay_days", ""),
                "sentiment_vorher": eff.get("sentiment_14d_before", ""),
                "sentiment_nachher": eff.get("sentiment_14d_after", ""),
            })

            if i < TOP_N_PER_PROJECT:
                warn = "  ⚠ evtl. themenfremd" if ctx.get("off_topic_suspect") else ""
                print(f"\n{p['date']} | {p['post_count']} Posts | {ctx['event_type']} | Konfidenz: {ctx['confidence']}{warn}")
                print(f"  {ctx['summary']}")
                if eff:
                    print(f"  Nachwirkung: {eff.get('persistence')} | Abklingzeit: {eff.get('decay_days')} Tage | "
                          f"Sentiment {eff.get('sentiment_14d_before')} -> {eff.get('sentiment_14d_after')}")

    if rows:
        with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=";")
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nAlle {len(rows)} Peaks exportiert nach: {OUTPUT_CSV.name} (in Excel öffnen)")
    else:
        print("Keine Peaks gefunden (Projektname oder Mindest-Postzahl prüfen).")


if __name__ == "__main__":
    main()