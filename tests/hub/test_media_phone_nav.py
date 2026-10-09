"""Media phone nav (B., 2026-10-07): inside Media the phone tab bar is the six Media sections (Home = Media home),
the Joey brand is the way out, and Media pages link the "Joey Media" manifest so a home-screen pin stays in Media.
Bar asserted inside <nav class="tabbar">, manifest/title metas inside <head> (never inside <title>)."""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.hub.conftest import shell_script
from tests.hub.test_media_frame import env, ROUTES  # noqa: F401  (env is a fixture)
from tests.hub.helpers import ARR, JELLY

REPO_ROOT = Path(__file__).resolve().parents[2]
MEDIA_BAR = [("/a/alpha", "Home"), ("/media/movies", "Movies"), ("/media/tv", "TV"), ("/media/diary", "Diary"),
             ("/media/playing", "Activity"), ("/media/discover", "Discover")]
SECTION_HREF = {"home": "/a/alpha", "movies": "/media/movies", "tv": "/media/tv", "diary": "/media/diary",
                "server": "/media/playing", "discover": "/media/discover"}


def tabbar(html):
    navs = re.findall(r'<nav class="tabbar"[^>]*>.*?</nav>', html, re.S)
    assert len(navs) == 1
    return navs[0]


def items(bar):
    return re.findall(r'<a href="([^"]+)"[^>]*>.*?<span>([^<]+)</span></a>', bar, re.S)


def head(html):
    """<head> after <title>, minus inline scripts (the boost script names the manifest/title in its own code)."""
    return re.sub(r"<script>.*?</script>", "", html.split("</head>", 1)[0].split("</title>", 1)[1], flags=re.S)


@pytest.mark.parametrize("route", list(ROUTES))
def test_media_pages_get_the_six_media_sections(env, route):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        html = c.get(route).text
    bar = tabbar(html)
    assert 'aria-label="Media sections (phone)"' in bar and 'hx-swap="innerHTML show:window:top"' in bar
    assert items(bar) == MEDIA_BAR
    assert bar.count('<svg class="ic"') == 6 and "<details" not in bar and "More" not in bar
    assert bar.count('aria-current="page"') == 1
    assert f'<a href="{SECTION_HREF[ROUTES[route][0]]}" aria-current="page">' in bar
    assert '<a class="brand" href="/" aria-label="Joey home">' in html     # the way back to the overall hub


@pytest.mark.parametrize("route", ["/", "/a/beta", "/weather"])
def test_non_media_pages_keep_the_global_bar(env, route):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        html = c.get(route).text
    bar = tabbar(html)
    assert 'aria-label="Sections (phone)"' in bar and "show:window:top" not in bar
    assert [label for _, label in items(bar)] == ["Hub", "Weather", "Alpha", "Beta"]
    h = head(html)
    assert '<link rel="manifest" href="/static/manifest.webmanifest">' in h
    assert "manifest-media" not in h and "Joey Media" not in h and "apple-mobile-web-app-title" not in h


@pytest.mark.parametrize("route", ["/a/alpha", "/media/movies", "/media/playing"])
def test_media_pages_link_the_joey_media_manifest(env, route):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        html = c.get(route).text
    h = head(html)
    assert re.findall(r'<link rel="manifest"[^>]*>', h) == ['<link rel="manifest" href="/static/manifest-media.webmanifest">']
    assert '<meta name="apple-mobile-web-app-title" content="Joey Media">' in h


def test_joey_media_manifest_is_valid_and_served(env):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        r = c.get("/static/manifest-media.webmanifest")
        main_manifest = c.get("/static/manifest.webmanifest").json()
    assert r.status_code == 200
    m = json.loads(r.text)
    assert (m["name"], m["short_name"], m["scope"], m["display"]) == ("Joey Media", "Media", "/", "standalone")
    assert m["icons"] == main_manifest["icons"]
    assert [(s["name"], s["url"]) for s in m["shortcuts"]] == [
        ("Movies", "/media/movies"), ("TV Shows", "/media/tv"), ("Activity", "/media/playing"), ("Discover", "/media/discover")]


def test_manifest_start_url_is_the_real_media_home():
    from hub import media_nav
    from hub.registry import load_registry
    m = json.loads((REPO_ROOT / "hub" / "static" / "manifest-media.webmanifest").read_text(encoding="utf-8"))
    area = media_nav.shelves_area(load_registry(REPO_ROOT / "config" / "areas.yaml"))
    assert m["start_url"] == f"/a/{area.id}"


def test_boosted_navigation_carries_the_manifest_across(env):
    """hx-boost swaps only <body>: the head script copies the response's manifest link and iOS app title over."""
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        script = shell_script(c, c.get("/").text)   # H-57: /static/joey.js
    assert "htmx:beforeSwap" in script and 'link[rel="manifest"]' in script
    assert "apple-mobile-web-app-title" in script
