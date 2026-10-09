"""media-speed (2026-10-07): the film page's cold open. Live reads overlap (total ~ the longest chain, not the
sum), nothing is read twice, a 404 is remembered, metadata rides a long restart-proof cache while request /
availability state keeps the short one, and the warm-up is bounded, idempotent and skipped without keys.
Upstreams are the test_media_film fakes, slowed down where timing matters; no network."""
import threading
import time

import pytest
import requests

from hub import images, media_discover as md, media_film, media_item, media_warmup
from tests.hub.helpers import env, SEERR_URL as SEERR, URL  # noqa: F401  (re-export: defined in tests/hub/helpers.py)

LAT = 0.25


def slow(both, latency=LAT):
    """Wrap the fake so every GET sleeps `latency` and logs (start, end, url)."""
    log, lock, real = [], threading.Lock(), both.get

    def get(url, params=None, headers=None, timeout=None, **kw):
        start = time.perf_counter()
        time.sleep(latency)
        resp = real(url, params=params, headers=headers, timeout=timeout)
        with lock:
            log.append((start, time.perf_counter(), url))
        return resp

    return get, log


def paths(both, prefix):
    return [c[len(prefix):] for c in both.calls if c.startswith(prefix)]


# ---- concurrency ----

def test_cold_movie_open_overlaps_jellyfin_and_jellyseerr(env, monkeypatch):
    client, both = env()
    get, log = slow(both)
    monkeypatch.setattr(requests, "get", get)
    with client:
        t0 = time.perf_counter()
        assert client.get("/media/item/mov1").status_code == 200
        took = time.perf_counter() - t0
    assert len(log) >= 7
    # the longest chain is 2 deep (Jellyfin user -> item; Jellyseerr title -> collection): ~0.5 s, not 7 x 0.25
    assert took < len(log) * LAT * 0.6, (took, len(log))
    item_call = next(c for c in log if c[2].endswith("/Users/u1/Items/mov1"))
    title_call = next(c for c in log if c[2].endswith("/api/v1/movie/603"))
    assert title_call[0] < item_call[1]   # the Jellyseerr read started before the Jellyfin item had answered


def test_seasons_episode_reads_run_side_by_side(monkeypatch):
    seasons = [{"Id": f"s{i}", "Name": f"Season {i}", "IndexNumber": i} for i in range(1, 6)]

    def fake_get(base, headers, path, params=None):
        time.sleep(LAT)
        if path.endswith("/Seasons"):
            return {"Items": seasons}
        return {"Items": [{"Id": f"e-{params['seasonId']}", "Name": "E", "IndexNumber": 1, "UserData": {}}]}

    monkeypatch.setattr(media_item.media_files, "_get", fake_get)
    t0 = time.perf_counter()
    out = media_item._seasons("b", {}, "u1", "ser1", "2026-10-07")
    took = time.perf_counter() - t0
    assert [s["number"] for s in out] == [1, 2, 3, 4, 5]                  # order kept
    assert [s["episodes"][0]["jf_id"] for s in out] == [f"e-s{i}" for i in range(1, 6)]
    assert took < 4 * LAT                                                  # 1 + 5 sequential would be 6 x LAT


# ---- nothing read twice ----

def test_movie_item_is_read_once(env):
    client, both = env()
    with client:
        b = client.get("/media/item/mov1").text
    assert paths(both, URL).count("/Users/u1/Items/mov1") == 1           # the file strip rides on the same read
    assert "4K" in b and "Dolby Digital Plus" in b


def test_episode_reads_its_show_once(env):
    client, both = env()
    with client:
        assert client.get("/media/item/ep3").status_code == 200
    jf = paths(both, URL)
    assert jf.count("/Users/u1/Items/ser1") == 1 and jf.count("/Shows/ser1/Seasons") == 1
    # the season's episode list + the file panel's ONE episodes read by the known series id (M-45; it used to list
    # every series, then every episode of the match, through /Users/{uid}/Items)
    assert jf.count("/Shows/ser1/Episodes") == 2 and "/Users/u1/Items" not in jf


def test_one_snapshot_read_per_film_request(env, monkeypatch):
    client, _ = env()
    import hub.main
    calls = []
    real = hub.main.shell.get_snapshots
    monkeypatch.setattr(hub.main.shell, "get_snapshots", lambda *a, **k: calls.append(1) or real(*a, **k))
    with client:
        client.get("/media/item/mov1")
        n_item = len(calls)
        client.get("/media/title/movie/603")
    assert n_item == 1 and len(calls) == 2


# ---- the 404 ----

def test_tv_title_never_asks_for_ratingscombined(env):
    client, both = env()
    with client:
        client.get("/media/item/ser1")
        client.get("/media/title/tv/100")
    seerr = paths(both, SEERR)
    assert not [p for p in seerr if p.endswith("ratingscombined")]
    assert seerr.count("/api/v1/tv/100/ratings") == 1


def test_a_404_is_remembered_across_cache_clears_and_restarts(env):
    client, both = env()
    with client:
        client.get("/media/title/tv/100")
        md.clear_cache()            # memory gone (as after a deploy restart); the meta files stay on disk
        media_item.clear_cache()
        client.get("/media/title/tv/100")
    assert paths(both, SEERR).count("/api/v1/tv/100/ratings") == 1        # the 404 answer came from disk
    assert paths(both, SEERR).count("/api/v1/tv/100") == 2                # the title body (request state) did not


def test_short_cache_remembers_a_404_too(env):
    client, both = env()
    with client:
        client.get("/media/item/ser1")
        media_item.clear_cache()
        client.get("/media/item/ser1")
    assert paths(both, SEERR).count("/api/v1/tv/100/similar") == 1


def test_a_network_failure_is_not_remembered(env):
    client, both = env()
    both.fail_seerr = True
    with client:
        client.get("/media/title/movie/603")
        both.fail_seerr = False
        b = client.get("/media/title/movie/603").text
    assert '<span class="sp-name">IMDb</span>' in b                       # retried, not a cached miss (media-ux4 pill)


# ---- TTL split ----

def test_metadata_long_request_state_short(env, monkeypatch):
    client, both = env()
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    with client:
        client.get("/media/title/movie/603")
        clock[0] += 11 * 60                                               # past the 10 min request-state TTL
        client.get("/media/title/movie/603")
        s = paths(both, SEERR)
        assert s.count("/api/v1/movie/603") == 2                          # title body (status) re-read
        assert s.count("/api/v1/movie/603/similar") == 2                  # shelves carry availability: short
        assert s.count("/api/v1/movie/603/ratingscombined") == 1          # ratings: long
        clock[0] += md.META_TTL
        client.get("/media/title/movie/603")
    assert paths(both, SEERR).count("/api/v1/movie/603/ratingscombined") == 2


def test_person_bio_long_credits_short(env, monkeypatch):
    client, both = env()
    both.seerr.table["/api/v1/person/7"] = {"name": "Ada Actor", "biography": "Born by the sea."}
    both.seerr.table["/api/v1/person/7/combined_credits"] = {"cast": []}
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    with client:
        client.get("/media/person/7")
        clock[0] += 11 * 60
        assert "Born by the sea." in client.get("/media/person/7").text
    s = paths(both, SEERR)
    assert s.count("/api/v1/person/7") == 1 and s.count("/api/v1/person/7/combined_credits") == 2


def test_season_episodes_ride_the_meta_cache(env):
    client, both = env()
    both.seerr.table["/api/v1/tv/100/season/4"] = {"episodes": [{"episodeNumber": 1, "name": "One"}]}
    with client:
        client.get("/media/title/tv/100/season/4")
        md.clear_cache()
        assert "One" in client.get("/media/title/tv/100/season/4").text
    assert paths(both, SEERR).count("/api/v1/tv/100/season/4") == 1


# ---- tmdb hint ----

def test_tmdb_hint_from_the_snapshot():
    jelly = {"movies": [{"item_key": "tmdb:603", "jf_id": "mov1"}], "shows": [{"item_key": "tmdb:100", "jf_id": "ser1"}],
             "up_next": [{"jf_id": "ep3", "show_key": "jf:ser1"}],
             "her": {"history": {"recent": [{"jf_id": "ep9", "show_key": "jf:ser1"}]}}}
    assert media_film.tmdb_hint(jelly, "mov1") == ("movie", 603)
    assert media_film.tmdb_hint(jelly, "ser1") == ("tv", 100)
    assert media_film.tmdb_hint(jelly, "ep3") == ("tv", 100)
    assert media_film.tmdb_hint(jelly, "ep9") == ("tv", 100)
    assert media_film.tmdb_hint(jelly, "nope") is None


# ---- page markup ----

def test_cast_and_posters_decode_async(env):
    client, _ = env()
    with client:
        b = client.get("/media/title/movie/603").text
    assert '<img class="castpic" src="/img/tmdb:/ada.jpg?h=400" alt="" loading="lazy" decoding="async"' in b
    assert 'class="poster' in b and b.count('decoding="async"') >= 2


# ---- warm-up ----

class Img:
    status_code = 200
    headers = {"content-type": "image/jpeg"}
    content = b"\xff\xd8jpeg"


def warm_env(env, monkeypatch, tmp_path, n_up_next=3):
    up = [{"jf_id": f"ep{i}", "show_key": "jf:ser1", "title": "Quiet Show"} for i in range(n_up_next)]
    latest = [{"jf_id": "mov1", "item_key": "tmdb:603", "title": "Harbour Lights"}]
    client, both = env(jelly_extra={"up_next": up, "latest": latest})
    monkeypatch.setenv("IMG_CACHE_DIR", str(tmp_path / "img"))
    real = requests.get
    fetched = []

    def get(url, params=None, headers=None, timeout=None, **kw):
        if "/Images/" in url or url.startswith("https://image.tmdb.org/"):
            fetched.append(url)
            return Img()
        return real(url, params=params, headers=headers, timeout=timeout)

    monkeypatch.setattr(requests, "get", get)
    return client, both, fetched


def test_warmup_targets_are_distinct_and_bounded():
    jelly = {"shows": [{"item_key": "tmdb:100", "jf_id": "ser1"}],
             "movies": [{"item_key": f"tmdb:{i}", "jf_id": f"m{i}"} for i in range(100)],
             "up_next": [{"jf_id": "ep1", "show_key": "jf:ser1"}, {"jf_id": "ep2", "show_key": "jf:ser1"}],
             "latest": [{"jf_id": f"m{i}"} for i in range(100)]}
    got = media_warmup.targets(jelly, limit=60)
    assert len(got) == 60 and got[0] == {"kind": "tv", "tmdb": 100, "art": "ser1"}
    assert len({(t["kind"], t["tmdb"]) for t in got}) == 60


def test_warmup_fetches_once_then_is_cheap(env, monkeypatch, tmp_path):
    _, both, fetched = warm_env(env, monkeypatch, tmp_path)
    first = media_warmup.warm_once(pause=0)
    assert first["titles"] == 2                                     # the show (3 episodes up next) + the film
    # poster + backdrop per title, plus the film's one cast photo with a profile path
    assert first["fetched"] == 5 and len(fetched) == 5
    assert any(u.endswith("/w500/ada.jpg") for u in fetched)     # film-quality: the portrait-card size (h=400)
    n_seerr = len(paths(both, SEERR))
    md.clear_cache()
    second = media_warmup.warm_once(pause=0)
    assert second["fetched"] == 0 and second["cached"] == 5 and len(fetched) == 5   # idempotent: images stay put
    seerr = paths(both, SEERR)[n_seerr:]
    assert not [p for p in seerr if "ratings" in p]                 # ratings came from the meta cache
    # and the film page now finds the ratings warm
    assert md.meta_get("/api/v1/movie/603/ratingscombined") is not None


def test_warmup_is_bounded(env, monkeypatch, tmp_path):
    warm_env(env, monkeypatch, tmp_path)
    assert media_warmup.warm_once(pause=0, limit=1)["titles"] == 1


def test_warmup_skipped_without_keys(env, monkeypatch, tmp_path):
    _, both, fetched = warm_env(env, monkeypatch, tmp_path)
    for k in ("JELLYFIN_API_KEY", "JELLYSEERR_API_KEY"):
        monkeypatch.delenv(k)
    both.calls.clear()
    assert media_warmup.warm_once(pause=0) == {"titles": 0, "fetched": 0, "cached": 0, "skipped": 0,
                                               "skipped_no_keys": True}
    assert both.calls == [] and fetched == []


def test_warmup_off_switch(monkeypatch):
    monkeypatch.setenv("MEDIA_WARMUP", "off")
    assert media_warmup.disabled()
    monkeypatch.setenv("MEDIA_WARMUP", "on")
    assert not media_warmup.disabled()


def test_images_warm_matches_the_route_cache(env, monkeypatch, tmp_path):
    client, _, fetched = warm_env(env, monkeypatch, tmp_path)
    assert images.warm("tmdb:/ada.jpg", 120) == "fetched"
    assert images.warm("tmdb:/ada.jpg", 120) == "cached"
    assert images.warm("bad ref", 120) == "skipped" and images.warm("tmdb:/ada.jpg", 121) == "skipped"
    with client:
        r = client.get("/img/tmdb:/ada.jpg?h=120")
    assert r.status_code == 200 and r.content == Img.content and len(fetched) == 1   # the route found it warm


def test_meta_cache_defaults_inside_the_mounted_poster_cache(monkeypatch, tmp_path):
    monkeypatch.delenv("META_CACHE_DIR")
    monkeypatch.setenv("IMG_CACHE_DIR", str(tmp_path / "img"))
    assert md.meta_dir() == tmp_path / "img" / "meta"


# ---- W2 (M-41, M-24): one snapshot read per Media page, one rating inbox per frame ----

@pytest.mark.parametrize("path", ["/media/discover", "/media/person/31", "/media/movies/watchlist",
                                  "/media/server/history", "/media/diary", "/media/library", "/media/movies"])
def test_one_snapshot_read_per_media_page(env, monkeypatch, path):
    client, _ = env()
    import hub.main
    reads = []
    real = hub.main.shell._read_snapshots
    monkeypatch.setattr(hub.main.shell, "_read_snapshots", lambda *a, **k: reads.append(1) or real(*a, **k))
    with client:
        assert client.get(path).status_code == 200
    assert len(reads) == 1, path


def test_the_media_frame_builds_the_rating_inbox_once(env, monkeypatch):
    client, _ = env(jelly_extra={"history": {"recent": [
        {"item_key": "tmdb:603", "kind": "movie", "title": "Harbour Lights", "watched_at": "2099-01-01T00:00:00Z"}]}})
    import hub.main
    calls = []
    real = hub.main.media_home._to_rate
    monkeypatch.setattr(hub.main.media_home, "_to_rate", lambda *a, **k: calls.append(1) or real(*a, **k))
    with client:
        assert client.get("/media/movies").status_code == 200   # the page itself builds no inbox: only the frame
    assert len(calls) == 1
