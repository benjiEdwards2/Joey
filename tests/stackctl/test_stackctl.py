"""stackctl (2026-10-12): the pure parts — Bearer auth and the service filter — plus the HTTP layer and the
one-job rule with the docker calls faked (no docker, no network beyond 127.0.0.1)."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from stackctl import stackctl

TOKEN = "s3cret-token-for-tests"


@pytest.mark.parametrize("header, ok", [
    (f"Bearer {TOKEN}", True),
    (f"bearer {TOKEN}", True),                 # the scheme is case-insensitive
    (f"Bearer {TOKEN}x", False),
    (f"Bearer {TOKEN[:-1]}", False),
    (f"Basic {TOKEN}", False),
    (TOKEN, False),
    ("Bearer ", False),
    ("", False),
    (None, False),
])
def test_authorized_needs_the_exact_bearer_token(header, ok):
    assert stackctl.authorized(header, TOKEN) is ok


def test_an_empty_token_never_authorizes():
    assert not stackctl.authorized("Bearer ", "") and not stackctl.authorized("Bearer x", "")


def test_services_to_update_drops_excluded_blanks_and_repeats_in_order():
    out = "gluetun\nqbittorrent\n\nwud\njellyfin\r\nstackctl\nseerr\njellyfin\n"
    assert stackctl.services_to_update(out, "wud stackctl") == ["gluetun", "qbittorrent", "jellyfin", "seerr"]
    assert stackctl.services_to_update(out, "") == ["gluetun", "qbittorrent", "wud", "jellyfin", "stackctl", "seerr"]
    assert stackctl.services_to_update("", "wud") == []


def test_mask_hides_the_token():
    assert stackctl.mask(f"pull failed for {TOKEN}", TOKEN) == "pull failed for ***"


@pytest.fixture()
def server(monkeypatch):
    """A live stackctl on 127.0.0.1 with `Job._cmd` faked: records the compose argv, a gate holds the job open."""
    calls, gate = [], threading.Event()

    def cmd(self, *args, capture=False):
        calls.append(args)
        if capture:
            return 0, "gluetun\nwud\njellyfin\nstackctl\n"
        gate.wait(5)
        self._say(f"pulled with {TOKEN}")
        return 0, ""
    monkeypatch.setattr(stackctl.Job, "_cmd", cmd)
    job = stackctl.Job("/volume1/media-server/docker-compose.yml", "wud stackctl", TOKEN)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), stackctl.make_handler(job, TOKEN))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def call(method, path, token=TOKEN):
        req = urllib.request.Request(f"http://127.0.0.1:{httpd.server_port}{path}", method=method,
                                     headers={"Authorization": f"Bearer {token}"} if token else {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    call.calls, call.gate, call.job = calls, gate, job
    yield call
    gate.set()
    httpd.shutdown()


def test_every_endpoint_needs_the_token(server):
    assert server("GET", "/status", token=None)[0] == 401
    assert server("POST", "/media/pull-up", token="wrong")[0] == 401
    assert server("GET", "/nope")[0] == 404
    assert server.calls == []


def test_pull_up_runs_once_at_a_time_and_status_reports_it(server):
    assert server("POST", "/media/pull-up") == (202, {"started": True})
    assert server("POST", "/media/pull-up") == (409, {"error": "running"})
    code, st = server("GET", "/status")
    assert code == 200 and st["running"] is True and st["started_at"] and st["finished_at"] is None
    server.gate.set()
    for _ in range(100):
        st = server("GET", "/status")[1]
        if not st["running"]:
            break
        threading.Event().wait(0.05)
    assert st["running"] is False and st["exit_code"] == 0 and st["finished_at"]
    assert server.calls == [("config", "--services"), ("pull", "gluetun", "jellyfin"),
                            ("up", "-d", "--no-deps", "gluetun", "jellyfin")]
    blob = json.dumps(st)
    assert TOKEN not in blob and "pulled with ***" in blob and st["log_tail"][-1] == "exit 0"
    assert len(st["log_tail"]) <= stackctl.LOG_LINES


def test_main_refuses_to_start_without_a_token(monkeypatch, capsys):
    monkeypatch.delenv("STACKCTL_TOKEN", raising=False)
    assert stackctl.main() == 2 and "refusing to start" in capsys.readouterr().err
