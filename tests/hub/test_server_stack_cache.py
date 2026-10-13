"""E1 (2026-10-13): the Server page's stackctl status line is read at most once per 30 s — an unreachable answer as
well as a good one — with its ages still worked out per request, and a Restart + update request drops the kept
answer. stackctl is the test_server_stack fake (requests monkeypatched); no network."""
import logging
from datetime import datetime, timedelta, timezone

import requests

from hub import server_stack
from tests.hub.test_server_stack import TOKEN, Resp, _iso, band, env, txt  # noqa: F401  (env fixture)


def gets(env):
    return [c for c in env.calls if c["method"] == "GET" and c["url"].endswith("/status")]


def later(monkeypatch, seconds):
    real = server_stack.time.monotonic
    monkeypatch.setattr(server_stack.time, "monotonic", lambda: real() + seconds)


def test_the_status_is_read_once_per_thirty_seconds(env, monkeypatch):
    with env() as client:
        first = band(client.get("/server").text)
        second = band(client.get("/server").text)
        assert len(gets(env)) == 1
        later(monkeypatch, server_stack.STATUS_TTL_S + 1)
        client.get("/server")
    assert len(gets(env)) == 2 and server_stack.STATUS_TTL_S == 30
    assert "Media stack · Last run finished OK · 1h ago" in txt(first) and txt(first) == txt(second)


def test_an_unreachable_stackctl_is_kept_too_with_the_same_words(env, caplog):
    env.status = requests.ConnectionError(f"{env.__name__} {TOKEN}")
    with caplog.at_level(logging.WARNING, logger="hub.server_stack"), env() as client:
        a = band(client.get("/server").text)
        b = band(client.get("/server").text)
    assert len(gets(env)) == 1
    assert "Media stack · stackctl unreachable" in txt(a) and "Media stack · stackctl unreachable" in txt(b)
    assert caplog.text.count("stackctl status failed: ConnectionError") == 1 and TOKEN not in caplog.text


def test_ages_are_worked_out_per_request_from_the_kept_answer(env):
    env()
    now = datetime.now(timezone.utc)
    assert server_stack.status(now)["text"] == "Last run finished OK · 1h ago"
    assert server_stack.status(now + timedelta(hours=2))["text"] == "Last run finished OK · 3h ago"
    assert len(gets(env)) == 1


def test_a_restart_request_drops_the_kept_answer(env):
    with env() as client:
        client.get("/server")
        env.status = Resp(200, {"running": True, "started_at": _iso(0), "finished_at": None, "exit_code": None})
        client.post("/server/stack/run", follow_redirects=False)
        after = band(client.get("/server").text)
    assert len(gets(env)) == 2 and "Media stack · Updating now" in txt(after)


def test_new_credentials_are_read_afresh(env, monkeypatch):
    env()
    server_stack.status()
    monkeypatch.setenv("STACKCTL_URL", "http://other.invalid:8810")
    server_stack.status()
    assert len(gets(env)) == 2
