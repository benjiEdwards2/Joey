"""JY-134 (P8, 2026-10-26, built as option A for B.'s pick): "Since your last visit" on the Server page.

One sentence per viewer ("you" / "her"), from stored data only: Joey's update runs and the runner history. A visit
starts after 30 minutes without a Server view; the row is written after the page, never during the render."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from hub import media_db, server_visits as sv
from tests.hub.helpers import write_history
from tests.hub.test_server import env, main_of  # noqa: F401 (fixture)

T0 = datetime(2026, 10, 26, 1, 0, tzinfo=timezone.utc)
YOU = {"Cf-Access-Authenticated-User-Email": "you@example.test"}
HER = {"Cf-Access-Authenticated-User-Email": "her@example.test"}


@pytest.fixture(autouse=True)
def _fresh():
    sv.clear()
    yield
    sv.clear()


def line(minutes_after_t0, **results):
    return {"ran_at": (T0 + timedelta(minutes=minutes_after_t0)).isoformat(),
            "results": {cid: ({"status": r} if isinstance(r, str) else {"status": r[0], "error": r[1]})
                        for cid, r in results.items()}}


# ---- the visit ---------------------------------------------------------------------------------------------------

def test_first_visit_has_nothing_to_compare_and_a_reload_keeps_the_start():
    assert sv.since_for("you", T0) is None
    sv.touch("you", T0)
    assert sv.since_for("you", T0 + timedelta(minutes=10)) is None        # still the first visit
    sv.touch("you", T0 + timedelta(minutes=10))
    later = T0 + timedelta(hours=3)
    assert sv.since_for("you", later) == T0 + timedelta(minutes=10)       # a new visit: the end of the last one
    sv.touch("you", later)
    assert sv.since_for("you", later + timedelta(minutes=20)) == T0 + timedelta(minutes=10)   # same visit, same start
    sv.touch("you", later + timedelta(minutes=20))
    assert sv.since_for("you", later + timedelta(hours=2)) == later + timedelta(minutes=20)


def test_each_viewer_has_their_own_visit():
    sv.touch("you", T0)
    sv.touch("her", T0 + timedelta(hours=5))
    now = T0 + timedelta(hours=8)
    assert sv.since_for("you", now) == T0 and sv.since_for("her", now) == T0 + timedelta(hours=5)


def test_no_identity_reads_and_writes_nothing():
    sv.touch(None, T0)
    sv.touch("jf:" + "a" * 32, T0)                                      # a friend key is never a Server viewer
    assert not media_db.db_path().exists()
    assert sv.since_for(None, T0) is None
    assert sv.sentence(None, T0, {}, []) is None


# ---- the words ---------------------------------------------------------------------------------------------------

def test_updates_after_the_start_are_named_in_request_order():
    since = T0
    req = {"radarr": {"requested_at": (T0 + timedelta(hours=2)).isoformat()},
           "sonarr": {"requested_at": (T0 + timedelta(hours=1)).isoformat()},
           "old": {"requested_at": (T0 - timedelta(hours=1)).isoformat()}}
    now = T0 + timedelta(days=2)
    assert sv.sentence("you", since, req, [], now=now) == \
        "Since your last visit 2d ago: sonarr and radarr were updated."
    one = {"sonarr": req["sonarr"]}
    assert sv.sentence("you", since, one, [], now=now) == "Since your last visit 2d ago: sonarr was updated."
    many = {f"c{i}": {"requested_at": (T0 + timedelta(minutes=i + 1)).isoformat()} for i in range(4)}
    sv.clear()
    assert sv.sentence("you", since, many, [], now=now) == \
        "Since your last visit 2d ago: c0, c1 and 2 more were updated."


def test_feeds_that_failed_and_recovered_after_the_start():
    history = [line(-30, wud=("error", "RuntimeError: before the visit")),
               line(10, wud=("error", "WUD failed (HTTP 500)"), arr="ok", gcal="ok"),
               line(20, wud=("error", "WUD failed (HTTP 500)"), arr=("error", "Arr failed (timeout)")),
               line(30, wud="ok", arr=("error", "Arr failed (timeout)")),                     # arr still failing
               line(40, wud="ok", gcal=("error", "MissingCredential: gcal: missing environment variable"),
                    arr=("error", "Arr failed (timeout)")),
               line(50, gcal="ok", arr=("error", "Arr failed (timeout)"))]
    got = sv.sentence("you", T0, {}, history, now=T0 + timedelta(hours=5))
    assert got == "Since your last visit 5h ago: wud failed 2 times, then recovered."
    sv.clear()
    once = [line(10, system=("error", "x")), line(20, system="ok")]
    assert sv.sentence("you", T0, {}, once, now=T0 + timedelta(hours=5)).endswith("system failed once, then recovered.")


def test_a_quiet_visit_says_nothing_changed():
    assert sv.sentence("her", T0, {}, [line(10, wud="ok")], now=T0 + timedelta(hours=5)) == \
        "Since your last visit 5h ago: nothing changed."


# ---- the page ----------------------------------------------------------------------------------------------------

def _set_last_seen(owner, at):
    with sqlite3.connect(media_db.db_path()) as db:
        db.execute("UPDATE server_last_visit SET last_seen = ? WHERE owner = ?",
                   (at.strftime("%Y-%m-%dT%H:%M:%SZ"), owner))


def test_the_page_says_it_from_the_second_visit_per_viewer(env, monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL_YOU", "you@example.test")
    with env() as client:
        first = main_of(client.get("/server", headers=YOU).text)
        assert "sincevisit" not in first                                        # first visit: nothing yet
        _set_last_seen("you", datetime.now(timezone.utc) - timedelta(hours=2))
        body = main_of(client.get("/server", headers=YOU).text)
        her = main_of(client.get("/server", headers=HER).text)
    p = body.split('<p class="metaline sincevisit">', 1)[1].split("</p>", 1)[0]
    assert p.startswith("Since your last visit 2h ago: ")
    assert body.index("sincevisit") < body.index('id="system"')
    assert "sincevisit" not in her                                              # her first visit


def test_no_identity_no_sentence_and_no_row(env, monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL_YOU", "you@example.test")
    with env() as client:
        client.get("/server")
        body = main_of(client.get("/server").text)
    assert "sincevisit" not in body
    with sqlite3.connect(media_db.db_path()) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rows = db.execute("SELECT COUNT(*) FROM server_last_visit").fetchone()[0] if "server_last_visit" in tables else 0
    assert rows == 0


def test_the_render_never_writes_the_visit(env, monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL_YOU", "you@example.test")
    with env() as client:
        client.get("/server", headers=YOU)                                     # the after-page task writes the row
        _set_last_seen("you", datetime.now(timezone.utc) - timedelta(hours=2))
        monkeypatch.setattr(sv, "touch", lambda *a, **k: None)
        body = main_of(client.get("/server", headers=YOU).text)
    assert "Since your last visit 2h ago" in body
    with sqlite3.connect(media_db.db_path()) as db:
        (since, last_seen), = db.execute("SELECT since, last_seen FROM server_last_visit").fetchall()
    assert since is None and abs(datetime.now(timezone.utc) - datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                                 - timedelta(hours=2)) < timedelta(minutes=1)


def test_the_sentence_reads_the_runner_history(env, monkeypatch, tmp_path):
    monkeypatch.setenv("OWNER_EMAIL_YOU", "you@example.test")
    with env() as client:
        client.get("/server", headers=YOU)
        _set_last_seen("you", datetime.now(timezone.utc) - timedelta(hours=2))
        write_history(tmp_path / "snaps", [(60, {"wud": ("error", "WUD failed (HTTP 500)")}), (30, {"wud": "ok"})])
        body = main_of(client.get("/server", headers=YOU).text)
    assert "wud failed once, then recovered" in body
