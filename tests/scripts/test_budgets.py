"""JY-013: scripts/budgets.py - p95 maths, parsers, verdicts, exit codes, report size, and the page payload run
against a loopback fake hub (127.0.0.1, port 0). No network, no ssh."""
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import budgets  # noqa: E402

FREE_M = """              total        used        free      shared  buff/cache   available
Mem:           3896        1900         300          12        1696        1650
Swap:          4095         800        3295
"""
HISTORY_PASS = ("2026-10-23T01:02:03Z PASS prev=abc1234 new=def5678 suite green, smoke ok tv=current "
                "end=2026-10-23T01:09:03Z dur=420s")


# ---------------------------------------------------------------- fake hub

class FakeHub:
    """Loopback hub: /, /a/<id>, media lists with item links, item pages, Discover. Records every request."""

    def __init__(self, slow: dict | None = None, broken: tuple = ()):
        self.hits: list[tuple[str, str]] = []
        self.slow = slow or {}
        self.broken = broken
        hub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _any(self):
                hub.hits.append((self.command, self.path))
                if self.command != "GET":
                    self.send_response(405)
                    self.end_headers()
                    return
                if self.path in hub.slow:
                    time.sleep(hub.slow[self.path])
                if self.path in hub.broken:
                    self.send_response(500)
                    self.end_headers()
                    return
                if self.path == "/media/movies":
                    body = "".join(f'<a href="/media/item/m{i}">m</a>' for i in range(5))
                elif self.path == "/media/tv":
                    body = "".join(f'<a href="/media/item/t{i}">t</a>' for i in range(5))
                elif self.path == "/" or self.path.startswith(("/a/", "/media/item/", "/media/discover")):
                    body = "<main>ok</main>"
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = body.encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_DELETE = _any

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def area_ids():
    return budgets.read_area_ids((REPO_ROOT / "config" / "areas.yaml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- maths and parsers

def test_p95_nearest_rank():
    assert budgets.p95(list(range(1, 21))) == 19          # ceil(0.95 * 20) = 19th smallest
    assert budgets.p95(list(range(100, 0, -1))) == 95     # unsorted input
    assert budgets.p95([7.5]) == 7.5
    assert budgets.p95([1, 2, 3]) == 3                    # ceil(2.85) = 3
    with pytest.raises(ValueError):
        budgets.p95([])


def test_parse_docker_stats():
    assert budgets.parse_docker_mem("123.4MiB / 384MiB") == pytest.approx(123.4)
    assert budgets.parse_docker_mem("1.5GiB / 2GiB\n") == pytest.approx(1536.0)
    assert budgets.parse_docker_mem("512KiB / 384MiB") == pytest.approx(0.5)
    with pytest.raises(ValueError):
        budgets.parse_docker_mem("--")


def test_parse_free_m():
    assert budgets.parse_free_available(FREE_M) == 1650
    with pytest.raises(ValueError):
        budgets.parse_free_available("             total       used       free     shared    buffers\nMem: 1 2 3 4 5\n")


def test_parse_history_line():
    assert budgets.parse_history_duration(HISTORY_PASS) == 420
    assert budgets.parse_history_duration("2026-10-01T00:00:00Z PASS prev=a new=b suite green") is None
    assert budgets.gate_row(HISTORY_PASS)["verdict"] == "PASS"
    assert budgets.gate_row(HISTORY_PASS.replace("dur=420s", "dur=700s"))["verdict"] == "FAIL"
    assert budgets.gate_row("2026-10-01T00:00:00Z PASS prev=a new=b")["value"] == "not recorded"
    assert budgets.gate_row("2026-10-01T00:00:00Z PASS prev=a new=b")["verdict"] == "INFO"
    assert budgets.gate_row(None)["verdict"] == "INFO"


def test_area_ids_from_yaml_skip_hidden_and_tiles():
    text = ("gated_hrefs: {}\nareas:\n  - id: one\n    hidden: true\n    tiles:\n      - id: tile-a\n"
            "        hidden: true\n  - id: two\n    tiles:\n      - id: tile-b\n  - id: three\nother: 1\n"
            "  - id: not-an-area\n")
    assert budgets.read_area_ids(text) == ["two", "three"]
    assert area_ids()  # the real config parses to at least one visible area


# ---------------------------------------------------------------- verdicts and exit codes (criterion 7)

def _rows(*verdicts):
    return [{"name": f"r{i}", "value": "x", "budget": "y", "verdict": v} for i, v in enumerate(verdicts)]


def test_exit_codes():
    assert budgets.exit_code(_rows("PASS", "PASS", "INFO", "SKIP")) == 0
    assert budgets.exit_code(_rows("PASS", "FAIL", "INFO")) == 1
    assert budgets.exit_code(_rows("PASS", "ERROR")) == 2
    assert budgets.exit_code(_rows("FAIL", "ERROR")) == 2


def test_row_verdicts_at_the_limits():
    assert budgets.page_row("h", [{"path": "/", "ms": [50.0] * 20}], 50)["verdict"] == "PASS"
    assert budgets.page_row("h", [{"path": "/", "ms": [10.0] * 18 + [51.0] * 2}], 50)["verdict"] == "FAIL"
    assert budgets.page_row("h", [{"path": "/", "ms": [10.0] * 19 + [999.0]}], 50)["verdict"] == "PASS"
    assert budgets.mem_row(200.0)["verdict"] == "PASS" and budgets.mem_row(200.1)["verdict"] == "FAIL"
    assert budgets.avail_row(1300, 1200)["verdict"] == "PASS"
    low = budgets.avail_row(1300, 1199)
    assert low["verdict"] == "FAIL" and low["value"].startswith("1,199 MB")
    cold, warm = budgets.discover_rows({"cold_ms": 3100, "warm_ms": 200, "error": ""})
    assert (cold["verdict"], warm["verdict"]) == ("FAIL", "PASS")


class FakeNas:
    """Stands in for ssh: answers each read-only NAS command; the page payload really runs from stdin."""

    def __init__(self, hub_url="", inspect=(0, "true\n"), mem="123.4MiB / 384MiB\n", free=FREE_M,
                 history=HISTORY_PASS + "\n", refuse=False):
        self.hub_url, self.inspect, self.mem, self.free, self.history = hub_url, inspect, mem, free, history
        self.refuse = refuse
        self.commands: list[str] = []

    def __call__(self, cmd, stdin=None, timeout=60.0):
        self.commands.append(cmd)
        if self.refuse:
            raise budgets.NasError("ssh failed: Permission denied (publickey).")
        if cmd.startswith("docker inspect"):
            return self.inspect[0], self.inspect[1], "Error: No such object" if self.inspect[0] else ""
        if cmd == "free -m":
            return 0, self.free, ""
        if cmd.startswith("docker stats"):
            return 0, self.mem, ""
        if cmd.startswith("grep "):
            return 0, self.history, ""
        if cmd.startswith("docker exec -i joey-hub python - "):
            args = cmd.split()[6:] + ["--base", self.hub_url]
            proc = subprocess.run([sys.executable, "-", *args], input=stdin, capture_output=True, timeout=120)
            return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")
        raise AssertionError(f"unexpected NAS command: {cmd}")


def test_nas_run_all_pass_exit_0_and_read_only(capsys):
    with FakeHub() as hub:
        nas = FakeNas(hub.url)
        code = budgets.main(["-n", "2"], runner=nas)
    out = capsys.readouterr().out
    assert code == 0, out
    assert out.count("PASS") >= 7 and "123.4 MiB" in out and "1,650 MB" in out and "7.0 min" in out
    assert {m for m, _ in hub.hits} == {"GET"}
    allowed = ("docker inspect ", "docker exec -i joey-hub python - ", "docker stats --no-stream ", "free -m",
               "grep -E ")
    assert all(c.startswith(allowed) for c in nas.commands), nas.commands
    assert all(">" not in c and " rm " not in c for c in nas.commands)
    assert nas.commands.count("free -m") == 2
    assert len(nas.commands) == 6   # one login per check


def test_nas_over_budget_exit_1(capsys):
    with FakeHub() as hub:
        code = budgets.main(["-n", "2"], runner=FakeNas(hub.url, mem="250MiB / 384MiB"))
    out = capsys.readouterr().out
    assert code == 1
    assert "joey-hub memory" in out and "FAIL" in out


def test_ssh_refused_exit_2_reason_printed_no_login(capsys, monkeypatch):
    class Proc:
        returncode, stdout, stderr = 255, b"", b"root@nas.local: Permission denied (publickey).\n"
    monkeypatch.setattr(budgets.subprocess, "run", lambda *a, **k: Proc())
    code = budgets.main(["-n", "2"], runner=budgets.ssh_runner("root@nas.local", ""))
    out = capsys.readouterr().out
    assert code == 2
    assert "Permission denied" in out and "ERROR" in out
    assert "root" not in out and "nas.local" not in out and "@" not in out
    assert len(out.splitlines()) <= budgets.MAX_LINES


def test_container_missing_exit_2(capsys):
    nas = FakeNas(inspect=(1, ""))
    code = budgets.main(["-n", "2", "--json"], runner=nas)
    report = json.loads(capsys.readouterr().out)
    assert code == 2 and report["exit"] == 2
    assert all(r["verdict"] == "ERROR" for r in report["rows"])
    assert "joey-hub missing" in report["rows"][0]["value"]
    assert nas.commands == [nas.commands[0]]   # nothing else runs once the container is gone


def test_history_without_duration_is_info_not_fail(capsys):
    with FakeHub() as hub:
        code = budgets.main(["-n", "1"], runner=FakeNas(hub.url, history="2026-10-01T00:00:00Z PASS prev=a new=b\n"))
    out = capsys.readouterr().out
    assert code == 0
    assert "not recorded" in out and "INFO" in out


# ---------------------------------------------------------------- --local and the payload (criteria 2, 6, 9)

def test_local_run_times_every_page_with_warmup(capsys):
    areas = area_ids()
    with FakeHub() as hub:
        code = budgets.main(["--local", hub.url, "-n", "3"])
    out = capsys.readouterr().out
    assert code == 0, out
    lines = out.splitlines()
    assert len(lines) == 8 and len(lines) <= budgets.MAX_LINES
    assert sum(ln.endswith("SKIP") for ln in lines) == 3
    paths = [p for _, p in hub.hits]
    for p in ["/", *(f"/a/{a}" for a in areas), "/media/movies", "/media/tv"]:
        assert paths.count(p) == 4, p                       # 1 warm-up + n timed
    items = sorted({p for p in paths if p.startswith("/media/item/")})
    assert items == ["/media/item/m0", "/media/item/m1", "/media/item/t0", "/media/item/t1"]  # alternate, max 4
    assert all(paths.count(p) == 4 for p in items)
    assert paths.count("/media/discover") == 2              # one cold, one warm
    assert {m for m, _ in hub.hits} == {"GET"}


def test_local_slow_hub_page_fails(capsys):
    with FakeHub(slow={"/": 0.08}) as hub:
        code = budgets.main(["--local", hub.url, "-n", "2", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert code == 1
    hub_row = report["rows"][0]
    assert hub_row["verdict"] == "FAIL" and "(/)" in hub_row["value"]


def test_local_broken_page_is_error(capsys):
    with FakeHub(broken=("/media/tv",)) as hub:
        code = budgets.main(["--local", hub.url, "-n", "1"])
    out = capsys.readouterr().out
    assert code == 2
    assert "/media/tv: HTTP 500" in out


def test_report_never_exceeds_20_lines():
    many = _rows(*(["FAIL"] * 40))
    text = budgets.render(many, 20, "NAS")
    assert len(text.splitlines()) == budgets.MAX_LINES
    assert text.splitlines()[-1].startswith("Summary")
