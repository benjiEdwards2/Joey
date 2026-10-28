"""JY-260 phase 2 - every film, series and season gets a Joey poster in the local store; /img serves it (pre-sized,
with today's path as the fallback); a template change re-renders; the backfill resumes from media.db and honours the
memory gate; the Jellyfin write-back runs only with B.'s poster key, backs up before it writes, is idempotent, re-applies
on drift and reverts byte-for-byte (a fake Jellyfin; no real one is ever called). Spec docs/specs/JY-260-posters.md."""
import base64
import hashlib
import io
import json
import shutil

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from hub import images, media_posters as mp, media_posters_render as r, media_posters_store as ms
from hub import media_posters_write as w, media_store, upstream
from tests.hub.test_media_frame import env  # noqa: F401 (frame env fixture)
from tests.hub.test_media_posters import LIB, S1, S2, Resp, fakes, img, snaps  # noqa: F401 (fixture)

A, B, C = "a" * 32, "b" * 32, "c" * 32
ALL = (A, B, C, S1, S2)   # 2 films, 1 series, its 2 real seasons


def img_app():
    app = FastAPI()
    app.include_router(images.router)
    return TestClient(app)


# ---- every item type, the store, /img ----

def test_every_film_series_and_season_gets_a_stored_poster(fakes):
    jf, tmdb, out = fakes
    counts = mp.dry_pass(snaps(LIB), pause=0)
    assert counts["rendered"] == 5 and counts["more"] is False
    kinds = {jf_id: ms.read_meta(jf_id)["kind"] for jf_id in ALL}
    assert kinds == {A: "movie", B: "movie", C: "tv", S1: "season", S2: "season"}
    for jf_id in ALL:
        assert ms.current(jf_id) == ms.read_meta(jf_id)["ver"]           # published: served without approval
        assert mp.state(jf_id)["status"] == "rendered"                   # and recorded in media.db


@pytest.mark.parametrize("h", ms.VARIANTS)
def test_variants_are_pre_sized_for_the_heights_joey_asks_for(fakes, h):
    mp.dry_pass(snaps(LIB), pause=0)
    with Image.open(ms.lookup(B, h)) as im:
        assert im.size == (round(h * 2 / 3), h) and im.format == "JPEG"


def test_a_height_above_the_variants_gets_the_master_and_an_unknown_one_nothing(fakes):
    mp.dry_pass(snaps(LIB), pause=0)
    with Image.open(ms.lookup(B, 1280)) as im:
        assert im.size == (1000, 1500)
    assert ms.lookup(B, 300) is None


def test_img_serves_the_stored_poster_without_an_upstream_call(fakes, monkeypatch):
    jf, tmdb, out = fakes
    mp.dry_pass(snaps(LIB), pause=0)
    jf.calls.clear()
    with img_app() as c:
        for jf_id in (B, C, S2):
            for h in (120, 240, 400, 600):
                resp = c.get(f"/img/jf:{jf_id}?h={h}")
                assert resp.status_code == 200 and resp.headers["content-type"] == "image/jpeg"
                assert resp.content == ms.lookup(jf_id, h).read_bytes()
                assert resp.headers["cache-control"] == images.HIT_CACHE     # the existing /img cache headers
        assert c.get(f"/img/jf:{B}").content == ms.lookup(B, 400).read_bytes()   # no h: the /img default 400
    assert jf.calls == []                                                 # never proxied
    assert images.warm(f"jf:{B}", 600) == "cached"                        # the warm-up skips stored posters too


def test_img_falls_back_to_todays_path_when_nothing_is_stored_or_posters_are_off(fakes, monkeypatch):
    jf, tmdb, out = fakes
    mp.dry_pass(snaps(LIB), pause=0)
    monkeypatch.setattr(images, "cache_dir", lambda: out.parent / "imgcache")
    jf.routes = {"/Images/": lambda: Resp(data=b"\xff\xd8jellyfin", ctype="image/jpeg")}
    other = "d" * 32
    with img_app() as c:
        assert c.get(f"/img/jf:{other}?h=240").content == b"\xff\xd8jellyfin"     # not stored: proxied as today
        assert c.get(f"/img/jf:{B}?h=240").content == ms.lookup(B, 240).read_bytes()   # stored: the Joey poster
        monkeypatch.setenv("POSTERS", "off")
        assert c.get(f"/img/jf:{B}?h=240").content == b"\xff\xd8jellyfin"         # off: the store is not served
        monkeypatch.setenv("POSTERS", "dry")
        ms.publish(B, False)                                                       # a reverted item: the original
        assert c.get(f"/img/jf:{B}?h=600").content == b"\xff\xd8jellyfin"
        assert c.get(f"/img/jfb:{B}?h=600").content == b"\xff\xd8jellyfin"         # backdrops are never the store


def test_a_template_change_re_renders_under_a_new_version_and_drops_the_old_files(fakes, monkeypatch, tmp_path):
    jf, tmdb, out = fakes
    mp.dry_pass(snaps(LIB), pause=0)
    old = ms.current(B)
    old_bytes = ms.lookup(B, 600).read_bytes()
    kit = tmp_path / "kit"
    shutil.copytree(r.STARTER, kit)
    data = json.loads((kit / "template.json").read_text(encoding="utf-8"))
    data["title"]["title_anchor"] = 0.70
    (kit / "template.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("POSTERS_TEMPLATE_DIR", str(kit))
    assert mp.dry_pass(snaps(LIB), pause=0)["rendered"] == 5
    new = ms.current(B)
    assert new != old and ms.read_meta(B)["ver"] == new and mp.state(B)["ver"] == new
    assert not list((out / B).glob(f"{old}.*")) and ms.lookup(B, 600).read_bytes() != old_bytes
    assert sorted(p.name for p in (out / B).iterdir()) == sorted(
        [f"{new}.full.jpg", *(f"{new}.{h}.jpg" for h in ms.VARIANTS), "meta.json", "current"])


# ---- the backfill: resume, the memory gate, the tick ----

def test_the_backfill_resumes_after_a_restart_from_media_db(fakes, monkeypatch):
    jf, tmdb, out = fakes
    monkeypatch.setenv("POSTERS_PER_PASS", "2")
    first = mp.dry_pass(snaps(LIB), pause=0)
    assert first["rendered"] == 2 and first["more"] is True
    done = {j for j in ALL if mp.state(j)}
    assert len(done) == 2 and mp.progress()["last"] in done and "backfill_done" not in mp.progress()
    media_store.reset()                                                   # a restart: nothing kept in memory
    media_store.forget()
    mp._ddl_done.clear()
    jf.calls.clear()
    second = mp.dry_pass(snaps(LIB), pause=0)
    assert second["rendered"] == 2 and second["cached"] == 2
    asked = {u.split("/Items/")[1].split("/")[0] for u in jf.calls if "/RemoteImages" in u}
    assert asked.isdisjoint(done)                                         # done items: no network at all
    third = mp.dry_pass(snaps(LIB), pause=0)
    assert third["rendered"] == 1 and third["more"] is False and "backfill_done" in mp.progress()


def test_the_backfill_order_is_recently_added_first_then_a_to_z(fakes, monkeypatch):
    monkeypatch.setenv("POSTERS_PER_PASS", "1")
    mp.dry_pass(snaps(LIB), pause=0)
    assert set(mp.states()) == {B}                                        # "New Film", added 2026-10-01


def test_the_memory_gate_skips_the_pass_and_the_tick_retries_soon(fakes, monkeypatch):
    jf, tmdb, out = fakes
    monkeypatch.setitem(mp._tick, "more", False)
    monkeypatch.setitem(mp._tick, "at", 0.0)
    got = mp.tick(lambda: snaps(LIB, free_gb=1.0), now=10_000.0)
    assert got["skipped_memory"] and jf.calls == [] and mp.states() == {}
    assert mp._tick["more"] is True                                       # next tick (5 min) tries again
    got = mp.tick(lambda: snaps(LIB), now=10_300.0)
    assert got["rendered"] == 5 and mp._tick["more"] is False
    assert mp.tick(lambda: snaps(LIB), now=10_600.0) is None              # through: hourly from now on
    assert mp.tick(lambda: snaps(LIB), now=10_300.0 + mp.EVERY_S)["cached"] == 5


# ---- the Jellyfin write-back (a fake Jellyfin) ----

ORIG = b"\xff\xd8original-poster-bytes"


class FakeJellyfin:
    """GET / POST / DELETE against an in-memory Jellyfin: items with ImageTags + LockData, and their Primary image."""
    def __init__(self, ids):
        self.items = {i: {"Id": i, "Name": "N", "Overview": "keep me", "LockData": False,
                          "ImageTags": {"Primary": "t-orig"}} for i in ids}
        self.images = {i: (ORIG, "image/jpeg") for i in ids}
        self.log, self.fail_upload = [], False
        self.remote = {"Images": [img(None, 7, name="clean")]}

    def _tag(self, i):
        self.items[i]["ImageTags"] = {"Primary": hashlib.sha256(self.images[i][0]).hexdigest()[:8]}

    def get(self, url, params=None, headers=None, timeout=None, stream=False):
        path = url.split("http://jf.test", 1)[1]
        self.log.append(("GET", path))
        if "/RemoteImages" in path:
            return Resp(body=self.remote)
        if path.startswith("/Shows/"):
            return Resp(body={"Items": [{"Id": S1, "IndexNumber": 1}, {"Id": S2, "IndexNumber": 2}]})
        jf_id = path.split("/")[2]
        if path.endswith("/Images/Primary"):
            body, ctype = self.images[jf_id]
            return Resp(data=body, ctype=ctype)
        return Resp(body=json.loads(json.dumps(self.items[jf_id])))

    def post(self, url, data=None, json=None, headers=None, timeout=None):
        path = url.split("http://jf.test", 1)[1]
        self.log.append(("POST", path))
        assert headers["Authorization"] == "MediaBrowser Token=" + "w" * 32     # the poster key, never the read key
        jf_id = path.split("/")[2]
        if path.endswith("/Images/Primary"):
            if self.fail_upload:
                return Resp(status=500)
            self.images[jf_id] = (base64.b64decode(data), headers["Content-Type"])
            self._tag(jf_id)
            return Resp(status=204)
        assert json["Overview"] == "keep me" and json["Id"] == jf_id     # the full DTO goes back, never a partial
        self.items[jf_id]["LockData"] = json["LockData"]
        return Resp(status=204)

    def delete(self, url, headers=None, timeout=None):
        self.log.append(("DELETE", url.split("http://jf.test", 1)[1]))
        return Resp(status=204)

    def writes(self):
        return [x for x in self.log if x[0] != "GET"]


@pytest.fixture()
def jelly_rw(fakes, monkeypatch):
    jf, tmdb, out = fakes
    fake = FakeJellyfin(ALL)
    sessions = {"jellyfin": fake, "tmdb": tmdb}
    monkeypatch.setattr(upstream, "session", lambda name: sessions[name])
    monkeypatch.setenv("POSTERS", "on")
    monkeypatch.setenv("JELLYFIN_POSTER_API_KEY", "w" * 32)
    return fake, out


def test_no_jellyfin_write_without_the_key(jelly_rw, monkeypatch):
    fake, out = jelly_rw
    monkeypatch.delenv("JELLYFIN_POSTER_API_KEY")
    counts = mp.dry_pass(snaps(LIB), pause=0)
    assert counts["rendered"] == 5 and counts["write"] == {"off": True}
    assert fake.writes() == [] and w.apply(B) == "skipped" and w.revert(B) == "reverted"
    assert fake.writes() == []


def test_dry_never_writes_even_with_the_key(jelly_rw, monkeypatch):
    fake, out = jelly_rw
    monkeypatch.setenv("POSTERS", "dry")
    assert "write" not in mp.dry_pass(snaps(LIB), pause=0) and fake.writes() == []


def test_the_original_is_backed_up_before_the_write_then_locked(jelly_rw):
    fake, out = jelly_rw
    counts = mp.dry_pass(snaps(LIB), pause=0)
    assert counts["write"]["written"] == 5 and counts["write"]["error"] == 0
    seq = [x for x in fake.log if B in x[1]]
    backup = seq.index(("GET", f"/Items/{B}/Images/Primary"))
    upload = seq.index(("POST", f"/Items/{B}/Images/Primary"))
    assert backup < upload < seq.index(("POST", f"/Items/{B}"))           # backup, then write, then lock
    assert ms.orig_path(B).read_bytes() == ORIG
    row = mp.state(B)
    assert row["orig_tag"] == "t-orig" and row["orig_ext"] == ".jpg" and row["locked_by_us"] == 1
    assert fake.images[B][0] == ms.master(B).read_bytes() and fake.items[B]["LockData"] is True
    assert row["live_ver"] == row["ver"] and row["live_tag"] == fake.items[B]["ImageTags"]["Primary"]


def test_a_failed_backup_means_no_write(jelly_rw):
    fake, out = jelly_rw
    fake.images[B] = (b"", "text/html")
    mp.dry_pass(snaps(LIB), pause=0)
    assert ("POST", f"/Items/{B}/Images/Primary") not in fake.log
    assert mp.state(B)["live_ver"] is None and "original" in mp.state(B)["last_error"]


def test_a_failed_upload_keeps_the_original_and_records_the_error(jelly_rw):
    fake, out = jelly_rw
    fake.fail_upload = True
    mp.dry_pass(snaps(LIB), pause=0)
    assert fake.images[B][0] == ORIG and mp.state(B)["live_ver"] is None
    assert "upload: HTTP 500" in mp.state(B)["last_error"] and ms.orig_path(B).read_bytes() == ORIG


def test_the_write_is_idempotent_and_drift_is_re_applied_once_a_day(jelly_rw, caplog):
    fake, out = jelly_rw
    mp.dry_pass(snaps(LIB), pause=0)
    fake.log.clear()
    assert w.write_pass(limit=30)["written"] == 0 and fake.writes() == []   # checked today: nothing to do
    from datetime import datetime, timedelta, timezone
    later = datetime.now(timezone.utc) + timedelta(days=1, minutes=1)
    assert w.write_pass(limit=30, now=later)["unchanged"] == 5 and fake.writes() == []
    fake.images[B] = (b"\xff\xd8a-metadata-refresh", "image/jpeg")       # Jellyfin overwrote it
    fake._tag(B)
    with caplog.at_level("WARNING", logger="hub.media_posters_write"):
        got = w.write_pass(limit=30, now=later + timedelta(days=1, minutes=1))
    assert got["reapplied"] == 1 and fake.images[B][0] == ms.master(B).read_bytes()
    assert any("re-applied" in rec.getMessage() for rec in caplog.records)
    assert ms.orig_path(B).read_bytes() == ORIG                         # the backup is the true original, kept
    fake.log.clear()
    assert w.write_pass(limit=30, now=later + timedelta(days=1, minutes=2))["reapplied"] == 0 and fake.writes() == []


def test_revert_restores_the_original_byte_for_byte_and_unlocks(jelly_rw):
    fake, out = jelly_rw
    mp.dry_pass(snaps(LIB), pause=0)
    assert w.revert(B) == "reverted"
    assert fake.images[B] == (ORIG, "image/jpeg") and fake.items[B]["LockData"] is False
    row = mp.state(B)
    assert row["reverted"] == 1 and row["live_ver"] is None and ms.lookup(B, 240) is None   # /img: the original
    fake.log.clear()
    mp.dry_pass(snaps(LIB), pause=0)
    assert fake.writes() == []                                           # a reverted item is never re-written
    assert w.restore(B) and ms.lookup(B, 240) is not None
    assert w.write_pass(limit=30)["written"] == 1 and fake.images[B][0] == ms.master(B).read_bytes()


def test_a_revert_asked_without_the_key_is_carried_out_once_it_is_back(jelly_rw, monkeypatch):
    fake, out = jelly_rw
    mp.dry_pass(snaps(LIB), pause=0)
    monkeypatch.delenv("JELLYFIN_POSTER_API_KEY")
    assert w.revert(B) == "pending" and ms.lookup(B, 240) is None and fake.images[B][0] != ORIG
    monkeypatch.setenv("JELLYFIN_POSTER_API_KEY", "w" * 32)
    assert w.write_pass(limit=30)["reverted"] == 1 and fake.images[B][0] == ORIG


def test_revert_of_an_item_that_had_no_poster_deletes_ours(jelly_rw):
    fake, out = jelly_rw
    fake.items[B]["ImageTags"] = {}
    mp.dry_pass(snaps(LIB), pause=0)
    assert mp.state(B)["orig_ext"] == "none" and ms.orig_path(B) is None
    w.revert(B)
    assert ("DELETE", f"/Items/{B}/Images/Primary") in fake.log


def test_nothing_logged_names_a_key_url_or_title(jelly_rw, caplog):
    fake, out = jelly_rw
    fake.fail_upload = True
    with caplog.at_level("INFO"):
        mp.dry_pass(snaps(LIB), pause=0)
    assert "w" * 32 not in caplog.text and "jf.test" not in caplog.text and "New Film" not in caplog.text


# ---- the review page's revert / restore, and friends ----

def test_review_page_revert_and_restore(fakes, env):  # noqa: F811
    from tests.hub.test_media_library_pages import jelly
    mp.dry_pass(snaps(LIB), pause=0)
    main = env(jellyfin=jelly())
    with TestClient(main.app) as c:
        resp = c.post(f"/media/posters/{B}/revert", follow_redirects=False)
        assert resp.status_code == 303 and ms.lookup(B, 240) is None and mp.state(B)["reverted"] == 1
        assert "Reverted: the original is shown" in c.get("/media/posters").text
        assert c.post(f"/media/posters/{B}/restore", follow_redirects=False).status_code == 303
        assert ms.lookup(B, 240) is not None
        assert c.post(f"/media/posters/{'f' * 32}/revert").status_code == 404
        assert c.post(f"/media/posters/{B}/revert", headers={"origin": "https://evil.example"}).status_code == 403


def test_friends_get_the_stored_poster_but_not_the_review_page(monkeypatch, tmp_path):
    from tests.hub.fake_jellyfin import FRIEND_ID
    from tests.hub.guest_pages import guest_client, sign_in
    from tests.hub.test_media_library_pages import jelly
    buf = io.BytesIO()
    Image.new("RGB", (1000, 1500), (200, 20, 20)).save(buf, "JPEG")
    ms.save(B, "v1", buf.getvalue())
    ms.write_meta(B, {"jf_id": B, "kind": "movie", "title": "New Film", "ver": "v1", "status": "rendered"})
    mp.set_state(B, kind="movie", ver="v1", status="rendered")
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": jelly()})
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        resp = c.get(f"/img/jf:{B}?h=240")
        assert resp.status_code == 200 and resp.content == ms.lookup(B, 240).read_bytes()
        missing = c.get("/no-such-page").text
        for method, path in (("GET", "/media/posters"), ("GET", f"/media/posters/img/{B}"),
                             ("POST", f"/media/posters/{B}/revert"), ("POST", f"/media/posters/{B}/restore")):
            resp = c.request(method, path, follow_redirects=False)
            assert resp.status_code == 404 and resp.text == missing, path
    assert ms.lookup(B, 240) is not None and not mp.state(B)["reverted"]
