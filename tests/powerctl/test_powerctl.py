"""powerctl (JY-274, 2026-11-05): Bearer auth, the one-pending rule, the stop-then-shutdown order and the 60 s cap,
with the commands faked or the dry-run default (no docker, no shutdown, no network beyond 127.0.0.1)."""
import json
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from powerctl import powerctl

TOKEN = "p0wer-token-for-tests"


class Ran:
    def __init__(self, code=0, stop_raises=None):
        self.calls, self.code, self.stop_raises = [], code, stop_raises

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw.get("timeout")))
        if argv[0] == "stop" and self.stop_raises:
            raise self.stop_raises
        return subprocess.CompletedProcess(argv, 0 if argv[0] == "stop" else self.code)


@pytest.mark.parametrize("header, ok", [(f"Bearer {TOKEN}", True), (f"bearer {TOKEN}", True),
                                        (f"Bearer {TOKEN}x", False), (f"Basic {TOKEN}", False), (TOKEN, False),
                                        ("", False), (None, False)])
def test_authorized(header, ok):
    assert powerctl.authorized(header, TOKEN) is ok
    assert not powerctl.authorized("Bearer ", "")


def test_stop_then_shutdown_with_the_cap():
    ran = Ran()
    job = powerctl.Job(["stop", "media"], ["halt-host"], grace_s=0, runner=ran)
    assert job.start() and not job.start()       # second request while pending
    assert job.done.wait(5)
    assert ran.calls == [(["stop", "media"], 60), (["halt-host"], 30)]
    st = job.status()
    assert st["pending"] is True and st["stage"] == "shutdown sent" and st["exit_code"] == 0
    assert not job.start()                        # still pending: the host is going away


def test_a_stuck_stop_still_shuts_down():
    ran = Ran(stop_raises=subprocess.TimeoutExpired("stop", 60))
    job = powerctl.Job(["stop"], ["halt-host"], grace_s=0, runner=ran)
    job.start()
    assert job.done.wait(5)
    assert [c[0] for c in ran.calls] == [["stop"], ["halt-host"]]
    assert any("shutting down anyway" in x for x in job.status()["log_tail"])


def test_a_failed_shutdown_clears_pending():
    job = powerctl.Job(["stop"], ["halt-host"], grace_s=0, runner=Ran(code=1))
    job.start()
    assert job.done.wait(5)
    assert job.status()["pending"] is False and job.status()["stage"] == "failed"


def test_empty_shutdown_is_a_dry_run():
    ran = Ran()
    job = powerctl.Job(["stop"], [], grace_s=0, runner=ran)
    job.start()
    assert job.done.wait(5)
    assert ran.calls == [(["stop"], 60)]
    assert any("dry run" in x for x in job.status()["log_tail"])


def test_dockerfile_carries_the_real_command_the_code_default_is_dry():
    from pathlib import Path
    df = (Path(powerctl.__file__).parent / "Dockerfile").read_text(encoding="utf-8")
    assert 'SHUTDOWN_CMD="nsenter -t 1 -m -u -i -n -p -- poweroff"' in df
    assert "SHUTDOWN_CMD\", \"\"" in Path(powerctl.__file__).read_text(encoding="utf-8")


@pytest.fixture()
def served():
    ran = Ran()
    job = powerctl.Job(["stop"], [], grace_s=0, runner=ran)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), powerctl.make_handler(job, TOKEN))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(method, path, token=TOKEN):
        req = urllib.request.Request(base + path, method=method, data=b"" if method == "POST" else None)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    call.job = job
    yield call
    srv.shutdown()


def test_http_power_down_202_then_409_and_status(served):
    assert served("POST", "/power-down", token=None)[0] == 401
    assert served("POST", "/power-down", token="wrong")[0] == 401
    assert served("POST", "/power-down") == (202, {"pending": True})
    assert served("POST", "/power-down") == (409, {"error": "pending"})
    assert served.job.done.wait(5)
    code, body = served("GET", "/status")
    assert code == 200 and body["pending"] is True and TOKEN not in json.dumps(body)
    assert served("GET", "/nope")[0] == 404
