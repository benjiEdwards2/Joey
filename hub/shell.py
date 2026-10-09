"""The page shell every router shares (T3 hub core, 2026-10-09): ONE Jinja2Templates instance and the
static asset version. Routers import `templates` from here instead of building their own env, so every
page carries the same globals (H-31: Discover pages once rendered `control-surface.css?v=` empty).

Globals that are functions of hub.main (media_nav, identity, score_for, ...) are set on this env by
hub.main at import. Templates are not re-stat'ed on every render (`auto_reload=False`) unless
HUB_DEV=1 (local template editing).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi.templating import Jinja2Templates

HUB_DIR = Path(__file__).resolve().parent
STATIC_DIR = HUB_DIR / "static"
TEMPLATES_DIR = HUB_DIR / "templates"


def _static_version(root: Path = STATIC_DIR) -> str:
    """Content hash of the whole static tree (names + bytes), appended as ?v= to every static URL, so a
    deploy that changes ANY asset (CSS, htmx, a logo) is never painted with a browser's cached copy —
    those URLs are served `immutable` (field note 2026-09-11, bit us 2026-10-05)."""
    digest = hashlib.sha1()
    try:
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
            digest.update(path.read_bytes())
    except OSError:
        return "0"
    return digest.hexdigest()[:8]


def dev_mode() -> bool:
    return os.environ.get("HUB_DEV", "").strip() == "1"


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.auto_reload = dev_mode()
templates.env.globals["static_v"] = _static_version()
