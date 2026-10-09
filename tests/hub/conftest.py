"""Shared hub test scaffolding (W2 media, 2026-10-09; M-59-lite, M-60).

* An autouse fixture empties every Media module's in-process cache before each test. `importlib.reload(hub.main)`
  reloads main only, so the Jellyseerr / Jellyfin / OMDb / awards caches used to leak from one test into the next —
  the most plausible source of the order-dependent flakes.
* The most-copied helpers live here: `main_of` (the page's <main>, ' · ' joins read as words), `main_raw` (the plain
  split), `write_envelope` (re-exported from test_store) and `app_with` (a registry + a client builder). The old
  import paths (`from tests.hub.test_media_film import main_of`, ...) keep working: those modules re-export these.
"""
import importlib
import re

import pytest
import yaml
from fastapi.testclient import TestClient

from tests.hub.helpers import write_envelope  # noqa: F401  (re-export: defined in tests/hub/helpers.py)

SEP = '<span class="sep"> · </span>'


def main_raw(html: str) -> str:
    """Everything from the page's <main on."""
    return html.split("<main", 1)[1]


def main_of(html: str) -> str:
    """main_raw with the dim ' · ' separator spans read as plain ' · ' (Restyle Phase 3), so pins read the words."""
    return main_raw(html).replace(SEP, " · ")


def shell_script(client, html: str) -> str:
    """The page's shell script (H-57: hub/static/joey.js, no longer inline in base.html), fetched from the versioned
    src the page's <head> names — so a pin on the script also proves the page loads it."""
    m = re.search(r'<script src="(/static/joey\.js\?v=[0-9a-z]+)" defer></script>', html.split("</head>", 1)[0])
    assert m, "joey.js is not loaded in <head>"
    r = client.get(m.group(1))
    assert r.status_code == 200
    return r.text


def app_with(tmp_path, monkeypatch, *areas):
    """Write `areas` as the registry and return build(snapshot_dir) -> a TestClient on a freshly reloaded hub.main."""
    path = tmp_path / "areas.yaml"
    path.write_text(yaml.safe_dump({"areas": list(areas)}), encoding="utf-8")
    monkeypatch.setenv("AREAS_PATH", str(path))

    def build(snapshot_dir):
        monkeypatch.setenv("SNAPSHOT_DIR", str(snapshot_dir))
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)

    return build


def clear_media_caches() -> None:
    """Every Media module's in-process cache, emptied."""
    from hub import (media_awards_badges, media_awards_icons, media_discover, media_files, media_film, media_hidden,
                     media_item, media_jellyfin, media_omdb, media_rank, media_resume)
    for clear in (media_discover.clear_cache, media_item.clear_cache, media_files.clear_cache, media_jellyfin.clear_cache,
                  media_omdb.clear_cache, media_hidden.clear, media_rank.clear_cache, media_resume.clear_cache,
                  media_awards_badges._cache.clear, media_awards_icons.override.cache_clear,
                  media_film._override_in.cache_clear):
        clear()


@pytest.fixture(autouse=True)
def _fresh_media_caches():
    clear_media_caches()
    yield
