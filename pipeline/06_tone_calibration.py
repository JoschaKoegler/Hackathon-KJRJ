"""Hand labels for the vendor tone classes.

Every post with vendor ``-1`` is labeled, plus a fixed sample of vendor ``0``
and ``1`` (three per project, seed 7). The label is the tone of the passage
about the matched project: positive, neutral, negative, or side when the
project is not what the piece is about. ``opposition`` is a separate question
and is not read off the tone.

Precision of a vendor class uses every labeled post of that class. Recall uses
the same labeled pool. The pool contains every ``-1`` and only a sample of the
other two classes, so recall of "negative" is higher than a full reading of
the corpus would give. The Heilbronn ``-1`` rows are a census.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSTS = ROOT / "pipeline" / "clean_data.json"
OUT = ROOT / "pipeline" / "tone_calibration.json"

# mention_id -> (passage tone, opposition)
GOLD = {
    # vendor -1, all 44
    "10002661,8177": ("side", False),
    "10057582,389": ("side", False),
    "10446419,1580": ("side", False),
    "11342743,809097": ("positive", False),
    "11765059,433494": ("side", False),
    "12471214,1591": ("side", False),
    "12569394,577": ("positive", False),
    "12802933,29080": ("neutral", False),
    "12851209,111310": ("side", False),
    "15729122,543": ("positive", False),
    "17290166,1218": ("positive", False),
    "19135019,114554": ("positive", False),
    "22236729,4593": ("positive", False),
    "22319433,98907": ("neutral", False),
    "22681797,402495": ("side", False),
    "23395896,563": ("positive", False),
    "23395896,566": ("positive", False),
    "25258353,402": ("negative", False),
    "25258364,81": ("negative", False),
    "25457264,1050": ("positive", False),
    "25524346,27678": ("side", False),
    "27963376,165074": ("negative", False),
    "27963376,185185": ("positive", False),
    "28294713,39618": ("negative", False),
    "28294713,54211": ("neutral", False),
    "28295106,859943": ("side", False),
    "28697418,12354": ("negative", False),
    "28878857,108843": ("positive", False),
    "29188508,11483": ("side", False),
    "29200025,10482": ("side", False),
    "29200025,13893": ("neutral", False),
    "29200849,17912": ("neutral", False),
    "29316251,23662754": ("positive", False),
    "29316251,31417335": ("neutral", False),
    "29316254,32892457": ("positive", False),
    "29714639,427320": ("neutral", False),
    "30108913,961608": ("negative", False),
    "4203683,65976": ("negative", False),
    "9672814,1186128": ("side", False),
    "9776584,4976": ("negative", False),
    "29128977,13722": ("side", False),
    "26446012,11038": ("positive", False),
    "25725533,229957": ("positive", False),
    "24930177,22752": ("neutral", False),
    # sample of vendor 0 and 1
    "27963376,192420": ("side", False),
    "12977600,409": ("positive", False),
    "28697418,9194": ("negative", False),
    "11412242,3191": ("positive", False),
    "11903632,559": ("positive", False),
    "12577603,1313": ("side", False),
    "24894377,1546": ("neutral", False),
    "29174404,185152": ("side", False),
    "11542449,188421": ("side", False),
    "9672814,1072634": ("positive", False),
    "28294950,457084": ("positive", False),
    "17669656,579": ("negative", False),
    "12434641,1820": ("neutral", False),
    "13906786,3339": ("negative", False),
    "29344551,2619": ("neutral", False),
    "28697418,10151": ("negative", False),
    "14202555,1292": ("negative", False),
    "27963376,169201": ("positive", False),
    "4101569,18733": ("positive", False),
    "12703082,601": ("negative", True),
    "29316253,16719468": ("positive", False),
    "10575219,1427": ("positive", False),
    "29174404,246205": ("negative", True),
    "29174404,167729": ("positive", False),
}

VENDOR = {1: "positive", 0: "neutral", -1: "negative"}


def main() -> None:
    posts = json.loads(POSTS.read_text(encoding="utf-8"))
    by_id = {post["mention_id"]: post for post in posts}
    missing = [key for key in GOLD if key not in by_id]
    if missing:
        raise SystemExit(f"unknown mention ids: {missing}")

    rows = []
    for mention_id, (tone, opposition) in GOLD.items():
        post = by_id[mention_id]
        vendor = VENDOR[post["sentiment"]]
        rows.append({
            "mention_id": mention_id,
            "project": post["matched_projects"][0],
            "vendor": vendor,
            "passage_tone": tone,
            "opposition": opposition,
            "title": post.get("title") or "",
        })

    def rates(subset: list[dict]) -> dict:
        out = {}
        for label in ("positive", "neutral", "negative"):
            predicted = [row for row in subset if row["vendor"] == label]
            actual = [row for row in subset if row["passage_tone"] == label]
            hit = [row for row in predicted if row["passage_tone"] == label]
            out[label] = {
                "precision": None if not predicted else round(len(hit) / len(predicted), 3),
                "precision_n": [len(hit), len(predicted)],
                "recall": None if not actual else round(len(hit) / len(actual), 3),
                "recall_n": [len(hit), len(actual)],
            }
        return out

    heilbronn_neg = [
        row for row in rows
        if row["project"] == "Heilbronn_Seilbahn" and row["vendor"] == "negative"
    ]
    opposition_hits = [row for row in rows if row["vendor"] == "negative" and row["opposition"]]
    report = {
        "labeled": len(rows),
        "vendor_counts": dict(Counter(row["vendor"] for row in rows)),
        "note": (
            "Every vendor -1 post is included. Vendor 0 and 1 are a sample of three posts "
            "per project. Recall of negative is therefore too high if read as a corpus rate. "
            "Precision of vendor -1 is a census."
        ),
        "passage_tone": rates(rows),
        "vendor_negative_that_are_opposition": {
            "all_projects": [len(opposition_hits), sum(row["vendor"] == "negative" for row in rows)],
            "heilbronn": [
                sum(row["opposition"] for row in heilbronn_neg),
                len(heilbronn_neg),
            ],
        },
        "heilbronn_vendor_negative": [
            {"title": row["title"], "passage_tone": row["passage_tone"], "opposition": row["opposition"]}
            for row in heilbronn_neg
        ],
        "rows": rows,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tone = report["passage_tone"]["negative"]
    opp = report["vendor_negative_that_are_opposition"]
    print(f"wrote {OUT}")
    print(f"vendor -1 precision as negative tone: {tone['precision']} ({tone['precision_n']})")
    print(f"vendor -1 that are opposition: {opp['all_projects'][0]}/{opp['all_projects'][1]}")
    print(f"Heilbronn vendor -1 that are opposition: {opp['heilbronn'][0]}/{opp['heilbronn'][1]}")


if __name__ == "__main__":
    main()
