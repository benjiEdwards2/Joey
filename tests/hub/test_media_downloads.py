"""Downloads (2026-10-06): /media/downloads page, the arr x qBittorrent join
(merge_downloading), This-week and title-page badges, and the hub hero sub-line.
The qbittorrent envelope is written in-test; nothing reads a sample file."""
import importlib
import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

from hub.media_downloads import merge_downloading, pct_for_keys
from tests.hub.test_media_discover import FAKE_KEY, FAKE_URL, MOVIE, Fake
from tests.hub.helpers import make_area, make_tile, shelf_area, write_envelope, write_registry
from tests.hub.conftest import main_of  # noqa: F401  (shared helper; other test modules import it from here)

H1, H2 = "a" * 40, "b" * 40
QB = {
    "summary": "2 downloading · 1.4 MB/s", "secondary": "5 seeding · 1 finished today",
    "active": [
        {"hash": H1, "name": "Midnight Harbour 2021 1080p", "kind": "movie", "category": "radarr", "pct": 43,
         "state_text": "Downloading", "speed_text": "1.1 MB/s", "eta_text": "12 min", "size_text": "4.2 GB",
         "added": "2026-10-06T01:00:00+00:00"},
        {"hash": H2, "name": "Some Show S01", "kind": "tv", "category": "sonarr", "pct": 10,
         "state_text": "Stalled", "speed_text": "", "eta_text": "", "size_text": "9.0 GB",
         "added": "2026-10-06T02:00:00+00:00"},
        {"hash": "c" * 40, "name": "Linux ISO", "kind": "other", "category": "", "pct": 99,
         "state_text": "Queued", "speed_text": "", "eta_text": "", "size_text": "1.0 GB",
         "added": "2026-10-06T03:00:00+00:00"},
    ],
    "finished": [{"hash": "d" * 40, "name": "Done Film", "kind": "movie", "size_text": "3.3 GB",
                  "when": "2026-10-06T00:00:00+00:00"}],
    "seeding": 5,
    "totals": {"dl_bps": 1468006, "up_bps": 235000, "dl_text": "1.4 MB/s", "up_text": "230 kB/s"},
}
EMPTY_QB = {"summary": "Nothing downloading", "secondary": "", "active": [], "finished": [], "seeding": 0,
            "totals": {"dl_bps": 0, "up_bps": 0, "dl_text": "0 B/s", "up_text": "0 B/s"}}
ARR = {"summary": "x", "secondary": "", "arrived": [], "updated": [], "disk": [],
       "this_week": [{"title": "Midnight Harbour", "kind": "movie", "date": date.today().isoformat(),
                      "label": "Digital", "item_key": "tmdb:603"}],
       "downloading": [{"title": "Midnight Harbour", "kind": "movie", "pct": 75, "status_text": "Downloading",
                        "time_left": "14 min", "item_key": "tmdb:603", "download_id": H1}]}


def area():
    a = shelf_area()
    a["tiles"].append(make_tile("dl-t", snapshot="qbittorrent", stale_after_minutes=10, detail="/media/downloads"))
    a["tiles"].append(make_tile("disc-t", snapshot="jellyseerr", stale_after_minutes=180, detail="/media/discover"))
    return a


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, area(), make_area("beta"))))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.delenv("JELLYSEERR_URL", raising=False)
    monkeypatch.delenv("JELLYSEERR_API_KEY", raising=False)

    def build(**data):
        for cid, d in data.items():
            write_envelope(tmp_path / "snaps", cid, age_minutes=1, data=d)
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)

    return build


def test_downloads_page_groups_words_and_totals(env):
    with env(qbittorrent=QB) as client:
        resp = client.get("/media/downloads")
    assert resp.status_code == 200
    body = main_of(resp.text)
    assert "↓ 1.4 MB/s · ↑ 230 kB/s · 5 seeding" in body
    order = [body.index(f">{h}</h2>") for h in ("Movies", "TV", "Other", "Finished today")]
    assert order == sorted(order)
    assert "Midnight Harbour 2021 1080p" in body and 'class="row-meta">Downloading · ' in body
    assert "43% done · 1.1 MB/s · 12 min left · 4.2 GB" in body and "width: 43%" in body
    assert 'class="row-meta">Stalled · ' in body and "10% done · 9.0 GB" in body
    assert "Done Film" in body and "3.3 GB" in body


def test_downloads_page_omits_empty_groups_and_states_empty_in_words(env):
    with env(qbittorrent={**QB, "active": [QB["active"][1]], "finished": []}) as client:
        body = main_of(client.get("/media/downloads").text)
    assert ">TV</h2>" in body and ">Movies</h2>" not in body and ">Other</h2>" not in body
    with env(qbittorrent=EMPTY_QB) as client:
        body = main_of(client.get("/media/downloads").text)
    assert "Nothing downloading" in body and "Nothing finished today" in body


def test_downloads_page_not_connected_shows_setup_note(env):
    with env(jellyfin={"summary": "x"}) as client:
        body = main_of(client.get("/media/downloads").text)
    assert "Not connected" in body and '<p class="metaline">n</p>' in body  # the tile's setup_note


def test_server_section_has_downloads_tab_after_library(env):
    with env(qbittorrent=QB) as client:
        html = client.get("/media/downloads").text
    tabs = re.search(r'<nav class="sectabs sub".*?</nav>', html, re.S).group(0)
    labels = [x.strip() for x in re.findall(r">([^<>]+)</a>", tabs) if x.strip()]
    assert labels[:4] == ["Live", "History", "Library", "Downloads"]  # F7 put History after Live
    assert 'aria-current="page">Downloads' in tabs


# merge_downloading -----------------------------------------------------------
ROW = {"title": "Midnight Harbour", "kind": "movie", "pct": 75, "status_text": "Downloading",
       "time_left": "14 min", "item_key": "tmdb:603", "download_id": H1}


def test_merge_overlays_live_progress_on_a_match():
    out = merge_downloading([ROW], {"active": [QB["active"][0]]})
    assert len(out) == 1
    assert out[0]["pct"] == 43 and out[0]["caption"] == "Downloading · 43% · 12 min"
    assert out[0]["title"] == "Midnight Harbour" and out[0]["item_key"] == "tmdb:603"


def test_merge_falls_back_to_arr_without_a_match():
    out = merge_downloading([{**ROW, "download_id": None}], {"active": [QB["active"][1]]})
    assert out[0]["pct"] == 75 and out[0]["caption"] == "Downloading · 14 min"
    assert out[1]["title"] == "Some Show S01"  # the unclaimed torrent follows


def test_merge_appends_unmatched_torrents_as_plain_rows():
    out = merge_downloading([ROW], QB)
    assert [r["title"] for r in out] == ["Midnight Harbour", "Some Show S01", "Linux ISO"]
    extra = out[2]
    assert extra["kind"] == "other" and extra["poster"] is None and extra["item_key"] is None
    assert extra["caption"] == "Queued · 99%"


def test_merge_with_qb_absent_leaves_arr_rows_unchanged():
    for qb in (None, {}, {"active": []}):
        out = merge_downloading([ROW], qb)
        assert len(out) == 1 and out[0]["pct"] == 75 and out[0]["status_text"] == "Downloading"
    assert merge_downloading(None, None) == []


def test_title_page_percentage_matches_the_item_key_not_a_title_prefix():
    """M-50 (W2): "It" must not pick up an "It Follows" download; a key (tmdb: / tvdb:) is the only match."""
    rows = [{"title": "It Follows", "item_key": "tmdb:270303", "pct": 40},
            {"title": "Aliens", "item_key": "tmdb:679", "pct": 12},
            {"title": "Some Show · S01E02", "item_key": "tvdb:100", "pct": 10},
            {"title": "Alien", "item_key": "tmdb:348", "pct": None}]
    assert pct_for_keys(rows, ["tmdb:679"]) == 12 and pct_for_keys(rows, ["tvdb:100"]) == 10
    assert pct_for_keys(rows, ["tmdb:346364"]) is None              # "It": no prefix match on "It Follows"
    assert pct_for_keys(rows, ["tmdb:348"]) is None                 # a queued row without a percentage
    assert pct_for_keys(rows, []) is None and pct_for_keys(None, ["tmdb:679"]) is None
    merged = merge_downloading([], {"active": [QB["active"][0]]})   # qBittorrent-only rows carry no key
    assert pct_for_keys(merged, ["tmdb:603"]) is None


EPISODES = ["3AM", "Two Dead Men", "Kandahar", "Resupply", "Gunner", "The Judas Goat", "Crosshairs",
            "Cold Steel", "Front Toward Enemy", "Virtue of the Vicious", "Danger Close", "Home", "Memento Mori"]
PACK = [{"title": f"Marvel's The Punisher · S01E{i:02d} · {name}", "kind": "episode", "pct": 20,
         "status_text": "Downloading", "time_left": "1 h", "poster": "/p.jpg", "item_key": "tvdb:331980",
         "download_id": H2.upper()} for i, name in enumerate(EPISODES, 1)]


def test_merge_collapses_a_season_pack_into_one_row():
    out = merge_downloading(PACK, {"active": [QB["active"][1]]})
    assert len(out) == 1
    assert out[0]["title"] == "Marvel's The Punisher · S01 · 13 episodes" and out[0]["kind"] == "season"
    assert out[0]["item_key"] == "tvdb:331980" and out[0]["poster"] == "/p.jpg"
    assert out[0]["pct"] == 10 and out[0]["caption"] == "Stalled · 10%"


def test_merge_keeps_different_hashes_and_null_ids_apart_in_order():
    other = [{**r, "download_id": "e" * 40} for r in PACK[3:5]]
    loose = [{**r, "download_id": None} for r in PACK[5:7]]
    out = merge_downloading([loose[0], *PACK[:3], ROW, *other, loose[1]], None)
    assert [r["title"] for r in out] == [loose[0]["title"], "Marvel's The Punisher · S01 · 3 episodes",
                                         "Midnight Harbour", "Marvel's The Punisher · S01 · 2 episodes",
                                         loose[1]["title"]]
    assert out[0]["kind"] == "episode" and out[2]["kind"] == "movie"


def test_merge_pack_title_falls_back_when_unparseable():
    rows = [{"title": "Odd Release", "kind": "episode", "download_id": H1}] * 2
    assert merge_downloading(rows, None)[0]["title"] == "Odd Release · 2 episodes"


def test_collapsed_pack_gives_one_badge_per_item_key():
    from hub.media_downloads import badges_by_item_key
    assert badges_by_item_key(merge_downloading(PACK, None)) == {"tvdb:331980": "Downloading · 20%"}


# shelf, library, badges, hero ---------------------------------------------------
def test_shelf_and_library_use_the_merged_rows(env):
    with env(arr=ARR, qbittorrent=QB, jellyfin={"summary": "x"}) as client:
        shelf = main_of(client.get("/a/alpha").text)
        lib = main_of(client.get("/media/library").text)
    assert "Downloading · 43% · 12 min" in shelf and "Linux ISO" in shelf
    assert '>Midnight Harbour</div><div class="row-meta">Downloading · 43% · 12 min left' in lib
    assert '>Linux ISO</div><div class="row-meta">Queued · 99%' in lib
    assert "width: 43%" in lib


def test_shelf_still_works_without_the_qb_snapshot(env):
    with env(arr=ARR, jellyfin={"summary": "x"}) as client:
        shelf = main_of(client.get("/a/alpha").text)
        lib = main_of(client.get("/media/library").text)
    assert "Downloading · 14 min" in shelf and '>Midnight Harbour</div><div class="row-meta">Downloading · 75% · 14 min left' in lib


def test_this_week_row_carries_a_download_badge(env, tmp_path):
    with env(arr=ARR, qbittorrent=QB) as client:
        lib = main_of(client.get("/media/library").text)
    week = lib.split(">This week</h2>", 1)[1].split(">Downloading</h2>", 1)[0]
    assert "Downloading · 43%</div>" in week
    (tmp_path / "snaps" / "qbittorrent.json").unlink()
    with env(arr=ARR) as client:
        lib = main_of(client.get("/media/library").text)
    week = lib.split(">This week</h2>", 1)[1].split(">Downloading</h2>", 1)[0]
    assert "Downloading · 75%" in week  # arr's own pct when qb is absent


@pytest.fixture()
def disc(env, monkeypatch):
    def go(title=None, **data):
        client = env(jellyseerr={"summary": "x", "requests": []}, jellyfin={"summary": "x"}, **data)
        from hub import media_discover
        media_discover.clear_cache()
        monkeypatch.setenv("JELLYSEERR_URL", FAKE_URL)
        monkeypatch.setenv("JELLYSEERR_API_KEY", FAKE_KEY)
        fake = Fake()
        if title:
            fake.table["/api/v1/movie/603"] = {**MOVIE, "title": title}
        monkeypatch.setattr(media_discover.requests, "get", fake.get)
        return client
    return go


def test_title_page_shows_download_badge_only_when_matching(disc):
    """M-50 (W2): the queue row's key (tmdb:603) decides, never its title."""
    other = {**ARR, "downloading": [{**r, "item_key": "tmdb:999"} for r in ARR["downloading"]]}
    with disc(title="Midnight Harbour", arr=other, qbittorrent=QB) as client:   # same title, another film's key
        assert "Downloading · " not in main_of(client.get("/media/title/movie/603").text)
    with disc(arr=ARR, qbittorrent=QB) as client:   # keyed tmdb:603, whatever the page's title says
        assert "Not on server · Downloading · 43%" in main_of(client.get("/media/title/movie/603").text)  # F10: in the status line


def test_title_page_skips_the_badge_silently_without_snapshots(disc):
    with disc(title="Midnight Harbour") as client:
        resp = client.get("/media/title/movie/603")
    assert resp.status_code == 200 and "Downloading ·" not in resp.text


def test_hub_hero_subline_present_only_when_downloading(env):
    jelly = {"summary": "1 playing now", "now_playing": [{"title": "T", "user": "U", "progress_pct": 1,
                                                         "play_method": "Direct", "poster": None}]}
    with env(jellyfin=jelly, qbittorrent=QB) as client:
        assert "2 downloading · 1.4 MB/s" in main_of(client.get("/").text)
    with env(jellyfin=jelly, qbittorrent=EMPTY_QB) as client:
        assert "Nothing downloading" not in main_of(client.get("/").text)
    with env(jellyfin=jelly) as client:
        assert "downloading" not in main_of(client.get("/").text)
