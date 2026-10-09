"""Media warm-up (media-speed, 2026-10-07): keep the film pages B. actually taps warm.

~60 s after startup and then every few hours, a background pass walks the titles on the Media home shelves
(Continue watching / Up next, Playing now, Recently added, Recently watched — both profiles), at most
MAX_TITLES, one at a time with a short pause, and:
  * reads each title's Jellyseerr body + ratings (ratings land in the long, restart-proof meta cache);
  * pre-fetches the film page's poster, backdrop and top-billed cast photos through the /img disk cache.
Everything it touches is cached, so a repeat pass is a handful of stats and short reads — cheap to run again
after the NAS's overnight power-off. MEDIA_WARMUP=off disables it; no Jellyseerr / Jellyfin keys = skipped.

Library pass (media-warm-library, 2026-10-07): after the shelf pass, at most once per 24 h (stamp file in the
meta cache dir), the same walk covers the WHOLE library — jellyfin snapshot movies + shows, both profiles,
de-duplicated — warming exactly what /media/item/{jf_id} renders: poster h=600, backdrop h=1280, the list-row
poster h=240 (/media/movies, /media/tv; media-ux2), the
top-CAST_MAX (8) cast photos at the portrait-card size (CAST_H, h=400 since film-quality), plus the title's ratings and body through the 6 h disk meta cache. Cached
images cost a stat; the pass is sequential with a pause between upstream fetches. MEDIA_WARMUP=shelves keeps
only the shelf pass.
"""

from __future__ import annotations

import logging
import os
import time

from hub import images, media_discover as md, media_files, media_item, media_rank
from hub.media_film import CAST_H as FILM_CAST_H, CAST_MAX

log = logging.getLogger("hub.media_warmup")

FIRST_DELAY_S = 60
EVERY_S = 3 * 3600
MAX_TITLES = 60
PAUSE_S = 0.5
CAST_WARM = CAST_MAX    # the film page shows CAST_MAX (8) cast photos
POSTER_H, BACKDROP_H, CAST_H = 600, 1280, FILM_CAST_H   # the sizes media_film.html asks /img for (cast: portrait cards)
LIST_POSTER_H = 240   # media-ux2: the Movies / TV Shows list rows' poster (_library_row.html asks h=240)


LIBRARY_EVERY_S = 24 * 3600
LIBRARY_PAUSE_S = 0.3
STAMP = "warmup_library.stamp"


def disabled() -> bool:
    return os.environ.get("MEDIA_WARMUP", "on").strip().lower() in ("off", "0", "false", "no")


def library_enabled() -> bool:
    return os.environ.get("MEDIA_WARMUP", "on").strip().lower() not in ("off", "0", "false", "no", "shelves")


def _stamp_path():
    return md.meta_dir() / STAMP


def library_due(now: float | None = None) -> bool:
    """True when the last completed full-library pass is over LIBRARY_EVERY_S old (or there never was one)."""
    try:
        last = float(_stamp_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    return (time.time() if now is None else now) - last >= LIBRARY_EVERY_S


def _stamp_done() -> None:
    try:
        path = _stamp_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(time.time()), encoding="utf-8")
    except OSError as exc:
        log.warning("media warm-up stamp write failed: %s", type(exc).__name__)


def library_targets(jelly: dict) -> list[dict]:
    """[{kind, tmdb|None, art}] — every film and show in the jellyfin snapshot, both profiles, de-duplicated by
    Jellyfin id. `art` is the id the item page draws poster / backdrop from (the item itself)."""
    profiles = [jelly] + ([jelly["her"]] if isinstance(jelly.get("her"), dict) else [])
    out, seen = [], set()
    for prof in profiles:
        for field, kind in (("movies", "movie"), ("shows", "tv")):
            for r in prof.get(field) or []:
                jf = str(r.get("jf_id") or "") if isinstance(r, dict) else ""
                if not jf or jf in seen or not media_item.ITEM_RE.match(jf):
                    continue
                seen.add(jf)
                key = str(r.get("item_key") or "")
                out.append({"kind": kind, "tmdb": int(key[5:]) if key.startswith("tmdb:") and key[5:].isdigit() else None,
                            "art": jf})
    return out


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


def warm_library(snaps=None, pause: float = LIBRARY_PAUSE_S) -> dict:
    """The full-library pass. -> counts {titles, fetched, cached, skipped, failed}; never raises. Per title: poster
    h=600 + backdrop h=1280 (Jellyfin), ratings + body via the 6 h disk meta cache, cast photos at CAST_H (what the
    item page renders). An image the upstream doesn't have (no backdrop, a 404 poster: images.warm's "skipped") is
    an answer, not a failure (M-44); `failed` counts only titles that raised."""
    from hub import media_film
    from hub.store import get_snapshots

    started = time.time()
    seerr, jf = md._creds() is not None, media_files._creds() is not None
    counts = {"titles": 0, "fetched": 0, "cached": 0, "skipped": 0, "failed": 0}
    if not (seerr or jf):
        counts["skipped_no_keys"] = True
        return counts
    snaps = get_snapshots() if snaps is None else snaps
    snap = snaps.get("jellyfin")
    jelly = (snap.data if snap else {}) or {}

    def img(ref, h):
        if ref:
            got = images.warm(ref, h)
            counts[got] += 1
            return got

    def rest():
        if pause:
            time.sleep(pause)

    if jf:
        try:
            media_files._user_id(*media_files._creds())
        except Exception as exc:
            log.warning("media library warm-up user lookup failed: %s", type(exc).__name__)
    for t in library_targets(jelly):
        counts["titles"] += 1
        try:
            if jf:
                for ref, h in ((f"jf:{t['art']}", POSTER_H), (f"jfb:{t['art']}", BACKDROP_H),
                               (f"jf:{t['art']}", LIST_POSTER_H)):
                    if img(ref, h) == "fetched":
                        rest()
            if seerr and t["tmdb"]:
                before = md._cache.get(f"meta:/api/v1/{t['kind']}/{t['tmdb']}")
                body = md.meta_get(f"/api/v1/{t['kind']}/{t['tmdb']}")
                media_film._ratings(t["kind"], t["tmdb"])
                if before is None and md._cache.get(f"meta:/api/v1/{t['kind']}/{t['tmdb']}", (0, 0))[0] > started:
                    rest()
                for c in media_film._cast(body if isinstance(body, dict) else {}, [])[:CAST_WARM]:
                    if img(c["ref"], CAST_H) == "fetched":
                        rest()
        except Exception as exc:
            counts["failed"] += 1
            log.warning("media library warm-up title failed: %s", type(exc).__name__)
    counts["seconds"] = round(time.time() - started, 1)
    log.info("media library warm-up: %(titles)s titles, %(fetched)s images fetched, %(cached)s already cached, "
             "%(skipped)s not upstream, %(failed)s failures, %(seconds)s s", counts)
    return counts


def run_pass(snaps=None, pause: float = PAUSE_S) -> dict:
    """What the background loop runs: the shelf pass, then — unless MEDIA_WARMUP=shelves — the library pass when
    it is due (24 h); first, meta cache files older than 7 days are deleted. The stamp is written after every completed pass (M-44: a missing backdrop or one bad title no
    longer re-runs the whole library every 3 h); a pass skipped for want of keys leaves it unstamped."""
    out = {"pruned": md.prune_meta(), "shelves": warm_once(snaps, pause)}   # M-47: the disk meta cache stays bounded
    if media_rank.due():  # film-quality: the File panel's library rank, one Jellyfin read per 24 h
        out["rank"] = media_rank.refresh()
    if library_enabled() and library_due():
        lib = warm_library(snaps)
        out["library"] = lib
        if not lib.get("skipped_no_keys"):
            _stamp_done()
    return out
