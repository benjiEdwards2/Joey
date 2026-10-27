"""JY-105 (B., 2026-10-27: "look B; ratings 9-10; 5 sources; refresh daily; friends: their own ratings; TV: row, never
first focus"): the "Because you rated these 9 or 10" shelf on Media Overview.

The warm-up (riding the 24 h library pass) reads Seerr recommendations for each viewer's top 5 title-level 9-10 ratings
into a per-viewer cache; the shelf reads only that cache. Seerr is faked (media_discover._fetch); no network.
Spec: docs/specs/JY-105-because-shelf.md."""
import importlib
import json
import os
import socket
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

from hub import media_because, media_db, media_discover as md, media_store, media_warmup
from tests.hub.fake_jellyfin import FRIEND_ID, OTHER_ID
from tests.hub.fake_seerr import res
from tests.hub.guest_pages import TV_UA, guest_client, shelf_titles, sign_in
from tests.hub.helpers import JELLY, make_area, shelf_area, write_envelope, write_registry
from tests.hub.test_tv_mode import gc, run_tv_pages  # noqa: F401  (gc: the TV fixture)

TITLE = "Because you rated these 9 or 10"
FRIEND = "jf:" + FRIEND_ID
OTHER = "jf:" + OTHER_ID
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


# ---- fakes ----

class Seerr:
    """media_discover._fetch stand-in: recommendations per (kind, tmdb); records every path asked."""

    def __init__(self, recs: dict, fail: set = frozenset()):
        self.recs, self.fail, self.calls = recs, fail, []

    def __call__(self, path, timeout=None):
        self.calls.append(path)
        parts = path.strip("/").split("/")   # api v1 <kind> <tmdb> recommendations
        key = (parts[2], int(parts[3]))
        if key in self.fail:
            return None, 500
        return {"page": 1, "results": self.recs.get(key, [])}, 200


def rate(monkeypatch, key, score, owner="you", kind="movie", level="show", at=0):
    monkeypatch.setattr(media_db, "_now", lambda: T0 + timedelta(hours=at))
    media_db.set_rating(key, score, kind, f"Title {key}", owner=owner, level=level)


def play(owner, item_key, show_key=None):
    with closing(media_store.connect()) as db, db:
        db.execute("INSERT INTO play(owner, item_key, show_key, title) VALUES(?,?,?,?)",
                   (owner, item_key, show_key, "x"))


class Snap:
    def __init__(self, data):
        self.data = data


def cache_file() -> Path:
    return Path(os.environ["META_CACHE_DIR"]) / media_because.FILE


def write_cache(viewers: dict) -> None:
    path = cache_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"at": time.time(), "viewers": viewers}), encoding="utf-8")


def rows(*results):
    return md._rows(list(results))


def source(title, score, kind, tmdb, *results):
    return {"title": title, "score": score, "kind": kind, "tmdb": tmdb, "rows": rows(*results)}


@pytest.fixture()
def seerr_env(monkeypatch):
    monkeypatch.setenv("JELLYSEERR_URL", "http://seerr.test:5055")
    monkeypatch.setenv("JELLYSEERR_API_KEY", "seerr-key-SECRET")


# ---- the warm-up ----

def test_warm_up_picks_each_viewers_top_five_and_drops_rated_and_watched(monkeypatch, seerr_env):
    # you: six 9-10 title-level tmdb ratings (the oldest 9 is the sixth), plus ones that are never sources
    rate(monkeypatch, "tmdb:6", 9, at=0)
    rate(monkeypatch, "tmdb:1", 10, at=1)
    rate(monkeypatch, "tmdb:2", 9, at=2)
    rate(monkeypatch, "tmdb:4", 9, at=3)
    rate(monkeypatch, "tmdb:3", 10, at=4)
    rate(monkeypatch, "tmdb:5", 9, at=5)
    rate(monkeypatch, "tmdb:7", 8, at=6)                        # under 9
    rate(monkeypatch, "tvdb:8", 10, kind="tv", at=7)            # Seerr cannot look it up
    rate(monkeypatch, "tmdb:9", 10, level="season", at=8)       # not title level
    rate(monkeypatch, "tmdb:100", 5, at=9)                      # rated (low): its title is dropped from recs
    # her: one source, shared with you (tmdb:3) - read once
    rate(monkeypatch, "tmdb:3", 9, owner="her", at=1)
    rate(monkeypatch, "tmdb:50", 10, owner="her", at=2)
    # a friend: only their own rating; the household's never feed it
    rate(monkeypatch, "tmdb:60", 9, owner=FRIEND, at=1)
    # watched on the server: you via the play table, the diary, an episode of a show, the snapshot's played flag
    play("you", "tmdb:101")
    play("you", "jf:ep1", show_key="jf:s107")
    media_db.add_manual_watch("tmdb:105", "movie", "Diary Film", owner="you")
    jelly = {"movies": [{"item_key": "tmdb:102", "jf_id": "m102", "played": True}],
             "shows": [{"item_key": "tmdb:107", "jf_id": "s107", "played": False}],
             "her": {"movies": [{"item_key": "tmdb:106", "jf_id": "m106", "played": True}], "shows": []}}
    recs = {("movie", 3): [res(100, "Rated Low"), res(101, "Played"), res(102, "Snapshot Played"),
                           res(103, "Keep A"), res(104, "Keep B"), res(105, "Diary Logged"),
                           res(106, "Her Played"), res(107, "Show Ep Watched", "tv")],
            ("movie", 50): [res(106, "Her Played"), res(501, "Her Keep")],
            ("movie", 60): [res(100, "Rated By You Only"), res(601, "Friend Keep")]}
    fake = Seerr(recs)
    monkeypatch.setattr(md, "_fetch", fake)

    out = media_because.refresh({"jellyfin": Snap(jelly)}, pause=0)

    viewers = json.loads(cache_file().read_text(encoding="utf-8"))["viewers"]
    assert [s["tmdb"] for s in viewers["you"]] == [3, 1, 5, 4, 2]          # score desc, newest first on a tie; 5 max
    assert viewers["you"][0]["score"] == 10 and viewers["you"][0]["title"] == "Title tmdb:3"
    assert [r["title"] for r in viewers["you"][0]["rows"]] == ["Keep A", "Keep B", "Her Played"]
    assert [s["tmdb"] for s in viewers["her"]] == [50, 3]
    assert [r["title"] for r in viewers["her"][0]["rows"]] == ["Her Keep"]    # her snapshot played film dropped
    assert "Keep A" in [r["title"] for r in viewers["her"][1]["rows"]]
    assert [s["tmdb"] for s in viewers[FRIEND]] == [60]                       # their own rating only
    assert [r["title"] for r in viewers[FRIEND][0]["rows"]] == ["Rated By You Only", "Friend Keep"]
    assert fake.calls.count("/api/v1/movie/3/recommendations") == 1           # shared source: one read
    assert len(fake.calls) == 7 and out["sources"] == 7


def test_a_failed_read_keeps_the_last_rows_and_no_keys_leaves_the_cache(monkeypatch, seerr_env):
    rate(monkeypatch, "tmdb:1", 10)
    monkeypatch.setattr(md, "_fetch", Seerr({("movie", 1): [res(11, "First Pass")]}))
    media_because.refresh({}, pause=0)
    monkeypatch.setattr(md, "_fetch", Seerr({}, fail={("movie", 1)}))
    media_because.refresh({}, pause=0)
    viewers = media_because.read()
    assert [r["title"] for r in viewers["you"][0]["rows"]] == ["First Pass"]
    for name in ("JELLYSEERR_URL", "JELLYSEERR_API_KEY"):
        monkeypatch.delenv(name)
    before = cache_file().read_text(encoding="utf-8")
    assert media_because.refresh({}, pause=0).get("skipped_no_keys")
    assert cache_file().read_text(encoding="utf-8") == before


def test_refresh_rides_the_24h_library_pass(monkeypatch):
    monkeypatch.setenv("MEDIA_WARMUP", "on")
    calls = []
    monkeypatch.setattr(media_warmup, "warm_once", lambda snaps=None, pause=0: {})
    monkeypatch.setattr(media_warmup, "warm_library", lambda snaps=None, pause=0: {"titles": 0})
    monkeypatch.setattr(media_warmup.media_rank, "due", lambda: False)
    monkeypatch.setattr(media_because, "refresh", lambda snaps=None, **kw: calls.append(1) or {"sources": 0})
    assert "because" in media_warmup.run_pass(snaps={}, pause=0) and len(calls) == 1
    assert "because" not in media_warmup.run_pass(snaps={}, pause=0) and len(calls) == 1   # within 24 h
    media_warmup._stamp_path().write_text(str(time.time() - 25 * 3600))
    media_warmup.run_pass(snaps={}, pause=0)
    assert len(calls) == 2                                                               # the next day
    monkeypatch.setenv("MEDIA_WARMUP", "shelves")
    media_warmup._stamp_path().write_text(str(time.time() - 25 * 3600))
    media_warmup.run_pass(snaps={}, pause=0)
    assert len(calls) == 2


# ---- the merge ----

def test_round_robin_across_sources_skips_repeats_and_caps_at_shelf_max():
    entry = [source("A", 10, "movie", 1, res(1001, "a1"), res(1002, "a2"), res(1003, "a3")),
             source("B", 10, "movie", 2, res(2001, "b1"), res(1001, "a1 again")),
             source("C", 9, "movie", 3, *[res(3000 + n, f"c{n}") for n in range(1, 21)])]
    got = media_because.merge(entry)
    assert [(r["title"], s["title"]) for r, s in got][:8] == [
        ("a1", "A"), ("b1", "B"), ("c1", "C"), ("a2", "A"), ("c2", "C"), ("a3", "A"), ("c3", "C"), ("c4", "C")]
    assert len(got) == 15 == media_because.shelf_max()
    assert media_because.merge([]) == [] and media_because.merge(None) == []


# ---- the shelf on the household front ----

@pytest.fixture()
def home(tmp_path, monkeypatch, seerr_env):
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, shelf_area(), make_area("beta"))))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    lib = [{"title": "On Server Film", "item_key": "tmdb:201", "jf_id": "a" * 32, "poster": "jf:x"}]
    write_envelope(tmp_path / "snaps", "jellyfin", age_minutes=1, data={**JELLY, "movies": lib, "shows": []})

    def boom(*a, **k):
        raise AssertionError("no upstream call on render")

    monkeypatch.setattr(md, "_fetch", boom)
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as client:
        yield client


def section(html: str, title: str = TITLE) -> str | None:
    main = html.split("<main", 1)[1]
    at = main.find(f'<h2 class="seclabel">{title}')
    if at < 0:
        return None
    return main[main.rfind("<section", 0, at):main.find("</section>", at)]


def you_her_friend():
    write_cache({
        "you": [source("Paper Moons", 9, "movie", 1, res(201, "Mine On Server"), res(202, "Mine To Request"))],
        "her": [source("Her Pick", 10, "movie", 2, res(301, "Hers Only"))],
        FRIEND: [source("Friend Pick", 9, "movie", 3, res(401, "Friend Only"))],
    })


def test_render_reads_only_the_cache_with_sockets_blocked(home, monkeypatch):
    you_her_friend()

    def blocked(*a, **k):
        raise AssertionError("socket opened on render")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(requests, "get", blocked)
    monkeypatch.setattr(requests.Session, "request", blocked)
    html = home.get("/a/alpha?owner_view=you").text
    sec = section(html)
    assert sec is not None
    assert "Paper Moons ★9" in sec
    assert 'href="/media/item/' + "a" * 32 + '"' in sec and "On server" in sec        # in the library: item page
    assert 'href="/media/title/movie/202"' in sec and "Request" in sec               # not on the server
    titles = shelf_titles(html.split("<main", 1)[1])
    assert titles.index(TITLE) == titles.index("Continue watching") + 1               # directly below it


def test_the_shelf_hides_when_the_cache_is_empty(home):
    assert TITLE not in home.get("/a/alpha?owner_view=you").text                            # no file
    write_cache({"you": []})
    assert TITLE not in home.get("/a/alpha?owner_view=you").text                            # an empty entry
    write_cache({"her": [source("Her Pick", 10, "movie", 2, res(301, "Hers Only"))]})
    html = home.get("/a/alpha?owner_view=you").text
    assert TITLE not in html and "Hers Only" not in html                              # no placeholder either
    cache_file().write_text("not json", encoding="utf-8")
    assert home.get("/a/alpha?owner_view=you").status_code == 200


def test_household_views_see_only_their_own_shelf(home):
    you_her_friend()
    mine, hers = section(home.get("/a/alpha?owner_view=you").text), section(home.get("/a/alpha?owner_view=her").text)
    assert "Mine To Request" in mine and "Hers Only" not in mine and "Friend Only" not in mine
    assert "Hers Only" in hers and "Mine To Request" not in hers and "Friend Only" not in hers


# ---- the media front: a friend's own shelf only ----

def test_a_friend_sees_only_their_own_shelf(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": {**JELLY, "movies": [], "shows": []}})
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        you_her_friend()
        sec = section(c.get("/a/media").text)
        assert sec is not None and "Friend Only" in sec and "Friend Pick ★9" in sec
        assert "Mine To Request" not in sec and "Hers Only" not in sec
        tv = section(c.get("/a/media", headers={"User-Agent": TV_UA}).text)
        assert "data-tv-later" in tv                                                  # TV: never first focus
        sign_in(c, fake, OTHER_ID)                                                    # a friend with no entry
        html = c.get("/a/media").text
        assert TITLE not in html and "Mine To Request" not in html and "Friend Only" not in html


# ---- TV focus order ----

def test_tv_the_shelf_is_a_row_reached_with_down_and_never_first_focus_under_node(gc, tmp_path):
    out = run_tv_pages(gc, tmp_path, r"""
function home(cont, rest) {
  var main = shell('overview'), row = 0;
  if (cont) { poster(main, 'c1', 1, row, 0); poster(main, 'c2', 2, row, 1); row++; }
  var sec = new El('section', { cls: ['sec'], attrs: { 'data-tv-later': '' } });
  main.append(sec);
  poster(sec, 'b1', 11, row, 0); poster(sec, 'b2', 12, row, 1); row++;
  if (rest) { poster(main, 'a1', 21, row, 0); poster(main, 'a2', 22, row, 1); }
}
load('/a/m1', function () { home(true, true); });
out.first = now(); key('ArrowDown'); out.down = now(); key('ArrowDown'); out.down2 = now();
load('/a/m2', function () { home(false, true); });
out.first_no_continue = now(); key('ArrowUp'); out.up = now();
load('/a/m3', function () { home(false, false); });
out.only = now();
""")
    assert out == {"first": "c1", "down": "b1", "down2": "a1", "first_no_continue": "a1", "up": "b1",
                   "only": "brand"}
