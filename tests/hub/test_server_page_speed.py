"""JY-226 (2026-10-24): the Server page within its render budget. `server_history.recent()` keeps the decoded
`server_system_samples` rows and re-reads the table only when its key (db path, MAX(ts), COUNT(*)) changes;
`server.sweep_stats` is memoised on the kept runner history. The pages must render exactly as before: the code before
JY-226 is copied below (`recent_before`, `sweep_stats_before`) as the reference. One frozen clock (server.datetime and
server_history._now); media.db in the test's temp dir (tests/conftest.py)."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest

from hub import media_db, server, server_history, server_uptime
from hub.store import get_runner_history, get_snapshots, parse_utc
from tests.hub.helpers import write_envelope, write_history
from tests.hub.test_server import env, main_of  # noqa: F401  (env is a fixture)

T = datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture(autouse=True)
def fresh_clock():
    """T is each test's own start, never the import's: under xdist a test runs minutes after collection, the system
    envelope (written at the real clock) was then newer than the newest seeded sample, and every render's background
    sample() added a row between two renders (CI, 2026-10-24)."""
    global T
    T = datetime.now(timezone.utc).replace(microsecond=0)


class _AnyDatetime(type):
    def __instancecheck__(cls, obj):   # server.py's isinstance(x, datetime) checks still see real datetimes
        return isinstance(obj, datetime)


class Frozen(datetime, metaclass=_AnyDatetime):
    @classmethod
    def now(cls, tz=None):
        return T if tz is not None else T.replace(tzinfo=None)


@pytest.fixture()
def frozen(monkeypatch):
    monkeypatch.setattr(server, "datetime", Frozen)
    monkeypatch.setattr(server_history, "_now", lambda: T)


# ---- the code before JY-226, verbatim but for names: the reference ---------------------------------------------------

def recent_before(now=None, days=7):
    if not media_db.db_path().is_file():
        return []
    since = server_history._iso((now or server_history._now()) - timedelta(days=days))
    with closing(media_db.connect()) as db:
        server_history.ensure(db)
        rows = db.execute("SELECT * FROM server_system_samples WHERE ts >= ? ORDER BY ts", (since,)).fetchall()
    out = []
    for r in rows:
        try:
            vols = json.loads(r["volumes"] or "[]")
        except ValueError:
            vols = []
        out.append({"at": parse_utc(r["ts"]), "cpu_pct": r["cpu_pct"], "ram_pct_used": r["ram_pct_used"],
                    "ram_free_gb": r["ram_free_gb"], "load_1m": r["load_1m"],
                    "volumes": [v for v in vols if isinstance(v, dict)]})
    return out


def sweep_stats_before(history, now=None):
    if not history:
        return None
    now = now or server.datetime.now(timezone.utc)
    since = now.timestamp() - server.SWEEP_WINDOW_HOURS * 3600
    stats, usable = {}, False
    for line in history:
        if not isinstance(line, dict) or not isinstance(line.get("results"), dict):
            continue
        at = parse_utc(line.get("ran_at"))
        if at is None:
            continue
        usable = True
        if at.timestamp() < since:
            continue
        for cid, res in line["results"].items():
            if not isinstance(res, dict):
                continue
            st = stats.setdefault(str(cid), {"runs": 0, "failures": 0, "failing": False,
                                             "reason": None, "last_ok": None, "_at": None})
            failed = res.get("status") == "error"
            st["runs"] += 1
            st["failures"] += failed
            if not failed and (st["last_ok"] is None or at > st["last_ok"]):
                st["last_ok"] = at
            if st["_at"] is None or at >= st["_at"]:
                st["_at"], st["failing"] = at, failed
                if failed:
                    st["reason"] = server._reason(res)
    if not usable:
        return None
    for st in stats.values():
        st.pop("_at")
    return stats


# ---- production-shaped data -------------------------------------------------------------------------------------------

def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_samples(every_min=30, days=8, newest=None):
    """One row per `every_min` over `days` (some older than the 7-day window), the newest at `newest` (after the system
    envelope, so a render's own sample() adds nothing). /volume1 grows ~1.4 %/day: the forecast episode is open."""
    newest = newest or T
    rows, k = [], 0
    t = newest - timedelta(days=days)
    while t <= newest:
        k += 1
        vols = [{"path": "/volume1", "pct_used": round(70 + k * 10 / (days * 1440 / every_min), 2), "free_gb": 900.0 - k},
                {"path": "/volume2", "pct_used": 66.0, "free_gb": 1248.0},
                {"path": "/volume1/Docker", "pct_used": round(74 + (k % 7) / 10, 2), "free_gb": 120.0}]
        rows.append((_iso(t), float(5 + k % 35), 60 + k % 25, 1.9, round(0.2 + (k % 9) / 5, 2), json.dumps(vols)))
        t += timedelta(minutes=every_min)
    with sqlite3.connect(media_db.db_path()) as db:
        db.execute(server_history.DDL)
        db.executemany("INSERT INTO server_system_samples VALUES(?,?,?,?,?,?)", rows)
    return rows


def seed_runner(snaps):
    """30 h of 30-minute sweeps against T, 7 minutes off the window's grid (some outside the 24 h window), a few
    failures, the latest failing for wud."""
    snaps.mkdir(parents=True, exist_ok=True)
    with (snaps / "_runner_history.jsonl").open("a", encoding="utf-8") as fh:
        for m in range(30 * 60 + 7, 0, -30):
            res = {"wud": ("error", "RuntimeError: WUD containers failed (HTTP 401)") if m % 150 == 7 else ("ok", None),
                   "arr": ("error", "RuntimeError: arr timed out") if m % 90 == 7 else ("ok", None),
                   "system": ("ok", None)}
            fh.write(json.dumps({"ran_at": (T - timedelta(minutes=m)).isoformat(),
                                 "results": {cid: {"status": st, "consecutive_failures": 0, "error": err}
                                             for cid, (st, err) in res.items()}}) + "\n")


@pytest.fixture()
def server_data(env, tmp_path, frozen):   # noqa: F811
    client = env()
    seed_samples()
    seed_runner(tmp_path / "snaps")
    return client


def _get(client, path):
    r = client.get(path)
    assert r.status_code == 200
    return r.content


# ---- AC 3 + 5: byte-identical pages -------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/a/server", "/server/space"])
def test_server_pages_are_byte_identical_with_the_caches(server_data, monkeypatch, path):
    decoded, windows = [], []
    real_decode, real_window = server_history._decode, server._sweep_window
    # JY-133 (2026-10-26, spec docs/specs/JY-133-service-uptime.md): the after-page task fills the uptime lines, so the
    # first render would differ from the rest; held empty here so this JY-226 check compares one data set.
    server_uptime.clear()
    monkeypatch.setattr(server_uptime, "tick", lambda *a, **k: None)
    with server_data as client:
        with monkeypatch.context() as m:   # the code before JY-226
            m.setattr(server_history, "recent", recent_before)
            m.setattr(server, "sweep_stats", sweep_stats_before)
            server_history.reset_forecast()
            before = _get(client, path)
            assert _get(client, path) == before   # the clock is frozen: the reference itself is stable
        monkeypatch.setattr(server_history, "_decode", lambda rows: decoded.append(1) or real_decode(rows))
        monkeypatch.setattr(server, "_sweep_window", lambda *a: windows.append(1) or real_window(*a))
        server_history.reset_forecast()
        server_history.clear_cache()
        server.clear_sweep_memo()
        cold = _get(client, path)
        warm = _get(client, path)
    assert cold == before and warm == before
    assert len(decoded) == 1   # the warm render read only the key
    if path == "/a/server":
        assert len(windows) == 1   # and reused the sweep stats
        body = main_of(before.decode("utf-8"))
        assert "reaches 85% in about" in body and 'id="history"' in body   # the forecast and the band are in play
        assert "wud failed" in body


def test_recent_matches_the_old_read_for_any_window_and_clock(server_data):
    for days in (1, 7, 8, 30):
        for now in (T, T - timedelta(hours=13), T + timedelta(days=2)):
            assert server_history.recent(now, days) == recent_before(now, days)


def test_forecast_loop_gives_the_same_state_as_before(server_data):
    state = server_history.refresh_forecast(now=T)
    assert state == server.forecast_step(None, recent_before(T), T)
    assert state["open"] and state["item"]["key"] == "forecast:/volume1"


# ---- AC 4: a new sample or a prune shows on the next read ---------------------------------------------------------------

def test_a_new_sample_shows_on_the_next_render(server_data):
    with server_data as client:
        first = main_of(_get(client, "/a/server").decode("utf-8"))
        with sqlite3.connect(media_db.db_path()) as db:
            db.execute("INSERT INTO server_system_samples VALUES(?,?,?,?,?,?)",
                       (_iso(T + timedelta(seconds=30)), 97.0, 84, 1.0, 3.5,
                        json.dumps([{"path": "/volume1", "pct_used": 80.5, "free_gb": 400.0}])))
        second = main_of(_get(client, "/a/server").decode("utf-8"))
    assert "now 97 %" not in first and "now 97 %" in second


def test_a_prune_alone_shows_on_the_next_read(server_data):
    n = len(server_history.recent(T, 30))
    with sqlite3.connect(media_db.db_path()) as db:   # MAX(ts) unchanged, COUNT(*) down
        db.execute("DELETE FROM server_system_samples WHERE ts < ?", (_iso(T - timedelta(days=7, hours=12)),))
    after = server_history.recent(T, 30)
    assert len(after) < n and after == recent_before(T, 30)


def test_sample_insert_and_prune_show_on_the_next_read(tmp_path, frozen):
    snaps = tmp_path / "snaps"
    seed_samples(every_min=60, days=9, newest=T - timedelta(minutes=10))
    kept = server_history.recent(T, 30)
    assert kept[0]["at"] < T - timedelta(days=8)
    write_envelope(snaps, "system", age_minutes=1, data={"cpu_pct": 42.0, "ram_pct_used": 70, "volumes": []})
    assert server_history.sample(get_snapshots(snaps)) is True   # inserts one, prunes everything over 8 days
    now = server_history.recent(T, 30)
    assert now == recent_before(T, 30)
    assert now[-1]["cpu_pct"] == 42.0 and now[0]["at"] >= T - timedelta(days=8, minutes=2)


def test_recent_returns_a_new_list_each_call(server_data):
    a, b = server_history.recent(), server_history.recent()
    assert a == b and a is not b
    a.clear()
    assert server_history.recent() == b


def test_recent_unreadable_db_is_empty(tmp_path, monkeypatch):
    media_db.db_path().parent.mkdir(parents=True, exist_ok=True)
    media_db.db_path().write_bytes(b"not a database" * 100)
    assert server_history.recent() == []


# ---- sweep_stats memo (AC 2) --------------------------------------------------------------------------------------------

def _hist(snaps):
    seed_runner(snaps)
    return get_runner_history(snaps)


def test_sweep_stats_memo_matches_and_recomputes_only_when_needed(tmp_path, monkeypatch):
    history = _hist(tmp_path / "snaps")
    calls = []
    real = server._sweep_window
    monkeypatch.setattr(server, "_sweep_window", lambda *a: calls.append(1) or real(*a))
    first = server.sweep_stats(history, T)
    assert first == sweep_stats_before(history, T)
    assert server.sweep_stats(history, T + timedelta(seconds=20)) == first and len(calls) == 1   # no line crossed
    later = T + timedelta(minutes=45)   # the window's start passes a line
    assert server.sweep_stats(history, later) == sweep_stats_before(history, later) and len(calls) == 2
    other = list(history)   # another list: computed afresh
    assert server.sweep_stats(other, later) == sweep_stats_before(other, later) and len(calls) == 3


def test_sweep_stats_memo_follows_the_store_when_the_file_grows(tmp_path):
    snaps = tmp_path / "snaps"
    history = _hist(snaps)
    server.sweep_stats(history, T)
    write_history(snaps, [(0, {"wud": "ok", "arr": "ok", "system": "ok"})])
    grown = get_runner_history(snaps)
    assert grown is not history
    assert server.sweep_stats(grown, T + timedelta(minutes=1)) == sweep_stats_before(grown, T + timedelta(minutes=1))
    assert server.sweep_stats(grown, T + timedelta(minutes=1))["wud"]["failing"] is False


def test_sweep_stats_callers_get_their_own_copy(tmp_path):
    history = _hist(tmp_path / "snaps")
    a = server.sweep_stats(history, T)
    a["wud"]["runs"] = -1
    a.pop("arr")
    assert server.sweep_stats(history, T) == sweep_stats_before(history, T)


def test_sweep_stats_no_usable_lines_is_none_memoised_or_not():
    junk = ["junk", {"ran_at": "nope", "results": {}}]
    assert server.sweep_stats(junk, T) is None and server.sweep_stats(junk, T) is None
    assert server.sweep_stats([], T) is None and server.sweep_stats(None, T) is None
