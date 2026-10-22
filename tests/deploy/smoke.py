"""WP9 live smoke test — runs INSIDE the hub container after `up -d`:

    docker compose exec -T hub python tests/deploy/smoke.py

Reaches the hub on its own loopback (no published port needed, so it works
identically before and after WP11 removes the LAN override). Exit 0 = healthy;
any non-zero aborts the deploy and triggers the rollback tail.

Joey TV WP-B1 (2026-10-21): `--front {private,media}` (default private, the line above) and `--base` (default the
container's own loopback). deploy.sh runs `--front media` inside joey-media when the media profile is active:

    docker compose exec -T joey-media python tests/deploy/smoke.py --front media

Media checks: /healthz says front=media; private paths answer 404; /app/version.json is 200 JSON with an integer
versionCode, or 404 before the first TV release is published (Joey TV WP-B8); / answers 303 (to the guest home). Every media
request carries a forged Cf-Access-Authenticated-User-Email: the media front ignores it (never a 401, Q23).
Locally: `python tests/deploy/smoke.py --front media --base http://127.0.0.1:8850` against the joey-media preview.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
CHECKS = ["/healthz", "/"]
# MacroMates static server on the same compose network (2026-10-05) — part of
# the stack, so a deploy that leaves it unservable rolls back like any other.
EXTRA = ["http://macromates/"]
MEDIA_404 = ["/server", "/whoami", "/a/calendar", "/media/downloads", "/money", "/openapi.json"]
FORGED = {"Cf-Access-Authenticated-User-Email": "smoke-forged@example.test"}
TV_VERSION = "/app/version.json"   # public (Q37); 404 until deploy.sh first publishes a release


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None   # a 3xx is the answer, never followed


_opener = urllib.request.build_opener(_NoRedirect)


def fetch(url: str, headers: dict | None = None) -> tuple[int, bytes]:
    """(status, body) without following redirects; an HTTP error status is an answer, not an exception."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with _opener.open(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _front_of(body: bytes) -> str | None:
    try:
        return json.loads(body).get("front")
    except (ValueError, AttributeError):
        return None


def check_private(base: str) -> int:
    status, body = fetch(base + "/healthz")
    front = _front_of(body)
    if status != 200 or front not in (None, "private"):   # None: a hub from before WP-B1 (rollback target)
        print(f"SMOKE FAIL {base}/healthz: HTTP {status}, front={front}")
        return 1
    for url in [base + path for path in CHECKS] + EXTRA:
        try:
            status, _ = fetch(url)
        except Exception as exc:  # noqa: BLE001 — any failure fails the smoke
            print(f"SMOKE FAIL {url}: {exc}")
            return 1
        if status != 200:
            print(f"SMOKE FAIL {url}: HTTP {status}")
            return 1
        print(f"smoke ok {url}")
    return 0


def _tv_version_ok(status: int, body: bytes) -> bool:
    if status == 404:
        return True
    try:
        code = json.loads(body).get("versionCode")
    except (ValueError, AttributeError):
        return False
    return status == 200 and isinstance(code, int) and not isinstance(code, bool)


def check_media(base: str) -> int:
    expected = [("/healthz", 200)] + [(path, 404) for path in MEDIA_404] + [(TV_VERSION, None), ("/", 303)]
    for path, want in expected:
        url = base + path
        try:
            status, body = fetch(url, FORGED)
        except Exception as exc:  # noqa: BLE001
            print(f"SMOKE FAIL {url}: {exc}")
            return 1
        if path == TV_VERSION:
            if not _tv_version_ok(status, body):
                print(f"SMOKE FAIL {url}: HTTP {status}, expected 200 JSON with versionCode, or 404")
                return 1
            print(f"smoke ok {url} -> {status}")
            continue
        if status != want:
            print(f"SMOKE FAIL {url}: HTTP {status}, expected {want}")
            return 1
        if path == "/healthz" and _front_of(body) != "media":
            print(f"SMOKE FAIL {url}: front={_front_of(body)}, expected media")
            return 1
        print(f"smoke ok {url} -> {status}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Joey deploy smoke")
    parser.add_argument("--front", choices=("private", "media"), default="private")
    parser.add_argument("--base", default=BASE)
    args = parser.parse_args(argv)
    base = args.base.rstrip("/")
    return check_media(base) if args.front == "media" else check_private(base)


if __name__ == "__main__":
    sys.exit(main())
