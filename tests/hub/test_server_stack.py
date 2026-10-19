"""Server → Restart + update media stack (2026-10-12): the hub routes against a faked stackctl (`requests.get` /
`requests.post` monkeypatched, nothing hits the network). The token must never reach a page, a redirect or a log."""
import importlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

from hub import server_stack
from tests.hub.helpers import write_envelope

SAMPLES = Path(__file__).resolve().parents[2] / "config" / "sample_snapshots"
URL, TOKEN = "http://stackctl.secret-host.invalid:8810", "stackSECRETtoken"
EVIL = {"origin": "https://evil.example"}


def main_of(html):
    return html.split("<main", 1)[1]


def txt(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html))


def band(html):
    return main_of(html).split('id="updates"', 1)[1].split('id="attention"', 1)[0]


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def _iso(minutes_ago):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("AREAS_PATH", raising=False)
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    for name in ("STACKCTL_URL", "STACKCTL_TOKEN", "WUD_URL", "WUD_USER", "WUD_PASS"):
        monkeypatch.delenv(name, raising=False)
    calls = []

    def fake(method):
        def call(url, **kw):
            calls.append({"method": method, "url": url, **kw})
            out = build.post if method == "POST" else build.status
            if isinstance(out, Exception):
                raise out
            return out
        return call
    monkeypatch.setattr(requests, "post", fake("POST"))
    monkeypatch.setattr(requests, "get", fake("GET"))

    def build(stack_env=True):
        if stack_env:
            monkeypatch.setenv("STACKCTL_URL", URL + "/")
            monkeypatch.setenv("STACKCTL_TOKEN", TOKEN)
        for p in SAMPLES.glob("*.json"):
            if not p.stem.startswith("_"):
                write_envelope(snaps, p.stem, age_minutes=1, data=json.loads(p.read_text(encoding="utf-8"))["data"])
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)
    build.post = Resp(202, {"started": True})
    build.status = Resp(200, {"running": False, "started_at": _iso(70), "finished_at": _iso(62), "exit_code": 0,
                              "log_tail": ["exit 0"]})
    build.calls = calls
    return build


def test_no_env_hides_the_button_and_the_line_and_calls_nothing(env):
    """WP-T3 (2026-10-19, S4): without STACKCTL_URL/TOKEN neither the button nor the "Media stack" line renders (was:
    the line said "Media stack · Not connected" on every visit)."""
    with env(stack_env=False) as client:
        b = band(client.get("/server").text)
        g = main_of(client.get("/server/stack/run?step=confirm").text)
        p = client.post("/server/stack/run", follow_redirects=False)
    assert "restart media stack" not in b and "Media stack" not in b
    assert "stackctl is not connected" in g and 'action="/server/stack/run"' not in g
    assert p.status_code == 303 and p.headers["location"] == "/server#updates"
    assert env.calls == []


def test_band_shows_the_button_and_the_last_run(env):
    with env() as client:
        r = client.get("/server")
    b = band(r.text)
    assert 'href="/server/stack/run?step=confirm">Update and restart media stack<' in b   # E3 (U27)
    assert "Media stack · Last run finished OK · 1h ago" in txt(b)
    assert env.calls == [{"method": "GET", "url": f"{URL}/status", "headers": {"Authorization": f"Bearer {TOKEN}"},
                          "timeout": 2}]
    assert TOKEN not in r.text and "secret-host" not in r.text


@pytest.mark.parametrize("status, words", [   # lambdas: the times are taken when the test runs, not at collection
    (lambda: Resp(200, {"running": True, "started_at": _iso(3), "finished_at": None, "exit_code": None}),
     "Updating now · started 3m ago"),
    (lambda: Resp(200, {"running": False, "started_at": None, "finished_at": None, "exit_code": None}), "No run yet"),
    (lambda: Resp(200, {"running": False, "started_at": _iso(70), "finished_at": _iso(65), "exit_code": 1}),
     "Last run failed (exit 1) · 1h ago"),
    (lambda: Resp(401, {"error": "unauthorized"}), "stackctl unreachable"),
    (lambda: requests.ConnectTimeout(f"{URL} {TOKEN}"), "stackctl unreachable"),
])
def test_status_words(env, caplog, status, words):
    env.status = status()
    with caplog.at_level(logging.WARNING), env() as client:
        r = client.get("/server")
    assert r.status_code == 200 and f"Media stack · {words}" in txt(band(r.text))
    assert TOKEN not in r.text + caplog.text and "secret-host" not in caplog.text


def test_confirm_page_explains_exactly_what_happens(env):
    with env() as client:
        r = client.get("/server/stack/run?step=confirm")
    body = txt(main_of(r.text))
    for line in server_stack.CONFIRM_LINES:
        assert line in body.replace("&#39;", "'").replace("&amp;", "&")
    assert "except WUD and stackctl" in body and "Jellyfin" in body and "WILL update" in body
    assert "v3.5.0" in body and "Joey itself is not touched" in body and "drop for a few minutes" in body
    assert 'method="post" action="/server/stack/run"' in r.text
    assert all(c["method"] == "GET" for c in env.calls) and TOKEN not in r.text


def test_confirm_while_running_offers_no_button(env):
    env.status = Resp(200, {"running": True, "started_at": _iso(1), "finished_at": None, "exit_code": None})
    with env() as client:
        g = main_of(client.get("/server/stack/run?step=confirm").text)
    assert "already running" in g and 'action="/server/stack/run"' not in g


@pytest.mark.parametrize("post, flag, words", [
    (Resp(202), "started", "Media stack update started"),
    (Resp(409), "busy", "A media stack update is already running"),
    (Resp(401), "refused", "stackctl refused the request"),
    (requests.ConnectionError(f"host=stackctl.secret-host.invalid {TOKEN}"), "unreachable", "stackctl unreachable"),
])
def test_post_calls_stackctl_with_the_bearer_token_and_flashes(env, caplog, post, flag, words):
    env.post = post
    with caplog.at_level(logging.WARNING), env() as client:
        r = client.post("/server/stack/run", follow_redirects=False)
        page = client.get(r.headers["location"]).text
    assert r.status_code == 303 and r.headers["location"] == f"/server?stack={flag}#updates"
    posts = [c for c in env.calls if c["method"] == "POST"]
    assert posts == [{"method": "POST", "url": f"{URL}/media/pull-up",
                      "headers": {"Authorization": f"Bearer {TOKEN}"}, "timeout": 10}]
    assert words in band(page)
    assert TOKEN not in page + caplog.text + r.headers["location"]


def test_post_without_same_origin_is_refused(env):
    with env() as client:
        r = client.post("/server/stack/run", headers=EVIL, follow_redirects=False)
    assert r.status_code == 403 and not [c for c in env.calls if c["method"] == "POST"]


def test_junk_stack_flash_is_ignored(env):
    with env() as client:
        b = band(client.get("/server?stack=<script>").text)
    assert "<script>" not in b and 'role="status"' not in b
