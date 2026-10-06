"""Hourly sweep: run every registered connector in isolation (WP22 step 5).

One connector crashing can never stop the others — each is wrapped separately,
even though Connector.run() already swallows its own failures. After every
sweep the runner writes `_runner.json` (the heartbeat, last sweep only) and
appends one JSON line to `_runner_history.jsonl` — the append-only evidence
WP38's 24 h soak counts beats from.

Driven by the container entrypoint's `sleep 3600` loop, not crond (D16). Since
2026-10-05 (D16 amended) a second 120 s loop runs `--only jellyfin,media_status,qbittorrent,arr,system`;
those sweeps are tagged `{"only": [...]}` so a soak counter can tell the
hourly full sweeps from the fast partial ones.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Iterable

from connectors.base import Connector, _now_iso, snapshot_dir

log = logging.getLogger("connectors.run_all")

HEARTBEAT_NAME = "_runner.json"
HISTORY_NAME = "_runner_history.jsonl"


def run_sweep(connectors: Iterable[Connector] | None = None,
              only: list[str] | None = None) -> dict:
    if connectors is None:
        from connectors import registry

        connectors = registry.build_all()
    if only:
        connectors = [c for c in connectors if getattr(c, "id", None) in only]

    results: dict[str, dict] = {}
    for connector in connectors:
        cid = getattr(connector, "id", connector.__class__.__name__)
        try:
            envelope = connector.run()
            results[cid] = {
                "status": envelope["status"],
                "consecutive_failures": envelope["consecutive_failures"],
                "error": envelope["error"],
            }
        except Exception as exc:  # run() shouldn't raise; isolate it anyway
            log.error("%s raised outside run(): %s", cid, exc)
            results[cid] = {
                "status": "error",
                "consecutive_failures": -1,
                "error": f"runner-level {type(exc).__name__}: {exc}",
            }
        log.info("%s: %s", cid, results[cid]["status"])
        print(f"{cid}: {results[cid]['status']}"
              + (f" ({results[cid]['error']})" if results[cid]["error"] else ""))

    sweep = {"ran_at": _now_iso(), "results": results}
    if only:
        sweep["only"] = list(only)
    _write_heartbeat(sweep)
    return sweep


def _write_heartbeat(sweep: dict) -> None:
    directory = snapshot_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / HEARTBEAT_NAME).write_text(
        json.dumps(sweep, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (directory / HISTORY_NAME).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(sweep, sort_keys=True) + "\n")


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
