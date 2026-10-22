"""P1a Free space (2026-10-22): GET /server/space lists the biggest watched films and finished shows on disk — LIST ONLY
(B., 2026-10-22: no delete, no button that changes anything). hub/server_space.py over the arr snapshot's
`library_sizes` and the jellyfin snapshot's library rows, joined by provider ids, never by title."""
import importlib
import json
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from hub import guest, server, server_space
from hub.store import Snapshot
from tests.hub.test_server import SAMPLES, env, main_of, txt  # noqa: F401  (env is a fixture)
from tests.hub.test_server_history import NOW, _samples

REPO_ROOT = Path(__file__).resolve().parents[2]
GIB = 1024 ** 3
THIS_YEAR = date.today().year


def snap(cid, data):
    return Snapshot(cid, "ok", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", 0, None, data, 1.0)


def film(n, title, tmdb, played=True, at=None):
    return {"title": title, "year": 2000 + n, "jf_id": f"film-{n}", "item_key": f"tmdb:{tmdb}" if tmdb else f"jf:film-{n}",
            "played": played, "last_played_at": at or f"{THIS_YEAR}-03-03T10:00:00.0000000Z"}


def show(n, title, key, unplayed=0, episodes=8):
    return {"title": title, "year": 2010 + n, "jf_id": f"show-{n}", "item_key": key, "played": unplayed == 0,
            "episodes": episodes, "unplayed": unplayed}


def radarr(tmdb, gib, title="Radarr title"):
    return {"tmdb_id": tmdb, "title": title, "year": None, "size_bytes": int(gib * GIB)}


def sonarr(gib, tvdb=None, tmdb=None, ended=True, title="Sonarr title"):
    return {"tvdb_id": tvdb, "tmdb_id": tmdb, "title": title, "size_bytes": int(gib * GIB), "ended": ended}


JELLY = {
    "movies": [film(1, "Big Watched", 101), film(2, "Never Watched", 102, played=False), film(3, "No Ids", None),
               film(4, "Same Title Other Id", 999), film(5, "Small Watched", 105)],
    "shows": [show(1, "Done Via Tmdb", "tmdb:501"), show(2, "Done Via Tvdb", "tvdb:602", episodes=1),
              show(3, "Still Airing", "tmdb:503"), show(4, "Half Watched", "tmdb:504", unplayed=2),
              show(5, "No Episodes", "tmdb:505", episodes=0)],
}
SIZES = {
    "radarr": [radarr(101, 40), radarr(102, 50), radarr(105, 2.5),
               radarr(104, 60, title="Same Title Other Id")],     # same title, different id: never joined
    "sonarr": [sonarr(30, tvdb=7001, tmdb=501), sonarr(12.4, tvdb=602), sonarr(80, tvdb=7003, tmdb=503, ended=False),
               sonarr(70, tmdb=504), sonarr(5, tmdb=505)],
}


def snaps(jelly=JELLY, sizes=SIZES, system=None):
    out = {"jellyfin": snap("jellyfin", jelly), "arr": snap("arr", {"library_sizes": sizes})}
    if system is not None:
        out["system"] = snap("system", system)
    return out


# ---- the list: rules, joins, order, sizes ----

def test_watched_films_and_finished_shows_in_one_list_by_size():
    sp = server_space.build(snaps())
    assert [r["title"] for r in sp["rows"]] == ["Big Watched", "Done Via Tmdb", "Done Via Tvdb", "Small Watched"]
    assert [r["size_text"] for r in sp["rows"]] == ["40.0 GB", "30.0 GB", "12.4 GB", "2.5 GB"]
    assert sp["rows"][0]["state_text"] == "Watched 3 Mar"
    assert sp["rows"][1]["state_text"] == "Finished · 8 episodes"
    assert sp["rows"][2]["state_text"] == "Finished · 1 episode"
    assert sp["rows"][0]["year"] == 2001 and sp["rows"][1]["year"] == 2011


def test_join_is_by_provider_ids_never_by_title():
    """Unwatched, id-less and same-title-other-id films stay out; a show joins by TMDB (Jellyfin's key) or TheTVDB."""
    titles = {r["title"] for r in server_space.build(snaps())["rows"]}
    assert not titles & {"Never Watched", "No Ids", "Same Title Other Id"}
    by_title = {**SIZES, "radarr": [radarr(None, 60, title="Big Watched")]}   # the title matches, no id: no row
    assert "Big Watched" not in {r["title"] for r in server_space.build(snaps(sizes=by_title))["rows"]}


def test_finished_needs_every_episode_watched_and_sonarr_ended():
    titles = {r["title"] for r in server_space.build(snaps())["rows"]}
    assert not titles & {"Still Airing", "Half Watched", "No Episodes"}


def test_ten_biggest_of_each():
    jelly = {"movies": [film(i, f"Film {i:02d}", 100 + i) for i in range(1, 15)],
             "shows": [show(i, f"Show {i:02d}", f"tvdb:{200 + i}") for i in range(1, 15)]}
    sizes = {"radarr": [radarr(100 + i, i) for i in range(1, 15)],
             "sonarr": [sonarr(i + 0.5, tvdb=200 + i) for i in range(1, 15)]}
    rows = server_space.build(snaps(jelly, sizes))["rows"]
    assert len(rows) == 20
    assert {r["title"] for r in rows if r["kind"] == "movie"} == {f"Film {i:02d}" for i in range(5, 15)}
    assert [r["size"] for r in rows] == sorted((r["size"] for r in rows), reverse=True)


def test_rows_link_to_the_joey_item_page():
    rows = {r["title"]: r for r in server_space.build(snaps())["rows"]}
    assert rows["Big Watched"]["href"] == "/media/item/film-1"
    assert rows["Done Via Tvdb"]["href"] == "/media/item/show-2"


# ---- the head line ----

def test_head_line_without_a_forecast():
    sp = server_space.build(snaps(), samples=[], now=NOW)
    assert sp["head"] == "Removing all 4 frees ~85 GB"


def test_head_line_with_the_forecast_adds_the_days_it_buys_back():
    samples = _samples(lambda i: [60, 62, 64, 67.5, 69, 70][i], [168, 120, 72, 23, 12, 0])
    system = {"volumes": [{"path": "/volume1", "total_gb": 1000.0, "free_gb": 300.0, "pct_used": 70}]}
    assert server.history_band(samples, NOW)["forecast"] is not None
    sp = server_space.build(snaps(system=system), samples=samples, now=NOW)
    week = [(s["at"], s["volumes"][0]["pct_used"]) for s in samples]
    rate = (server.DISK_TARGET_PCT - 70) / server.disk_days(week)
    freed = sum(r["size"] for r in sp["rows"]) / GIB
    expected = server._days_text(freed / 1000.0 * 100 / rate)
    assert sp["head"] == f"Removing all 4 frees ~85 GB (≈ {expected} at this rate)"


def test_a_slow_disk_has_no_forecast_and_no_days():
    samples = _samples(lambda i: [8.0, 8.1, 8.2, 8.3, 8.35, 8.4][i], [168, 120, 72, 23, 12, 0])
    system = {"volumes": [{"path": "/volume1", "total_gb": 1000.0}]}
    assert server_space.build(snaps(system=system), samples=samples, now=NOW)["head"] == "Removing all 4 frees ~85 GB"


def test_one_row_and_small_totals_read_naturally():
    sp = server_space.build(snaps(sizes={"radarr": [radarr(105, 2.5)], "sonarr": []}))
    assert sp["head"] == "Removing it frees ~2.5 GB"


# ---- empty and not connected ----

def test_empty_state():
    sp = server_space.build(snaps(sizes={"radarr": [radarr(102, 50)], "sonarr": None}))
    assert (sp["rows"], sp["head"], sp["empty"]) == ([], None, "Nothing watched is taking space yet")


def test_no_sizes_or_no_jellyfin_is_not_connected():
    assert server_space.build({"jellyfin": snap("jellyfin", JELLY), "arr": snap("arr", {})})["empty"] == "Not connected"
    assert server_space.build({"arr": snap("arr", {"library_sizes": SIZES})})["empty"] == "Not connected"


# ---- the page and the two links ----

def test_page_lists_rows_with_links_and_no_form_or_button(env):
    arr = json.loads((SAMPLES / "arr.json").read_text(encoding="utf-8"))["data"]
    arr["library_sizes"] = SIZES
    with env(arr=arr, jellyfin=JELLY) as client:
        r = client.get("/server/space")
    assert r.status_code == 200
    assert r.text.split("<title>", 1)[1].split("</title>", 1)[0] == "Free space · Joey"
    body = main_of(r.text)
    text = txt(body)
    assert "Removing all 4 frees ~85 GB" in text
    assert "Big Watched2001 · 40.0 GB · Watched 3 Mar" in text          # title, then its meta line
    assert "Done Via Tmdb2011 · 30.0 GB · Finished · 8 episodes" in text
    assert text.index("Big Watched") < text.index("Done Via Tmdb") < text.index("Small Watched")
    assert 'href="/media/item/film-1"' in body and 'href="/media/item/show-1"' in body
    assert "<form" not in body and "<button" not in body and "Delete" not in text   # list only


def test_page_empty_state_from_the_samples(env):
    """The committed samples carry library_sizes, but no sample Jellyfin title has a matching TMDB id."""
    with env() as client:
        body = main_of(client.get("/server/space").text)
    assert "Nothing watched is taking space yet" in txt(body)


def test_the_forecast_attention_item_opens_free_space():
    item = {"key": "forecast:/volume1", "text": "/volume1 reaches 85% in 12 days at this rate"}
    assert server.attention_action(item, {}) == {"text": item["text"], "href": "/server/space", "action": "Free space",
                                                 "new_tab": False}
    disk = server.attention_action({"key": "disk:/volume1", "text": "x"}, {})
    assert disk["href"] is None and disk["action"] is None           # the disk item itself is unchanged


def test_the_system_disk_block_links_free_space(env):
    with env() as client:
        body = main_of(client.get("/server").text)
    system = body.split('id="system"', 1)[1].split('id="services"', 1)[0]
    assert system.count('href="/server/space"') == 1 and ">Free space</a>" in system


# ---- owner only ----

def test_space_is_private_and_the_media_front_refuses_it(monkeypatch):
    assert ("GET", "/server/space") in guest.PRIVATE and ("GET", "/server/space") not in guest.GUEST
    assert guest.allows("GET", "/server/space") is False
    monkeypatch.setenv("AREAS_PATH", str(REPO_ROOT / "config" / "areas.yaml"))
    monkeypatch.setenv("OWNER_EMAIL_YOU", "you@example.com")
    monkeypatch.setenv("JOEY_FRONT", "media")
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as client:
        unknown = client.get("/no-such-page-xyz", follow_redirects=False)
        r = client.get("/server/space", follow_redirects=False)
    assert (r.status_code, r.content) == (404, unknown.content)


def test_space_has_no_write_route():
    import hub.main
    from tests.hub.test_guest_routes import route_pairs
    assert {(m, p) for m, p in route_pairs(hub.main.app.routes) if p.startswith("/server/space")} == {
        ("GET", "/server/space")}
