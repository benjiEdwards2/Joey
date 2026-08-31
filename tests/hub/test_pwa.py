"""WP21 (offline half) — PWA manifest + icons wired into the hub."""
import importlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_manifest_is_valid_and_dark():
    m = json.loads((REPO_ROOT / "hub/static/manifest.webmanifest").read_text(encoding="utf-8"))
    assert m["name"] == "Jarvis"
    assert m["display"] == "standalone"
    assert m["background_color"] == "#08090D" and m["theme_color"] == "#08090D"
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
