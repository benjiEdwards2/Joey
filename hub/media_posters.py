"""JY-260 phase 1: pick each title's TMDB poster and render the Joey poster into a local cache (spec
docs/specs/JY-260-posters.md). Nothing here writes to Jellyfin; that is phase 2, behind B.'s own poster write key (Q4A).

* `POSTERS=off|dry|on` (default off). `dry`: the background loop (hub/tasks.py) renders up to POSTERS_PER_PASS titles
  per pass into POSTERS_DIR (default <IMG_CACHE_DIR>/posters): `<jf_id>.jpg` + `<jf_id>.json`. `on` is phase 2: for
  now it logs once and does exactly what `dry` does.
* The pick (Q3A): Jellyfin's own RemoteImages list for the item (its bundled TMDB key, no new secret). Text-less
  (no language) first, then English, then anything else; within each, more votes, then more pixels. Art is fetched
  only from image.tmdb.org, capped at 5 MB like /img.
* Order (Q9A): recently added first, then A-Z. A title re-renders when the template kit or its words change; a title
  with no TMDB poster is recorded (`no_source`) and not asked again until the template changes. An upstream failure
  writes nothing, so the next pass retries it.
* The review page (hub/media_posters_pages.py) reads only what this writes: no network on render.
Logs carry counts and exception types only, never a URL, key or name.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from hub import images, media_item, media_jellyfin, upstream
from hub import media_posters_render as render

log = logging.getLogger("hub.media_posters")

MODES = ("off", "dry", "on")
FIRST_DELAY_S = 180
EVERY_S = 3600
PER_PASS = 30
PAUSE_S = 2.0
TMDB_ART = "https://image.tmdb.org/t/p/"
DEFAULT_TEMPLATE_DIR = "/data/posters/template"
_warned_on = {"done": False}


def mode() -> str:
    v = os.environ.get("POSTERS", "").strip().lower()
    return v if v in MODES else "off"


def disabled() -> bool:
    return mode() == "off"


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.environ.get(name, "").strip())))
    except ValueError:
        return default


def per_pass() -> int:
    return _int_env("POSTERS_PER_PASS", PER_PASS, 1, 500)


def series_sub() -> bool:
    """The phase-2 switch for a series' "Seasons a–b · yyyy–yyyy" sub-line (default off)."""
    return os.environ.get("POSTERS_SERIES_SUB", "").strip().lower() in ("on", "1", "true", "yes")


def out_dir() -> Path:
    return Path(os.environ.get("POSTERS_DIR", "").strip() or images.cache_dir() / "posters")


def template_dir() -> Path:
    """B.'s kit (POSTERS_TEMPLATE_DIR, the NAS folder mounted read-only), else the starter kit in the image."""
    folder = Path(os.environ.get("POSTERS_TEMPLATE_DIR", "").strip() or DEFAULT_TEMPLATE_DIR)
    return folder if (folder / "template.json").is_file() else render.STARTER


def template_state() -> tuple[render.Template | None, list[str], bool]:
    """(template or None, problems, is_starter). Local files only."""
    folder = template_dir()
    try:
        return render.load_template(folder), [], folder == render.STARTER
    except render.TemplateError as exc:
        return None, exc.problems, folder == render.STARTER


# ---- the pick ----

def _lang_rank(lang) -> int:
    lang = (lang or "").strip().lower() if isinstance(lang, str) or lang is None else "?"
    return 0 if not lang else (1 if lang == "en" else 2)


def pick(remote) -> dict | None:
    """The poster to use from a RemoteImages `Images` list, or None. -> {url, lang, votes, width, height, fallback}."""
    best, best_key = None, None
    for im in remote if isinstance(remote, list) else []:
        if not isinstance(im, dict):
            continue
        url = im.get("Url")
        if not isinstance(url, str) or not url.startswith(TMDB_ART):
            continue
        votes = im.get("VoteCount") if isinstance(im.get("VoteCount"), int) else 0
        w = im.get("Width") if isinstance(im.get("Width"), int) else 0
        h = im.get("Height") if isinstance(im.get("Height"), int) else 0
        key = (_lang_rank(im.get("Language")), -votes, -(w * h))
        if best_key is None or key < best_key:
            lang = im.get("Language") or None
            best, best_key = {"url": url, "lang": lang, "votes": votes, "width": w, "height": h,
                              "fallback": (None, "en", "other")[key[0]]}, key
    return best


def remote_images(jf_id: str) -> list:
    """The item's TMDB poster list through Jellyfin (GET only). Raises on no answer / non-2xx."""
    creds = media_jellyfin.creds()
    if creds is None:
        raise RuntimeError("Jellyfin not configured")
    body = media_jellyfin.get(*creds, f"/Items/{jf_id}/RemoteImages",
                              {"type": "Primary", "providerName": "TheMovieDb", "includeAllLanguages": "true"})
    return (body or {}).get("Images") or [] if isinstance(body, dict) else []


def fetch_art(url: str) -> bytes | None:
    """The poster bytes from image.tmdb.org (GET, capped at images.MAX_BYTES), or None."""
    if not url.startswith(TMDB_ART):
        return None
    resp = upstream.session("tmdb").get(url, timeout=images.TIMEOUT, stream=True)
    try:
        if resp.status_code != 200:
            return None
        ctype = str(resp.headers.get("content-type", "")).split(";")[0].strip().lower()
        if ctype not in images.EXT:
            return None
        return images._read_capped(resp)
    finally:
        close = getattr(resp, "close", None)
        if close:
            close()


# ---- targets and the cache ----

def targets(jelly: dict) -> list[dict]:
    """Every film and series in the jellyfin snapshot (both profiles, de-duplicated), recently added first, then A-Z."""
    profiles = [jelly] + ([jelly["her"]] if isinstance(jelly.get("her"), dict) else [])
    out, seen = [], set()
    for prof in profiles:
        for field, kind in (("movies", "movie"), ("shows", "tv")):
            for r in prof.get(field) or []:
                jf = str(r.get("jf_id") or "") if isinstance(r, dict) else ""
                if not jf or jf in seen or not media_item.ITEM_RE.match(jf):
                    continue
                seen.add(jf)
                out.append({"jf_id": jf, "kind": kind, "title": str(r.get("title") or ""),
                            "year": r.get("year") if isinstance(r.get("year"), int) else None,
                            "added_at": str(r.get("added_at") or "")})
    return order(out)


def order(rows: list[dict]) -> list[dict]:
    """Q9A: recently added first, then A-Z (case-insensitive)."""
    rows = sorted(rows, key=lambda r: (r.get("title") or "").casefold())
    return sorted(rows, key=lambda r: r.get("added_at") or "", reverse=True)


def _text_hash(title: str, sub: str) -> str:
    return hashlib.sha256(f"{title}\0{sub}".encode("utf-8")).hexdigest()[:12]


def _read_side(path: Path) -> dict | None:
    try:
        side = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return side if isinstance(side, dict) else None


def _write_atomic(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.stem[:16] + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rows() -> list[dict]:
    """The cache's sidecars, Q9A order (the review page; local files only)."""
    folder = out_dir()
    try:
        paths = sorted(folder.glob("*.json"))
    except OSError:
        return []
    out = []
    for path in paths:
        side = _read_side(path)
        if side and media_item.ITEM_RE.match(str(side.get("jf_id") or "")) and path.stem == side["jf_id"]:
            out.append(side)
    return order(out)


def image_path(jf_id: str) -> Path | None:
    """The rendered JPEG for a Jellyfin id, or None (bad id / not rendered)."""
    if not media_item.ITEM_RE.match(jf_id or ""):
        return None
    path = out_dir() / f"{jf_id}.jpg"
    return path if path.is_file() else None


# ---- the pass ----

def dry_pass(snaps: dict, pause: float = PAUSE_S, limit: int | None = None) -> dict:
    """Render what is new or stale into the cache, at most `limit` (POSTERS_PER_PASS). Never writes to Jellyfin.
    -> counts {titles, rendered, cached, no_source, failed} (+ template_error); never raises."""
    m = mode()
    if m == "off":
        return {"off": True}
    if m == "on" and not _warned_on["done"]:
        _warned_on["done"] = True
        log.warning("POSTERS=on is phase 2 (not built): rendering only, as dry")
    counts = {"titles": 0, "rendered": 0, "cached": 0, "no_source": 0, "failed": 0}
    tpl, problems, _ = template_state()
    if tpl is None:
        counts["template_error"] = len(problems)
        log.warning("posters: template not used (%s problems)", len(problems))
        return counts
    snap = (snaps or {}).get("jellyfin")   # the caller (hub.tasks) reads the snapshots: this module never does
    jelly = getattr(snap, "data", snap) or {}
    folder = out_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("posters: cache folder unavailable: %s", type(exc).__name__)
        counts["failed"] = 1
        return counts
    limit = per_pass() if limit is None else limit
    started = time.time()
    for t in targets(jelly if isinstance(jelly, dict) else {}):
        if counts["rendered"] + counts["no_source"] + counts["failed"] >= limit:
            break
        counts["titles"] += 1
        sub = render.sub_line(t["kind"], year=t["year"], series_sub=series_sub())
        text = _text_hash(t["title"], sub)
        side = _read_side(folder / f"{t['jf_id']}.json")
        if side and side.get("template") == tpl.version and (side.get("text") == text
                                                              or side.get("status") == "no_source"):
            counts["cached"] += 1
            continue
        try:
            chosen = pick(remote_images(t["jf_id"]))
            art = fetch_art(chosen["url"]) if chosen else None
            base = {**t, "sub": sub, "template": tpl.version, "text": text, "rendered_at": _now(),
                    "pick": {k: chosen[k] for k in ("lang", "votes", "width", "height", "fallback")} if chosen else None}
            if chosen is None:
                base["status"] = "no_source"
                counts["no_source"] += 1
            elif art is None:
                raise RuntimeError("art unavailable")
            else:
                _write_atomic(folder / f"{t['jf_id']}.jpg", render.render(tpl, art, t["title"], sub))
                base["status"] = "rendered"
                counts["rendered"] += 1
            _write_atomic(folder / f"{t['jf_id']}.json", json.dumps(base).encode("utf-8"))
        except Exception as exc:   # one bad title never stops the pass; nothing written, so it retries next pass
            counts["failed"] += 1
            log.warning("posters: title failed: %s", type(exc).__name__)
        if pause:
            time.sleep(pause)
    counts["seconds"] = round(time.time() - started, 1)
    if counts["rendered"] or counts["no_source"] or counts["failed"]:
        log.info("posters (%s): %s rendered, %s no TMDB poster, %s failed, %s cached, %s s", m, counts["rendered"],
                 counts["no_source"], counts["failed"], counts["cached"], counts["seconds"])
    return counts
