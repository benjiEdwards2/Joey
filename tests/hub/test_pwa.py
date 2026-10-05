"""WP21 (offline half) — PWA manifest + icons wired into the hub."""
import importlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_manifest_is_valid_and_dark():
    m = json.loads((REPO_ROOT / "hub/static/manifest.webmanifest").read_text(encoding="utf-8"))
    assert m["name"] == "Joey"
    assert m["display"] == "standalone"
    assert m["background_color"] == "#141414" and m["theme_color"] == "#141414"
    assert {i["sizes"] for i in m["icons"]} == {"192x192", "512x512"}


def test_icons_exist_and_are_png():
    for size in (192, 512):
        p = REPO_ROOT / f"hub/static/icon-{size}.png"
        assert p.is_file()
        assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_base_page_links_manifest_and_htmx(monkeypatch):
    monkeypatch.delenv("AREAS_PATH", raising=False)
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as c:
        html = c.get("/").text
        assert 'rel="manifest"' in html
        assert 'name="theme-color"' in html
        assert "htmx.min.js" in html
        assert c.get("/static/manifest.webmanifest").status_code == 200


def test_icons_are_square_at_declared_sizes_from_committed_source():
    """2026-09-11: icons come from the committed joey photo, face-centred.
    Dimensions read straight from the PNG IHDR chunk — no Pillow in the test image."""
    import struct

    assert (REPO_ROOT / "hub/static/icon_source.jpg").is_file()
    for size in (192, 512):
        head = (REPO_ROOT / f"hub/static/icon-{size}.png").read_bytes()[:24]
        w, h = struct.unpack(">II", head[16:24])
        assert (w, h) == (size, size)


def test_icon_urls_are_cache_busted():
    """2026-09-11: Chrome caches manifest icons by URL — a version query forces
    the new kangaroo icon to be fetched on re-install."""
    m = json.loads((REPO_ROOT / "hub/static/manifest.webmanifest").read_text(encoding="utf-8"))
    assert all("?v=" in i["src"] for i in m["icons"])
    base = (REPO_ROOT / "hub/templates/base.html").read_text(encoding="utf-8")
    assert 'rel="apple-touch-icon" href="/static/icon-192.png?v=' in base


def test_stylesheet_link_is_content_versioned(monkeypatch):
    """2026-10-05: a deploy changed the CSS and browsers kept the stale copy
    (no Cache-Control on StaticFiles) — the link now carries a content hash."""
    import re
    import hub.main
    from fastapi.testclient import TestClient
    with TestClient(hub.main.app) as client:
        html = client.get("/").text
    m = re.search(r'href="/static/control-surface\.css\?v=([0-9a-f]{8})"', html)
    assert m, html[:400]
    assert m.group(1) == hub.main._static_version()


def test_asset_version_meta_and_boost_reload_guard(monkeypatch):
    """A tab open across a deploy must not boost new markup under the old stylesheet (2026-10-06):
    the page carries its asset version in a meta tag and reloads fully when a boosted response
    carries a different one."""
    import importlib
    from fastapi.testclient import TestClient
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as c:
        html = c.get("/").text
    v = hub.main.templates.env.globals["static_v"]
    assert f'<meta name="joey-asset-v" content="{v}">' in html
    assert "htmx:beforeSwap" in html and "joey-asset-v" in html.split("</nav>")[-1]
    assert "shouldSwap = false" in html and "window.location.href" in html


def test_links_never_use_browser_default_colours():
    css = (REPO_ROOT / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
    assert "\na { color: inherit; }" in css
    assert "main a:not([class]) { color: var(--accent" in css
