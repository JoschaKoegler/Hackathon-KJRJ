"""Switches for cities, channels, circles, and the trend.

Change the selection here. The calculation lives in the other files in this
package. Then restart ``python dashboard.py``.
"""

from pathlib import Path

# Repository root, one level above this package.
ROOT = Path(__file__).resolve().parent.parent

# Filtered posts from pipeline/01_filter_posts.py.
POSTS_FILE = Path("data") / "01_filtered" / "posts.json"
# Peaks from pipeline/02_detect_peaks.py. The crawler writes events.json
# beside it; the dashboard prefers that file when it exists.
PEAKS_FILE = Path("data") / "02_peaks" / "peaks.json"
EVENTS_FILE = Path("data") / "02_peaks" / "events.json"

HOST = "127.0.0.1"
PORT = 8765

# Buttons under the timeline, left to right.
# A new entry appears as a button once a project below points at its id.
CITY_BUTTONS = [
    {"id": "All", "label": "All", "hint": "Every project"},
    {"id": "Heilbronn", "label": "Heilbronn", "hint": "Cable car and IPAI campus"},
    {"id": "Bonn", "label": "Bonn", "hint": "Bonn cable car"},
    {"id": "Paris", "label": "Paris", "hint": "Câble C1"},
]

# Exactly one project per post, as matched_projects in posts.json.
# IPAI is in Heilbronn. Give it its own button by mapping it to a new id
# and adding that id to CITY_BUTTONS.
CITY_BY_PROJECT = {
    "Heilbronn_Seilbahn": "Heilbronn",
    "IPAI_Campus": "Heilbronn",
    "Bonn_Seilbahn": "Bonn",
    "Paris_Cable_C1": "Paris",
}

PROJECT_LABEL = {
    "Heilbronn_Seilbahn": "Heilbronn cable car",
    "IPAI_Campus": "IPAI campus",
    "Bonn_Seilbahn": "Bonn cable car",
    "Paris_Cable_C1": "Paris Câble C1",
}

# Right-hand switch. The channel comes from prepare.channel_of,
# the same rule as notebooks/explore_language_and_channels.ipynb.
CHANNEL_BUTTONS = [
    {"id": "News", "label": "News"},
    {"id": "Social", "label": "Social"},
]
CHANNEL_BY_SOURCE = {
    "News": "News",
    "Social": "Social",
    # "Other web" has no button and appears in neither view.
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

# Word cloud. "posts": a term counts once per post.
# "occurrences": every appearance in the text counts.
# The cloud reads the same prepared text as text stance.
TERM_COUNT = 10
TERM_COUNTING = "posts"
TEXT_CHARS = 2500
TOKEN_CHARS = TEXT_CHARS

DEFAULT_CITY = "All"
DEFAULT_CHANNEL = "News"
