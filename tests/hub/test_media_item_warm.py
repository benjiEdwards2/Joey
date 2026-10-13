"""E1 (2026-10-13): Jellyfin item data stays warm. The item cache serves an entry up to 6 h old and re-reads it in
the background once it is over 10 min old (stale-while-revalidate); Joey's own watch-state writes still drop it; and
after each new jellyfin snapshot the warm-up reads the Media home's Playing now / Continue watching / Recently added
items that are not fresh (at most 20, paced). Jellyfin and Seerr are the helpers fakes; no network."""
import time

from hub import media_item, media_resume, media_warmup, tasks
from tests.hub.helpers import URL, env  # noqa: F401  (env fixture)
from tests.hub.test_store import write_envelope


def jf_paths(both):
    return [c[len(URL):] for c in both.calls if c.startswith(URL)]


def age(jf_id, seconds):
    at, data = media_item._cache[jf_id]
    media_item._cache[jf_id] = (time.time() - seconds, data)


def test_ttls():
    assert media_item.CACHE_TTL == 6 * 3600 and media_item.FRESH_S == 600


def test_a_fresh_item_is_not_read_again(env):
    client, both = env()
    with client:
        client.get("/media/item/mov1")
        n = len(jf_paths(both))
        client.get("/media/item/mov1")
    media_item.drain_refresh()
    assert len(jf_paths(both)) == n


def test_a_stale_item_is_served_at_once_and_refreshed_behind(env):
    client, both = env()
    with client:
        client.get("/media/item/mov1")
        age("mov1", media_item.FRESH_S + 60)
        stale_at = media_item._cache["mov1"][0]
        both.jf.fail = both.fail_jf = True        # the page must not need Jellyfin for a stale entry
        r = client.get("/media/item/mov1")
        assert r.status_code == 200 and "Harbour Lights" in r.text and "Couldn't reach Jellyfin" not in r.text
        media_item.drain_refresh()
        assert media_item._cache["mov1"][0] == stale_at                   # a failed refresh keeps the entry
        both.fail_jf = False
        client.get("/media/item/mov1")
        media_item.drain_refresh()
    assert media_item._cache["mov1"][0] > stale_at                        # the background read replaced it
    assert jf_paths(both).count("/Users/u1/Items/mov1") >= 2


def test_an_entry_past_six_hours_is_read_before_the_page(env):
    client, both = env()
    with client:
        client.get("/media/item/mov1")
        age("mov1", media_item.CACHE_TTL + 1)
        n = jf_paths(both).count("/Users/u1/Items/mov1")
        client.get("/media/item/mov1")
    assert jf_paths(both).count("/Users/u1/Items/mov1") == n + 1
    assert time.time() - media_item._cache["mov1"][0] < 60


def test_one_refresh_per_item_however_many_views(env, monkeypatch):
    client, both = env()
    with client:
        client.get("/media/item/mov1")
    age("mov1", media_item.FRESH_S + 1)
    queued = []
    monkeypatch.setattr(media_item._refresh_pool, "submit", lambda fn: queued.append(fn))
    for _ in range(5):
        assert media_item._data("mov1") is not None
    assert len(queued) == 1 and media_item._refreshing == {"mov1"}
    queued[0]()
    assert media_item._refreshing == set() and time.time() - media_item._cache["mov1"][0] < 60


def test_a_watched_mark_still_drops_the_cache_and_a_read_across_it_is_not_kept(env):
    client, both = env()
    with client:
        client.get("/media/item/mov1")
    assert "mov1" in media_item._cache
    gen = media_item._gen[0]
    media_item.invalidate()
    assert media_item._cache == {} and media_item._gen[0] == gen + 1
    real = media_item._build

    def build_then_mark(jf_id):   # Joey writes watch state while this read is in flight
        out = real(jf_id)
        media_item.invalidate()
        return out
    media_item._build = build_then_mark
    try:
        assert media_item._read("mov1") is not None
    finally:
        media_item._build = real
    assert "mov1" not in media_item._cache                                 # the pre-write answer was not cached


def test_the_resume_write_path_reads_the_show_fresh(env, monkeypatch):
    client, both = env()
    with client:
        client.get("/media/item/ser1")
    age("ser1", media_item.FRESH_S + 1)
    n = jf_paths(both).count("/Users/u1/Items/ser1")
    eps = media_resume.season_episodes("ser1", "sea1")
    assert eps and jf_paths(both).count("/Users/u1/Items/ser1") == n + 1  # read now, not served stale


# ---- the item warm-up ----

JELLY = {"now_playing": [{"jf_id": "np1"}],
         "up_next": [{"jf_id": "ep3"}, {"jf_id": "np1"}, {"jf_id": "bad id"}],
         "latest": [{"jf_id": "old", "added_at": "2026-10-01T00:00:00Z"}, {"jf_id": "mov1", "added_at": "2026-10-12T00:00:00Z"}],
         "her": {"up_next": [{"jf_id": "ser1"}, {"jf_id": "ep3"}], "latest": []}}


def test_item_targets_are_the_home_rows_in_shelf_order_both_profiles():
    assert media_warmup.item_targets(JELLY) == ["np1", "ep3", "mov1", "old", "ser1"]
    assert media_warmup.ITEM_MAX == 20 and media_warmup.TICK_S == 60


def test_item_pass_reads_what_is_not_fresh_and_skips_the_rest(env, monkeypatch):
    client, both = env(jelly_extra={"up_next": [{"jf_id": "ep3"}], "latest": [{"jf_id": "mov1"}, {"jf_id": "ser1"}]})
    with client:
        client.get("/media/item/mov1")                                      # fresh already
    sleeps = []
    monkeypatch.setattr(media_warmup.time, "sleep", sleeps.append)
    first = media_warmup.warm_items()
    # ep3 is read (and with it its show, ser1); mov1 was fresh, ser1 is fresh by the time its turn comes
    assert first == {"items": 3, "fetched": 1, "failed": 0, "cached": 2}
    assert sleeps == [media_warmup.ITEM_PAUSE_S]                            # paced after a read, not after a hit
    n = len(jf_paths(both))
    assert media_warmup.warm_items()["cached"] == 3 and len(jf_paths(both)) == n   # all fresh: no read at all
    age("ep3", media_item.FRESH_S + 1)
    assert media_warmup.warm_items(pause=0)["fetched"] == 1


def test_item_pass_is_bounded(env):
    up = [{"jf_id": f"x{i}"} for i in range(30)]
    client, both = env(jelly_extra={"up_next": up})
    out = media_warmup.warm_items(pause=0)
    assert out["fetched"] + out["failed"] == media_warmup.ITEM_MAX
    assert out["items"] == media_warmup.ITEM_MAX


def test_item_pass_without_jellyfin_keys_reads_nothing(env, monkeypatch):
    client, both = env(jelly_extra={"up_next": [{"jf_id": "ep3"}]})
    monkeypatch.delenv("JELLYFIN_API_KEY")
    both.calls.clear()
    assert media_warmup.warm_items(pause=0)["skipped_no_keys"] and both.calls == []


def test_tick_runs_the_pass_every_three_hours_and_items_on_each_new_snapshot(env, monkeypatch, tmp_path):
    env(jelly_extra={"up_next": [{"jf_id": "ep3"}]})
    monkeypatch.setattr(media_warmup, "_tick", {"pass_at": None, "snapshot": None})
    passes, items = [], []
    monkeypatch.setattr(media_warmup, "run_pass", lambda snaps=None, pause=0: passes.append(1) or {})
    monkeypatch.setattr(media_warmup, "warm_items", lambda snaps=None, **k: items.append(1) or {})
    media_warmup.tick(now=1000.0)
    assert passes == [1] and items == [1]                                   # first tick: both
    media_warmup.tick(now=1060.0)
    assert passes == [1] and items == [1]                                   # same snapshot, within 3 h: nothing
    time.sleep(0.01)
    write_envelope(tmp_path / "snaps", "jellyfin", age_minutes=0, data={"summary": "x", "up_next": []})
    media_warmup.tick(now=1120.0)
    assert passes == [1] and items == [1, 1]                                # a new sweep: the item pass only
    media_warmup.tick(now=1000.0 + media_warmup.EVERY_S)
    assert passes == [1, 1] and items == [1, 1]                             # 3 h on: the full pass again


def test_the_background_loop_ticks_every_minute(monkeypatch):
    seen = {}

    async def fake_every(label, first_s, every_s, fn):
        seen.update(label=label, first=first_s, every=every_s, fn=fn)
    monkeypatch.setattr(tasks, "_every", fake_every)
    called = []
    monkeypatch.setattr(media_warmup, "tick", lambda: called.append(1))
    import asyncio
    asyncio.run(tasks._media_warmup_loop())
    seen["fn"]()
    assert seen["first"] == media_warmup.FIRST_DELAY_S and seen["every"] == media_warmup.TICK_S and called == [1]
