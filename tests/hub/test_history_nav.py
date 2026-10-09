"""Back/Forward is navigation only (2026-10-08): htmx keeps no history snapshots and reloads on a history miss,
HTML pages are sent `Cache-Control: no-store` (static files keep their own caching), and a flash's query params
are stripped from the address bar after render."""
import importlib
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from tests.hub.conftest import shell_script

REPO_ROOT = Path(__file__).resolve().parents[2]


def client(monkeypatch):
    monkeypatch.delenv("AREAS_PATH", raising=False)
    import hub.main
    importlib.reload(hub.main)
    return TestClient(hub.main.app), hub.main


def test_htmx_config_meta_disables_history_cache(monkeypatch):
    c, _ = client(monkeypatch)
    with c:
        html = c.get("/").text
    m = re.search(r"<meta name=\"htmx-config\" content='([^']+)'>", html)
    assert m, "htmx-config meta missing from base.html"
    cfg = json.loads(m.group(1))
    assert cfg == {"historyCacheSize": 0, "refreshOnHistoryMiss": True}
    assert html.index('name="htmx-config"') < html.index("htmx.min.js")  # read when htmx initialises


def test_vendored_htmx_knows_the_config_names():
    js = (REPO_ROOT / "hub/static/htmx.min.js").read_text(encoding="utf-8")
    assert 'version:"2.0.4"' in js
    assert "historyCacheSize:10" in js and "refreshOnHistoryMiss:false" in js  # the defaults we override


def test_pages_are_no_store_and_static_is_not(monkeypatch):
    c, _ = client(monkeypatch)
    with c:
        page = c.get("/")
        css = c.get("/static/control-surface.css")
        health = c.get("/healthz")
    assert page.headers["content-type"].startswith("text/html")
    assert page.headers["cache-control"] == "no-store"
    assert css.status_code == 200 and "no-store" not in css.headers.get("cache-control", "")
    assert "no-store" not in health.headers.get("cache-control", "")  # JSON is not a page


def test_404_page_is_no_store_too(monkeypatch):
    c, _ = client(monkeypatch)
    with c:
        r = c.get("/a/does-not-exist")
    assert r.headers["content-type"].startswith("text/html") and r.headers["cache-control"] == "no-store"


def test_flash_params_are_stripped_after_render(monkeypatch):
    c, main = client(monkeypatch)
    with c:
        html = c.get("/").text
        js = shell_script(c, html)
    assert "history.replaceState(history.state" in js
    assert "htmx:pushedIntoHistory" in js  # boosted POST -> 303 -> pushed URL is cleaned too
    keys = json.loads(re.search(r"<meta name=\"joey-flash-params\" content='(\[[^\]]*\])'>", html).group(1))
    assert set(keys) == set(main.FLASH_PARAMS)
    # every flash a write route redirects with is in the list
    for k in ("follow", "requested", "error", "flash", "c", "code", "done"):
        assert k in keys
    for k in ("q", "sort", "kind", "offset", "mode", "step", "owner_view"):
        assert k not in keys  # real page state stays in the URL


def test_flash_keys_cover_the_redirects_in_code():
    """Grep the write routes' redirect targets: any `?word=` / `&word=` they build is a known flash key."""
    from hub import main
    src = "".join((REPO_ROOT / "hub" / f).read_text(encoding="utf-8")
                  for f in ("media_follow.py", "media_discover.py", "server_updates.py"))
    assert 'f"follow={word}"' in src and '"requested=1"' in src and 'f"error={code}"' in src
    assert {"follow", "requested", "error", "flash", "c", "code"} <= set(main.FLASH_PARAMS)
