"""WP9 live smoke test — runs INSIDE the hub container after `up -d`:

    docker compose exec -T hub python tests/deploy/smoke.py

Reaches the hub on its own loopback (no published port needed, so it works
identically before and after WP11 removes the LAN override). Exit 0 = healthy;
any non-zero aborts the deploy and triggers the rollback tail.
"""

import sys
import urllib.request

BASE = "http://127.0.0.1:8000"
CHECKS = ["/healthz", "/"]
# MacroMates static server on the same compose network (2026-10-05) — part of
# the stack, so a deploy that leaves it unservable rolls back like any other.
EXTRA = ["http://macromates/"]


def main() -> int:
    for url in [BASE + path for path in CHECKS] + EXTRA:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status != 200:
                    print(f"SMOKE FAIL {url}: HTTP {r.status}")
                    return 1
        except Exception as exc:  # noqa: BLE001 — any failure fails the smoke
            print(f"SMOKE FAIL {url}: {exc}")
            return 1
        print(f"smoke ok {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
