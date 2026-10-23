"""JY-031 (2026-10-23): the disk forecast on the hub card and in Discord. One forecast per hub loop tick, cached in
memory (hub/server_history.py); the hub card, the /server render and the loop's Discord check read it, so all three
build one Attention key set. Hysteresis 30 / 45 days; "collecting" keeps an open episode open. Fake webhook
(requests.post), fake clock (fixed NOW passed in), media.db in the test's temp dir (tests/conftest.py)."""
import importlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from hub import media_db, server, server_alerts, server_history
from tests.hub.helpers import write_envelope
from tests.hub.test_server import ALL_UP, LAN_CLIENT, SAMPLES, SYSTEM, main_of, txt
from tests.hub.test_server_alerts import posts  # noqa: F401  (the fake webhook fixture)

NOW = datetime(2026, 10, 20, 2, 0, tzinfo=timezone.utc)
DISCORD = "Joey Server: Disk: reaches 85% in about 23 days (Volume 1, 412 GB free)"
# The hub-level tests freeze server_history's clock here (fix round 2026-10-23: no real datetime.now()). It lies after
# any envelope a test writes, so the tick's own system sample is never newer than the seeded line and is skipped.
LATER = datetime(2099, 1, 1, 3, 0, tzinfo=timezone.utc)


def linear(days_left, now=NOW, free=412.0, gap_h=0, path="/volume1", slope=1.0):
    """15 samples 12 h apart over 7 days, +`slope` %/day, ending at 85 - days_left * slope (so disk_days ==
    days_left); the newest is `gap_h` hours old (over 24 => collecting). A negative days_left ends over 85 %."""
    last = 85 - days_left * slope
    return [{"at": now - timedelta(hours=12 * k + gap_h), "cpu_pct": 5.0, "ram_pct_used": 70, "ram_free_gb": 2.0,
             "load_1m": 0.1, "volumes": [{"path": path, "pct_used": last - k / 2 * slope, "free_gb": free}]}
            for k in range(14, -1, -1)]


def flat(now=NOW, gap_h=0, pct=60.0):
    return [{**s, "volumes": [{"path": "/volume1", "pct_used": pct, "free_gb": 412.0}]}
            for s in linear(23, now, gap_h=gap_h)]


def _seed(samples):
    with sqlite3.connect(media_db.db_path()) as db:
        db.execute(server_history.DDL)
        db.executemany("INSERT INTO server_system_samples VALUES(?,?,?,?,?,?)", [
            (s["at"].strftime("%Y-%m-%dT%H:%M:%SZ"), s["cpu_pct"], s["ram_pct_used"], s["ram_free_gb"], s["load_1m"],
             json.dumps(s["volumes"])) for s in samples])


def disk_posts(posts):
    return [p["text"] for p in posts if p["text"].startswith("Joey Server: Disk: ")]


def tick(samples):
    """One hub loop tick at the fake clock: the forecast step, then the Discord check (no snapshots)."""
    server_history.refresh_forecast(samples, NOW)
    server_alerts.check_once(set(), {})


def seen_rows():
    with sqlite3.connect(media_db.db_path()) as db:
        return [r[0] for r in db.execute("SELECT key FROM server_attention_seen WHERE key LIKE 'forecast:%'")]


# ---- the words ----------------------------------------------------------------------------------------------------

def test_forecast_item_words_volume_name_and_rounding():
    item = server.forecast_item("/volume1", 23.0, 412.0)
    assert item == {"key": "forecast:/volume1", "text": "Disk: reaches 85% in about 23 days (Volume 1, 412 GB free)",
                    "words": "reaches 85% in about 23 days"}
    assert server.forecast_item("/volume2", 22.6, 2130.7)["text"] == (
        "Disk: reaches 85% in about 22 days (Volume 2, 2,131 GB free)")
    # N days (fix round 2026-10-23): whole days rounded DOWN, at least 1, so an item opened under 30 never reads 30
    words = {d: server.forecast_item("/volume1", d)["words"] for d in (29.6, 22.5, 1.2, 0.3, 1000.9)}
    assert words == {29.6: "reaches 85% in about 29 days", 22.5: "reaches 85% in about 22 days",
                     1.2: "reaches 85% in about 1 day", 0.3: "reaches 85% in about 1 day",
                     1000.9: "reaches 85% in about 1,000 days"}
    # no number: kept open at or over the target, or restored with no projection yet
    assert server.forecast_item("/volume1", None, 3, full=True)["text"] == "Disk: at or over 85% (Volume 1, 3 GB free)"
    assert server.forecast_item("/volume1", None)["words"] == "filling fast"
    # a path that is not /volumeN stays the path; no free number => no free words
    assert server.forecast_item("/data/snapshots", 9, None)["text"] == (
        "Disk: reaches 85% in about 9 days (/data/snapshots)")
    # fix round (2026-10-23): any path under /volumeN is that volume, so the sample data reads "(Volume 1, ...)"
    assert [server.volume_name(p) for p in ("/volume12", "/volume1/Docker", "/volume1x", "/data/volume1")] == [
        "Volume 12", "Volume 1", "/volume1x", "/data/volume1"]


def test_discord_message_is_exact_against_a_fake_webhook(posts):
    _seed(linear(23))
    server_history.refresh_forecast(now=NOW)            # reads the temp media.db through recent(NOW)
    assert server_alerts.check_once(set(), {}) >= 1
    assert disk_posts(posts) == [DISCORD]
    assert posts[-1]["url"] == "https://discord.invalid/api/webhooks/1/SECRET"


# ---- hysteresis: one post per episode ------------------------------------------------------------------------------

def test_step_starts_under_30_and_ends_only_over_45_or_flat():
    st = server.forecast_step(None, linear(30), NOW)
    assert not st["open"] and st["item"] is None and st["days"] == 30          # 30 is not under 30
    st = server.forecast_step(st, linear(29), NOW)
    assert st["open"] and st["item"]["key"] == "forecast:/volume1"
    for days in (35, 45, 31):
        st = server.forecast_step(st, linear(days), NOW)
        assert st["open"], days                                                # 30-45 keeps it open
    assert not server.forecast_step(st, linear(46), NOW)["open"]               # over 45 ends it
    assert not server.forecast_step(st, flat(), NOW)["open"]                   # flat ends it
    assert not server.forecast_step(None, linear(35), NOW)["open"]             # 30-45 never opens one


def test_one_post_per_episode_across_a_30_35_28_wobble(posts):
    for days in (30, 28, 35, 30, 28, 44, 35, 28):
        tick(linear(days))
    assert disk_posts(posts) == ["Joey Server: Disk: reaches 85% in about 28 days (Volume 1, 412 GB free)"]
    tick(linear(46))                                    # over 45: the episode ends, its seen-row goes; no resolved post
    assert seen_rows() == [] and len(disk_posts(posts)) == 1
    tick(linear(35))                                    # 35 after the end opens nothing
    assert len(disk_posts(posts)) == 1
    tick(linear(25))                                    # a new episode: one more post
    assert disk_posts(posts)[1:] == ["Joey Server: Disk: reaches 85% in about 25 days (Volume 1, 412 GB free)"]
    tick(flat())
    assert seen_rows() == [] and len(disk_posts(posts)) == 2


# ---- collecting and restarts keep an open episode -----------------------------------------------------------------

def test_collecting_keeps_an_open_episode_and_a_return_does_not_post_again(posts):
    tick(linear(20))
    assert len(disk_posts(posts)) == 1
    tick(linear(20, gap_h=40))                          # NAS off for 40 h: fewer than 2 samples in 24 h
    st = server_history._forecast
    assert st["collecting"] and st["open"] and server_history.forecast()["key"] == "forecast:/volume1"
    assert seen_rows() == ["forecast:/volume1"]
    tick(linear(35))                                    # back, now 35 days: same episode
    assert len(disk_posts(posts)) == 1 and seen_rows() == ["forecast:/volume1"]
    tick(linear(60, gap_h=40))                          # collecting again: the open episode is not judged, so not ended
    tick(flat(gap_h=40))                                # ... even when the older history reads flat
    assert server_history._forecast["open"] and len(disk_posts(posts)) == 1
    assert server_history.forecast()["words"] == "reaches 85% in about 35 days"   # its last item, kept


def test_collecting_never_opens_an_episode(posts):
    tick(linear(10, gap_h=40))
    assert not server_history._forecast["open"] and disk_posts(posts) == []


def test_a_hub_restart_keeps_the_episode_from_its_seen_row(posts):
    """The NAS is off every night: the first step after a start reads the seen-row, so 35 days stays open."""
    tick(linear(25))
    server_history.reset_forecast()                     # the hub restarts
    tick(linear(35))
    assert server_history._forecast["open"] and len(disk_posts(posts)) == 1
    server_history.reset_forecast()
    tick(linear(35, gap_h=40))                          # restart while collecting: rebuilt from the 7-day projection
    assert server_history._forecast["item"]["words"] == "reaches 85% in about 35 days"
    assert seen_rows() == ["forecast:/volume1"] and len(disk_posts(posts)) == 1


def test_a_restart_with_no_seen_row_starts_closed_between_30_and_45():
    server_history.refresh_forecast(linear(35), NOW)
    assert server_history.forecast_peek() is None


# ---- the hub card --------------------------------------------------------------------------------------------------

def _card_snaps(tmp_path, **data):
    from hub.store import get_snapshots
    d = tmp_path / "card"
    for cid, payload in data.items():
        write_envelope(d, cid, age_minutes=1, data=payload)
    return get_snapshots(d)


def test_hub_card_words_and_warn_state(tmp_path):
    snaps = _card_snaps(tmp_path, media_status=ALL_UP, system=SYSTEM)
    assert server.hub_card(snaps, set(), {"warning": None}) == {
        "summary": "All up", "secondary": "disk 74%", "state": "ok"}
    item = server.forecast_item("/volume2", 23, 10)
    assert server.hub_card(snaps, set(), {"warning": None}, forecast=item) == {
        "summary": "All up", "secondary": "disk 74% · reaches 85% in about 23 days", "state": "warn"}


def _hub(tmp_path, monkeypatch, samples=True, **data):
    snaps = tmp_path / "snaps"
    snaps.mkdir(exist_ok=True)
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    monkeypatch.delenv("AREAS_PATH", raising=False)
    if samples:
        for p in SAMPLES.glob("*.json"):
            if not p.stem.startswith("_"):
                write_envelope(snaps, p.stem, age_minutes=1, data=json.loads(p.read_text(encoding="utf-8"))["data"])
    for cid, d in data.items():
        write_envelope(snaps, cid, age_minutes=1, data=d)
    import hub.main
    importlib.reload(hub.main)
    return hub.main, TestClient(hub.main.app, client=(LAN_CLIENT, 50000))


def _server_card(html):
    return main_of(html).split('href="/a/server"', 1)[1].split("</a>", 1)[0]


def test_hub_page_card_shows_the_forecast_and_needs_attention(tmp_path, monkeypatch):
    _, client = _hub(tmp_path, monkeypatch, samples=False, media_status=ALL_UP, system=SYSTEM)
    with client:
        before = _server_card(client.get("/").text)
        server_history.refresh_forecast(linear(23), NOW)       # the loop's tick caches an open forecast
        card = _server_card(client.get("/").text)
    assert "reaches 85%" not in before and "Needs attention" not in before
    assert "disk 74% · reaches 85% in about 23 days" in txt(card)
    assert '<span class="badge badge-wait">Needs attention</span>' in card


# ---- the three paths build one key set ----------------------------------------------------------------------------

def test_hub_card_server_page_and_loop_build_the_same_key_set(posts, tmp_path, monkeypatch):
    main, client = _hub(tmp_path, monkeypatch)
    _seed(linear(23, now=LATER))
    monkeypatch.setattr(server_history, "_now", lambda: LATER)
    real_items, real_recent = server.attention_items, server_history.recent
    keysets, reads = [], []

    def spy(*a, **k):
        items = real_items(*a, **k)
        keysets.append({i["key"] for i in items})
        return items
    monkeypatch.setattr(server, "attention_items", spy)
    monkeypatch.setattr(server_history, "recent", lambda *a, **k: reads.append(1) or real_recent(*a, **k))
    with client:
        main._server_tick()                             # the loop: sample, forecast, Discord check
        loop = keysets[-1]
        reads.clear()
        assert client.get("/").status_code == 200
        assert reads == []                              # no recent() on a hub render
        card = keysets[-1]
        assert client.get("/server").status_code == 200
        page = keysets[-1]
        main._server_tick()                             # the render's sync kept the seen-row: no second post
    assert "forecast:/volume1" in loop and loop == card == page
    assert disk_posts(posts) == [DISCORD]
    assert seen_rows() == ["forecast:/volume1"]


def test_server_page_shows_the_cached_forecast_in_attention(tmp_path, monkeypatch):
    _, client = _hub(tmp_path, monkeypatch)
    server_history.refresh_forecast(linear(23), NOW)
    with client:
        body = main_of(client.get("/server").text)
    assert "Disk: reaches 85% in about 23 days (Volume 1, 412 GB free)" in body
    assert 'href="/server/space"' in body


def test_cold_start_server_render_computes_once_then_reads_the_cache(tmp_path, monkeypatch):
    """The minute after a start (no tick yet): the /server render computes from its own samples, once."""
    _, client = _hub(tmp_path, monkeypatch)
    _seed(linear(23, now=LATER))
    monkeypatch.setattr(server_history, "_now", lambda: LATER)
    steps = []
    real_step = server.forecast_step
    monkeypatch.setattr(server, "forecast_step", lambda *a, **k: steps.append(1) or real_step(*a, **k))
    with client:
        for _ in range(2):
            assert "Disk: reaches 85% in about 23 days" in main_of(client.get("/server").text)
    assert steps == [1]


def test_hub_render_before_the_first_tick_has_no_forecast_and_reads_no_history(tmp_path, monkeypatch):
    _, client = _hub(tmp_path, monkeypatch)
    _seed(linear(23, now=LATER))
    monkeypatch.setattr(server_history, "_now", lambda: LATER)
    reads = []
    monkeypatch.setattr(server_history, "recent", lambda *a, **k: reads.append(1) or [])
    with client:
        card = _server_card(client.get("/").text)
    assert reads == [] and "reaches 85%" not in card and server_history.forecast_peek() is None


def test_seen_keys_never_creates_media_db():
    assert server_alerts.seen_keys("forecast:") == set() and not media_db.db_path().exists()
    media_db.db_path().parent.mkdir(parents=True, exist_ok=True)
    sqlite3.connect(media_db.db_path()).close()        # a db without the table
    assert server_alerts.seen_keys("forecast:") == set()


# ---- fix round (2026-10-23) ---------------------------------------------------------------------------------------

def test_reaching_85_while_open_stays_one_silent_episode(posts):
    """84.9 -> 85.1 -> 84.9 while still filling: one post in all (the orchestrator's answer to B.'s question)."""
    for days in (0.1, -0.1, 0.1, -0.1, 0.1):
        tick(linear(days))
    assert disk_posts(posts) == ["Joey Server: Disk: reaches 85% in about 1 day (Volume 1, 412 GB free)"]
    tick(linear(-0.1))
    assert server_history.forecast()["words"] == "at or over 85%" and seen_rows() == ["forecast:/volume1"]


def test_at_85_a_closed_episode_does_not_open():
    st = server.forecast_step(None, linear(-0.1), NOW)
    assert not st["open"] and st["item"] is None


def test_the_85_episode_clears_on_a_flat_disk_or_on_a_slow_projection_below_85(posts):
    tick(linear(0.1))
    tick(linear(-0.1))
    tick(flat(pct=86.0))                                 # flat while full: ends
    assert seen_rows() == [] and len(disk_posts(posts)) == 1
    tick(linear(0.1))                                    # filling fast again: a new episode
    tick(linear(-0.1))
    tick(linear(40, slope=0.02))                         # under 85 again, filling slowly: 40 days keeps it open
    assert seen_rows() == ["forecast:/volume1"] and len(disk_posts(posts)) == 2
    tick(linear(50, slope=0.02))                         # the full item cleared and the projection is over 45: ends
    assert seen_rows() == [] and len(disk_posts(posts)) == 2


def test_a_restart_while_collecting_with_no_projection_keeps_the_episode(posts):
    tick(linear(25))
    server_history.reset_forecast()                      # restart, then the NAS was off: collecting, flat history
    tick(flat(gap_h=40))
    st = server_history._forecast
    assert st["open"] and st["collecting"] and st["item"]["text"] == "Disk: filling fast (Volume 1, 412 GB free)"
    assert seen_rows() == ["forecast:/volume1"] and len(disk_posts(posts)) == 1
    tick(flat())                                         # a real computed flat projection ends it
    assert seen_rows() == [] and len(disk_posts(posts)) == 1


def test_a_failed_first_compute_skips_the_forecast_and_keeps_the_rest(posts, monkeypatch, caplog):
    import logging
    tick(linear(25))                                     # an episode is open and posted
    server_history.reset_forecast()
    monkeypatch.setattr(server, "forecast_step", lambda *a, **k: 1 / 0)
    item = {"key": "down:prowlarr", "text": "Prowlarr is Down"}
    monkeypatch.setattr(server, "attention_items", lambda *a, **k: [item] + ([a[5]] if len(a) > 5 and a[5] else []))
    with caplog.at_level(logging.WARNING, logger="hub.server_alerts"):
        assert server_alerts.check_once(set(), {}) == 1  # the other alert still goes
    assert posts[-1]["text"] == "Joey Server: Prowlarr is Down"
    assert seen_rows() == ["forecast:/volume1"] and len(disk_posts(posts)) == 1   # the forecast row stays
    assert "disk forecast skipped this time: ZeroDivisionError" in caplog.text and "SECRET" not in caplog.text


def test_server_render_with_a_failed_forecast_still_renders_and_keeps_the_row(posts, tmp_path, monkeypatch):
    tick(linear(25))
    server_history.reset_forecast()
    _, client = _hub(tmp_path, monkeypatch)
    monkeypatch.setattr(server, "forecast_step", lambda *a, **k: 1 / 0)
    with client:
        assert client.get("/server").status_code == 200
        assert client.get("/server/space").status_code == 200
    assert seen_rows() == ["forecast:/volume1"] and len(disk_posts(posts)) == 1


def test_free_space_days_follow_the_cached_forecast(tmp_path, monkeypatch):
    """Free space's "(≈ N days)" appears exactly when the Server page's Attention has the forecast (reviewer B)."""
    from hub import server_space
    from tests.hub.test_server_space import snaps as space_snaps
    system = {"volumes": [{"path": "/volume1", "total_gb": 1000.0, "free_gb": 412.0, "pct_used": 62}]}
    samples = linear(23)
    st = server.forecast_step(None, samples, NOW)
    with_days = server_space.build(space_snaps(system=system), samples, NOW, forecast=st["item"])["head"]
    assert with_days.startswith("Removing all 4 frees ~85 GB (≈ ") and with_days.endswith(" at this rate)")
    # 35 days: history_band has no forecast (over 30), but an open episode does - Free space follows the episode
    open35 = server.forecast_step(st, linear(35), NOW)["item"]
    assert server.history_band(linear(35), NOW)["forecast"] is None and open35 is not None
    assert "(≈ " in server_space.build(space_snaps(system=system), linear(35), NOW, forecast=open35)["head"]
    assert "(≈ " not in server_space.build(space_snaps(system=system), samples, NOW, forecast=None)["head"]


def test_free_space_page_reads_the_cache(tmp_path, monkeypatch):
    _, client = _hub(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(server_history, "forecast", lambda *a, **k: calls.append(1) or None)
    with client:
        assert client.get("/server/space").status_code == 200
    assert calls == [1]
