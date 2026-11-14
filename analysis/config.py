"""Switches for cities, channels, circles, and the trend.

Change the selection here. The calculation lives in the other files in this
package. Then restart ``python dashboard.py``.
"""

from pathlib import Path

# Repository root, one level above this package.
ROOT = Path(__file__).resolve().parent.parent

# Filtered posts from pipeline/01_filter_posts.py.
POSTS_FILE = Path("pipeline") / "clean_data.json"
LEGACY_POSTS_FILE = Path("data") / "01_filtered" / "posts.json"
# Peaks with context from pipeline/03_attach_events.py.
# Falls back to 02_detect_peaks.py, then the older data/ copy.
CONTEXT_FILE = Path("pipeline") / "projects_with_context.json"
PEAKS_FILE = Path("pipeline") / "detected_events.json"
LEGACY_PEAKS_FILE = Path("data") / "02_peaks" / "peaks.json"
EVENTS_FILE = Path("data") / "02_peaks" / "events.json"

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

# Exactly one project per post, as matched_projects in posts.json.
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

# Three circles. analysis/stance.py does the mapping.
# "sentiment": vendor field sentiment. 1 support, 0 neutral, -1 opposition.
#              -99 and empty values stay outside the circles.
# "text":      phrase patterns in stance.py. support / mixed / oppose.
#              "no clear stance" stays outside the circles.
STANCE_SOURCE = "sentiment"
CIRCLES = ["Support", "Neutral", "Opposition"]

# Trend arrow: balance (support - opposition) / classified posts,
# current window minus the immediately previous window of the same length.
# Below this threshold, in percentage points, the arrow stays flat.
TREND_THRESHOLD_POINTS = 2.0
# Below this many classified posts the window is too thin for an arrow.
MIN_TREND_BASE = 8

# Raw term list, kept for notebooks. The page draws themes, not this list.
# "posts": a term counts once per post.
# "occurrences": every appearance in the text counts.
TERM_COUNT = 10
TERM_COUNTING = "posts"
TEXT_CHARS = 2500
TOKEN_CHARS = TEXT_CHARS

DEFAULT_CITY = "All"
DEFAULT_CHANNEL = "All"
