"""Awards marks (awards-ui item 1, 2026-10-09): which drawing a ceremony / category uses, and the override logos.

The drawings themselves live in `templates/_award_icons.html` (inline SVG in currentColor, self-drawn — not the
ceremonies' trademark logos). A file `hub/static/awards/<body id>.svg|png|webp` replaces a ceremony's drawing
(`override`), like `hub/static/badges/`; the ceremony name stays as its alt text.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from hub import media_awards_seed as seed

OVERRIDE_DIR = Path(__file__).resolve().parent / "static" / "awards"
OVERRIDE_EXTS = ("svg", "png", "webp")
BODY_IDS = tuple(b["id"] for b in sorted(seed.BODIES, key=lambda b: b["sort"]))   # M-21: the seed's ceremony order
SHAPES = BODY_IDS + ("trophy", "laurel", "seen", "person", "reel", "clapper", "nib")

# A category's icon by its name (first rule wins): acting -> person, directing -> clapper, writing -> nib,
# the picture / series / Palme categories -> reel, everything else -> trophy.
CAT_RULES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\b(actor|actress|performance|cast|ensemble|male|female)\b", re.I), "person"),
    (re.compile(r"direct", re.I), "clapper"),
    (re.compile(r"screenplay|writing|written|writer", re.I), "nib"),
    (re.compile(r"\b(picture|film|series|palme|production|grand prix|jury prize)\b", re.I), "reel"),
)


def cat_icon(name: str | None) -> str:
    for rule, shape in CAT_RULES:
        if rule.search(name or ""):
            return shape
    return "trophy"


@lru_cache(maxsize=32)
def override(body_id: str) -> str | None:
    """'/static/awards/<id>.<ext>' when that file exists (checked once per process: the folder only changes on deploy)."""
    if body_id not in BODY_IDS:
        return None
    for ext in OVERRIDE_EXTS:
        if (OVERRIDE_DIR / f"{body_id}.{ext}").is_file():
            return f"/static/awards/{body_id}.{ext}"
    return None
