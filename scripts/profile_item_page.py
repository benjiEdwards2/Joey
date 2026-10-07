"""Local profile of the film page's cold open with faked upstreams (no network, no NAS).

Every faked Jellyfin / Jellyseerr GET sleeps LATENCY seconds and is logged with its start/end
offset, so the output shows which live calls a cold open makes, and which overlap.

    python scripts/profile_item_page.py [latency_s]

Uses the test fixtures (tests/hub/test_media_item.py + test_media_film.py) — run from the repo root.
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

LATENCY = float(sys.argv[1]) if len(sys.argv) > 1 else 0.3


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="joey-prof-"))
    from tests.hub import test_media_film as tf, test_media_item as ti
    from tests.hub.test_registry import make_area, make_tile, write_registry
    from tests.hub.test_store import write_envelope

    area = tf.shelf_area()
    area["tiles"].append(make_tile("disc-t", snapshot="jellyseerr", stale_after_minutes=180, detail="/media/discover"))
    env = {"AREAS_PATH": str(write_registry(tmp, area, make_area("beta"))), "MEDIA_DB_PATH": str(tmp / "media.db"),
           "SNAPSHOT_DIR": str(tmp / "snaps"), "PLAY_RECORDER": "off", "MEDIA_BACKUP": "off", "MEDIA_WARMUP": "off",
           "IMG_CACHE_DIR": str(tmp / "img"), "META_CACHE_DIR": str(tmp / "meta"),
           "JELLYFIN_URL": ti.URL, "JELLYFIN_API_KEY": ti.KEY, "JELLYSEERR_URL": tf.SEERR, "JELLYSEERR_API_KEY": tf.SKEY}
    os.environ.update(env)
    os.environ.pop("JELLYFIN_USER", None)
    write_envelope(tmp / "snaps", "jellyfin", age_minutes=1,
                   data={"summary": "x", "server_id": "srv-1", "movies": tf.LIB_MOVIES, "shows": tf.LIB_SHOWS,
                         "up_next": [{"title": "Quiet Show · S04E03", "jf_id": "ep3", "item_key": "jf:ser1", "show_key": "jf:ser1"}]})
    write_envelope(tmp / "snaps", "arr", age_minutes=1, data={"summary": "x"})
    write_envelope(tmp / "snaps", "jellyseerr", age_minutes=1, data={"summary": "x", "requests": []})

    import hub.main
    importlib.reload(hub.main)
    from fastapi.testclient import TestClient
    from hub import media_discover, media_files, media_item

    both = tf.Both()
    log: list[tuple[float, float, str, int]] = []
    lock = threading.Lock()
    t0 = [0.0]

    def slow_get(url, params=None, headers=None, timeout=None, **kw):
        start = time.perf_counter()
        time.sleep(LATENCY)
        resp = both.get(url, params=params, headers=headers, timeout=timeout)
        with lock:
            short = url.replace(ti.URL, "JF").replace(tf.SEERR, "SEERR")
            log.append((start - t0[0], time.perf_counter() - t0[0], short, resp.status_code))
        return resp

    requests.get = slow_get
    client = TestClient(hub.main.app)

    def clear():
        for fn in (media_files.clear_cache, media_item.clear_cache, media_discover.clear_cache):
            fn()
        meta = getattr(media_discover, "clear_meta", None)
        if meta:
            meta(disk=True)

    with client:
        for path in ("/media/item/mov1", "/media/item/ser1", "/media/item/ep3"):
            for label in ("cold", "warm"):
                if label == "cold":
                    clear()
                log.clear()
                t0[0] = time.perf_counter()
                r = client.get(path)
                ms = (time.perf_counter() - t0[0]) * 1000
                print(f"{path} {label}: {ms:.0f} ms, HTTP {r.status_code}, {len(log)} live calls")
                for start, end, url, code in sorted(log):
                    print(f"    {start * 1000:6.0f}-{end * 1000:6.0f} ms  {code}  {url}")


if __name__ == "__main__":
    main()
