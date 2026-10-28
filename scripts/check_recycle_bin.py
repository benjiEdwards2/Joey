"""JY-265 phase 0: is the Radarr / Sonarr recycle bin set? READ ONLY (GET only), stdlib only.

    python scripts/check_recycle_bin.py            # from Windows: runs the probe inside joey-hub over ssh

The NAS: JOEY_NAS (default root@nas.local), key JOEY_NAS_KEY (default ~/.ssh/joey_nas), as scripts/joey_common.py.
This same file is piped to `docker exec -i joey-hub python - --probe`, where it reads the hub's own RADARR_URL /
RADARR_API_KEY / SONARR_URL / SONARR_API_KEY and makes ONE call per app: `GET /api/v3/config/mediamanagement`. It
never writes, and it never prints a URL, a key or a host: only, per app, whether a recycle bin is set, its path and
its cleanup days (`recycleBin`, `recycleBinCleanupDays`). A failure prints the exception type or the HTTP status.

Q6 A (B., 2026-10-28) makes the recycle bin required for content removes. Setting it is NOT done here: it is a
separate step that needs B.'s OK.

Exit 0 = both apps answered and both have a recycle bin; 1 = an app has none or did not answer; 2 = could not run.
"""
from __future__ import annotations

import json
import os
import sys

APPS = ("radarr", "sonarr")
PATH = "/api/v3/config/mediamanagement"
CONTAINER = "joey-hub"
TIMEOUT = 10


# ---- inside joey-hub ----

def read_app(app: str, get=None) -> dict:
    """{app, answered, set, path, days, why} for one app. `get(url, key) -> (status, body)` is the test seam."""
    base = os.environ.get(f"{app.upper()}_URL", "").strip().rstrip("/")
    key = os.environ.get(f"{app.upper()}_API_KEY", "").strip()
    out = {"app": app, "answered": False, "set": False, "path": "", "days": None, "why": ""}
    if not base or not key:
        out["why"] = "not configured in the hub"
        return out
    try:
        status, body = (get or _get)(base + PATH, key)
    except Exception as exc:   # type only: an error message can carry the URL
        out["why"] = type(exc).__name__
        return out
    if not 200 <= status < 300 or not isinstance(body, dict):
        out["why"] = f"HTTP {status}"
        return out
    path = body.get("recycleBin")
    days = body.get("recycleBinCleanupDays")
    out.update(answered=True, set=isinstance(path, str) and bool(path.strip()),
               path=path.strip() if isinstance(path, str) else "",
               days=days if isinstance(days, int) and not isinstance(days, bool) else None)
    return out


def _get(url: str, key: str) -> tuple[int, object]:
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, method="GET", headers={"X-Api-Key": key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None


def probe(get=None) -> list[dict]:
    return [read_app(app, get) for app in APPS]


# ---- on Windows ----

def line(row: dict) -> str:
    name = row["app"].capitalize()
    if not row["answered"]:
        return f"FAIL  {name}: no answer ({row['why']})"
    if not row["set"]:
        return f"FAIL  {name}: recycle bin set: no · cleanup days: {row['days']}"
    return f"PASS  {name}: recycle bin set: yes · path: {row['path']} · cleanup days: {row['days']}"


def report(rows: list[dict]) -> int:
    for r in rows:
        print(line(r))
    ok = all(r["answered"] and r["set"] for r in rows)
    print(("PASS" if ok else "FAIL") + "  recycle bin: " + ", ".join(
        f"{r['app']}={'yes' if r['set'] else 'no'}" for r in rows))
    return 0 if ok else 1


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--probe" in argv:            # inside joey-hub: one JSON line, nothing else
        print(json.dumps(probe()))
        return 0
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from joey_common import ssh_run
    try:
        src = open(os.path.abspath(__file__), encoding="utf-8").read()
        r = ssh_run(f"docker exec -i {CONTAINER} python - --probe", stdin=src, timeout=60)
    except (RuntimeError, OSError) as exc:
        print(f"ERROR {exc}" if isinstance(exc, RuntimeError) else f"ERROR {type(exc).__name__}")
        return 2
    try:
        rows = json.loads((r.stdout.strip().splitlines() or [""])[-1])
        assert isinstance(rows, list) and all(isinstance(x, dict) and x.get("app") in APPS for x in rows)
    except (ValueError, AssertionError):
        print(f"ERROR the probe gave no readable answer (exit {r.returncode})")
        return 2
    return report(rows)


if __name__ == "__main__":
    sys.exit(main())
