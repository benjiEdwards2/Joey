"""powerctl (JY-274, 2026-11-05): power the NAS down on request - stop the media stack cleanly, then the host.

A tiny stdlib-only HTTP service beside Joey on the NAS (powerctl/NAS_INSTALL.md), started with the host PID namespace,
privileged, and the Docker socket. Joey's hub calls it server-side only (hub/server_power.py); the browser never sees
the token. Home Assistant may later make the SAME call ("Goodnight"): one stable endpoint, below.

  POST /power-down -> 202 {"pending": true} | 409 {"error": "pending"} while a power-down is already under way
                      job: wait GRACE_S, STOP_CMD (stop the media compose project, capped at 60 s), then SHUTDOWN_CMD
  GET  /status     -> {pending, requested_at, stage, exit_code, log_tail}

Every endpoint needs `Authorization: Bearer <POWERCTL_TOKEN>` (constant-time compare). The token is never logged.
Env: POWERCTL_TOKEN (required - no token, no start), STOP_CMD (default `docker compose -p media-server stop -t 45`),
SHUTDOWN_CMD (EMPTY = dry run: the shutdown is only logged, never run; the Dockerfile sets the real one), GRACE_S
(seconds before the stop starts, default 3, so the hub's answer and log write finish first), PORT (default 8811).
"""

from __future__ import annotations

import hmac
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG_LINES = 50
STOP_CAP_S = 60
DEFAULT_STOP_CMD = "docker compose -p media-server stop -t 45"
DEFAULT_PORT = 8811


def authorized(header: str | None, token: str) -> bool:
    """True only for `Bearer <token>` with the exact token (constant-time compare); an empty token never matches."""
    if not token or not header:
        return False
    scheme, _, given = header.strip().partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(given.strip().encode(), token.encode())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Job:
    """At most one power-down. `pending` stays true once the shutdown command ran (the host is going away); a failed
    shutdown clears it so the owner can try again. An empty `shutdown_cmd` is a dry run (tests, a laptop)."""

    def __init__(self, stop_cmd: list[str] | None, shutdown_cmd: list[str] | None, grace_s: float = 3,
                 stop_cap_s: float = STOP_CAP_S, runner=subprocess.run):
        self.stop_cmd, self.shutdown_cmd = list(stop_cmd or []), list(shutdown_cmd or [])
        self.grace_s, self.stop_cap_s, self.runner = grace_s, stop_cap_s, runner
        self.lock = threading.Lock()
        self.pending = False
        self.requested_at = None
        self.stage = "idle"
        self.exit_code: int | None = None
        self.log: deque[str] = deque(maxlen=LOG_LINES)
        self.done = threading.Event()

    def status(self) -> dict:
        with self.lock:
            return {"pending": self.pending, "requested_at": self.requested_at, "stage": self.stage,
                    "exit_code": self.exit_code, "log_tail": list(self.log)}

    def start(self) -> bool:
        """False while a power-down is pending; else starts one in the background."""
        with self.lock:
            if self.pending:
                return False
            self.pending, self.requested_at, self.stage, self.exit_code = True, _now(), "waiting", None
            self.log.clear()
            self.done.clear()
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def _say(self, line: str) -> None:
        with self.lock:
            self.log.append(line.rstrip())

    def _stage(self, name: str) -> None:
        with self.lock:
            self.stage = name

    def _run(self) -> None:
        time.sleep(self.grace_s)
        if self.stop_cmd:
            self._stage("stopping")
            self._say("$ " + " ".join(self.stop_cmd))
            try:   # a stuck or failed stop never blocks the shutdown: it is capped and only logged
                r = self.runner(self.stop_cmd, timeout=self.stop_cap_s, capture_output=True, text=True,
                                errors="replace")
                self._say(f"stop exit {r.returncode}")
            except subprocess.TimeoutExpired:
                self._say(f"stop still running after {self.stop_cap_s:g} s - shutting down anyway")
            except Exception as exc:
                self._say(f"stop failed: {type(exc).__name__}")
        self._stage("shutting down")
        if not self.shutdown_cmd:
            self._say("dry run: SHUTDOWN_CMD is empty - the host is NOT powered off")
            code = 0
        else:
            self._say("$ " + " ".join(self.shutdown_cmd))
            try:
                code = self.runner(self.shutdown_cmd, timeout=30).returncode
            except Exception as exc:
                self._say(f"shutdown failed: {type(exc).__name__}")
                code = 1
        with self.lock:
            self.exit_code = code
            self.stage = "shutdown sent" if code == 0 else "failed"
            if code != 0:
                self.pending = False
            self.log.append(f"exit {code}")
        self.done.set()


def make_handler(job: Job, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "powerctl"

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
            if method == "POST" and self.path == "/power-down":
                return self._send(202, {"pending": True}) if job.start() else self._send(409, {"error": "pending"})
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
    token = os.environ.get("POWERCTL_TOKEN", "").strip()
    if not token:
        print("powerctl: POWERCTL_TOKEN is not set - refusing to start", file=sys.stderr)
        return 2
    stop = shlex.split(os.environ.get("STOP_CMD", DEFAULT_STOP_CMD))
    shutdown = shlex.split(os.environ.get("SHUTDOWN_CMD", ""))
    job = Job(stop, shutdown, grace_s=float(os.environ.get("GRACE_S", "3")))
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    shown = " ".join(shutdown) or "DRY RUN"
    print(f"powerctl: listening on :{port}, stop '{' '.join(stop)}', shutdown '{shown}'", file=sys.stderr)
    ThreadingHTTPServer(("0.0.0.0", port), make_handler(job, token)).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
