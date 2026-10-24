"""Measure the CLAUDE.md performance budgets on the NAS (JY-013). Stdlib only, read only.

    python scripts/budgets.py [-n 20] [--json]           measure production over ssh (one login per check)
    python scripts/budgets.py --local http://127.0.0.1:PORT [-n 20] [--json]
                                                          time the pages of a local hub; NAS-only rows show SKIP

The NAS: JOEY_NAS (default root@nas.local, as deploy/push.sh), key JOEY_NAS_KEY (default ~/.ssh/joey_nas; used
when the file exists). Page timings run INSIDE joey-hub: this same file is piped to `docker exec -i joey-hub
python - --payload ...` (the hub port is not published). Each page is fetched once untimed, then timed n times;
rows report the worst page's p95 (nearest rank) and the max. Discover gets one cold and one warm fetch.
Hub pages are `/` and /a/<id> for every area in config/areas.yaml that is not `hidden: true`.

Exit 0 = every measured row within budget; 1 = a row over budget; 2 = a measurement could not run (ERROR rows;
2 wins over 1). The report is one line per budget row plus one summary line. Nothing printed names the NAS login.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HUB_CONTAINER = "joey-hub"
IN_CONTAINER_BASE = "http://127.0.0.1:8000"
HISTORY_LOG = "/volume1/Docker/joey/life-dashboard/deploy/history.log"
DISCOVER_PATH = "/media/discover"          # hub/media_discover.py
MEDIA_LISTS = ("/media/movies", "/media/tv")
MAX_ITEMS = 4
ITEM_RE = re.compile(r'href="/media/item/([A-Za-z0-9-]{1,64})"')
AREA_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

# CLAUDE.md "Performance budgets"
HUB_P95_MS = 50.0
MEDIA_P95_MS = 150.0
DISCOVER_MS = 3000.0
HUB_MEM_MIB = 200.0
NAS_AVAIL_MB = 1200.0
GATE_S = 600.0

PASS, FAIL, INFO, SKIP, ERROR = "PASS", "FAIL", "INFO", "SKIP", "ERROR"
MAX_LINES = 20


# ---------------------------------------------------------------- page-timing payload (laptop and container)

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # the target is always loopback


def _get(base: str, path: str, timeout: float = 30.0) -> tuple[float, int, bytes, str]:
    """One GET. Returns (ms, status, body, error); error names the exception type only (never the URL)."""
    t0 = time.perf_counter()
    try:
        with _OPENER.open(urllib.request.Request(base + path, method="GET"), timeout=timeout) as resp:
            body, code, err = resp.read(), resp.status, ""
    except urllib.error.HTTPError as exc:
        body, code, err = b"", exc.code, f"HTTP {exc.code}"
    except Exception as exc:  # connection refused, timeout: report, never raise
        body, code, err = b"", 0, type(exc).__name__
    if code != 200 and not err:
        err = f"HTTP {code}"
    return (time.perf_counter() - t0) * 1000.0, code, body, err


def _time_path(base: str, path: str, n: int) -> tuple[dict, bytes]:
    """Warm-up fetch (untimed), then n timed fetches."""
    _, _, body, err = _get(base, path)
    if err:
        return {"path": path, "error": err}, b""
    samples = []
    for _ in range(n):
        ms, _, _, err = _get(base, path)
        if err:
            return {"path": path, "error": err}, body
        samples.append(round(ms, 2))
    return {"path": path, "ms": samples}, body


def _item_ids(bodies: list[bytes]) -> list[str]:
    """Up to MAX_ITEMS item ids, alternating between the lists (films and shows)."""
    lists = [list(dict.fromkeys(ITEM_RE.findall(b.decode("utf-8", "replace")))) for b in bodies]
    out: list[str] = []
    for i in range(max((len(x) for x in lists), default=0)):
        for ids in lists:
            if i < len(ids) and ids[i] not in out:
                out.append(ids[i])
    return out[:MAX_ITEMS]


def measure_pages(base: str, area_ids: list[str], n: int) -> dict:
    """The payload: GETs only. Discover first, so its cold fetch is as cold as this run can make it."""
    base = base.rstrip("/")
    cold_ms, _, _, cold_err = _get(base, DISCOVER_PATH, timeout=60.0)
    warm_ms, _, _, warm_err = _get(base, DISCOVER_PATH, timeout=60.0)
    discover = {"cold_ms": round(cold_ms, 1), "warm_ms": round(warm_ms, 1), "error": cold_err or warm_err}
    hub = [_time_path(base, p, n)[0] for p in ["/"] + [f"/a/{a}" for a in area_ids]]
    media, bodies = [], []
    for path in MEDIA_LISTS:
        res, body = _time_path(base, path, n)
        media.append(res)
        bodies.append(body)
    media += [_time_path(base, f"/media/item/{i}", n)[0] for i in _item_ids(bodies)]
    return {"n": n, "hub": hub, "media": media, "discover": discover}


# ---------------------------------------------------------------- maths, parsing, verdicts

def p95(samples: list[float]) -> float:
    """Nearest-rank 95th percentile: the ceil(0.95 * N)-th smallest sample."""
    if not samples:
        raise ValueError("no samples")
    s = sorted(samples)
    return s[math.ceil(0.95 * len(s)) - 1]


_UNIT_MIB = {"B": 1 / 1048576, "KB": 1000 / 1048576, "KIB": 1 / 1024, "MB": 1e6 / 1048576, "MIB": 1.0,
             "GB": 1e9 / 1048576, "GIB": 1024.0}


def parse_docker_mem(text: str) -> float:
    """`123.4MiB / 384MiB` (docker stats MemUsage) -> 123.4 (MiB used)."""
    m = re.search(r"([\d.]+)\s*([KMG]?i?B)\s*/", text, re.IGNORECASE)
    if not m or m.group(2).upper() not in _UNIT_MIB:
        raise ValueError("no memory usage in docker stats output")
    return float(m.group(1)) * _UNIT_MIB[m.group(2).upper()]


def parse_free_available(text: str) -> float:
    """`free -m` -> the Mem row's `available` column (MB)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    header = next((ln.split() for ln in lines if "available" in ln.split()), None)
    mem = next((ln.split() for ln in lines if ln.split()[0].lower() == "mem:"), None)
    if header is None or mem is None:
        raise ValueError("no available column in free -m output")
    values = mem[1:]
    idx = header.index("available")
    if len(values) != len(header):
        raise ValueError("free -m columns do not line up")
    return float(values[idx])


def parse_history_duration(line: str) -> float | None:
    """A deploy.sh history line -> dur in seconds, or None when the line carries no `dur=`."""
    m = re.search(r"\bdur=(\d+)s\b", line)
    return float(m.group(1)) if m else None


def read_area_ids(text: str) -> list[str]:
    """Area ids from areas.yaml (no PyYAML): `  - id:` entries under `areas:`, minus `    hidden: true` ones."""
    areas: list[dict] = []
    in_areas = False
    for line in text.splitlines():
        if re.match(r"^areas:\s*(#.*)?$", line):
            in_areas = True
            continue
        if re.match(r"^[^\s#]", line):
            in_areas = False
        if not in_areas:
            continue
        m = re.match(r"^  - id:\s*['\"]?([A-Za-z0-9_-]+)", line)
        if m:
            areas.append({"id": m.group(1), "hidden": False})
        elif areas and re.match(r"^    hidden:\s*true\b", line):
            areas[-1]["hidden"] = True
    return [a["id"] for a in areas if not a["hidden"] and AREA_ID_RE.match(a["id"])]


def _row(name: str, value: str, budget: str, verdict: str) -> dict:
    return {"name": name, "value": value, "budget": budget, "verdict": verdict}


def page_row(name: str, results: list[dict] | None, limit_ms: float, error: str = "") -> dict:
    budget = f"p95 <= {limit_ms:.0f} ms"
    if error:
        return _row(name, error, budget, ERROR)
    bad = next((r for r in results or [] if "error" in r), None)
    if bad is not None:
        return _row(name, f"{bad['path']}: {bad['error']}", budget, ERROR)
    if not results:
        return _row(name, "no pages measured", budget, ERROR)
    worst = max(results, key=lambda r: p95(r["ms"]))
    w, mx = p95(worst["ms"]), max(max(r["ms"]) for r in results)
    value = f"p95 {w:.0f} ms ({worst['path']}), max {mx:.0f} ms, {len(results)} pages"
    return _row(name, value, budget, PASS if w <= limit_ms else FAIL)


def discover_rows(d: dict | None, error: str = "") -> list[dict]:
    budget = f"<= {DISCOVER_MS / 1000:.0f} s"
    err = error or (d or {}).get("error") or ("" if d else "not measured")
    rows = []
    for label, key in (("cold", "cold_ms"), ("warm", "warm_ms")):
        name = f"Discover page, {label}"
        if err:
            rows.append(_row(name, err, budget, ERROR))
        else:
            ms = float(d[key])
            rows.append(_row(name, f"{ms / 1000:.2f} s", budget, PASS if ms <= DISCOVER_MS else FAIL))
    return rows


def mem_row(mib: float | None, error: str = "") -> dict:
    name, budget = "joey-hub memory", f"<= {HUB_MEM_MIB:.0f} MiB"
    if error or mib is None:
        return _row(name, error or "not measured", budget, ERROR)
    return _row(name, f"{mib:.1f} MiB", budget, PASS if mib <= HUB_MEM_MIB else FAIL)


def avail_row(before: float | None, after: float | None, error: str = "") -> dict:
    name, budget = "NAS available memory", f">= {NAS_AVAIL_MB:,.0f} MB"
    if error or before is None or after is None:
        return _row(name, error or "not measured", budget, ERROR)
    low = min(before, after)
    value = f"{low:,.0f} MB (before {before:,.0f}, after {after:,.0f})"
    return _row(name, value, budget, PASS if low >= NAS_AVAIL_MB else FAIL)


def gate_row(line: str | None, error: str = "") -> dict:
    name, budget = "Full gate (deploy.sh)", f"<= {GATE_S / 60:.0f} min"
    if error:
        return _row(name, error, budget, ERROR)
    if not line:
        return _row(name, "no PASS line in history.log", budget, INFO)
    dur = parse_history_duration(line)
    if dur is None:
        return _row(name, "not recorded", budget, INFO)
    stamp = line.split()[0]
    return _row(name, f"{dur / 60:.1f} min (PASS {stamp})", budget, PASS if dur <= GATE_S else FAIL)


def skip_row(name: str, budget: str) -> dict:
    return _row(name, "local run", budget, SKIP)


def exit_code(rows: list[dict]) -> int:
    verdicts = {r["verdict"] for r in rows}
    return 2 if ERROR in verdicts else 1 if FAIL in verdicts else 0


def summary(rows: list[dict], n: int, where: str) -> str:
    counts = ", ".join(f"{sum(r['verdict'] == v for r in rows)} {v}" for v in (PASS, FAIL, INFO, SKIP, ERROR))
    return f"Summary ({where}, n={n}): {counts} -> exit {exit_code(rows)}"


def render(rows: list[dict], n: int, where: str) -> str:
    lines = [f"{r['name']:<29} {r['value']:<52} {r['budget']:<15} {r['verdict']}" for r in rows]
    lines = lines[:MAX_LINES - 1] + [summary(rows, n, where)]
    return "\n".join(line.rstrip() for line in lines)


# ---------------------------------------------------------------- NAS side (ssh)

class NasError(Exception):
    pass


def scrub(text: str, nas: str = "") -> str:
    """Last stderr line, with the login, the bare NAS host and any user@host / e-mail removed."""
    last = next((ln.strip() for ln in reversed(text.splitlines()) if ln.strip()), "")
    if nas:
        last = last.replace(nas, "<nas>")
        host = nas.split("@", 1)[-1]   # the whole value when there is no @
        if host:
            last = last.replace(host, "<nas>")
    last = re.sub(r"[\w.+-]+@[\w.-]+", "<nas>", last)
    return last[:100]


def ssh_runner(nas: str, key: str):
    """run(remote_cmd, stdin=None, timeout=60) -> (rc, stdout, stderr); NasError when ssh itself fails."""
    def run(remote_cmd: str, stdin: bytes | None = None, timeout: float = 60.0) -> tuple[int, str, str]:
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
        if key and os.path.isfile(key):
            cmd += ["-i", key]
        cmd += [nas, remote_cmd]
        try:
            proc = subprocess.run(cmd, input=stdin if stdin is not None else b"", capture_output=True,
                                  timeout=timeout)
        except FileNotFoundError:
            raise NasError("ssh not found on this computer") from None
        except subprocess.TimeoutExpired:
            raise NasError(f"ssh timed out after {timeout:.0f} s") from None
        out, err = proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")
        if proc.returncode == 255:
            raise NasError(f"ssh failed: {scrub(err, nas)}" if scrub(err, nas) else "ssh failed (exit 255)")
        return proc.returncode, out, err
    return run


def payload_source() -> bytes:
    return Path(__file__).read_text(encoding="utf-8").encode("utf-8")


def measure_nas(run, area_ids: list[str], n: int, scrub_nas: str = "") -> list[dict]:
    """Every budget row, one ssh login per check. Read only: docker inspect / exec (GETs) / stats, free, grep."""
    try:
        rc, out, err = run(f"docker inspect -f '{{{{.State.Running}}}}' {HUB_CONTAINER}")
        if rc != 0:
            raise NasError(f"container {HUB_CONTAINER} missing")
        if out.strip() != "true":
            raise NasError(f"container {HUB_CONTAINER} not running")
    except NasError as exc:
        reason = str(exc)
        return ([page_row("Hub page render, warm", None, HUB_P95_MS, reason),
                 page_row("Media list / item page, warm", None, MEDIA_P95_MS, reason)]
                + discover_rows(None, reason)
                + [mem_row(None, reason), avail_row(None, None, reason), gate_row(None, reason)])

    def free() -> tuple[float | None, str]:
        try:
            rc, out, err = run("free -m")
            if rc != 0:
                return None, f"free -m failed: {scrub(err, scrub_nas)}"
            return parse_free_available(out), ""
        except (NasError, ValueError) as exc:
            return None, str(exc)

    before, before_err = free()

    pages, pages_err = None, ""
    try:
        cmd = (f"docker exec -i {HUB_CONTAINER} python - --payload -n {int(n)} "
               f"--areas={','.join(area_ids)}")
        rc, out, err = run(cmd, stdin=payload_source(), timeout=600.0)
        if rc != 0:
            pages_err = f"payload failed: {scrub(err, scrub_nas) or f'exit {rc}'}"
        else:
            pages = json.loads(out.strip().splitlines()[-1])
    except NasError as exc:
        pages_err = str(exc)
    except (ValueError, IndexError):
        pages_err = "payload printed no JSON"

    after, after_err = free()

    mib, mem_err = None, ""
    try:
        rc, out, err = run(f"docker stats --no-stream --format '{{{{.MemUsage}}}}' {HUB_CONTAINER}")
        if rc != 0:
            mem_err = f"docker stats failed: {scrub(err, scrub_nas)}"
        else:
            mib = parse_docker_mem(out)
    except (NasError, ValueError) as exc:
        mem_err = str(exc)

    line, gate_err = None, ""
    try:
        # tail's exit code hides a missing log, so test it first (BusyBox sh, no pipefail needed)
        rc, out, err = run(f"test -r {HISTORY_LOG} || exit 3; grep -E '^[^ ]+ PASS ' {HISTORY_LOG} | tail -n 1")
        if rc == 3:
            gate_err = "history.log not readable"
        else:
            line = out.strip() or None
    except NasError as exc:
        gate_err = str(exc)

    p = pages or {}
    return ([page_row("Hub page render, warm", p.get("hub"), HUB_P95_MS, pages_err),
             page_row("Media list / item page, warm", p.get("media"), MEDIA_P95_MS, pages_err)]
            + discover_rows(p.get("discover"), pages_err)
            + [mem_row(mib, mem_err), avail_row(before, after, before_err or after_err), gate_row(line, gate_err)])


def measure_local(base: str, area_ids: list[str], n: int) -> list[dict]:
    p = measure_pages(base, area_ids, n)
    return ([page_row("Hub page render, warm", p["hub"], HUB_P95_MS),
             page_row("Media list / item page, warm", p["media"], MEDIA_P95_MS)]
            + discover_rows(p["discover"])
            + [skip_row("joey-hub memory", f"<= {HUB_MEM_MIB:.0f} MiB"),
               skip_row("NAS available memory", f">= {NAS_AVAIL_MB:,.0f} MB"),
               skip_row("Full gate (deploy.sh)", f"<= {GATE_S / 60:.0f} min")])


# ---------------------------------------------------------------- command line

def main(argv: list[str] | None = None, runner=None) -> int:
    ap = argparse.ArgumentParser(description="Measure the CLAUDE.md performance budgets (JY-013). Read only.")
    ap.add_argument("-n", type=int, default=20, help="timed fetches per page after one warm-up (default 20)")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--local", metavar="URL", help="time a local hub's pages directly; NAS-only rows show SKIP")
    ap.add_argument("--payload", action="store_true", help=argparse.SUPPRESS)   # inside joey-hub
    ap.add_argument("--areas", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--base", default=IN_CONTAINER_BASE, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):   # JY-241: never UnicodeEncodeError on a cp1252 Windows pipe
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if args.n < 1:
        ap.error("-n must be at least 1")

    if args.payload:
        areas = [a for a in (args.areas or "").split(",") if AREA_ID_RE.match(a)]
        print(json.dumps(measure_pages(args.base, areas, args.n)))
        return 0

    areas_file = Path(__file__).resolve().parent.parent / "config" / "areas.yaml"
    area_ids = read_area_ids(areas_file.read_text(encoding="utf-8"))
    if args.local:
        rows, where = measure_local(args.local, area_ids, args.n), "local"
    else:
        nas = os.environ.get("JOEY_NAS", "root@nas.local")
        key = os.path.expanduser(os.environ.get("JOEY_NAS_KEY", "~/.ssh/joey_nas"))
        rows, where = measure_nas(runner or ssh_runner(nas, key), area_ids, args.n, nas), "NAS"

    code = exit_code(rows)
    if args.json:
        print(json.dumps({"where": where, "n": args.n, "rows": rows, "summary": summary(rows, args.n, where),
                          "exit": code}, indent=2))
    else:
        print(render(rows, args.n, where))
    return code


if __name__ == "__main__":
    sys.exit(main())
