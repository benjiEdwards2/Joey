"""Media warm-up (media-speed, 2026-10-07): keep the film pages B. actually taps warm.

~60 s after startup and then every few hours, a background pass walks the titles on the Media home shelves
(Continue watching / Up next, Playing now, Recently added, Recently watched — both profiles), at most
MAX_TITLES, one at a time with a short pause, and:
  * reads each title's Jellyseerr body + ratings (ratings land in the long, restart-proof meta cache);
  * pre-fetches the film page's poster, backdrop and top-billed cast photos through the /img disk cache.
Everything it touches is cached, so a repeat pass is a handful of stats and short reads — cheap to run again
after the NAS's overnight power-off. MEDIA_WARMUP=off disables it; no Jellyseerr / Jellyfin keys = skipped.
"""

from __future__ import annotations

import logging
import os
import time

from hub import images, media_discover as md, media_files

log = logging.getLogger("hub.media_warmup")

FIRST_DELAY_S = 60
EVERY_S = 3 * 3600
MAX_TITLES = 60
PAUSE_S = 0.5
CAST_WARM = 8           # the film page shows CAST_MAX (8) cast photos
POSTER_H, BACKDROP_H, CAST_H = 600, 1280, 120   # the sizes media_film.html asks /img for


def disabled() -> bool:
    return os.environ.get("MEDIA_WARMUP", "on").strip().lower() in ("off", "0", "false", "no")


def targets(jelly: dict, limit: int = MAX_TITLES) -> list[dict]:
    """[{kind, tmdb, art}] — the distinct titles behind the home shelves, shelf order, capped at `limit`.
    `art` is the Jellyfin id the film page draws its poster / backdrop from (the show for an episode)."""
    from hub.media_film import tmdb_hint

    profiles = [jelly] + ([jelly["her"]] if isinstance(jelly.get("her"), dict) else [])
    out, seen = [], set()
    for prof in profiles:
        rows = ((prof.get("now_playing") or []) + (prof.get("up_next") or []) + (prof.get("latest") or [])
                + ((prof.get("history") or {}).get("recent") or []))
        for r in rows:
            if not isinstance(r, dict) or not r.get("jf_id"):
                continue
            hint = tmdb_hint(jelly, str(r["jf_id"]))
            if hint is None or hint in seen:
                continue
            seen.add(hint)
            show = str(r.get("show_key") or "")
            art = show[3:] if show.startswith("jf:") else str(r["jf_id"])
            out.append({"kind": hint[0], "tmdb": hint[1], "art": art})
            if len(out) >= limit:
                return out
    return out


def warm_once(snaps=None, pause: float = PAUSE_S, limit: int = MAX_TITLES) -> dict:
    """One bounded, idempotent pass. -> counts (for the log and the tests); never raises."""
    from hub import media_film
    from hub.store import get_snapshots

    seerr, jf = md._creds() is not None, media_files._creds() is not None
    counts = {"titles": 0, "fetched": 0, "cached": 0, "skipped": 0}
    if not (seerr or jf):
        counts["skipped_no_keys"] = True
        return counts
    snaps = get_snapshots() if snaps is None else snaps
    snap = snaps.get("jellyfin")
    jelly = (snap.data if snap else {}) or {}

    def img(ref, h):
        if ref:
            counts[images.warm(ref, h)] += 1

    if jf:
        try:  # the Jellyfin user id every item read needs (cached an hour)
            media_files._user_id(*media_files._creds())
        except Exception as exc:
            log.warning("media warm-up user lookup failed: %s", type(exc).__name__)
    for t in targets(jelly, limit):
        counts["titles"] += 1
        try:
            if jf:
                img(f"jf:{t['art']}", POSTER_H)
                img(f"jfb:{t['art']}", BACKDROP_H)
            if seerr:
                body = media_film._cget(f"/api/v1/{t['kind']}/{t['tmdb']}")
                media_film._ratings(t["kind"], t["tmdb"])
                for c in media_film._cast(body if isinstance(body, dict) else {}, [])[:CAST_WARM]:
                    img(c["ref"], CAST_H)
        except Exception as exc:  # one bad title never stops the pass
            log.warning("media warm-up title failed: %s", type(exc).__name__)
        if pause:
            time.sleep(pause)
    log.info("media warm-up: %(titles)s titles, %(fetched)s images fetched, %(cached)s already cached", counts)
    return counts
