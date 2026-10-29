"""JY-265 phase 2: remove the whole film or show, files included (spec docs/specs/JY-265-remove.md section 6, phase 2).

Seerr, Radarr / Sonarr (tests/hub/fake_arr.py), Jellyfin and the Discord webhook are faked at requests.*; no network.
Every delete goes through the arr app's own DELETE with deleteFiles=true (its recycle bin), never the filesystem.
"""
import copy
import importlib
import sqlite3

import pytest
import requests
import yaml
from fastapi.testclient import TestClient

from hub import media_follow, media_hidden, media_remove
from tests.hub.fake_arr import RADARR, SONARR, Resp
from tests.hub.helpers import make_area, write_envelope
from tests.hub.test_media_remove import HOOK, SAMPLE, SECRETS, SEERR, SKEY, Fake

JF = "http://jellyfin.secret-host.invalid:8096"
JKEY = "j-SECRET-jellyfin"
FILM = "/media/remove/movie/1003"     # Desert Crossing: Available, a file on disk, request 12
SHOW = "/media/remove/tv/2002"        # Night Ferry: series 9, one episode file, request 14
FILM_PATH = "/data/media/movies/Desert Crossing (2024)"
ARR_SNAP = {"library_sizes": {
    "radarr": [{"tmdb_id": 1003, "title": "Desert Crossing", "year": 2024, "size_bytes": 4 * 1024 ** 3}],
    "sonarr": [{"tvdb_id": 82002, "tmdb_id": 2002, "title": "Night Ferry", "size_bytes": 1717986918, "ended": True}]}}
JF_SNAP = {"shows": [{"item_key": "tvdb:82002", "jf_id": "abcdef0123456789abcdef0123456789", "title": "Night Ferry"}]}


class WholeFake(Fake):
    """Fake + Seerr media read / clear + Jellyfin Sessions / Media/Updated / Refresh."""

    def __init__(self):
        super().__init__()
        film = copy.deepcopy(self.arr.movies[0])
        film.update(id=11, title="Desert Crossing", year=2024, tmdbId=1003, hasFile=True, path=FILM_PATH,
                    sizeOnDisk=4 * 1024 ** 3, movieFile={"id": 77, "size": 4 * 1024 ** 3})
        self.arr.movies.append(film)
        self.sessions: list = []
        self.jf: list[tuple] = []
        self.jf_status = 204
        self.sessions_status = 200
        self.media_delete_status = 204

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        if url.startswith(JF):
            self.jf.append(("GET", url[len(JF):]))
            return Resp(copy.deepcopy(self.sessions), self.sessions_status)
        if url.startswith(SEERR + "/api/v1/movie/") or url.startswith(SEERR + "/api/v1/tv/"):
            self._seerr("GET", url, headers)
            return Resp({"id": int(url.rsplit("/", 1)[1]), "mediaInfo": {"id": 900}})
        return super().get(url, params=params, headers=headers, timeout=timeout, **kw)

    def delete(self, url, headers=None, timeout=None, **kw):
        if url.startswith(SEERR + "/api/v1/media/"):
            self._seerr("DELETE", url, headers)
            return Resp(None, self.media_delete_status)
        return super().delete(url, headers=headers, timeout=timeout, **kw)

    def post(self, url, json=None, headers=None, timeout=None, **kw):
        if url.startswith(JF):
            assert timeout
            self.jf.append(("POST", url[len(JF):], json, kw.get("params")))
            return Resp(None, self.jf_status if url.endswith("/Media/Updated") else 204)
        return super().post(url, json=json, headers=headers, timeout=timeout, **kw)

    def arr_writes(self):
        return [(m, b, p, prm) for m, b, p, prm, _ in self.arr.writes()]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    area = make_area("alpha", "req-t", snapshot="jellyseerr", stale_after_minutes=180, detail="/media/requests")
    path = tmp_path / "areas.yaml"
    path.write_text(yaml.safe_dump({"areas": [area]}), encoding="utf-8")
    for k, v in {"AREAS_PATH": str(path), "MEDIA_DB_PATH": str(tmp_path / "media.db"), "JELLYSEERR_URL": SEERR,
                 "JELLYSEERR_API_KEY": SKEY, "SERVER_DISCORD_WEBHOOK": HOOK, "REMOVE_API": "on",
                 "JELLYFIN_URL": JF, "JELLYFIN_API_KEY": JKEY, "SNAPSHOT_DIR": str(tmp_path / "snaps")}.items():
        monkeypatch.setenv(k, v)
    media_hidden.clear()
    media_remove.clear()
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyseerr", age_minutes=1, data=copy.deepcopy(SAMPLE))
    write_envelope(snaps, "arr", age_minutes=1, data=copy.deepcopy(ARR_SNAP))
    write_envelope(snaps, "jellyfin", age_minutes=1, data=copy.deepcopy(JF_SNAP))
    import hub.main
    importlib.reload(hub.main)
    fake = WholeFake()
    for k, v in fake.arr.env().items():
        monkeypatch.setenv(k, v)
    for m in ("get", "put", "delete", "post"):
        monkeypatch.setattr(requests, m, getattr(fake, m))
    yield TestClient(hub.main.app), fake, tmp_path / "media.db"
    media_hidden.clear()
    media_remove.clear()


def hidden(page: str, name: str) -> str:
    return page.split(f'name="{name}" value="', 1)[1].split('"', 1)[0]


def confirm(client, url):
    page = client.get(url + "?step=confirm&scope=whole").text
    return {"scope": "whole", "arr_id": hidden(page, "arr_id"), "fids": hidden(page, "fids"),
            "bytes": hidden(page, "bytes")}, page


def post(client, url, form, typed):
    return client.post(url, data={**form, "typed": typed}, follow_redirects=False)


def audit(db):
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM media_removals ORDER BY id")]


def test_pick_offers_whole_film_from_the_cache_with_no_call(env):
    client, fake, _ = env
    with client:
        pick = client.get(FILM).text
    assert 'value="whole"' in pick and "Whole film" in pick and "4.0 GB" in pick
    assert not fake.arr.calls and not fake.jf


def test_film_is_deleted_once_with_files_then_seerr_and_jellyfin(env):
    client, fake, db = env
    with client:
        form, page = confirm(client, FILM)
        assert "Radarr deletes 1 file · 4.0 GB" in page and "recycle bin" in page and 'name="typed"' in page
        r = post(client, FILM, form, "desert crossing!")
        assert r.status_code == 303 and "done=whole" in r.headers["location"]
        after = client.get(FILM).text
    deletes = [w for w in fake.arr_writes() if w[0] == "DELETE"]
    assert deletes == [("DELETE", RADARR, "/api/v3/movie/11", {"deleteFiles": "true", "addImportExclusion": "false"})]
    assert ("DELETE", "/api/v1/request/12") in fake.seerr and ("DELETE", "/api/v1/media/900") in fake.seerr
    assert fake.jf[-1][:3] == ("POST", "/Library/Media/Updated", {"Updates": [{"Path": FILM_PATH, "UpdateType": "Deleted"}]})
    row = audit(db)[-1]
    assert row["scope"] == "whole" and row["outcome"] == "done" and row["files"] == 1 and row["bytes"] == 4 * 1024 ** 3
    assert not any(s in str(row) for s in SECRETS) and FILM_PATH not in str(row)
    assert len(fake.discord) == 1 and "Desert Crossing" in fake.discord[0]
    assert 'value="whole"' not in after   # hidden until the next arr sweep


def test_show_is_unfollowed_after_a_successful_series_delete(env, monkeypatch):
    client, fake, _ = env
    order = []
    with client:
        media_follow.follow("show", 2002, "Night Ferry")
        real = fake.arr.delete
        monkeypatch.setattr(fake.arr, "delete", lambda *a, **k: (order.append(media_follow.get("show", 2002)), real(*a, **k))[1])
        form, _ = confirm(client, SHOW)
        r = post(client, SHOW, form, "Night Ferry")
    assert r.status_code == 303 and "done=whole" in r.headers["location"]
    assert order[0] is not None and media_follow.get("show", 2002) is None   # kept until the DELETE succeeded
    deletes = [w for w in fake.arr_writes() if w[0] == "DELETE"]
    assert deletes == [("DELETE", SONARR, "/api/v3/series/9", {"deleteFiles": "true", "addImportListExclusion": "false"})]


def test_blank_recycle_bin_refuses_with_nothing_deleted(env):
    client, fake, _ = env
    fake.arr.config[RADARR]["recycleBin"] = ""
    with client:
        page = client.get(FILM + "?step=confirm&scope=whole").text
        r = post(client, FILM, {"scope": "whole", "arr_id": "11", "fids": "77", "bytes": str(4 * 1024 ** 3)},
                 "Desert Crossing")
    assert "no recycle bin set" in page and 'name="typed"' not in page
    assert "error=nobin" in r.headers["location"] and not fake.arr.writes() and not fake.seerr


def test_wrong_typed_title_refuses_before_any_call(env):
    client, fake, _ = env
    with client:
        form, _ = confirm(client, FILM)
        n = len(fake.arr.calls)
        r = post(client, FILM, form, "Desert")
    assert "error=typed" in r.headers["location"] and len(fake.arr.calls) == n and not fake.arr.writes()


def test_changed_file_since_confirm_refuses(env):
    client, fake, _ = env
    with client:
        form, _ = confirm(client, FILM)
        fake.arr.movies[-1]["movieFile"] = {"id": 78, "size": 4 * 1024 ** 3}
        r = post(client, FILM, form, "Desert Crossing")
    assert "error=changed" in r.headers["location"] and not fake.arr.writes()


def test_someone_watching_refuses(env):
    client, fake, _ = env
    fake.sessions = [{"UserName": "g", "NowPlayingItem": {"Path": FILM_PATH + "/film.mkv", "ProviderIds": {}}}]
    with client:
        form, _ = confirm(client, FILM)
        r = post(client, FILM, form, "Desert Crossing")
    assert "error=watching" in r.headers["location"] and not fake.arr.writes()


def test_fourth_whole_remove_in_an_hour_refuses(env):
    client, fake, _ = env
    now = __import__("time").monotonic()
    for _ in range(3):
        assert media_remove._rate_whole(now)[0]
    with client:
        form, _ = confirm(client, FILM)
        r = post(client, FILM, form, "Desert Crossing")
    assert "error=rate" in r.headers["location"] and not fake.arr.writes()


def test_a_second_remove_while_one_runs_is_refused(env):
    client, fake, _ = env
    with client:
        form, _ = confirm(client, FILM)
        media_remove._lock.acquire()
        try:
            r = post(client, FILM, form, "Desert Crossing")
        finally:
            media_remove._lock.release()
    assert "error=busy" in r.headers["location"] and not fake.arr.writes()


def test_jellyfin_500_falls_back_to_a_series_refresh(env):
    client, fake, _ = env
    fake.jf_status = 500
    with client:
        form, _ = confirm(client, SHOW)
        r = post(client, SHOW, form, "Night Ferry")
    assert "done=whole" in r.headers["location"]
    assert fake.jf[-1][:2] == ("POST", "/Items/abcdef0123456789abcdef0123456789/Refresh")
    assert fake.jf[-1][3] == {"Recursive": "true"}


def test_jellyfin_down_says_it_catches_up(env):
    client, fake, _ = env
    fake.jf_status = 500
    with client:
        form, _ = confirm(client, FILM)
        r = post(client, FILM, form, "Desert Crossing")
        page = client.get(r.headers["location"]).text
    assert "done=wholelate" in r.headers["location"] and "Jellyfin will catch up on its next scan" in page


def test_ratings_diary_and_follows_of_other_titles_stay(env):
    client, fake, db = env
    with client:
        with sqlite3.connect(db) as c:
            tables = [t for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
                      if t != "media_removals" and not t.startswith("sqlite_")]
            before = {t: c.execute(f"SELECT * FROM {t}").fetchall() for t in tables}
        form, _ = confirm(client, FILM)
        post(client, FILM, form, "Desert Crossing")
        with sqlite3.connect(db) as c:
            after = {t: c.execute(f"SELECT * FROM {t}").fetchall() for t in tables}
    assert before == after


def test_seerr_failure_after_the_arr_delete_is_partial(env):
    client, fake, db = env
    fake.media_delete_status = 500
    with client:
        form, _ = confirm(client, FILM)
        r = post(client, FILM, form, "Desert Crossing")
    assert "error=wholepartial" in r.headers["location"]
    row = audit(db)[-1]
    assert row["outcome"] == "partial" and "delete with files" in row["steps"] and "HTTP 500" in row["steps"]


def test_arr_delete_refused_is_failed(env):
    client, fake, db = env
    fake.arr.delete_status = 500
    with client:
        form, _ = confirm(client, FILM)
        r = post(client, FILM, form, "Desert Crossing")
    assert "error=deletefail" in r.headers["location"] and audit(db)[-1]["outcome"] == "failed" and not fake.discord


def test_running_download_is_cancelled_through_radarr(env):
    client, fake, _ = env
    fake.arr.queue[RADARR] = [{"id": 55, "movieId": 11}]
    with client:
        form, _ = confirm(client, FILM)
        post(client, FILM, form, "Desert Crossing")
    deletes = [w for w in fake.arr_writes() if w[0] == "DELETE"]
    assert deletes[0] == ("DELETE", RADARR, "/api/v3/queue/55", {"removeFromClient": "true", "blocklist": "false"})


def test_flag_off_shows_no_whole_option(env, monkeypatch):
    client, fake, _ = env
    monkeypatch.setenv("REMOVE_API", "off")
    with client:
        assert client.get(FILM).status_code == 404
    assert not fake.arr.calls


def _timeout_then(fake, monkeypatch, drop: bool, reread_raises=False):
    real_delete, real_get = fake.arr.delete, fake.arr.get

    def delete(url, **k):
        if "/api/v3/movie/" in url or "/api/v3/series/" in url:
            if drop:
                real_delete(url, **k)
            raise requests.Timeout("read timed out")
        return real_delete(url, **k)

    def get(url, **k):
        if reread_raises and url.endswith("/api/v3/movie/11"):
            raise requests.ConnectionError("down")
        return real_get(url, **k)
    monkeypatch.setattr(fake.arr, "delete", delete)
    monkeypatch.setattr(fake.arr, "get", get)


def test_timed_out_delete_that_went_through_carries_on_as_partial(env, monkeypatch):
    client, fake, db = env
    with client:
        form, _ = confirm(client, FILM)
        _timeout_then(fake, monkeypatch, drop=True)
        r = post(client, FILM, form, "Desert Crossing (2024)")
        page = client.get(r.headers["location"]).text
    assert "error=wholeslow" in r.headers["location"] and "Nothing was removed" not in page
    assert ("DELETE", "/api/v1/media/900") in fake.seerr and audit(db)[-1]["outcome"] == "partial"


def test_timed_out_delete_still_there_is_failed(env, monkeypatch):
    client, fake, db = env
    with client:
        form, _ = confirm(client, FILM)
        _timeout_then(fake, monkeypatch, drop=False)
        r = post(client, FILM, form, "Desert Crossing")
    assert "error=deletefail" in r.headers["location"] and not fake.seerr and audit(db)[-1]["outcome"] == "failed"


def test_timed_out_delete_with_no_reread_never_says_nothing_removed(env, monkeypatch):
    client, fake, db = env
    with client:
        form, _ = confirm(client, FILM)
        _timeout_then(fake, monkeypatch, drop=True, reread_raises=True)
        r = post(client, FILM, form, "Desert Crossing")
        page = client.get(r.headers["location"]).text
    assert "error=wholeunsure" in r.headers["location"] and "Nothing was removed" not in page
    assert audit(db)[-1]["outcome"] == "unsure" and "removed Desert" not in fake.discord[-1]


def test_failed_series_delete_keeps_the_follow(env):
    client, fake, db = env
    fake.arr.delete_status = 500
    with client:
        media_follow.follow("show", 2002, "Night Ferry")
        form, _ = confirm(client, SHOW)
        r = post(client, SHOW, form, "Night Ferry")
        assert "error=deletefail" in r.headers["location"] and media_follow.get("show", 2002)


def test_a_crash_after_the_delete_still_leaves_an_unsure_row(env, monkeypatch):
    from hub import media_remove_whole
    client, fake, db = env
    monkeypatch.setattr(media_remove_whole, "_seerr_clear", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    with client:
        form, _ = confirm(client, FILM)
        client.post(FILM, data={**form, "typed": "Desert Crossing"}, follow_redirects=False)
    rows = audit(db)
    assert len(rows) == 1 and rows[0]["outcome"] == "unsure" and rows[0]["files"] == 1
    assert "delete with files" in rows[0]["steps"] and "RuntimeError" in rows[0]["steps"]


def test_a_crash_before_the_delete_is_failed(env, monkeypatch):
    from hub import media_remove_whole
    client, fake, db = env
    monkeypatch.setattr(media_remove_whole, "_cancel_queue", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    with client:
        form, _ = confirm(client, FILM)
        client.post(FILM, data={**form, "typed": "Desert Crossing"}, follow_redirects=False)
    assert audit(db)[-1]["outcome"] == "failed" and not fake.arr.writes()
