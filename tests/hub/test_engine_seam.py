"""JY-264 P4: the engine-seam ratchet. Jellyfin's URL, key and auth header are read in hub/media_jellyfin.py; the
modules below still do their own and are moved in phase 5 (images, writes, auth). Each phase-5 PR shrinks ALLOWLIST;
it ends empty. A new module that reads them fails here."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

HUB = Path(__file__).resolve().parents[2] / "hub"
ADAPTER = "media_jellyfin.py"
PATTERN = re.compile(r"JELLYFIN_URL|JELLYFIN_API_KEY|MediaBrowser")

ALLOWLIST = {
    "images.py",               # P5 images
    "media_posters_write.py",  # P5 writes
    "media_resume.py",         # P5 writes
    "player_api.py",           # P5 writes
    "guest_auth.py",           # P5 auth
}


def _offenders() -> set[str]:
    """Modules with the names in a code string or call (docstrings and comments don't count)."""
    out = set()
    for f in HUB.rglob("*.py"):
        if f.name == ADAPTER:
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and PATTERN.search(n.value):
                out.add(f.name)
        mods, fns = set(), set()   # names bound to hub.upstream, and to upstream.session (any alias)
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module == "hub":
                mods |= {a.asname or a.name for a in n.names if a.name == "upstream"}
            elif isinstance(n, ast.ImportFrom) and n.module == "hub.upstream":
                fns |= {a.asname or a.name for a in n.names if a.name == "session"}
            elif isinstance(n, ast.Import):
                mods |= {a.asname or a.name for a in n.names if a.name == "hub.upstream"}
        for c in ast.walk(tree):
            if not isinstance(c, ast.Call) or f.name == "upstream.py":
                continue
            fn = c.func
            hit = (isinstance(fn, ast.Attribute) and fn.attr == "session" and isinstance(fn.value, ast.Name)
                   and fn.value.id in mods) or (isinstance(fn, ast.Name) and fn.id in fns)
            if hit:
                arg = c.args[0] if c.args else None
                literal = isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                if not literal or arg.value == "jellyfin":   # a non-literal name could be "jellyfin": flag it
                    out.add(f.name)
    return out


def test_no_new_module_talks_to_jellyfin_itself():
    assert _offenders() <= ALLOWLIST, sorted(_offenders() - ALLOWLIST)


def test_allowlist_has_no_stale_entries():
    assert ALLOWLIST <= _offenders(), sorted(ALLOWLIST - _offenders())
