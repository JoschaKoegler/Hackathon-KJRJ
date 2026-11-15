"""Switches and data paths. Restart ``python 03_dashboard.py`` after a change.

``02_laufzeit`` only reads these files. Scoring lives in ``01_vorverarbeitung``.
"""

from pathlib import Path

# Repository root, one level above this package.
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "00_data"

# 01_vorverarbeitung/01_filtern.py            →  posts.json
# 02_sentiment_analyse.py                     →  tone_score, tone_cue, tone_gap, story_key, circle
# 03_stance_analyse.py                        →  stance
# 08_token_fallback.py                        →  terms, categories, arguments
# 04_peak_erkennung.py + 05_trendbrueche.py   →  01_vorverarbeitung/peaks.json
# 06_peak_kontext.py                          →  context.json
# 07_themen_zuordnung.py                      →  themes.json
# definitions.json and facts.json are hand-authored.
# load_posts reads the stored columns and does not score again.
# City, channel, and the display text are built in beitraege.prepare.
POSTS_FILE = DATA / "posts.json"
DEFINITIONS_FILE = DATA / "definitions.json"
CONTEXT_FILE = DATA / "context.json"
THEMES_FILE = DATA / "themes.json"
FACTS_FILE = DATA / "facts.json"
PEAKS_FILE = ROOT / "01_vorverarbeitung" / "peaks.json"

HOST = "127.0.0.1"
PORT = 8765

# Buttons in the header, left to right.
# A new entry appears as a button once a project below points at its id.
CITY_BUTTONS = [
    {"id": "All", "label": "All", "hint": "Every project"},
    {"id": "Heilbronn", "label": "Heilbronn cable car", "hint": "Urban cable car Heilbronn"},
    {"id": "IPAI", "label": "IPAI", "hint": "IPAI campus"},
    {"id": "Bonn", "label": "Bonn", "hint": "Bonn cable car"},
    {"id": "Paris", "label": "Paris", "hint": "Câble C1"},
]

# Exactly one project per post, as matched_projects in data/posts.json.
CITY_BY_PROJECT = {
    "Heilbronn_Seilbahn": "Heilbronn",
    "IPAI_Campus": "IPAI",
    "Bonn_Seilbahn": "Bonn",
    "Paris_Cable_C1": "Paris",
}

PROJECT_LABEL = {
    "Heilbronn_Seilbahn": "Heilbronn cable car",
    "IPAI_Campus": "IPAI campus",
    "Bonn_Seilbahn": "Bonn cable car",
    "Paris_Cable_C1": "Paris Câble C1",
}

# Channel switch in the header. "All" skips the cut in select_posts.
CHANNEL_BUTTONS = [
    {"id": "All", "label": "All", "hint": "News, social, and other web"},
    {"id": "News", "label": "News"},
    {"id": "Social", "label": "Social media"},
]
CHANNEL_BY_SOURCE = {
    "News": "News",
    "Social": "Social",
    "Other web": "Other web",
}

# Recorded in /api/summary. Circles are the stored tone_score from 02_sentiment_analyse.py.
STANCE_SOURCE = "tone"

# Trend arrow: balance (positive share minus negative share) against the
# previous window of the same length. A change larger than this band, in
# points, points the arrow up or down. Inside the band it stays neutral.
TREND_THRESHOLD_POINTS = 0.0

TEXT_CHARS = 2500

DEFAULT_CITY = "All"
DEFAULT_CHANNEL = "All"

# One colour per cause on the timeline. The id is what the page reads.
EVENT_FAMILIES = [
    {"id": "decision", "label": "Political decision", "color": "#0c4a8a"},
    {"id": "planning", "label": "Planning", "color": "#6b4c9a"},
    {"id": "construction", "label": "Construction", "color": "#b86e00"},
    {"id": "opening", "label": "Opening", "color": "#1b6b45"},
    {"id": "disruption", "label": "Disruption", "color": "#9a3b38"},
    {"id": "media", "label": "Coverage only", "color": "#8a7560"},
    {"id": "other", "label": "Other", "color": "#5c6570"},
]
