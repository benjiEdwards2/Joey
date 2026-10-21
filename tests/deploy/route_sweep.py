"""Joey TV WP-B1 (2026-10-21) — the route sweep for the WP-B5 BG2 live check of the guest front.

    python tests/deploy/route_sweep.py --base https://media.joeyhome.net [--jf-id <32 hex>] [--ref <img ref>]
                                       [--area-id calendar] [--cookie "<name>=<value>"]

Imports hub.guest's tables, fills every path parameter from a fixed id table, and sends EVERY PRIVATE (method, path)
pair with its own verb (POST / DELETE included, empty body) plus every GET template of the GUEST and RESERVED tables.
Prints one line per request: method, path, status, sha256 of the body (the 404 page's hash is the same for every
private path). It never follows a redirect. It runs from the repo root (it imports hub.guest), and it does not
judge: WP-B5 compares the lines (every PRIVATE line 404 with the hash of /no-such-page).
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hub import guest  # noqa: E402

FIXED = {"kind": "movie", "tmdb_id": "603", "provider_id": "8", "person_id": "287", "name": "x", "n": "1",
         "item_key": "movie:603", "rid": "1", "app": "radarr", "arr_id": "1", "year": "2026", "path:path": "x",
         "rest:path": "x"}
UNKNOWN = "/no-such-page"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fill(template: str, args) -> str:
    values = {**FIXED, "jf_id": args.jf_id, "ref:path": args.ref, "area_id": args.area_id}
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", value)
    if "{" in out:
        raise ValueError(f"no fixed value for a parameter in {template}")
    return out


def plan(args) -> list[tuple[str, str]]:
    """(method, path): the unknown path first, then every PRIVATE pair, then every GET of GUEST and RESERVED."""
    pairs = [("GET", UNKNOWN)] + [(m, fill(t, args)) for m, t in guest.PRIVATE]
    pairs += [("GET", fill(t, args)) for m, t in guest.GUEST + guest.RESERVED if m == "GET"]
    return list(dict.fromkeys(pairs))


def send(opener, base: str, method: str, path: str, cookie: str | None) -> tuple[int, str]:
    headers = {"Cookie": cookie} if cookie else {}
    data = b"" if method in ("POST", "DELETE", "PUT") else None
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with opener.open(req, timeout=15) as r:
            status, body = r.status, r.read()
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read()
    return status, hashlib.sha256(body).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sweep the guest front's route tables")
    parser.add_argument("--base", required=True)
    parser.add_argument("--jf-id", default="0" * 32)
    parser.add_argument("--ref", default="x")
    parser.add_argument("--area-id", default="calendar")
    parser.add_argument("--cookie")
    args = parser.parse_args(argv)
    base = args.base.rstrip("/")
    opener = urllib.request.build_opener(_NoRedirect)
    for method, path in plan(args):
        status, digest = send(opener, base, method, path, args.cookie)
        print(f"{method:6} {path} {status} {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
