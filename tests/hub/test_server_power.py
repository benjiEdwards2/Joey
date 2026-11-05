"""JY-274 (2026-11-05): Server -> Power down NAS, against an in-process fake powerctl (`requests.post` monkeypatched;
nothing reaches the network, the NAS or a real helper). The token never reaches a page, power.log or a log line."""
import importlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

from hub import server_power
from hub.identity import IDENTITY_HEADER
from tests.hub.helpers import write_envelope

SAMPLES = Path(__file__).resolve().parents[2] / "config" / "sample_snapshots"
URL, TOKEN = "http://powerctl.secret-host.invalid:8811", "powerSECRETtoken"
YOU, HER = {IDENTITY_HEADER: "you@example.invalid"}, {IDENTITY_HEADER: "her@example.invalid"}
EVIL = {"origin": "https://evil.example"}
DAY = datetime(2026, 11, 5, 12, 0)
NIGHT = datetime(2026, 11, 5, 21, 45)


def main_of(html):
    return html.split("<main", 1)[1]


def txt(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html))


class Resp:
    def __init__(self, status=202, body=None):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("AREAS_PATH", raising=False)
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "sqlite" / "media.db"))
    monkeypatch.setenv("OWNER_EMAIL_YOU", "you@example.invalid")
    monkeypatch.setenv("OWNER_NAME_YOU", "Benji")
    for name in ("POWER_URL", "POWER_TOKEN", "STACKCTL_URL", "STACKCTL_TOKEN", "WUD_URL", "WUD_USER", "WUD_PASS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(server_power, "local_now", lambda: build.now)
    calls = []

    def fake_post(url, **kw):   # the fake powerctl: records every call, answers build.answer
        calls.append({"url": url, **kw})
        if isinstance(build.answer, Exception):
            raise build.answer
        return build.answer
    monkeypatch.setattr(requests, "post", fake_post)

    def build(power_env=True):
        if power_env:
            monkeypatch.setenv("POWER_URL", URL + "/")
            monkeypatch.setenv("POWER_TOKEN", TOKEN)
        for p in SAMPLES.glob("*.json"):
            if not p.stem.startswith("_"):
                write_envelope(snaps, p.stem, age_minutes=1, data=json.loads(p.read_text(encoding="utf-8"))["data"])
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)
    build.answer = Resp(202, {"pending": True})
    build.now = DAY
    build.calls = calls
    build.log = tmp_path / "sqlite" / "power.log"
    return build


def lines(env):
    return [json.loads(x) for x in env.log.read_text(encoding="utf-8").splitlines()] if env.log.exists() else []


def press(client, text="POWER DOWN", headers=YOU, **kw):
    return client.post("/server/power", data={"confirm": text}, headers=headers, **kw)


def test_owner_sees_the_pill_and_none_yet(env):
    with env() as client:
        r = client.get("/server", headers=YOU)
    head = r.text.split('class="pagehead"', 1)[1].split("</header>", 1)[0]
    assert 'href="/server/power"' in head and "Power down" in head
    assert "Last shutdown: none yet" in txt(head)
    assert TOKEN not in r.text and "secret-host" not in r.text and env.calls == []


def test_her_view_has_no_pill_and_gets_403(env):
    with env() as client:
        page = client.get("/server", headers=HER).text
        g = client.get("/server/power", headers=HER)
        p = press(client, headers=HER)
    assert 'href="/server/power"' not in page and "Last shutdown: none yet" in txt(page)
    assert g.status_code == 403 and p.status_code == 403
    assert env.calls == [] and lines(env) == []


def test_media_front_never_serves_the_route(env, monkeypatch):
    """Friends sign in on the media front: the route is PRIVATE (the GuestGate 404s it) and the handler refuses too."""
    from hub import guest
    assert ("GET", "/server/power") in guest.PRIVATE and ("POST", "/server/power") in guest.PRIVATE
    with env() as client:
        monkeypatch.setattr(guest, "is_media", lambda: True)
        assert server_power.can_press(type("R", (), {"headers": {}, "cookies": {}, "query_params": {},
                                                     "state": None, "scope": {}})()) is False


def test_unset_hides_the_pill_and_the_form(env):
    with env(power_env=False) as client:
        page = client.get("/server", headers=YOU).text
        g = main_of(client.get("/server/power", headers=YOU).text)
        p = main_of(press(client).text)
    assert 'href="/server/power"' not in page
    assert "powerctl is not connected" in g and 'action="/server/power"' not in g
    assert "The NAS is untouched" in p and env.calls == []
    assert [x["outcome"] for x in lines(env)] == ["off"]


def test_get_is_the_confirm_page_only(env):
    with env() as client:
        r = client.get("/server/power", headers=YOU)
    m = main_of(r.text)
    assert r.status_code == 200 and env.calls == [] and lines(env) == []
    assert 'action="/server/power"' in m and 'name="confirm"' in m and "Type POWER DOWN to confirm" in m
    assert "07:00 on the ADM power schedule" in m and "power button on the NAS" in m
    assert "friends watching now will be cut off" not in m   # 12:00: no warning
    assert TOKEN not in r.text and "secret-host" not in r.text


@pytest.mark.parametrize("now, warned", [(NIGHT, True), (datetime(2026, 11, 5, 6, 59), True),
                                         (datetime(2026, 11, 5, 7, 0), False), (datetime(2026, 11, 5, 21, 29), False)])
def test_late_warning(env, now, warned):
    env.now = now
    with env() as client:
        m = main_of(client.get("/server/power", headers=YOU).text)
    assert ("friends watching now will be cut off until 07:00" in m) is warned


@pytest.mark.parametrize("text", ["", "power down", "POWER", "POWERDOWN"])
def test_wrong_text_does_nothing(env, text):
    with env() as client:
        m = main_of(press(client, text).text)
    assert "Type POWER DOWN exactly" in m and env.calls == []
    assert [x["outcome"] for x in lines(env)] == ["wrong_text"]


def test_other_origin_does_nothing(env):
    with env() as client:
        r = press(client, headers={**YOU, **EVIL})
    assert r.status_code == 403 and env.calls == [] and lines(env) == []


def test_valid_press_calls_the_helper_once_and_logs(env, caplog):
    with caplog.at_level(logging.DEBUG), env() as client:
        r = press(client)
        page = client.get("/server", headers=YOU).text
    m = main_of(r.text)
    assert "Shutting down in 60 s" in m and 'action="/server/power"' not in m
    assert env.calls == [{"url": f"{URL}/power-down", "headers": {"Authorization": f"Bearer {TOKEN}"}, "timeout": 2}]
    rows = lines(env)
    assert [(x["outcome"], x["who"]) for x in rows] == [("started", "Benji")]
    assert "Last shutdown: just now by Benji" in txt(page)
    for blob in (r.text, page, env.log.read_text(encoding="utf-8"), caplog.text):
        assert TOKEN not in blob and "secret-host" not in blob


def test_second_press_while_pending(env):
    with env() as client:
        press(client)
        env.answer = Resp(409, {"error": "pending"})
        m = main_of(press(client).text)
    assert "already pending" in m and len(env.calls) == 2
    assert [x["outcome"] for x in lines(env)] == ["started", "pending"]


@pytest.mark.parametrize("answer, words", [
    (lambda: requests.ConnectTimeout(f"{URL} {TOKEN}"), "powerctl unreachable"),
    (lambda: Resp(401, {"error": "unauthorized"}), "powerctl refused"),
    (lambda: Resp(500), "powerctl refused"),
])
def test_helper_failure_is_an_error_and_untouched(env, caplog, answer, words):
    env.answer = answer()
    with caplog.at_level(logging.WARNING), env() as client:
        r = press(client)
        page = client.get("/server", headers=YOU).text
    m = main_of(r.text)
    assert words in m and "The NAS is untouched" in m and "Shutting down" not in m
    assert "Last shutdown: none yet" in txt(page)
    assert TOKEN not in caplog.text and "secret-host" not in caplog.text and TOKEN not in r.text


def test_last_shutdown_reads_the_newest_started_line(env, tmp_path):
    env.log.parent.mkdir(parents=True, exist_ok=True)
    old = (datetime.now(timezone.utc) - timedelta(hours=26)).isoformat(timespec="seconds")
    new = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(timespec="seconds")
    env.log.write_text("\n".join([json.dumps({"at": old, "who": "Benji", "outcome": "started"}),
                                  "not json",
                                  json.dumps({"at": new, "who": "B.", "outcome": "started"}),
                                  json.dumps({"at": new, "who": "B.", "outcome": "unreachable"})]) + "\n",
                       encoding="utf-8")
    with env() as client:
        assert "Last shutdown: 3h ago by B." in txt(client.get("/server", headers=YOU).text)


def test_token_is_in_no_template_or_source():
    root = Path(__file__).resolve().parents[2]
    for p in [*(root / "hub" / "templates").glob("*.html"), root / "hub" / "server_power.py"]:
        assert TOKEN not in p.read_text(encoding="utf-8")
    assert "POWER_TOKEN" not in (root / "hub" / "templates" / "server_power.html").read_text(encoding="utf-8")
