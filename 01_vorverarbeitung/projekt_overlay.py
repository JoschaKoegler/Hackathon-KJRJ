"""Overlay für ``01_filtern.py``.

Liest ``briefs/<id>.json`` und ``assigned/<id>.json``.
Schreibt das Log ``assign_overlay.json``. Das Dashboard liest es nicht.
Ohne assigned-Datei bleiben die Regeln aus ``00_data/definitions.json``.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT = BASE_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

POSTS_FILE = importlib.import_module("02_laufzeit.config").POSTS_FILE

BRIEFS_DIR = BASE_DIR / "briefs"
ASSIGNED_DIR = BASE_DIR / "assigned"
CLEAN_DATA_FILE = POSTS_FILE
OVERLAY_FILE = BASE_DIR / "assign_overlay.json"

# Dieselbe Form wie ein Eintrag in data/posts.json.
REQUIRED_FIELDS = (
    "mention_id",
    "published_at",
    "source_name",
    "url",
    "title",
    "content",
    "matched_projects",
    "also_mentions",
)


def brief_from_form(project_id: str, name: str, location: str, description: str) -> dict:
    """Eingabe, die das Formular „Neues Projekt“ später schickt."""
    brief = {
        "id": str(project_id or "").strip(),
        "name": str(name or "").strip(),
        "location": str(location or "").strip(),
        "description": str(description or "").strip(),
    }
    missing = [key for key, value in brief.items() if not value]
    if missing:
        raise ValueError(f"Steckbrief unvollständig: {', '.join(missing)}")
    return brief


def load_briefs() -> list[dict]:
    if not BRIEFS_DIR.is_dir():
        return []
    briefs = []
    for path in sorted(BRIEFS_DIR.glob("*.json")):
        brief = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(brief, dict):
            raise ValueError(f"{path.name} ist kein Steckbrief.")
        brief_from_form(
            brief.get("id", ""),
            brief.get("name", ""),
            brief.get("location", ""),
            brief.get("description", ""),
        )
        if brief["id"] != path.stem:
            raise ValueError(f"{path.name}: id muss dem Dateinamen entsprechen.")
        briefs.append(brief)
    return briefs


def assign_posts(brief: dict, mentions: list[dict] | None = None) -> list[dict] | None:
    """Platzhalter für das Modell.

    ``brief`` ist der Steckbrief aus der Oberfläche. ``mentions`` sind die
    Rohbeiträge, die das Modell später liest. Solange der Aufruf fehlt, gilt
    die schon geprüfte Datei ``assigned/<id>.json``. Ohne diese Datei bleibt
    die Regex-Zuordnung zuständig.
    """
    del mentions  # der Platzhalter liest die Rohbeiträge noch nicht
    path = ASSIGNED_DIR / f"{brief['id']}.json"
    if not path.is_file():
        return None
    posts = json.loads(path.read_text(encoding="utf-8"))
    validate_assigned(brief["id"], posts)
    return posts


def validate_assigned(project_id: str, posts) -> None:
    if not isinstance(posts, list) or not posts:
        raise ValueError(f"{project_id}: assigned-Datei muss eine nicht leere Liste sein.")
    seen = set()
    for index, post in enumerate(posts):
        if not isinstance(post, dict):
            raise ValueError(f"{project_id}: Eintrag {index} ist kein Objekt.")
        missing = [field for field in REQUIRED_FIELDS if field not in post]
        if missing:
            raise ValueError(f"{project_id}: Eintrag {index} ohne {', '.join(missing)}.")
        projects = post.get("matched_projects")
        if not isinstance(projects, list) or not projects or projects[0] != project_id:
            raise ValueError(f"{project_id}: matched_projects muss mit dieser Projekt-ID beginnen.")
        if not isinstance(post.get("also_mentions"), list):
            raise ValueError(f"{project_id}: also_mentions muss eine Liste sein.")
        mention_id = str(post.get("mention_id") or "").strip()
        if not mention_id or mention_id in seen:
            raise ValueError(f"{project_id}: mention_id fehlt oder ist doppelt ({mention_id!r}).")
        seen.add(mention_id)


def overlay_assigned(posts: list[dict]) -> tuple[list[dict], dict]:
    """Ersetzt Regex-Treffer durch Modellergebnisse und schreibt den Bericht.

    Ein Beitrag gehört nur einem Hauptprojekt. Liegt seine mention_id im
    Modellergebnis, wandert er dorthin, auch wenn die Regex ihn woanders hatte.
    Zweimal ausführen ändert das Ergebnis nicht.
    """
    ready = []
    pending = []
    for brief in load_briefs():
        assigned = assign_posts(brief)
        if assigned is None:
            pending.append(brief["id"])
        else:
            ready.append((brief, assigned))

    if not ready:
        report = {"replaced_projects": {}, "pending_briefs": pending, "posts_after": len(posts)}
        OVERLAY_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return posts, report

    by_project = {brief["id"]: assigned for brief, assigned in ready}
    owner_of = {
        str(post["mention_id"]): project_id
        for project_id, assigned in by_project.items()
        for post in assigned
    }
    kept = []
    replaced = Counter()
    moved_to = Counter()
    moved_from = Counter()
    for post in posts:
        primary = (post.get("matched_projects") or [None])[0]
        mention_id = str(post.get("mention_id") or "")
        if primary in by_project:
            replaced[primary] += 1
            continue
        if mention_id in owner_of:
            moved_to[owner_of[mention_id]] += 1
            moved_from[primary or "(ohne Projekt)"] += 1
            continue
        kept.append(post)

    for brief, assigned in ready:
        assigned.sort(key=lambda post: str(post.get("published_at") or ""))
        kept.extend(assigned)

    report = {
        "replaced_projects": {
            brief["id"]: {
                "brief": f"briefs/{brief['id']}.json",
                "assigned": f"assigned/{brief['id']}.json",
                "posts": len(assigned),
                "previous_posts_replaced": replaced[brief["id"]],
                "moved_from_other_projects": moved_to[brief["id"]],
            }
            for brief, assigned in ready
        },
        "moved_from_other_projects": dict(moved_from),
        "pending_briefs": pending,
        "posts_before": len(posts),
        "posts_after": len(kept),
    }
    OVERLAY_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return kept, report


def main():
    if not CLEAN_DATA_FILE.is_file():
        print(f"FEHLER: {CLEAN_DATA_FILE} fehlt. Zuerst 01_filter_posts.py ausführen.")
        return
    posts = json.loads(CLEAN_DATA_FILE.read_text(encoding="utf-8"))
    merged, report = overlay_assigned(posts)
    CLEAN_DATA_FILE.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"{CLEAN_DATA_FILE}: {report['posts_before']} -> {report['posts_after']} Beiträge")
    for project_id, info in report["replaced_projects"].items():
        print(
            f"  {project_id}: {info['posts']} aus {info['assigned']}, "
            f"{info['previous_posts_replaced']} bisherige Beiträge ersetzt, "
            f"{info['moved_from_other_projects']} aus anderen Projekten übernommen"
        )
    if report["pending_briefs"]:
        print("  ohne Modellergebnis, Regex bleibt:", ", ".join(report["pending_briefs"]))


if __name__ == "__main__":
    main()
