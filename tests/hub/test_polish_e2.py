"""WP E2 UI polish batch (2026-10-13, review_ui.md section (c)): template / stylesheet / script pins for U1, U2, U6, U8,
U10, U11, U16, U17, U18, U19, U21, U22, U23 and the evaluation's P3c / P6 / font preload. Source-level on purpose: each
check pins the markup or rule that carries the behaviour (the rendering pages have their own tests)."""
import re
from pathlib import Path

HUB = Path(__file__).resolve().parents[2] / "hub"
TEMPLATES = HUB / "templates"
CSS = (HUB / "static" / "control-surface.css").read_text(encoding="utf-8")
JS = (HUB / "static" / "joey.js").read_text(encoding="utf-8")
KEEP = 'hx-swap="innerHTML show:none"'


def tpl(name):
    return (TEMPLATES / name).read_text(encoding="utf-8")


def rules(css=CSS):
    """Flattened `selector{body}` text with comments stripped (one space between tokens)."""
    return re.sub(r"\s+", " ", re.sub(r"/\*.*?\*/", "", css, flags=re.S))


# U1 --------------------------------------------------------------------------------------------------------------

def test_action_forms_keep_the_scroll_position():
    """Mark watched / Reset / Hide / season toggle, watchlist x, Follow / Unfollow, server Ignore / Unignore all re-render
    the same page: they swap the boosted body with show:none (the F1 pattern) instead of jumping to the top."""
    for name, expected in (("_resume_acts.html", 5), ("media_watchlist.html", 1), ("media_following.html", 1),
                           ("_follow_show.html", 1), ("_film_makers.html", 1), ("_film_collection.html", 1),
                           ("media_person.html", 1), ("server.html", 2)):
        src = tpl(name)
        forms = [m for m in re.findall(r'<form[^>]*method="post"[^>]*>', src)
                 if "/ignore" in m or "/unignore" in m or name != "server.html"]
        assert len(forms) == expected, (name, len(forms))
        assert all(KEEP in f for f in forms), (name, [f for f in forms if KEEP not in f])
