"""The sweep: run every registered connector in isolation (WP22 step 5).

One connector crashing can never stop the others — each is wrapped separately,
even though Connector.run() already swallows its own failures. After every
sweep the runner writes `_runner.json` (the heartbeat, last sweep only) and
appends one JSON line to `_runner_history.jsonl` — the append-only evidence
WP38's 24 h soak counts beats from.

Driven by the container entrypoint's `sleep 3600` loop, not crond (D16). Since
2026-10-05 (D16 amended) a second 120 s loop runs
`--only jellyfin,media_status,qbittorrent,arr,system,uptime_kuma` (every other feed is hourly only);
those sweeps are tagged `{"only": [...]}` so a soak counter can tell the
hourly full sweeps from the fast partial ones.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from connectors.base import Connector, _now_iso, mask_urls, replace_with_retry, snapshot_dir, write_envelope

log = logging.getLogger("connectors.run_all")

HEARTBEAT_NAME = "_runner.json"
HISTORY_NAME = "_runner_history.jsonl"
# Rotation (C-16, N-10): past HISTORY_MAX_BYTES the file is rewritten (tmp + os.replace) to
# its newest lines from the last HISTORY_KEEP_DAYS days, capped at half the limit so the next
# rewrite is days away (14 days of fast-loop lines alone is ~6 MB). The hub reads the last
# 2 MB / 1000 lines and the WP38 soak needs >= 24 h (~750 lines, ~0.5 MB) — both kept.
HISTORY_MAX_BYTES = 5 * 1024 * 1024
HISTORY_KEEP_DAYS = 14


def run_sweep(connectors: Iterable[Connector] | None = None,
              only: list[str] | None = None) -> dict:
    if connectors is None:
        from connectors import registry

        connectors = registry.build_all()
    if only:
        connectors = [c for c in connectors if getattr(c, "id", None) in only]

    results: dict[str, dict] = {}
    durations: dict[str, int] = {}
    partial = 0
    sweep_start = time.monotonic()
    for connector in connectors:
        cid = getattr(connector, "id", connector.__class__.__name__)
        started = time.monotonic()
        try:
            envelope = connector.run()
            results[cid] = {
                "status": envelope["status"],
                "consecutive_failures": envelope["consecutive_failures"],
                "error": envelope["error"],
            }
        except Exception as exc:  # run() shouldn't raise; isolate it anyway
            reason = mask_urls(f"{type(exc).__name__}: {exc}")
            log.error("%s raised outside run(): %s", cid, reason)
            results[cid] = {
                "status": "error",
                "consecutive_failures": -1,
                "error": f"runner-level {reason}",
            }
        durations[cid] = _ms(started)
        # One container-log line per NON-ok result (C-24, N-27); ok results are counted in
        # the summary line below instead of being printed and logged one by one.
        if results[cid]["status"] != "ok":
            print(f"{cid}: {results[cid]['status']}"
                  + (f" ({results[cid]['error']})" if results[cid]["error"] else ""))
        elif _partial(envelope):
            partial += 1

    sweep = {"ran_at": _now_iso(), "results": results}
    if only:
        sweep["only"] = list(only)
    sweep_ms = _ms(sweep_start)
    _write_heartbeat(sweep, durations, sweep_ms)
    ok = sum(1 for r in results.values() if r["status"] == "ok")
    print(f"sweep ok={ok} err={len(results) - ok} partial={partial} ms={sweep_ms}")
    return sweep


# data keys by which an ok envelope reports that part of its sources failed
PARTIAL_KEYS = ("app_errors", "feed_errors")


def _partial(envelope) -> bool:
    data = envelope.get("data") if isinstance(envelope, dict) else None
    return isinstance(data, dict) and any(data.get(k) for k in PARTIAL_KEYS)


def _ms(since: float) -> int:
    return int(round((time.monotonic() - since) * 1000))


def _write_heartbeat(sweep: dict, durations: dict[str, int] | None = None,
                     sweep_ms: int | None = None) -> None:
    directory = snapshot_dir()
    directory.mkdir(parents=True, exist_ok=True)
    # Atomic (C-15): the hourly and the 120 s loop both write it while the hub reads it.
    write_envelope(directory / HEARTBEAT_NAME, sweep)
    # The history line is the heartbeat plus timings (N-11): `duration_ms` per result and
    # `sweep_ms` per line. The heartbeat itself stays timing-free (byte-stable samples).
    line = {**sweep, "results": {cid: ({**res, "duration_ms": durations[cid]}
                                       if durations and cid in durations else res)
                                 for cid, res in sweep["results"].items()}}
    if sweep_ms is not None:
        line["sweep_ms"] = sweep_ms
    history = directory / HISTORY_NAME
    with history.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, sort_keys=True) + "\n")
    try:
        if history.stat().st_size > HISTORY_MAX_BYTES:
            _rotate_history(history, sweep["ran_at"])
    except Exception as exc:  # rotation trouble never fails a sweep — next sweep retries
        log.warning("history rotation skipped: %s", type(exc).__name__)


def _rotate_history(history: Path, now_iso: str) -> None:
    """Rewrite `history` atomically to its newest lines no older than HISTORY_KEEP_DAYS and
    no bigger than HISTORY_MAX_BYTES // 2 in total; unparseable lines are dropped. A line
    another loop appends during the rewrite can be lost — once every few days, accepted."""
    cutoff = datetime.fromisoformat(now_iso) - timedelta(days=HISTORY_KEEP_DAYS)
    kept: list[str] = []
    size = 0
    for raw in reversed(history.read_text(encoding="utf-8").splitlines()):
        try:
            at = datetime.fromisoformat(str(json.loads(raw)["ran_at"]).replace("Z", "+00:00"))
        except Exception:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=cutoff.tzinfo)
        if at < cutoff:
            break
        size += len(raw.encode("utf-8")) + 1
        if size > HISTORY_MAX_BYTES // 2:
            break
        kept.append(raw)
    tmp = history.with_name(f"{history.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text("".join(f"{raw}\n" for raw in reversed(kept)), encoding="utf-8")
    replace_with_retry(tmp, history)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the connector sweep.")
    parser.add_argument("--only", help="comma-separated connector ids to run (default: all)")
    args = parser.parse_args(argv or [])
    only = [i.strip() for i in args.only.split(",") if i.strip()] if args.only else None
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_sweep(only=only)
    return 0  # a failed feed is data, not a runner failure — the loop keeps going


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
