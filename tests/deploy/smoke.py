"""WP9 live smoke test — runs INSIDE the hub container after `up -d`:

    docker compose exec -T hub python tests/deploy/smoke.py

Reaches the hub on its own loopback (no published port needed, so it works
identically before and after WP11 removes the LAN override). Exit 0 = healthy;
any non-zero aborts the deploy and triggers the rollback tail.
"""

import sys
import urllib.request

# WP9 drill (c): dead port — the real base is http://127.0.0.1:8000 (reverted
# right after the drill; the rollback tail must fire and restore PREV_SHA).
BASE = "http://127.0.0.1:9999"
CHECKS = ["/healthz", "/"]


def main() -> int:
    for path in CHECKS:
        try:
            with urllib.request.urlopen(BASE + path, timeout=5) as r:
                if r.status != 200:
                    print(f"SMOKE FAIL {path}: HTTP {r.status}")
                    return 1
        except Exception as exc:  # noqa: BLE001 — any failure fails the smoke
            print(f"SMOKE FAIL {path}: {exc}")
            return 1
        print(f"smoke ok {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
