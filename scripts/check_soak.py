"""Soak check for the connector fleet (JY-210, from WP38 step 1). Stdlib only, READ ONLY.

    python scripts/check_soak.py HISTORY [--hours 24] [--min-ok 22] [--min-sweeps 22]
                                 [--exempt money] [--expect id,id,...] [--snapshots DIR] [--now ISO]

HISTORY is a copy of `_runner_history.jsonl` (one JSON line per sweep: `ran_at`, `results{id: {status, ...}}`, and
`only` / `except` on the partial sweeps). It is written by `connectors/run_all.py` into the snapshots dir. Nothing
here writes, deletes or contacts anything; copy the file off the NAS first (see docs/runbook.md "Soak check").

Over the last --hours (default 24) it asserts:
  * at least --min-sweeps sweeps of the HOURLY loop ran (lines without an `only` tag; 2 missed beats allowed of 24);
  * every connector id (those in the window, plus any named in --expect) has at least --min-ok status=ok results
    and is not at status=error for the whole window. An --exempt id (default `money`, whose empty inbox is normal)
    is not held to the ok count; it only must never report error.
With --snapshots DIR it also lists each snapshot's status and age (`*.json` not starting `_`) and fails a snapshot
whose `updated_at` is older than the window or whose status is error with no ok beat in the window.

Exit 0 = PASS; 1 = a check failed; 2 = could not run (no file, no usable lines). One line per connector, one summary line.
Malformed history lines are skipped and counted.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def parse_iso(text) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def load_history(path: Path) -> tuple[list[dict], int]:
    """(usable sweep lines oldest first, count of skipped lines). A usable line has a parseable `ran_at` and a `results` dict."""
    lines, skipped = [], 0
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except ValueError:
            skipped += 1
            continue
        at = parse_iso(row.get("ran_at")) if isinstance(row, dict) else None
        if at is None or not isinstance(row.get("results"), dict):
            skipped += 1
            continue
        lines.append({"at": at, "only": bool(row.get("only")), "results": row["results"]})
    lines.sort(key=lambda r: r["at"])
    return lines, skipped


def check(lines, now: datetime, hours: float = 24, min_ok: int = 22, min_sweeps: int = 22,
          exempt=("money",), expect=()) -> dict:
    """{ok, sweeps, all_sweeps, rows: [{id, ok, errors, runs, exempt, verdict, why}], why: [...]}; pure, no I/O."""
    since = now - timedelta(hours=hours)
    window = [r for r in lines if since <= r["at"] <= now]
    hourly = [r for r in window if not r["only"]]
    seen = set(expect)
    for r in window:
        seen.update(r["results"])
    rows = []
    for cid in sorted(seen):
        results = [r["results"][cid] for r in window if isinstance(r["results"].get(cid), dict)]
        n_ok = sum(1 for x in results if x.get("status") == "ok")
        n_err = sum(1 for x in results if x.get("status") == "error")
        is_exempt = cid in exempt
        why = []
        if not results:
            why.append("no results in the window")
        elif n_err == len(results):
            why.append("error in every result")
        elif is_exempt and n_err:
            why.append(f"reported error {n_err}x")
        if not is_exempt and results and n_ok < min_ok:
            why.append(f"{n_ok} ok < {min_ok}")
        rows.append({"id": cid, "ok": n_ok, "errors": n_err, "runs": len(results), "exempt": is_exempt,
                     "verdict": "FAIL" if why else "PASS", "why": "; ".join(why)})
    problems = [f"{len(hourly)} hourly sweeps < {min_sweeps}"] if len(hourly) < min_sweeps else []
    problems += [f"{r['id']}: {r['why']}" for r in rows if r["verdict"] == "FAIL"]
    if not rows:
        problems.append("no connector results in the window")
    return {"ok": not problems, "sweeps": len(hourly), "all_sweeps": len(window), "rows": rows, "why": problems}


def check_snapshots(directory: Path, now: datetime, hours: float, rows) -> list[dict]:
    """One row per snapshot file: {id, status, age_h, verdict, why}. Read only; unreadable files FAIL."""
    out = []
    ok_ids = {r["id"] for r in rows if r["ok"]}
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_"):
            continue
        cid = path.stem
        try:
            env = json.loads(path.read_text(encoding="utf-8"))
            status = env.get("status")
            at = parse_iso(env.get("updated_at"))
        except (OSError, ValueError, AttributeError):
            out.append({"id": cid, "status": "?", "age_h": None, "verdict": "FAIL", "why": "unreadable"})
            continue
        age = (now - at).total_seconds() / 3600 if at else None
        why = []
        if age is None:
            why.append("no updated_at")
        elif age > hours:
            why.append(f"updated {age:.1f} h ago")
        if status == "error" and cid not in ok_ids:
            why.append("status error, no ok beat in the window")
        out.append({"id": cid, "status": status, "age_h": age, "verdict": "FAIL" if why else "PASS", "why": "; ".join(why)})
    return out


def _split(text: str) -> tuple[str, ...]:
    return tuple(x for x in (s.strip() for s in text.split(",")) if x)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Read-only soak check of _runner_history.jsonl (JY-210).")
    p.add_argument("history", type=Path, help="a copy of _runner_history.jsonl")
    p.add_argument("--hours", type=float, default=24)
    p.add_argument("--min-ok", type=int, default=22, help="ok results per connector in the window (default 22 of 24)")
    p.add_argument("--min-sweeps", type=int, default=22, help="hourly-loop sweeps in the window (default 22 of 24)")
    p.add_argument("--exempt", default="money", help="comma list: ids not held to the ok count (default money)")
    p.add_argument("--expect", default="", help="comma list: ids that must appear even if they never ran")
    p.add_argument("--snapshots", type=Path, help="a copy of the snapshots dir: also check each snapshot's age and status")
    p.add_argument("--now", help="ISO time for the end of the window (default: the newest history line)")
    ns = p.parse_args(argv)
    try:
        lines, skipped = load_history(ns.history)
    except OSError as exc:
        print(f"ERROR cannot read {ns.history.name}: {type(exc).__name__}")
        return 2
    if not lines:
        print(f"ERROR no usable sweep lines in {ns.history.name} ({skipped} skipped)")
        return 2
    now = parse_iso(ns.now) if ns.now else lines[-1]["at"]
    if now is None:
        print("ERROR --now is not an ISO time")
        return 2
    res = check(lines, now, ns.hours, ns.min_ok, ns.min_sweeps, _split(ns.exempt), _split(ns.expect))
    for r in res["rows"]:
        tag = " (exempt from the ok count)" if r["exempt"] else ""
        print(f"{r['verdict']}  {r['id']:<16} ok={r['ok']} error={r['errors']} runs={r['runs']}{tag}"
              + (f"  [{r['why']}]" if r["why"] else ""))
    failed = list(res["why"])
    if ns.snapshots:
        for s in check_snapshots(ns.snapshots, now, ns.hours, res["rows"]):
            age = "?" if s["age_h"] is None else f"{s['age_h']:.1f} h"
            print(f"{s['verdict']}  snapshot {s['id']:<10} status={s['status']} age={age}"
                  + (f"  [{s['why']}]" if s["why"] else ""))
            if s["verdict"] == "FAIL":
                failed.append(f"snapshot {s['id']}: {s['why']}")
    verdict = "PASS" if not failed else "FAIL"
    print(f"{verdict}  soak: {res['sweeps']} hourly sweeps ({res['all_sweeps']} in all) in {ns.hours:g} h to "
          f"{now:%Y-%m-%dT%H:%M:%SZ}, {skipped} bad line(s) skipped" + ("" if not failed else "; " + "; ".join(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
