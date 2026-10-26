"""Overnight digest (P2, 2026-10-22): hub/server_digest.py — the text built from snapshots, the once-a-day send, the
Server page's one line. requests.post is mocked; media.db is the conftest's isolated tmp file; the clock is a fixed
aware datetime handed to `build` / `tick` / `last_sent` (hub-local, as the loop passes it)."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hub import media_db, server_alerts, server_digest, store
from tests.hub.helpers import write_envelope
from tests.hub.test_server import env, main_of, txt  # noqa: F401  (env is a fixture)

SAMPLES = Path(__file__).resolve().parents[2] / "config" / "sample_snapshots"
HOOK = "https://discord.invalid/api/webhooks/1/SECRET"
MEL = timezone(timedelta(hours=11))
# the sample sweep is stamped 2026-01-01T00:00Z; 08:00 Melbourne = 2025-12-31T21:00Z, 17 min after its newest arrival
NOW = datetime(2026, 1, 1, 8, 0, tzinfo=MEL)


def at(hh, mm, day=1):
    return datetime(2026, 1, day, hh, mm, tzinfo=MEL)


@pytest.fixture(autouse=True)
def _fresh_fails():
    server_digest._fails.clear()
    yield
    server_digest._fails.clear()


@pytest.fixture(autouse=True)
def _hub_up_long(monkeypatch):
    # JY-254: these tests run as a hub that started long ago, past the boot grace (the boot tests pass `booted`)
    monkeypatch.setattr(server_digest, "STARTED", datetime(2025, 1, 1, tzinfo=timezone.utc))


def sample_data(cid):
    return json.loads((SAMPLES / f"{cid}.json").read_text(encoding="utf-8"))["data"]


@pytest.fixture()
def snapdir(tmp_path, monkeypatch):
    d = tmp_path / "snaps"
    d.mkdir()
    monkeypatch.setenv("SNAPSHOT_DIR", str(d))

    def put(*cids, **custom):
        for cid in cids:
            write_envelope(d, cid, age_minutes=1, data=sample_data(cid))
        for cid, data in custom.items():
            write_envelope(d, cid, age_minutes=1, data=data)
        return store.get_snapshots(d)
    return put


class Resp:
    def __init__(self, code):
        self.status_code = code


class Calls(list):
    state: dict


@pytest.fixture()
def posts(monkeypatch):
    calls, state = Calls(), {"code": 204}

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "text": json["content"]})
        return Resp(state["code"])
    monkeypatch.setattr(server_alerts.requests, "post", fake_post)
    monkeypatch.setenv("SERVER_DISCORD_WEBHOOK", HOOK)
    monkeypatch.delenv("DIGEST", raising=False)
    monkeypatch.delenv("DIGEST_AT", raising=False)
    calls.state = state
    return calls


def rows():
    if not media_db.db_path().exists():
        return None
    with sqlite3.connect(media_db.db_path()) as db:
        try:
            return db.execute("SELECT day, at, text FROM server_digest_sent").fetchall()
        except sqlite3.OperationalError:
            return None


# ---- the text ---------------------------------------------------------------------------------------------------

ALL = ("arr", "wud", "system", "media_status", "qbittorrent")


def test_text_from_the_sample_snapshots(snapdir):
    text = server_digest.build(snapdir(*ALL), NOW)
    assert text == ("Joey digest · Thu 1 Jan · Arrived: 3 episodes · 2 updates pending · Disk 74 % · "
                    "Down: Prowlarr · 1 torrent stalled")
    assert len(text) <= 300 and "  " not in text


def test_arrivals_count_films_and_episodes_separately_inside_24_hours_only(snapdir):
    now = datetime(2026, 1, 1, 8, 0, tzinfo=MEL)
    arrived = [
        {"at": "2025-12-31T20:00:00+00:00", "kind": "movie", "title": "Harbour Lights"},
        {"at": "2025-12-31T19:00:00+00:00", "kind": "season", "title": "Quiet Coast · S02 · 3 episodes"},
        {"at": "2025-12-31T18:00:00+00:00", "kind": "episode", "title": "Night Ferry · S01E04 · Last Crossing"},
        {"at": "2025-12-30T09:00:00+00:00", "kind": "movie", "title": "Too Old"},      # > 24 h before now
        {"at": "2026-01-01T09:00:00+00:00", "kind": "movie", "title": "In The Future"},  # after now: ignored
    ]
    text = server_digest.build(snapdir(arr={"arrived": arrived}), now)
    assert text == "Joey digest · Thu 1 Jan · Arrived: 4 episodes, 1 film"
    one = server_digest.build(snapdir(arr={"arrived": arrived[:1]}), now)
    assert one.endswith("Arrived: 1 film")
    none = server_digest.build(snapdir(arr={"arrived": arrived[3:4]}), now)
    assert none.endswith("Nothing new arrived")


def test_all_clear_words(snapdir):
    apps = [{"id": "a", "name": "A", "up": True}, {"id": "b", "name": "B", "up": True}]
    snaps = snapdir(media_status={"apps": apps}, wud={"containers": [{"name": "x", "update_available": False}]},
                    qbittorrent={"active": []}, system={"volumes": [{"path": "/v", "pct_used": 71}]})
    assert server_digest.build(snaps, NOW) == ("Joey digest · Thu 1 Jan · No updates pending · Disk 71 % · "
                                               "All 2 services up · Nothing downloading")


def test_down_services_are_named_and_active_torrents_counted(snapdir):
    snaps = snapdir(media_status={"apps": [{"id": "radarr", "name": "Radarr", "up": False},
                                           {"id": "wud", "name": "WUD", "up": False}, {"id": "x", "name": "X", "up": True}]},
                    qbittorrent={"active": [{"state_text": "Downloading"}, {"state_text": "Downloading"},
                                            {"state_text": "Paused"}]})
    assert server_digest.build(snaps, NOW) == "Joey digest · Thu 1 Jan · Down: Radarr, WUD · 2 downloading"


def test_ignored_updates_are_not_counted(snapdir):
    from hub import server_updates
    server_updates.set_ignore("uptime-kuma", "2.0.2")
    text = server_digest.build(snapdir("wud"), NOW)
    assert text.endswith("1 update pending")


def test_a_missing_snapshot_leaves_its_part_out(snapdir):
    text = server_digest.build(snapdir("system", "media_status"), NOW)
    assert text == "Joey digest · Thu 1 Jan · Disk 74 % · Down: Prowlarr"


def test_no_snapshots_means_no_message(snapdir):
    assert server_digest.build({}, NOW) is None
    # an envelope that carries none of the digest's fields is not a part either
    assert server_digest.build(snapdir(arr={"summary": "x"}, wud={}), NOW) is None


# ---- the once-a-day send ----------------------------------------------------------------------------------------

def test_no_webhook_means_no_post_and_no_row(snapdir, posts, monkeypatch):
    snapdir(*ALL)
    monkeypatch.delenv("SERVER_DISCORD_WEBHOOK")
    assert server_digest.tick(at(9, 0)) is False and posts == []
    assert rows() is None


def test_digest_off_does_nothing(snapdir, posts, monkeypatch):
    snapdir(*ALL)
    monkeypatch.setenv("DIGEST", "off")
    assert server_digest.tick(at(9, 0)) is False and posts == [] and rows() is None


def test_before_digest_at_nothing_is_sent(snapdir, posts):
    snapdir(*ALL)
    assert server_digest.tick(at(7, 29)) is False and posts == [] and rows() is None


def test_at_digest_at_one_post_then_nothing_more_that_day(snapdir, posts):
    snapdir(*ALL)
    assert server_digest.tick(at(7, 30)) is True
    assert len(posts) == 1 and posts[0]["url"] == HOOK and posts[0]["text"].startswith("Joey digest · Thu 1 Jan · ")
    assert [(d, t) for d, _, t in rows()] == [("2026-01-01", posts[0]["text"])]
    assert server_digest.tick(at(7, 35)) is False and server_digest.tick(at(23, 0)) is False and len(posts) == 1


def test_a_hub_that_starts_late_still_sends_once_and_the_next_day_sends_again(snapdir, posts):
    snapdir(*ALL)
    assert server_digest.tick(at(9, 0)) is True and server_digest.tick(at(9, 5)) is False
    assert server_digest.tick(at(7, 30, day=2)) is True
    assert [r[0] for r in rows()] == ["2026-01-01", "2026-01-02"] and len(posts) == 2


def test_digest_at_comes_from_the_env(snapdir, posts, monkeypatch):
    snapdir(*ALL)
    monkeypatch.setenv("DIGEST_AT", "06:15")
    assert server_digest.send_after() == (6, 15)
    assert server_digest.tick(at(6, 14)) is False and server_digest.tick(at(6, 15)) is True
    monkeypatch.setenv("DIGEST_AT", "junk")
    assert server_digest.send_after() == (7, 30)


def test_failed_post_records_no_row_then_retries_and_gives_up_after_three(snapdir, posts):
    snapdir(*ALL)
    posts.state["code"] = 404
    assert server_digest.tick(at(8, 0)) is False
    assert rows() == []
    posts.state["code"] = 204
    assert server_digest.tick(at(8, 5)) is True and len(posts) == 2 and len(rows()) == 1
    # a permanently refused webhook stops after MAX_FAILS, and tomorrow is a fresh day
    posts.state["code"] = 500
    for m in range(5):
        server_digest.tick(at(8, m, day=2))
    assert len(posts) == 2 + server_digest.MAX_FAILS
    posts.state["code"] = 204
    assert server_digest.tick(at(8, 0, day=3)) is True


def test_nothing_to_say_sends_nothing_and_tries_again_later(posts):
    # no snapshot dir content at all
    assert server_digest.tick(at(9, 0)) is False and posts == [] and not rows()


# ---- the Server page line ---------------------------------------------------------------------------------------

def test_last_sent_words(snapdir, posts, monkeypatch):
    snapdir(*ALL)
    assert server_digest.last_sent(at(9, 0)) == "Digest · not sent today"
    assert server_digest.tick(at(7, 31)) is True
    assert server_digest.last_sent(at(9, 0)) == "Digest · sent 07:31"
    assert server_digest.last_sent(at(9, 0, day=2)) == "Digest · not sent today"
    monkeypatch.setenv("DIGEST", "off")
    assert server_digest.last_sent(at(9, 0)) is None
    monkeypatch.setenv("DIGEST", "on")
    monkeypatch.delenv("SERVER_DISCORD_WEBHOOK")
    assert server_digest.last_sent(at(9, 0)) is None


def test_server_page_shows_the_digest_line_only_with_a_webhook(env, posts, monkeypatch):
    monkeypatch.delenv("SERVER_DISCORD_WEBHOOK", raising=False)
    with env() as client:
        assert "digestline" not in client.get("/server").text
    monkeypatch.setenv("SERVER_DISCORD_WEBHOOK", HOOK)
    with env() as client:
        body = main_of(client.get("/server").text)
    assert 'class="metaline digestline">Digest · not sent today</p>' in body
    assert body.index('id="system"') < body.index("digestline") < body.index('id="services"')   # System band, under the sweeps line
    assert HOOK not in body
    day = datetime.now().astimezone()
    with sqlite3.connect(media_db.connect().execute("PRAGMA database_list").fetchone()[2]) as db:
        db.execute(server_digest.DDL)
        db.execute("INSERT INTO server_digest_sent(day, at, text) VALUES(?,?,?)",
                   (day.date().isoformat(), day.replace(hour=7, minute=31).isoformat(), "x"))
    with env() as client:
        body = main_of(client.get("/server").text)
    assert "Digest · sent 07:31" in txt(body)


def test_the_loop_is_registered_beside_the_alerts_loop():
    from hub import tasks
    assert (server_digest.FIRST_DELAY_S, server_digest.EVERY_S) == (90, 300)
    assert tasks._server_digest_loop.__doc__ and "server_digest.tick" in Path(tasks.__file__).read_text(encoding="utf-8")


# ---- JY-254: the boot grace -------------------------------------------------------------------------------------

BOOT = at(7, 28)   # the NAS (and joey-hub with it) came up at 07:28; DIGEST_AT 07:30 is due on the first tick


def status_at(d, updated, apps):
    """A media_status envelope whose last success is `updated` (aware), the rest from the samples."""
    for cid in ("arr", "wud", "system", "qbittorrent"):
        write_envelope(d, cid, age_minutes=1, data=sample_data(cid))
    ts = updated.isoformat()
    (d / "media_status.json").write_text(json.dumps({
        "connector": "media_status", "schema_version": 1, "fetched_at": ts, "updated_at": ts, "status": "ok",
        "consecutive_failures": 0, "error": None, "data": {"apps": apps}}), encoding="utf-8")


DOWN_BEFORE_BOOT = [{"id": "jellyfin", "name": "Jellyfin", "up": False}, {"id": "radarr", "name": "Radarr", "up": False}]
ALL_UP = [{"id": "jellyfin", "name": "Jellyfin", "up": True}, {"id": "radarr", "name": "Radarr", "up": True}]
ONE_DEAD = [{"id": "jellyfin", "name": "Jellyfin", "up": True}, {"id": "radarr", "name": "Radarr", "up": False}]


@pytest.fixture()
def snapsdir(tmp_path, monkeypatch):
    d = tmp_path / "snaps"
    d.mkdir()
    monkeypatch.setenv("SNAPSHOT_DIR", str(d))
    return d


def test_boot_plus_2_min_with_only_pre_boot_samples_does_not_say_down(snapsdir, posts):
    status_at(snapsdir, BOOT - timedelta(hours=9), DOWN_BEFORE_BOOT)
    assert server_digest.tick(BOOT + timedelta(minutes=2), booted=BOOT) is False
    assert posts == [] and not rows()


def test_boot_plus_5_min_with_a_fresh_all_up_sample_sends_at_once(snapsdir, posts):
    status_at(snapsdir, BOOT + timedelta(minutes=4), ALL_UP)
    assert server_digest.tick(BOOT + timedelta(minutes=5), booted=BOOT) is True
    assert len(posts) == 1 and "All 2 services up" in posts[0]["text"] and "Down" not in posts[0]["text"]


def test_boot_plus_5_min_with_a_service_still_starting_holds(snapsdir, posts):
    status_at(snapsdir, BOOT + timedelta(minutes=4), ONE_DEAD)
    assert server_digest.tick(BOOT + timedelta(minutes=5), booted=BOOT) is False
    assert posts == [] and not rows()


def test_boot_plus_30_min_a_dead_service_still_shows_down(snapsdir, posts):
    status_at(snapsdir, BOOT + timedelta(minutes=29), ONE_DEAD)
    assert server_digest.tick(BOOT + timedelta(minutes=30), booted=BOOT) is True
    assert len(posts) == 1 and "Down: Radarr" in posts[0]["text"]


def test_the_wait_is_capped_even_with_no_sample_after_boot(snapsdir, posts):
    status_at(snapsdir, BOOT - timedelta(hours=9), DOWN_BEFORE_BOOT)
    assert server_digest.tick(BOOT + timedelta(minutes=14), booted=BOOT) is False
    assert server_digest.tick(BOOT + server_digest.BOOT_GRACE + timedelta(minutes=1), booted=BOOT) is True
    assert len(posts) == 1 and "Down: Jellyfin, Radarr" in posts[0]["text"]


def test_boot_grace_is_15_minutes_from_the_hub_start():
    assert server_digest.BOOT_GRACE == timedelta(minutes=15)
    assert server_digest.STARTED.tzinfo is not None
