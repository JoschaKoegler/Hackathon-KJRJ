"""Preprocessing only. The dashboard reads the kept file and does not run these checks.

Three checks, in order. The first failing check ends the post.

  1. Valid date
  2. Duplicate
  3. Project buzzwords

Change the conditions in the CONDITIONS section below.
The words themselves live in project_definitions.json.
"""

import json
import re
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path


# ==========================================
# PATHS
# ==========================================
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "daten"
# Raw export sits one level above the repo. The file is too large for Git.
RAW_DIR = BASE_DIR.parent
FILTERED_DIR = DATA_DIR / "01_gefiltert"
RAW_FILE_NAME = "FSI_Heilbronn_Medienbeiträge (1).json"
KEPT_FILE = FILTERED_DIR / "clean_data.json"
INPUT_FILE = RAW_DIR / RAW_FILE_NAME
SCRIPT_DIR = Path(__file__).resolve().parent
BUZZWORD_FILE = SCRIPT_DIR / "project_definitions.json"

# One folder per rejection. Both duplicate reasons share one folder.
OUTPUT_FOLDERS = {
    "invalid_or_missing_date": DATA_DIR / "rejected" / "invalid-date",
    "duplicate_title_and_start": DATA_DIR / "rejected" / "duplicates",
    "similar_over_95": DATA_DIR / "rejected" / "duplicates",
    "no_target_project_match": DATA_DIR / "rejected" / "no-project-match",
}


# ==========================================
# CONDITIONS
# Edit the numbers and the rules here. Do not put these rules in JSON.
# ==========================================

# 1. Date
# published_at must be ISO-8601.
# A trailing Z is read as +00:00.
# An offset without a colon, such as +0100, is rewritten to +01:00.
# Anything else is rejected as invalid_or_missing_date.

# 2. Duplicate, compared only with posts already kept.
# A post is a duplicate when either side is true:
#   title similarity >= TITLE_SIMILARITY
#   AND the first CONTENT_PREFIX_CHARACTERS of the content are equal
# OR
#   the whole lowercased title plus content is >= FULL_TEXT_SIMILARITY
TITLE_SIMILARITY = 0.90
CONTENT_PREFIX_CHARACTERS = 150
FULL_TEXT_SIMILARITY = 0.95

# 3. Project
# Buzzwords are loaded from project_definitions.json.
# A project matches only when both counts are at least 1:
#   topic hits >= 1
#   context hits >= 1
# Score = topic hits + context hits.
# If several projects match, the higher score wins.
# A tie goes to the earlier entry in the JSON.
# The result is exactly one project id, or none.


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_project_buzzwords(path: Path) -> dict:
    """Keep the order from project_definitions.json. That order breaks ties."""
    raw = load_json(path)
    rules = {}
    for entry in raw["projects"]:
        rules[entry["id"]] = {
            "topic_terms": list(entry["topic_terms"]),
            "context_terms": list(entry["context_terms"]),
        }
    if not rules:
        raise ValueError(f"No projects in {path}")
    return rules


PROJECT_BUZZWORDS = load_project_buzzwords(BUZZWORD_FILE)


# ==========================================
# HELPERS
# ==========================================
def normalize_text(text) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def is_valid_timestamp(timestamp) -> bool:
    if not timestamp:
        return False
    try:
        cleaned = re.sub(
            r"([+-]\d{2})(\d{2})$",
            r"\1:\2",
            str(timestamp).strip().replace("Z", "+00:00"),
        )
        datetime.fromisoformat(cleaned)
        return True
    except ValueError:
        return False


def assign_one_project(text, rules=None) -> list[str]:
    """Return one project id, or an empty list. See the CONDITIONS section."""
    rules = PROJECT_BUZZWORDS if rules is None else rules
    text_lower = str(text or "").lower()
    scored = []
    for index, (name, rule) in enumerate(rules.items()):
        topic_hits = sum(len(re.findall(pattern, text_lower)) for pattern in rule["topic_terms"])
        context_hits = sum(len(re.findall(pattern, text_lower)) for pattern in rule["context_terms"])
        if topic_hits >= 1 and context_hits >= 1:
            scored.append((topic_hits + context_hits, -index, name))
    if not scored:
        return []
    scored.sort(reverse=True)
    return [scored[0][2]]


def simhash64(text: str) -> int:
    """64-bit fingerprint over the words. Used only to find candidates."""
    counts = [0] * 64
    empty = True
    for token in text.split():
        empty = False
        value = 2166136261
        for character in token:
            value ^= ord(character)
            value = (value * 16777619) & 0xFFFFFFFF
        rotated = ((value << 16) | (value >> 16)) & 0xFFFFFFFF
        for bit in range(32):
            counts[bit] += 1 if value & (1 << bit) else -1
            counts[bit + 32] += 1 if rotated & (1 << bit) else -1
    if empty:
        return 0
    out = 0
    for bit, weight in enumerate(counts):
        if weight > 0:
            out |= 1 << bit
    return out


def lengths_can_reach_similarity(left: int, right: int) -> bool:
    """A ratio of 0.95 is impossible when the lengths differ too much."""
    if left <= 0 or right <= 0:
        return False
    shorter = min(left, right)
    longer = max(left, right)
    return shorter / longer > 0.90


def text_similarity(left: str, right: str) -> float:
    """Share of the matching character sequence, from 0 to 1."""
    if not left or not right:
        return 0.0
    matcher = SequenceMatcher(None, left, right)
    if matcher.quick_ratio() <= FULL_TEXT_SIMILARITY:
        return matcher.quick_ratio()
    return matcher.ratio()


class SeenPosts:
    """Posts already kept. Later posts are compared only against this set."""

    def __init__(self):
        self._titles: list[str] = []
        self._prefixes: dict[str, list[int]] = {}
        self._texts: list[str] = []
        self._lengths: list[int] = []
        self._bands: list[dict[int, list[int]]] = [dict() for _ in range(4)]
        self._windows: dict[str, list[int]] = {}

    def title_and_prefix(self, title: str, prefix: str) -> bool:
        """Same content prefix and a title at or above TITLE_SIMILARITY."""
        for index in self._prefixes.get(prefix, ()):
            if text_similarity(title, self._titles[index]) >= TITLE_SIMILARITY:
                return True
        return False

    def _window_keys(self, text: str) -> list[str]:
        length = len(text)
        if length <= 80:
            return [text] if text else []
        return [text[start:start + 80] for start in (0, length // 3, (2 * length) // 3)]

    def too_similar(self, text: str) -> bool:
        if not text or not self._texts:
            return False
        length = len(text)
        signature = simhash64(text)
        candidates: set[int] = set()
        for band, table in enumerate(self._bands):
            candidates.update(table.get((signature >> (band * 16)) & 0xFFFF, ()))
        for key in self._window_keys(text):
            candidates.update(self._windows.get(key, ()))
        for index in candidates:
            if not lengths_can_reach_similarity(length, self._lengths[index]):
                continue
            if text_similarity(text, self._texts[index]) >= FULL_TEXT_SIMILARITY:
                return True
        return False

    def remember(self, title: str, prefix: str, text: str) -> None:
        index = len(self._texts)
        self._titles.append(title)
        self._prefixes.setdefault(prefix, []).append(index)
        self._texts.append(text)
        self._lengths.append(len(text))
        if not text:
            return
        signature = simhash64(text)
        for band, table in enumerate(self._bands):
            table.setdefault((signature >> (band * 16)) & 0xFFFF, []).append(index)
        for key in self._window_keys(text):
            self._windows.setdefault(key, []).append(index)


def extract_records(raw_json) -> list[dict]:
    if isinstance(raw_json, list):
        return raw_json
    if isinstance(raw_json, dict):
        for key in ("data", "mentions", "items", "records", "articles"):
            if isinstance(raw_json.get(key), list):
                return raw_json[key]
    raise ValueError(
        "Unrecognized JSON structure. Expected a list, or a list under "
        "data, mentions, items, records, or articles."
    )


def evaluate_post(post: dict, seen: SeenPosts) -> tuple[bool, list[str], str]:
    """Run the three checks. The first failing reason ends the post."""
    if not is_valid_timestamp(post.get("published_at")):
        return False, [], "invalid_or_missing_date"

    title = normalize_text(post.get("title"))
    content = normalize_text(post.get("content"))
    text_lower = f"{title} {content}".strip().lower()
    title_key = title.lower()
    prefix = content.lower()[:CONTENT_PREFIX_CHARACTERS]

    if seen.title_and_prefix(title_key, prefix):
        return False, [], "duplicate_title_and_start"
    if seen.too_similar(text_lower):
        return False, [], "similar_over_95"

    matched_projects = assign_one_project(text_lower)
    if not matched_projects:
        return False, [], "no_target_project_match"

    seen.remember(title_key, prefix, text_lower)
    return True, matched_projects, "kept"


# ==========================================
# MAIN
# ==========================================
def main():
    if not INPUT_FILE.exists():
        print(f"ERROR: raw file not found:\n{INPUT_FILE}")
        print(f"Expected in the folder above the repo: {RAW_DIR}")
        return

    source = Path("..") / INPUT_FILE.relative_to(RAW_DIR)
    print(f"Loading raw posts from '{source}'...")
    with open(INPUT_FILE, "r", encoding="utf-8") as handle:
        raw_posts = extract_records(json.load(handle))

    seen = SeenPosts()
    kept_posts = []
    buckets = {reason: [] for reason in OUTPUT_FOLDERS}
    stats = Counter()
    project_counts = Counter()

    for post in raw_posts:
        is_kept, projects, reason = evaluate_post(post, seen)
        stats[reason] += 1

        if reason in OUTPUT_FOLDERS:
            post["matched_projects"] = projects
            post["rejection_reason"] = reason
            buckets[reason].append(post)
        elif is_kept:
            post["matched_projects"] = projects
            kept_posts.append(post)
            for project in projects:
                project_counts[project] += 1

    FILTERED_DIR.mkdir(parents=True, exist_ok=True)
    with open(KEPT_FILE, "w", encoding="utf-8") as handle:
        json.dump(kept_posts, handle, ensure_ascii=False, indent=2)

    written = {}
    for reason, folder in OUTPUT_FOLDERS.items():
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "posts.json"
        if target in written:
            written[target].extend(buckets[reason])
        else:
            written[target] = list(buckets[reason])
    for target, posts in written.items():
        with target.open("w", encoding="utf-8") as handle:
            json.dump(posts, handle, ensure_ascii=False)

    total = len(raw_posts)
    kept = len(kept_posts)

    print("\n" + "=" * 65)
    print("FILTER RESULT")
    print("=" * 65)
    print(f"Read:                {total:>6}")
    print(f"Kept:                {kept:>6} ({(kept / total * 100) if total else 0:.1f}%)")
    for reason, count in stats.most_common():
        if reason == "kept":
            continue
        folder = OUTPUT_FOLDERS[reason].relative_to(BASE_DIR)
        print(f"  {reason:<28} {count:>6}  {folder}")

    print("\nProjects in the kept set")
    for project, count in project_counts.most_common():
        print(f"  {project:<28} {count:>6}")

    print("\nKept file")
    print(f"  {KEPT_FILE.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
