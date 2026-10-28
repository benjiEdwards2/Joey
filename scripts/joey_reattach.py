"""JY-264: the library re-attach from B.'s computer, until the Server page has a screen for its report.

    python scripts/joey_reattach.py report           # the newest run: a report waiting for you, an apply, an undo
    python scripts/joey_reattach.py dry-run          # what a re-attach would change now (writes nothing)
    python scripts/joey_reattach.py apply RUN_ID     # apply a stored report, only if the library still matches it
    python scripts/joey_reattach.py undo RUN_ID      # undo an applied run

Household only: it runs `docker exec joey-hub python -m hub.library_reattach ...` on the NAS over ssh with B.'s key
(JOEY_NAS, default root@nas.local; JOEY_NAS_KEY, default ~/.ssh/joey_nas, as scripts/budgets.py). It prints the hub's
PASS / FAIL lines, which carry run ids, counts, kinds, titles and match tiers only: no Jellyfin ids, no paths, and
never the NAS host. The deploy window rule holds: the NAS is off 22:00-07:00.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

CONTAINER = "joey-hub"
ACTIONS = {"report": "--latest", "dry-run": "--dry-run", "apply": "--apply-report", "undo": "--undo"}
NEEDS_ID = ("apply", "undo")


def remote_command(action: str, run_id: int | None = None) -> str:
    flag = ACTIONS[action]
    tail = f" {int(run_id)}" if action in NEEDS_ID else ""
    return f"docker exec {CONTAINER} python -m hub.library_reattach {flag}{tail}"


def ssh_runner(nas: str, key: str):
    """run(remote_cmd) -> (rc, stdout); RuntimeError (with no host in it) when ssh itself fails."""
    def run(remote_cmd: str, timeout: float = 300.0) -> tuple[int, str]:
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
        if key and os.path.isfile(key):
            cmd += ["-i", key]
        cmd += [nas, remote_cmd]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except FileNotFoundError:
            raise RuntimeError("ssh not found on this computer") from None
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"ssh timed out after {timeout:.0f} s") from None
        if proc.returncode == 255:
            raise RuntimeError("ssh could not reach the NAS (is it on? 07:00-22:00)")
        return proc.returncode, proc.stdout.decode("utf-8", "replace")
    return run


def main(argv=None, runner=None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/joey_reattach.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=sorted(ACTIONS))
    ap.add_argument("run_id", nargs="?", type=int)
    args = ap.parse_args(argv)
    if args.action in NEEDS_ID and args.run_id is None:
        ap.error(f"{args.action} needs a RUN_ID (see: report)")
    if runner is None:
        runner = ssh_runner(os.environ.get("JOEY_NAS", "root@nas.local"),
                            os.path.expanduser(os.environ.get("JOEY_NAS_KEY", "~/.ssh/joey_nas")))
    try:
        rc, out = runner(remote_command(args.action, args.run_id))
    except RuntimeError as exc:
        print(f"FAIL  {args.action} - {exc}")
        return 1
    # only the hub CLI's own lines; anything else (a docker error naming paths) becomes one plain word
    lines = [line for line in out.splitlines() if line.startswith(("PASS ", "FAIL ", "      "))]
    print("\n".join(lines) if lines else f"FAIL  {args.action} - no answer from {CONTAINER} (exit {rc})")
    return 0 if rc == 0 and lines else 1


if __name__ == "__main__":
    sys.exit(main())
