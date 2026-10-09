"""T3 hub core (2026-10-09): one shared page shell (hub/shell.py) — every page, whichever router renders it,
carries the same asset version (H-31 / M-23: Discover once shipped `control-surface.css?v=` empty)."""
import importlib
import re

from fastapi.testclient import TestClient

from tests.hub.test_registry import make_area, make_tile, write_registry
from tests.hub.test_store import write_envelope

CSS_V = re.compile(r'href="/static/control-surface\.css\?v=([0-9a-f]*)"')


def _client(tmp_path, monkeypatch):
    area = make_area("alpha", "play-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/playing")
    area["layout"] = "shelves"
    area["tiles"].append(make_tile("disc-t", snapshot="jellyseerr", stale_after_minutes=180,
                                   detail="/media/discover"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.delenv("JELLYSEERR_URL", raising=False)
    monkeypatch.delenv("JELLYSEERR_API_KEY", raising=False)
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, area)))
    write_envelope(tmp_path / "snaps", "jellyfin", age_minutes=1, data={"summary": "x", "movies": []})
    write_envelope(tmp_path / "snaps", "jellyseerr", age_minutes=1, data={"summary": "x", "requests": []})
    import hub.main
    importlib.reload(hub.main)
    return TestClient(hub.main.app)


def test_discover_page_carries_the_same_asset_version_as_movies(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as c:
        disc, movies = c.get("/media/discover"), c.get("/media/movies")
    assert disc.status_code == 200 and movies.status_code == 200
    v_disc, v_movies = CSS_V.search(disc.text), CSS_V.search(movies.text)
    assert v_disc and v_movies
    assert v_disc.group(1) and v_disc.group(1) == v_movies.group(1)
    assert f'<meta name="joey-asset-v" content="{v_disc.group(1)}">' in disc.text


def test_one_template_env_is_shared(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch):
        import hub.main
        from hub import media_discover, media_watchlist, media_write, shell
        assert hub.main.templates is shell.templates
        for mod in (media_discover, media_write, media_watchlist):  # interim copy until the media WP
            g = mod.templates.env.globals
            for key in ("static_v", "score_for", "resume_acts", "media_nav", "identity", "flash_params"):
                assert key in g, (mod.__name__, key)


def test_static_version_hashes_the_whole_tree(tmp_path):
    from hub.shell import _static_version
    (tmp_path / "a.css").write_text("x", encoding="utf-8")
    (tmp_path / "logos").mkdir()
    (tmp_path / "logos" / "l.svg").write_text("<svg/>", encoding="utf-8")
    before = _static_version(tmp_path)
    (tmp_path / "logos" / "l.svg").write_text("<svg></svg>", encoding="utf-8")  # a logo alone changes it
    assert re.fullmatch(r"[0-9a-f]{8}", before) and _static_version(tmp_path) != before


def test_templates_do_not_auto_reload_outside_dev():
    from hub import shell
    assert shell.templates.env.auto_reload is shell.dev_mode()


def _plain_client(monkeypatch, tmp_path):
    monkeypatch.delenv("AREAS_PATH", raising=False)
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    import hub.main
    importlib.reload(hub.main)
    return TestClient(hub.main.app)


def test_static_cache_control_versioned_vs_unversioned(tmp_path, monkeypatch):
    """H-56 / N-48: a ?v= static URL is immutable for a year; manifests and un-versioned files an hour;
    pages stay no-store; a static 404 is never pinned."""
    with _plain_client(monkeypatch, tmp_path) as c:
        css = c.get("/static/control-surface.css?v=abc12345")
        bare = c.get("/static/control-surface.css")
        manifest = c.get("/static/manifest.webmanifest")
        icon = c.get("/static/icon-192.png?v=3")
        missing = c.get("/static/nope.css?v=1")
        page = c.get("/")
    assert css.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert icon.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert bare.headers["cache-control"] == "public, max-age=3600"
    assert manifest.headers["cache-control"] == "public, max-age=3600"
    assert missing.status_code == 404 and "immutable" not in missing.headers.get("cache-control", "")
    assert page.headers["cache-control"] == "no-store"


def test_text_is_gzipped_and_images_are_not(tmp_path, monkeypatch):
    """N-49: pages and CSS over 1 KB are gzipped when asked; PNGs and /img are sent as they are."""
    with _plain_client(monkeypatch, tmp_path) as c:
        gz = {"Accept-Encoding": "gzip"}
        page, css = c.get("/", headers=gz), c.get("/static/control-surface.css?v=1", headers=gz)
        icon, poster = c.get("/static/icon-192.png?v=3", headers=gz), c.get("/img/none?h=240", headers=gz)
        small = c.get("/healthz", headers=gz)
    assert page.headers.get("content-encoding") == "gzip" and "<html" in page.text
    assert css.headers.get("content-encoding") == "gzip"
    assert css.headers["cache-control"].endswith("immutable")
    for r in (icon, poster, small):  # small: under 1 KB
        assert "content-encoding" not in r.headers


def test_request_log_skips_quiet_paths_and_never_logs_the_email(tmp_path, monkeypatch, caplog):
    """H-58 / N-28: one line per page, owner word only; healthcheck, static files and posters are silent."""
    import logging
    monkeypatch.setenv("OWNER_EMAIL_YOU", "me@example.invalid")
    with _plain_client(monkeypatch, tmp_path) as c, caplog.at_level(logging.INFO, logger="hub"):
        c.get("/", headers={"Cf-Access-Authenticated-User-Email": "me@example.invalid"})
        c.get("/weather", headers={"Cf-Access-Authenticated-User-Email": "other@example.invalid"})
        c.get("/nope")
        c.get("/healthz"), c.get("/static/manifest.webmanifest"), c.get("/img/none?h=240")
    lines = [r.getMessage() for r in caplog.records if r.name == "hub" and " owner=" in r.getMessage()]
    assert lines == ["GET / owner=you -> 200", "GET /weather owner=her -> 200", "GET /nope owner=none -> 404"]
    assert "example.invalid" not in caplog.text
    assert logging.getLogger("uvicorn.access").disabled


def test_one_pure_asgi_middleware_layer(tmp_path, monkeypatch):
    """H-59: no BaseHTTPMiddleware left — the shell layer and gzip are plain ASGI classes."""
    from starlette.middleware.base import BaseHTTPMiddleware
    with _plain_client(monkeypatch, tmp_path):
        import hub.main
        from hub.shell import Compress, ShellMiddleware
        classes = [m.cls for m in hub.main.app.user_middleware]
    assert ShellMiddleware in classes and Compress in classes and BaseHTTPMiddleware not in classes


def test_every_loop_logs_type_only_and_keeps_going(monkeypatch, caplog):
    """H-23: the one loop helper — an error is logged by type (never its text) and the next run still happens."""
    import asyncio
    import logging

    import hub.main as main
    runs = []

    def fn():
        runs.append(1)
        if len(runs) == 1:
            raise RuntimeError("secret detail http://x.invalid")

    async def go():
        task = asyncio.create_task(main._every("demo", 0, 0, fn))
        while len(runs) < 2:
            await asyncio.sleep(0.01)
        task.cancel()

    with caplog.at_level(logging.WARNING, logger="hub"):
        asyncio.run(go())
    assert "demo task error: RuntimeError" in caplog.text and "secret" not in caplog.text
