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
