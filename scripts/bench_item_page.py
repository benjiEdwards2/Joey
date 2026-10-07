"""Benchmark the Media film pages against a running hub (media-speed, 2026-10-07). Stdlib only.

    python scripts/bench_item_page.py [--url http://127.0.0.1:8000] [-n 8] [--images] [ids ...]

Without ids it collects /media/item/<id> links from /media/movies and /media/tv (films and shows alternately)
and opens each one twice: the first open is "cold" for any page not opened in the last 10 min (the hub's
short cache), the second is "warm". --images also fetches every /img ref on the page once (sequentially,
first view = cold for refs not yet in the hub's disk cache). Run it inside the hub container on the NAS
before and after a deploy (scripts/ is not in the image, so pipe it in):
    docker exec -i <hub container> python - -n 8 --images < scripts/bench_item_page.py
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
import time
import urllib.request
from html import unescape

ITEM_RE = re.compile(r'href="/media/item/([A-Za-z0-9-]{1,64})"')
IMG_RE = re.compile(r'(?:src="|url\(\')(/img/[^"\']+)')


def get(base: str, path: str) -> tuple[float, int, bytes]:
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(base + path, timeout=60) as resp:
            body, code = resp.read(), resp.status
    except Exception as exc:  # report and carry on
        print(f"  {path}: {type(exc).__name__}", file=sys.stderr)
        body, code = b"", 0
    return (time.perf_counter() - t0) * 1000, code, body


def collect(base: str, n: int) -> list[str]:
    lists = []
    for section in ("/media/movies", "/media/tv"):
        _, _, body = get(base, section)
        ids = list(dict.fromkeys(ITEM_RE.findall(body.decode("utf-8", "replace"))))
        lists.append(ids)
    out = []
    for pair in zip(*lists):
        out.extend(pair)
    for ids in lists:  # one list shorter than the other: top up from the longer one
        out.extend(i for i in ids if i not in out)
    return out[:n]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("-n", type=int, default=8)
    ap.add_argument("--images", action="store_true")
    ap.add_argument("ids", nargs="*")
    args = ap.parse_args()
    base = args.url.rstrip("/")
    ids = args.ids or collect(base, args.n)
    if not ids:
        sys.exit("no /media/item links found — is the hub up and the Jellyfin snapshot present?")
    cold, warm, img_ms = [], [], []
    print(f"{'item':<36} {'first':>8} {'second':>8} {'imgs':>5} {'img ms':>8}")
    for jf in ids:
        c_ms, code, body = get(base, f"/media/item/{jf}")
        w_ms, _, _ = get(base, f"/media/item/{jf}")
        cold.append(c_ms)
        warm.append(w_ms)
        refs = list(dict.fromkeys(unescape(m) for m in IMG_RE.findall(body.decode("utf-8", "replace"))))
        total = sum(get(base, r)[0] for r in refs) if args.images else 0.0
        if args.images:
            img_ms.append(total)
        print(f"{jf:<36} {c_ms:8.0f} {w_ms:8.0f} {len(refs):5d} {total:8.0f}" + ("" if code == 200 else f"  HTTP {code}"))
    print(f"median first open {statistics.median(cold):.0f} ms (max {max(cold):.0f}) | "
          f"median second open {statistics.median(warm):.0f} ms"
          + (f" | median images per page {statistics.median(img_ms):.0f} ms (sequential)" if img_ms else ""))


if __name__ == "__main__":
    main()
