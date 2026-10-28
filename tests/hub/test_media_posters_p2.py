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


def url(jf_id, h=None):
    """The URL Joey's pages render for a stored poster: /img/jf:<id>?h=..&v=<published version>."""
    return f"/img/jf:{jf_id}?" + (f"h={h}&" if h else "") + f"v={mp.url_version('jf:' + jf_id)}"


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
                resp = c.get(url(jf_id, h))
                assert resp.status_code == 200 and resp.headers["content-type"] == "image/jpeg"
                assert resp.content == ms.lookup(jf_id, h).read_bytes()
                assert resp.headers["cache-control"] == images.HIT_CACHE     # the existing /img cache headers
        assert c.get(url(B)).content == ms.lookup(B, 400).read_bytes()      # no h: the /img default 400
    assert jf.calls == []                                                 # never proxied


def test_img_falls_back_to_todays_path_when_nothing_is_stored_or_posters_are_off(fakes, monkeypatch):
    jf, tmdb, out = fakes
    mp.dry_pass(snaps(LIB), pause=0)
    monkeypatch.setattr(images, "cache_dir", lambda: out.parent / "imgcache")
    jf.routes = {"/Images/": lambda: Resp(data=b"\xff\xd8jellyfin", ctype="image/jpeg")}
    other = "d" * 32
    with img_app() as c:
        assert c.get(f"/img/jf:{other}?h=240").content == b"\xff\xd8jellyfin"     # not stored: proxied as today
        v = url(B, 240)
        assert c.get(v).content == ms.lookup(B, 240).read_bytes()                  # stored: the Joey poster
        assert c.get(f"/img/jf:{B}?h=240").content == b"\xff\xd8jellyfin"         # no v: never the store
        monkeypatch.setenv("POSTERS", "off")
        assert c.get(v).content == b"\xff\xd8jellyfin"                            # off: the store is not served
        monkeypatch.setenv("POSTERS", "dry")
        ms.publish(B, False)                                                       # a reverted item: the original,
        stale = c.get(v)                                                           # short-cached under the old v
        assert stale.content == b"\xff\xd8jellyfin" and stale.headers["cache-control"] == images.FALLBACK_CACHE
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
        self.fail_lock, self.fail_reads = False, 0   # the lock POST answers 500 / the next n item reads answer 500
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
        if self.fail_reads:
            self.fail_reads -= 1
            return Resp(status=500)
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
        if self.fail_lock:
            return Resp(status=500)
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
    fake.images[B] = (ORIG, "image/jpeg")                                # a refresh put the original back
    fake.items[B]["ImageTags"] = {"Primary": "t-orig"}
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
    ms.save(B, "0abc12de34", buf.getvalue())
    ms.write_meta(B, {"jf_id": B, "kind": "movie", "title": "New Film", "ver": "0abc12de34", "status": "rendered"})
    mp.set_state(B, kind="movie", ver="0abc12de34", status="rendered")
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": jelly()})
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        resp = c.get(url(B, 240))
        assert resp.status_code == 200 and resp.content == ms.lookup(B, 240).read_bytes()
        missing = c.get("/no-such-page").text
        for method, path in (("GET", "/media/posters"), ("GET", f"/media/posters/img/{B}"),
                             ("POST", f"/media/posters/{B}/revert"), ("POST", f"/media/posters/{B}/restore")):
            resp = c.request(method, path, follow_redirects=False)
            assert resp.status_code == 404 and resp.text == missing, path
    assert ms.lookup(B, 240) is not None and not mp.state(B)["reverted"]


# ---- the versioned URL (cache-busting) ----

def test_pages_put_the_published_version_on_jf_poster_urls(fakes, monkeypatch):
    from hub import shell
    mp.dry_pass(snaps(LIB), pause=0)
    ver = ms.current(B)
    macro = shell.templates.env.from_string('{% from "_poster.html" import poster %}{{ poster(ref, "New Film", 240) }}')
    tile = shell.templates.env.from_string('{% from "_tv_tile.html" import art %}{{ art(ref, "New Film", 600) }}')
    for tpl in (macro, tile):
        assert f"&amp;v={ver}" in tpl.render(ref=f"jf:{B}")
        assert "v=" not in tpl.render(ref=f"jf:{'d' * 32}")              # nothing stored: today's URL
        assert "v=" not in tpl.render(ref="tmdb:/x.jpg") and "v=" not in tpl.render(ref=None)
    ms.publish(B, False)
    assert "v=" not in macro.render(ref=f"jf:{B}")                       # reverted: the plain URL again
    monkeypatch.setenv("POSTERS", "off")
    assert mp.url_version(f"jf:{B}") == ""


def test_a_new_poster_gets_a_new_url(fakes, monkeypatch, tmp_path):
    mp.dry_pass(snaps(LIB), pause=0)
    before = url(B, 240)
    kit = tmp_path / "kit"
    shutil.copytree(r.STARTER, kit)
    data = json.loads((kit / "template.json").read_text(encoding="utf-8"))
    data["title"]["title_anchor"] = 0.70
    (kit / "template.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("POSTERS_TEMPLATE_DIR", str(kit))
    mp.dry_pass(snaps(LIB), pause=0)
    assert url(B, 240) != before


@pytest.mark.parametrize("v", ["../../media.db", "..%2F..%2Fmeta", "v1/../x", "ZZZZZZZZ", "", "a" * 40, "%00",
                               "current", "full"])
def test_a_bad_or_hostile_v_is_ignored_safely(fakes, monkeypatch, v):
    jf, tmdb, out = fakes
    mp.dry_pass(snaps(LIB), pause=0)
    monkeypatch.setattr(images, "cache_dir", lambda: out.parent / "imgcache")
    jf.routes = {"/Images/": lambda: Resp(data=b"\xff\xd8jellyfin", ctype="image/jpeg")}
    with img_app() as c:
        resp = c.get(f"/img/jf:{B}?h=240&v={v}")
    assert resp.status_code == 200 and resp.content == b"\xff\xd8jellyfin"   # today's path, never a store file
    assert images._stored("jf", B, 240, v) is None


# ---- review fixes (2026-10-28): a write that may have happened is always undoable; hand-set posters; backoff ----

def later(days=1):
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone.utc) + timedelta(days=days, minutes=1)


def test_a_failed_lock_after_the_upload_is_recorded_finished_next_pass_and_revertable(jelly_rw):
    fake, out = jelly_rw
    fake.fail_lock = True
    mp.dry_pass(snaps(LIB), pause=0)
    row = mp.state(B)
    assert fake.images[B][0] == ms.master(B).read_bytes()                 # Jellyfin holds the Joey poster ...
    assert row["wrote"] == 1 and row["live_ver"] == row["ver"] and row["live_tag"] is None   # ... and we know it
    assert "lock: HTTP 500" in row["last_error"]
    fake.fail_lock = False
    fake.log.clear()
    assert w.write_pass(limit=30)["finished"] == 5
    assert ("POST", f"/Items/{B}/Images/Primary") not in fake.log          # finished without a second upload
    assert fake.items[B]["LockData"] is True and mp.state(B)["live_tag"] == fake.items[B]["ImageTags"]["Primary"]


def test_a_revert_after_a_failed_lock_restores_the_original(jelly_rw):
    fake, out = jelly_rw
    fake.fail_lock = True
    mp.dry_pass(snaps(LIB), pause=0)
    fake.fail_lock = False
    assert w.revert(B) == "reverted" and fake.images[B] == (ORIG, "image/jpeg")
    assert mp.state(B)["wrote"] == 0


def test_a_failed_read_back_after_the_upload_is_revertable(jelly_rw, monkeypatch):
    fake, out = jelly_rw
    real = w._upload

    def upload_then_fail_reads(*a, **k):
        real(*a, **k)
        fake.fail_reads = 1
    monkeypatch.setattr(w, "_upload", upload_then_fail_reads)
    mp.dry_pass(snaps(LIB), pause=0)
    row = mp.state(B)
    assert row["wrote"] == 1 and row["live_ver"] == row["ver"] and "item: HTTP 500" in row["last_error"]
    monkeypatch.setattr(w, "_upload", real)
    assert w.revert(B) == "reverted" and fake.images[B] == (ORIG, "image/jpeg")


def test_a_crash_between_the_upload_and_the_record_is_still_undone(jelly_rw, monkeypatch):
    fake, out = jelly_rw
    monkeypatch.setenv("POSTERS", "dry")
    mp.dry_pass(snaps(LIB), pause=0)
    monkeypatch.setenv("POSTERS", "on")
    real = w._upload

    def upload_then_die(*a, **k):
        real(*a, **k)
        raise KeyboardInterrupt   # the process dies before live_ver is recorded
    monkeypatch.setattr(w, "_upload", upload_then_die)
    with pytest.raises(KeyboardInterrupt):
        w.apply(B)
    row = mp.state(B)
    assert row["wrote"] == 1 and row["pending_ver"] == row["ver"] and row["live_ver"] is None
    assert fake.images[B][0] == ms.master(B).read_bytes()
    monkeypatch.setattr(w, "_upload", real)
    assert w.revert(B) == "reverted" and fake.images[B] == (ORIG, "image/jpeg")   # honest: the original is back


def test_a_crash_after_the_upload_is_reconciled_by_the_next_pass(jelly_rw, monkeypatch):
    fake, out = jelly_rw
    monkeypatch.setenv("POSTERS", "dry")
    mp.dry_pass(snaps(LIB), pause=0)
    monkeypatch.setenv("POSTERS", "on")
    real = w._upload

    def upload_then_die(*a, **k):
        real(*a, **k)
        raise KeyboardInterrupt
    monkeypatch.setattr(w, "_upload", upload_then_die)
    with pytest.raises(KeyboardInterrupt):
        w.apply(B)
    monkeypatch.setattr(w, "_upload", real)
    assert w.write_pass(limit=30)["written"] == 5
    row = mp.state(B)
    assert row["pending_ver"] is None and row["live_ver"] == row["ver"] and row["live_tag"]


def test_a_revert_that_cannot_reach_jellyfin_says_so(jelly_rw, monkeypatch):
    fake, out = jelly_rw
    mp.dry_pass(snaps(LIB), pause=0)
    fake.fail_upload = True
    assert w.revert(B) == "error" and fake.images[B][0] != ORIG          # never "reverted" when it was not
    fake.fail_upload = False
    assert w.write_pass(limit=30)["reverted"] == 1 and fake.images[B] == (ORIG, "image/jpeg")


def hand_set(fake, jf_id):
    fake.images[jf_id] = (b"\xff\xd8bs-own-poster", "image/jpeg")
    fake._tag(jf_id)


def test_a_hand_set_poster_is_left_alone_and_marked_manual(jelly_rw, caplog):
    fake, out = jelly_rw
    mp.dry_pass(snaps(LIB), pause=0)
    hand_set(fake, B)
    fake.log.clear()
    with caplog.at_level("WARNING", logger="hub.media_posters_write"):
        got = w.write_pass(limit=30, now=later())
    assert got["manual"] == 1 and got["reapplied"] == 0 and fake.writes() == []
    assert mp.state(B)["manual"] == 1 and any("by hand" in rec.getMessage() for rec in caplog.records)
    assert w.write_pass(limit=30, now=later(3))["manual"] == 0 and fake.writes() == []   # never fought again
    assert fake.images[B][0] == b"\xff\xd8bs-own-poster"


def test_revert_keeps_a_hand_set_poster_unless_asked_and_reapply_wins_over_it(jelly_rw):
    fake, out = jelly_rw
    mp.dry_pass(snaps(LIB), pause=0)
    hand_set(fake, B)
    w.write_pass(limit=30, now=later())
    assert w.revert(B) == "manual" and fake.images[B][0] == b"\xff\xd8bs-own-poster"   # his poster stays
    assert ms.lookup(B, 240) is None                                     # Joey stops serving its own
    assert w.write_pass(limit=30, now=later(2))["reverted"] == 0 and fake.images[B][0] == b"\xff\xd8bs-own-poster"
    assert w.revert(B, restore_manual=True) == "reverted" and fake.images[B] == (ORIG, "image/jpeg")
    hand_set(fake, A)
    w.write_pass(limit=30, now=later())
    assert mp.state(A)["manual"] == 1 and w.reapply(A)
    assert w.write_pass(limit=30, now=later())["written"] == 1 and fake.images[A][0] == ms.master(A).read_bytes()
    assert mp.state(A)["manual"] == 0


def test_three_write_failures_back_off_for_a_day_and_free_the_pass(jelly_rw):
    fake, out = jelly_rw
    fake.fail_upload = True
    mp.dry_pass(snaps(LIB), pause=0)                                     # failure 1 (each of the 5)
    w.write_pass(limit=30)                                               # 2
    w.write_pass(limit=30)                                               # 3: backoff
    assert mp.state(B)["fails"] == 3 and mp.in_backoff(mp.state(B))
    fake.log.clear()
    got = w.write_pass(limit=30)
    assert got["backoff"] == 5 and got["error"] == 0 and fake.writes() == []
    fake.fail_upload = False
    assert w.write_pass(limit=30, now=later())["written"] == 5           # retried after 24 h
    assert mp.state(B)["fails"] == 0 and mp.state(B)["retry_at"] is None


def test_three_render_failures_back_off_and_do_not_eat_the_pass_limit(fakes, monkeypatch):
    jf, tmdb, out = fakes
    monkeypatch.setenv("POSTERS_PER_PASS", "1")
    jf.routes = {"/Shows/": Resp(body={"Items": []}), f"/Items/{B}/RemoteImages": Resp(status=500),
                 "/RemoteImages": Resp(body={"Images": [img(None, 7, name="clean")]})}
    for _ in range(3):
        assert mp.dry_pass(snaps(LIB), pause=0)["failed"] == 1        # B (newest) fails, holding the 1-item pass
    assert mp.in_backoff(mp.state(B)) and mp.state(B)["status"] == "failed"
    got = mp.dry_pass(snaps(LIB), pause=0)
    assert got["backoff"] == 1 and got["rendered"] == 1                  # the pass moves on to the next item


def test_the_review_page_shows_manual_and_backing_off_items(fakes, env, monkeypatch):  # noqa: F811
    from tests.hub.test_media_library_pages import jelly
    jf, tmdb, out = fakes
    mp.dry_pass(snaps(LIB), pause=0)
    mp.set_state(A, manual=1, wrote=1)
    for _ in range(3):
        mp.record_failure(C, "WriteError: upload: HTTP 500")
    mp.record_failure("e" * 32, "RuntimeError", kind="movie", title="Never Rendered", status="failed")
    mp.record_failure("e" * 32, "RuntimeError")
    mp.record_failure("e" * 32, "RuntimeError")
    main = env(jellyfin=jelly())
    with TestClient(main.app) as c:
        body = c.get("/media/posters").text
        assert "Manual: changed by hand in Jellyfin" in body and "Re-apply the Joey poster" in body
        assert "Put the original back in Jellyfin" in body
        assert "Failed 3 times" in body and "Never Rendered" in body and "Try again now" in body
        assert c.post(f"/media/posters/{C}/reapply", follow_redirects=False).status_code == 303
        assert not mp.in_backoff(mp.state(C))


# ---- verifier fixes (2026-10-28): a failed revert retries the revert; the item lock; confirmed restores ----

def _fail_revert_three_times(fake):
    mp.dry_pass(snaps(LIB), pause=0)
    fake.fail_upload = True
    assert w.revert(B) == "error"                                        # failure 1
    w.write_pass(limit=30)                                                # 2
    w.write_pass(limit=30)                                                # 3: backoff
    assert mp.in_backoff(mp.state(B)) and mp.state(B)["reverted"] == 1


def test_try_again_on_a_failing_revert_retries_the_revert_never_reapplies(jelly_rw):
    """Verifier repro 1, fixed: "Try again now" posts /retry, which repeats the revert."""
    fake, out = jelly_rw
    _fail_revert_three_times(fake)
    row = [r for r in mp.rows() if r["jf_id"] == B][0]
    assert row["backoff"] and row["reverted"] and row["wrote"]
    fake.fail_upload = False
    assert w.retry(B) == "reverted"
    assert mp.state(B)["reverted"] == 1 and fake.images[B] == (ORIG, "image/jpeg")
    fake.log.clear()
    w.write_pass(limit=30, now=later())                                   # the revert is sticky
    assert not [x for x in fake.writes() if B in x[1]]


def test_the_page_offers_retry_the_revert_for_a_failing_revert(jelly_rw, env):  # noqa: F811
    from tests.hub.test_media_library_pages import jelly
    fake, out = jelly_rw
    _fail_revert_three_times(fake)
    fake.fail_upload = False
    main = env(jellyfin=jelly())
    with TestClient(main.app) as c:
        body = c.get("/media/posters").text
        assert "Retry the revert" in body and f"/media/posters/{B}/retry" in body
        assert "Revert pending: Jellyfin still has the Joey poster" in body
        resp = c.post(f"/media/posters/{B}/retry", follow_redirects=False)
        assert resp.status_code == 303 and resp.headers["location"].endswith("?done=reverted")
        assert "Jellyfin has the original again (confirmed)" in c.get(resp.headers["location"]).text
        assert "<script" not in c.get("/media/posters?done=%3Cscript%3E").text.split("<main", 1)[1]
    assert mp.state(B)["reverted"] == 1 and fake.images[B] == (ORIG, "image/jpeg")


def test_a_revert_racing_an_upload_queues_and_is_never_lost(jelly_rw, monkeypatch):
    """Verifier repro 2, fixed: B. clicks Revert while the upload is in flight."""
    fake, out = jelly_rw
    mp.dry_pass(snaps(LIB), pause=0)
    mp.set_state(B, live_ver=None)                                       # B due for a (re)write
    monkeypatch.setattr(w, "REVERT_WAIT_S", 0.0)
    real_post = fake.post
    said = {}

    def post(url, **kw):
        if url.endswith(f"/Items/{B}/Images/Primary") and not said:
            said["revert"] = w.revert(B)                                 # in the middle of the upload
        return real_post(url, **kw)
    monkeypatch.setattr(fake, "post", post)
    w.apply(B)
    assert said["revert"] == "queued"                                    # never "reverted" while a write is in flight
    assert mp.state(B)["reverted"] == 1 and mp.state(B)["wrote"] == 1
    assert w.write_pass(limit=30)["reverted"] == 1 and fake.images[B] == (ORIG, "image/jpeg")
    assert mp.state(B)["wrote"] == 0 and mp.state(B)["lock_owner"] is None


def test_a_revert_that_waits_gets_the_lock_once_the_write_ends(jelly_rw):
    import threading as th
    fake, out = jelly_rw
    mp.dry_pass(snaps(LIB), pause=0)
    mp.set_state(B, reverted=1)
    assert mp.claim(B, "the-write-pass")
    th.Timer(0.3, mp.release, args=(B, "the-write-pass")).start()
    assert w._undo(B, wait_s=5) == "reverted" and fake.images[B] == (ORIG, "image/jpeg")


def test_a_write_never_starts_while_a_revert_holds_the_item(jelly_rw):
    fake, out = jelly_rw
    mp.dry_pass(snaps(LIB), pause=0)
    mp.set_state(B, live_ver=None)
    assert mp.claim(B, "a-web-revert")
    fake.log.clear()
    assert w.apply(B) == "skipped" and not fake.writes()
    mp.set_state(B, reverted=1)                                          # the revert's intent lands ...
    mp.release(B, "a-web-revert")
    assert w.apply(B) == "skipped" and not fake.writes()                 # ... and the write re-reads it under the lock


def test_a_stale_lock_from_a_crashed_holder_expires():
    from datetime import datetime, timedelta, timezone
    mp.set_state(B, kind="movie", status="rendered")
    t0 = datetime(2026, 10, 28, tzinfo=timezone.utc)
    assert mp.claim(B, "crashed", now=t0)
    assert not mp.claim(B, "next", now=t0 + timedelta(seconds=mp.LOCK_TTL_S - 1))
    assert mp.claim(B, "next", now=t0 + timedelta(seconds=mp.LOCK_TTL_S + 1))


def test_a_restore_jellyfin_did_not_take_is_not_reported_as_reverted(jelly_rw, monkeypatch):
    fake, out = jelly_rw
    mp.dry_pass(snaps(LIB), pause=0)
    real_post = fake.post

    def swallow(url, **kw):   # answers 204 to the restore upload but keeps the Joey image
        if url.endswith("/Images/Primary") and base64.b64decode(kw["data"]) == ORIG:
            fake.log.append(("POST", url.split("http://jf.test", 1)[1]))
            return Resp(status=204)
        return real_post(url, **kw)
    monkeypatch.setattr(fake, "post", swallow)
    assert w.revert(B) == "error" and "not confirmed" in mp.state(B)["last_error"]
    assert mp.state(B)["wrote"] == 1                                     # still owed: retried by the next pass


def test_queued_reverts_run_even_when_the_template_is_unusable(jelly_rw, monkeypatch):
    fake, out = jelly_rw
    mp.dry_pass(snaps(LIB), pause=0)
    monkeypatch.setattr(w, "REVERT_WAIT_S", 0.0)
    assert mp.claim(B, "busy")
    assert w.revert(B) == "queued"
    mp.release(B, "busy")
    monkeypatch.setattr(mp, "template_state", lambda: (None, ["broken"], True))
    counts = mp.dry_pass(snaps(LIB), pause=0)
    assert counts["write"]["reverted"] == 1 and fake.images[B] == (ORIG, "image/jpeg")


def test_an_older_poster_table_gains_the_new_columns(monkeypatch, tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    monkeypatch.setenv("MEDIA_DB_PATH", str(path))
    with sqlite3.connect(path) as db:   # the 94b3c34 shape
        db.execute("""CREATE TABLE poster(jf_id TEXT PRIMARY KEY, kind TEXT NOT NULL, ver TEXT, template TEXT,
            status TEXT NOT NULL, reverted INTEGER NOT NULL DEFAULT 0, bytes INTEGER, rendered_at TEXT, orig_ext TEXT,
            orig_tag TEXT, live_ver TEXT, live_tag TEXT, locked_by_us INTEGER NOT NULL DEFAULT 0, written_at TEXT,
            checked_at TEXT, last_error TEXT)""")
        db.execute("INSERT INTO poster(jf_id, kind, status) VALUES (?, 'movie', 'rendered')", (B,))
    db.close()
    mp._ddl_done.clear()
    mp.set_state(B, wrote=1, manual=0, fails=2, title="Kept")
    assert mp.state(B)["fails"] == 2 and mp.claim(B, "x")


def test_a_season_list_that_keeps_failing_backs_off(fakes):
    jf, tmdb, out = fakes
    jf.routes = {"/Shows/": Resp(status=500), "/RemoteImages": Resp(body={"Images": [img(None, 7, name="clean")]})}
    for _ in range(3):
        mp.dry_pass(snaps(LIB), pause=0)
    assert mp.in_backoff(mp.state(C)) and mp.state(C)["kind"] == "tv"
    jf.calls.clear()
    got = mp.dry_pass(snaps(LIB), pause=0)
    assert got["backoff"] == 1 and not [u for u in jf.calls if "/Shows/" in u]


# ---- verifier follow-ups (2026-10-28): a busy database reads as a busy item; the lock heartbeat ----

def test_a_locked_database_on_claim_is_retried_then_the_item_is_skipped(jelly_rw, monkeypatch, caplog):
    import sqlite3
    fake, out = jelly_rw
    mp.dry_pass(snaps(LIB), pause=0)
    mp.set_state(B, live_ver=None)
    calls = {"n": 0}
    real = mp.connect

    def locked():
        calls["n"] += 1
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(mp, "CLAIM_RETRY_S", 0.0)
    monkeypatch.setattr(mp, "connect", locked)
    with caplog.at_level("WARNING", logger="hub.media_posters"):
        assert mp.claim(B, "x") is False
    assert calls["n"] == mp.CLAIM_TRIES and any("item lock unavailable" in r.getMessage() for r in caplog.records)
    fake.log.clear()
    assert w.apply(B) == "skipped" and not fake.writes()               # busy: skipped this pass, nothing raised
    monkeypatch.setattr(mp, "connect", real)
    assert w.apply(B) == "written"


def test_a_slow_backup_read_keeps_its_lock_alive(jelly_rw, monkeypatch):
    import time as _time
    fake, out = jelly_rw
    monkeypatch.setenv("POSTERS", "dry")
    mp.dry_pass(snaps(LIB), pause=0)
    monkeypatch.setenv("POSTERS", "on")
    monkeypatch.setattr(mp, "LOCK_TTL_S", 1)
    monkeypatch.setattr(w, "BEAT_S", 0.2)
    rivals = []

    class Slow(Resp):
        def iter_content(self, n):
            for i in range(4):                       # 4 x 0.5 s: twice the 1 s lock lifetime
                _time.sleep(0.5)
                rivals.append(mp.claim(B, "a-rival"))  # a stale-lock takeover would succeed here
                yield ORIG[:4] if i == 0 else b""
            yield ORIG[4:]
    real_get = fake.get

    def get(url, **kw):
        if url.endswith(f"/Items/{B}/Images/Primary"):
            fake.log.append(("GET", url.split("http://jf.test", 1)[1]))
            return Slow(data=ORIG, ctype="image/jpeg")
        return real_get(url, **kw)
    monkeypatch.setattr(fake, "get", get)
    assert w.apply(B) == "written"
    assert rivals and not any(rivals)                # the live writer never lost its lock
    assert ms.orig_path(B).read_bytes() == ORIG


def test_a_writer_that_lost_its_lock_stops_before_uploading(jelly_rw, monkeypatch):
    fake, out = jelly_rw
    monkeypatch.setenv("POSTERS", "dry")
    mp.dry_pass(snaps(LIB), pause=0)
    monkeypatch.setenv("POSTERS", "on")
    real = w.backup

    def backup_then_taken_over(base, headers, jf_id, item):
        real(base, headers, jf_id, item)
        mp.set_state(jf_id, lock_owner="someone-else", lock_until="2999-01-01T00:00:00Z")
    monkeypatch.setattr(w, "backup", backup_then_taken_over)
    assert w.apply(B) == "error" and "item lock lost" in mp.state(B)["last_error"]
    assert ("POST", f"/Items/{B}/Images/Primary") not in fake.log


def test_the_tv_backdrop_url_matches_the_tile_url_for_a_stored_poster(fakes):
    """tv_home.img_url (the blurred-poster backdrop tv.js swaps to) stays the same browser-cache entry as art()."""
    from hub import shell, tv_home
    mp.dry_pass(snaps(LIB), pause=0)
    tile = shell.templates.env.from_string('{% from "_tv_tile.html" import art %}{{ art(ref, "New Film", 240) }}')
    drawn = tile.render(ref=f"jf:{B}").split('src="', 1)[1].split('"', 1)[0].replace("&amp;", "&")
    assert tv_home.img_url(f"jf:{B}", "New Film", 240) == drawn and f"&v={ms.current(B)}" in drawn
