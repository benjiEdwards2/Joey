"""stackctl (2026-10-12): the one thing WUD can't do — pull + recreate the whole media-server stack on request.

A tiny stdlib-only HTTP service that runs beside the media stack on the NAS (stackctl/NAS_INSTALL.md) with the
Docker socket and the media-server compose folder mounted. Joey's hub calls it server-side only
(hub/server_stack.py); the browser never sees the token.

  POST /media/pull-up  -> 202 job started | 409 a job is already running
                          job: `docker compose config --services`, drop EXCLUDE, `pull <svcs>`, `up -d --no-deps <svcs>`
  GET  /status         -> {running, started_at, finished_at, exit_code, log_tail}  (last 50 output lines)

Every endpoint needs `Authorization: Bearer <STACKCTL_TOKEN>` (constant-time compare). The token is never logged;
any output line that somehow contains it is masked. Env: STACKCTL_TOKEN (required — no token, no start),
COMPOSE_FILE (default /volume1/media-server/docker-compose.yml — mounted at the SAME path as on the host so relative
bind paths, `.env` and the compose project name all resolve exactly as when B. runs compose there), EXCLUDE
(compose SERVICE names, default "wud stackctl"), PORT (default 8810).
"""

from __future__ import annotations

import hmac
import json
import os
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG_LINES = 50
DEFAULT_COMPOSE_FILE = "/volume1/media-server/docker-compose.yml"
DEFAULT_EXCLUDE = "wud stackctl"
DEFAULT_PORT = 8810


# ---- pure (unit-tested, no docker) ----

def authorized(header: str | None, token: str) -> bool:
    """True only for `Bearer <token>` with the exact token (constant-time compare); an empty token never matches."""
    if not token or not header:
        return False
    scheme, _, given = header.strip().partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(given.strip().encode(), token.encode())


def services_to_update(config_services: str, exclude: str) -> list[str]:
    """`docker compose config --services` output -> the services to pull + recreate: EXCLUDE dropped, order kept,
    no blanks or repeats."""
    skip = set(exclude.split())
    out: list[str] = []
    for line in config_services.splitlines():
        name = line.strip()
        if name and name not in skip and name not in out:
            out.append(name)
    return out


def mask(line: str, token: str) -> str:
    return line.replace(token, "***") if token else line


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---- the one job ----

class Job:
    """At most one pull-up at a time; its state is what GET /status returns."""

    def __init__(self, compose_file: str, exclude: str, token: str):
        self.compose_file, self.exclude, self.token = compose_file, exclude, token
        self.lock = threading.Lock()
        self.running = False
        self.started_at = self.finished_at = None
        self.exit_code: int | None = None
        self.log: deque[str] = deque(maxlen=LOG_LINES)

    def status(self) -> dict:
        with self.lock:
            return {"running": self.running, "started_at": self.started_at, "finished_at": self.finished_at,
                    "exit_code": self.exit_code, "log_tail": list(self.log)}

    def start(self) -> bool:
        """False when a job is already running; else starts one in the background."""
        with self.lock:
            if self.running:
                return False
            self.running, self.started_at, self.finished_at, self.exit_code = True, _now(), None, None
            self.log.clear()
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def _say(self, line: str) -> None:
        with self.lock:
            self.log.append(mask(line.rstrip(), self.token))

    def _cmd(self, *args: str, capture: bool = False) -> tuple[int, str]:
        """Run `docker compose -f FILE <args>`; output lines go to the log (unless `capture`, which returns stdout)."""
        argv = ["docker", "compose", "-f", self.compose_file, *args]
        self._say("$ " + " ".join(argv[1:]))
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT if not capture else subprocess.PIPE,
                                text=True, errors="replace")
        if capture:
            out, err = proc.communicate()
            for line in (err or "").splitlines():
                self._say(line)
            return proc.returncode, out or ""
        for line in proc.stdout:
            self._say(line)
        return proc.wait(), ""

    def _run(self) -> None:
        code = 1
        try:
            code, out = self._cmd("config", "--services", capture=True)
            svcs = services_to_update(out, self.exclude) if code == 0 else []
            if code == 0 and not svcs:
                self._say("no services left after EXCLUDE")
                code = 1
            if code == 0:
                self._say("services: " + " ".join(svcs))
                code, _ = self._cmd("pull", *svcs)
            if code == 0:
                code, _ = self._cmd("up", "-d", "--no-deps", *svcs)
        except Exception as exc:  # e.g. docker missing: the type only
            self._say(f"failed: {type(exc).__name__}")
            code = 1
        with self.lock:
            self.running, self.finished_at, self.exit_code = False, _now(), code
            self.log.append(f"exit {code}")


# ---- HTTP ----

def make_handler(job: Job, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "stackctl"

        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            if code == 401:
                self.send_header("WWW-Authenticate", "Bearer")
            self.end_headers()
            self.wfile.write(data)

        def _route(self, method: str) -> None:
            if not authorized(self.headers.get("Authorization"), token):
                return self._send(401, {"error": "unauthorized"})
            if method == "POST" and self.path == "/media/pull-up":
                return self._send(202, {"started": True}) if job.start() else self._send(409, {"error": "running"})
            if method == "GET" and self.path == "/status":
                return self._send(200, job.status())
            return self._send(404, {"error": "not found"})

        def do_GET(self):  # noqa: N802
            self._route("GET")

        def do_POST(self):  # noqa: N802
            self._route("POST")

        def log_message(self, fmt, *args):  # request line + status only; headers (the token) are never printed
            sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    return Handler


def main() -> int:
    token = os.environ.get("STACKCTL_TOKEN", "").strip()
    if not token:
        print("stackctl: STACKCTL_TOKEN is not set - refusing to start", file=sys.stderr)
        return 2
    job = Job(os.environ.get("COMPOSE_FILE", DEFAULT_COMPOSE_FILE),
              os.environ.get("EXCLUDE", DEFAULT_EXCLUDE), token)
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    print(f"stackctl: listening on :{port}, compose file {job.compose_file}, exclude '{job.exclude}'", file=sys.stderr)
    ThreadingHTTPServer(("0.0.0.0", port), make_handler(job, token)).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
