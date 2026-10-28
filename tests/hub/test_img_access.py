"""JY-263: on the media front /img serves a Jellyfin image (poster, backdrop, stored Joey poster) only for an id the
viewer was shown. Household and the private front: everything. No network call is made to decide. Invented ids."""
import importlib
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

from hub import guest, img_access, images, media_item, media_posters
from hub.identity import Identity
from tests.hub.helpers import write_envelope

REPO_ROOT = Path(__file__).resolve().parents[2]
FRIEND = Identity(owner="jf:" + "f00d" * 8, name="Sample Friend", jf_user_id="f00d" * 8)
OTHER = Identity(owner="jf:" + "beef" * 8, name="Other Friend", jf_user_id="beef" * 8)
HOUSEHOLD = Identity(owner="you", name="Sample Owner", jf_user_id="a1" * 16)
SHARED, HER_ONLY, OWN, SEASON = "a" * 32, "b" * 32, "c" * 32, "d" * 32
JPEG = b"\xff\xd8\xff\xe0fakejpegbytes"


class Resp:
    status_code, headers, content = 200, {"content-type": "image/jpeg"}, JPEG


@pytest.fixture()
def calls(monkeypatch, tmp_path):
    """The media front, an empty image cache, a Jellyfin that answers every image, and a log of every upstream call."""
    monkeypatch.setenv("JOEY_FRONT", "media")
    monkeypatch.setenv("IMG_CACHE_DIR", str(tmp_path / "img"))
    monkeypatch.setenv("JELLYFIN_URL", "http://jelly.example.invalid:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "KEY")
    monkeypatch.setenv("AREAS_PATH", str(REPO_ROOT / "config" / "areas.yaml"))
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyfin", data={
        "movies": [{"jf_id": SHARED, "title": "Shared Film"}], "shows": [], "latest": [],
        "her": {"movies": [{"jf_id": HER_ONLY, "title": "Her Film"}], "shows": []}})
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    log = []

    def fake_get(url, params=None, headers=None, timeout=None, stream=False):
        log.append(url)
        return Resp()

    monkeypatch.setattr(requests, "get", fake_get)
    img_access.clear()
    return log


def client_as(monkeypatch, who):
    monkeypatch.setattr(guest, "identity_provider", lambda scope: who)
    import hub.main
    importlib.reload(hub.main)
    return TestClient(hub.main.app)


def get(c, ref, **kw):
    return c.get(f"/img/{ref}", follow_redirects=False, **kw)


def is_card(r):
    return r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")


def test_friend_cannot_fetch_an_item_outside_the_shared_library(calls, monkeypatch):
    c = client_as(monkeypatch, FRIEND)
    for ref in (f"jf:{HER_ONLY}", f"jfb:{HER_ONLY}", f"jfb:{HER_ONLY}/1"):
        assert is_card(get(c, ref)), ref
    assert calls == []   # refused before any upstream call


def test_friend_cannot_fetch_a_stored_poster_of_a_hidden_item(calls, monkeypatch, tmp_path):
    stored = tmp_path / "abc123.jpg"
    stored.write_bytes(b"STORED")
    monkeypatch.setattr(media_posters, "served", lambda jf_id, h: stored)
    c = client_as(monkeypatch, FRIEND)
    assert is_card(get(c, f"jf:{HER_ONLY}", params={"v": "abc123"}))
    ok = get(c, f"jf:{SHARED}", params={"v": "abc123"})   # a visible item still gets the stored poster
    assert ok.content == b"STORED" and ok.headers["cache-control"] == images.HIT_CACHE


def test_friend_fetches_a_shared_library_item_with_unchanged_headers(calls, monkeypatch):
    c = client_as(monkeypatch, FRIEND)
    for ref in (f"jf:{SHARED}", f"jfb:{SHARED}"):
        r = get(c, ref)
        assert r.status_code == 200 and r.content == JPEG
        assert r.headers["content-type"] == "image/jpeg" and r.headers["cache-control"] == images.HIT_CACHE
    assert len(calls) == 2


def test_friend_fetches_what_their_own_reads_showed_and_no_one_elses(calls, monkeypatch):
    img_access.note(FRIEND.jf_user_id, {"item": {"id": OWN, "poster": f"jf:{OWN}"},
                                        "seasons": [{"id": SEASON, "episodes": [{"jf_id": "e" * 32}]}]})
    c = client_as(monkeypatch, FRIEND)
    for ident in (OWN, SEASON, "e" * 32):
        assert get(c, f"jf:{ident}").content == JPEG
    other = client_as(monkeypatch, OTHER)
    assert is_card(get(other, f"jf:{OWN}"))   # another friend's read does not open it for this one


def test_media_item_read_notes_the_viewers_ids(calls, monkeypatch):
    monkeypatch.setattr(media_item, "_build", lambda jf_id: {
        "item": {"id": OWN, "poster": f"jf:{OWN}", "backdrop": f"jfb:{OWN}", "show_id": None},
        "seasons": [{"id": SEASON, "episodes": []}], "files": None})
    monkeypatch.setattr(guest, "is_media", lambda: True)
    from hub import media_jellyfin
    token = media_jellyfin.bind_viewer(FRIEND.jf_user_id)
    try:
        media_item._read(OWN, force=True)
    finally:
        media_jellyfin.reset_viewer(token)
    assert img_access.friend_may_see(FRIEND.jf_user_id, SEASON)
    assert not img_access.friend_may_see(OTHER.jf_user_id, SEASON)


def test_household_on_the_media_front_is_unaffected(calls, monkeypatch):
    c = client_as(monkeypatch, HOUSEHOLD)
    r = get(c, f"jf:{HER_ONLY}")
    assert r.status_code == 200 and r.content == JPEG and r.headers["cache-control"] == images.HIT_CACHE


def test_private_front_is_unaffected(calls, monkeypatch):
    monkeypatch.delenv("JOEY_FRONT")
    import hub.main
    importlib.reload(hub.main)
    r = get(TestClient(hub.main.app), f"jf:{HER_ONLY}")
    assert r.status_code == 200 and r.content == JPEG


def test_tmdb_and_arr_refs_are_not_checked(calls, monkeypatch):
    c = client_as(monkeypatch, FRIEND)
    assert get(c, "tmdb:/abc.jpg").content == JPEG


def test_unknown_viewer_gets_the_ordinary_404_page(calls, monkeypatch):
    class Bare:
        scope = {"state": {}}
    assert img_access.allowed(Bare(), "jf", HER_ONLY) is None


def test_deciding_makes_no_network_call_and_snapshot_is_read_once(calls, monkeypatch):
    c = client_as(monkeypatch, FRIEND)
    get(c, f"jf:{SHARED}")
    before = len(calls)
    reads = []
    from hub import shell
    real = shell.get_snapshots
    monkeypatch.setattr(shell, "get_snapshots", lambda *a, **k: reads.append(1) or real(*a, **k))
    for _ in range(20):
        assert is_card(get(c, f"jf:{HER_ONLY}"))
    assert len(calls) == before and reads == []   # 20 refusals: no upstream call, snapshot set reused
