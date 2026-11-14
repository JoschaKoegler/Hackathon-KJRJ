"""Expectations, fears, and misunderstandings.

Phrase patterns on the prepared text. This is separate from the theme
list: "Kosten" is any mention of money, "Zu hohe Kosten" is the claim
that the project is too expensive. A post can match several claims.
"""

from __future__ import annotations

import re
from collections import Counter

import pandas as pd

# Order is the order on the page.
CLAIMS = (
    {
        "id": "nutzen",
        "label": "Nutzen im Alltag",
        "polarity": "hope",
        "pattern": (
            r"verkehrsentlast|verkehrschaos|verkehrlich\w* nutzen|geringer nutzen|"
            r"wenig nutzen|kein nutzen|ohne nutzen|"
            r"verkehr(?:sprobleme)?.{0,25}entlast|entlast\w*.{0,30}verkehr|"
            r"zeiterspar|zeitgewinn|gain de temps|temps gagn[ée]|fahrtzeit|fahrzeit|"
            r"alltagstaug|weniger umsteigen|direktverbindung|"
            r"alternative zum (?:auto|pkw|stau)|\bstaus?\b|embouteillage"
        ),
    },
    {
        "id": "kosten",
        "label": "Zu hohe Kosten",
        "polarity": "fear",
        "pattern": (
            r"zu teuer|teurer als|wird teurer|kostenexplosion|unbezahlbar|"
            r"geldverschwend|unwirtschaftlich|millionengrab|zu hohe kosten|"
            r"kosten zu hoch|kostensteigerung|kostenrisiko|kostenintensiv|kostspielig|"
            r"lohnt sich nicht|rechnet sich nicht|nicht finanzier|"
            r"trop cher|trop co[uû]teux|co[uû]t trop"
        ),
    },
    {
        "id": "machbarkeit",
        "label": "Machbarkeit",
        "polarity": "fear",
        "pattern": (
            r"machbarkeit|\bmachbar\b|undurchf[üu]hr|nicht realisier|unrealistisch|"
            r"luftnummer|faisabilit|nicht umsetzbar"
        ),
    },
    {
        "id": "klima",
        "label": "Klimaschutz",
        "polarity": "hope",
        "pattern": (
            r"klimaschutz|klimaneutral|klimafreund|emission|"
            r"ökologisch|oekologisch|[ée]colog|ecolog|carbone|treibhaus|"
            r"umweltfreundlich|emissionsfrei|emissionsarm|"
            r"nachhaltig\w* (?:mobilit|verkehr|transport|l[öo]sung)"
        ),
    },
    {
        "id": "laerm",
        "label": "Lärm",
        "polarity": "fear",
        "pattern": r"\bl[äa]rm|\bbruits?\b|ruhest[öo]rung|nuisance sonore",
    },
    {
        "id": "stadtbild",
        "label": "Stadtbild und Ästhetik",
        "polarity": "fear",
        "pattern": (
            r"[äa]sthet|stadtbild|verschandel|h[äa]sslich|sichtachse|verschatt|"
            r"erscheinungsbild|esth[ée]ti"
        ),
    },
    {
        "id": "naturschutz",
        "label": "Naturschutz",
        "polarity": "fear",
        "pattern": (
            r"naturschutz|artenschutz|baumf[äa]ll|landschaftsbild|"
            r"eingriff in (?:die )?(?:natur|landschaft)|biotop"
        ),
    },
    {
        "id": "sicherheit",
        "label": "Sicherheit und Ausfälle",
        "polarity": "fear",
        "pattern": (
            r"\bunf[äa]ll|evakuier|[ée]vacuation|\bagress|\bpanne\b|"
            r"windanf[äa]ll|st[öo]ranf[äa]ll|bei sturm|betriebsst[öo]r|hors service"
        ),
    },
    {
        "id": "barriere",
        "label": "Barrierefreiheit",
        "polarity": "hope",
        "pattern": r"barrierefrei|rollstuhl|accessibilit|\bpmr\b|personen mit eingeschr[äa]nkter",
    },
    {
        "id": "verzoegerung",
        "label": "Verzögerung",
        "polarity": "fear",
        "pattern": (
            r"verz[öo]gert sich|bauverz[öo]g|terminverzug|hinter dem zeitplan|"
            r"projektverz[öo]g|seilbahn\w*.{0,30}verz[öo]ger|verz[öo]ger\w*.{0,30}seilbahn|"
            r"\ben retard\b"
        ),
    },
    {
        "id": "prestige",
        "label": "Prestigeprojekt",
        "polarity": "fear",
        "pattern": (
            r"prestige|leuchtturm|vorzeigeprojekt|symbolpolitik|imageprojekt|"
            r"selbstdarstellung|"
            r"schwarz(?:-|\s)gruppe.{0,50}(?:aufgekauft|gesponsert|sponsor|bestimmt)|"
            r"(?:aufgekauft|gesponsert|m[äa]zen).{0,40}schwarz"
        ),
    },
    {
        "id": "jobs",
        "label": "Neue Arbeitsplätze",
        "polarity": "hope",
        "pattern": (
            r"ansiedlung|standortvorteil|neue arbeitspl|arbeitspl[äa]tze schaff|"
            r"schafft.{0,24}arbeitspl|neue jobs|jobs schaff"
        ),
    },
)

LABEL_FOR = {entry["id"]: entry["label"] for entry in CLAIMS}
_PATTERNS = [(entry["id"], re.compile(entry["pattern"])) for entry in CLAIMS]


def argument_label(argument_id: str) -> str:
    return LABEL_FOR.get(argument_id, argument_id)


def arguments_in(text) -> list[str]:
    """Claim ids mentioned in one post, in page order."""
    low = str(text or "").lower()
    return [argument_id for argument_id, pattern in _PATTERNS if pattern.search(low)]


def attach(frame: pd.DataFrame) -> pd.DataFrame:
    """Adds ``arguments`` (claim ids, one post can have several)."""
    frame["arguments"] = frame["text"].map(arguments_in)
    return frame


def argument_profile(frame: pd.DataFrame) -> list[dict]:
    """One row per claim, in page order.

    ``count`` is posts that raise the claim. ``share`` divides that by
    the posts in the frame. ``terms`` are short snippets that triggered it.
    """
    counts = {entry["id"]: 0 for entry in CLAIMS}
    examples: dict[str, Counter] = {entry["id"]: Counter() for entry in CLAIMS}
    channel_counts: dict[str, Counter] = {entry["id"]: Counter() for entry in CLAIMS}
    total = len(frame)
    if total and "text" in frame.columns:
        channels = frame["channel"] if "channel" in frame.columns else [""] * total
        pairs = zip(frame["text"], channels)
    else:
        pairs = []
    for text, channel in pairs:
        low = str(text or "").lower()
        for argument_id, pattern in _PATTERNS:
            match = pattern.search(low)
            if not match:
                continue
            counts[argument_id] += 1
            if channel:
                channel_counts[argument_id][channel] += 1
            snippet = re.sub(r"\s+", " ", match.group(0)).strip()[:48]
            if snippet:
                examples[argument_id][snippet] += 1
    rows = []
    for entry in CLAIMS:
        count = counts[entry["id"]]
        rows.append({
            "id": entry["id"],
            "label": entry["label"],
            "count": count,
            "share": (count / total) if total else 0.0,
            "terms": [snippet for snippet, _count in examples[entry["id"]].most_common(2)],
            "polarity": entry.get("polarity") or "",
            "by_channel": {
                name: int(channel_counts[entry["id"]].get(name, 0))
                for name in ("News", "Social", "Other web")
            },
        })
    return rows
