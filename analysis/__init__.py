"""Runtime analysis for the dashboard, in file order.

1. ``prepare.py`` reads the filtered posts and sets text, city, and channel.
2. ``stance.py`` sets text stance, vendor tone, and the three circles.
3. ``terms.py`` groups tokens into themes such as Kosten and Nachhaltigkeit.
4. ``curated.py`` reads themes, hopes, and fears for a project that has them.
5. ``summary.py`` filters, counts the timeline, and computes the trend.

The switches live in ``config.py``. ``dashboard.py`` only draws the page.
"""
