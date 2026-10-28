"""JY-260 phase 2: write the stored Joey posters back to Jellyfin (spec docs/specs/JY-260-posters.md, "Phase 2").

Runs only with POSTERS=on AND JELLYFIN_POSTER_API_KEY set (Q4A: B.'s own key, revocable on its own). With POSTERS=on
and no key it logs one line and writes nothing; the local store is still served by /img.

Per item, in order (each step must succeed before the next):
  1. backup, once: the item's current Primary image (GET /Items/{id}/Images/Primary, no size params = the original)
     into the store as `orig.<ext>`, and its ImageTags.Primary into media.db. An item with no Primary records "none".
  2. upload: POST /Items/{id}/Images/Primary, the master JPEG base64-encoded.
  3. lock (Q5A): LockData true through POST /Items/{id} with the item's full DTO, only when it was not locked already
     (then `locked_by_us`, so a revert unlocks only what Joey locked).
  4. read back the new ImageTags.Primary and store it as `live_tag`.
`wrote` + `pending_ver` are recorded BEFORE every upload and `live_ver` straight after it, so a failure (or a crash)
between the upload and the lock / read-back is finished by the next pass, and a revert always restores the original
when any Joey write may have happened. Idempotent: an item whose stored version is live and whose tag still matches is
not written again. Once a day per item the live tag is compared: back to the original (or none) = drift, re-applied
once and logged; a tag that is neither Joey's upload nor the original = a hand-set poster (`manual`): left alone, not
re-applied, and a revert leaves it in Jellyfin unless B. asks for the original (orchestrator default 2026-10-28, B.
may override). Revert puts the backup back (or deletes the Primary when there was none) and unlocks what Joey locked;
it is recorded first, so a revert asked for while the key is missing is carried out by the next pass that has it.
An item that fails 3 times in a row backs off for 24 h (media_posters.record_failure), so it cannot hold the pass;
"Try again now" repeats what failed (a revert retries the revert), never a re-apply.
Every write and every revert of an item runs under that item's lock (media_posters.claim: one atomic UPDATE in
media.db, so it holds across threads and processes); `apply` re-reads `reverted` under the lock, and a revert waits
for an in-flight write (REVERT_WAIT_S) or queues itself. A revert reports "reverted" only after a re-read confirms
Jellyfin holds the original again.
Logs carry counts and exception types only, never a URL, key or name.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from hub import media_posters as mp, media_posters_store as store, upstream

log = logging.getLogger("hub.media_posters_write")

KEY_ENV = "JELLYFIN_POSTER_API_KEY"
DRIFT_S = 24 * 3600
TIMEOUT = 20
MAX_ORIG_BYTES = 20 * 1024 * 1024
CTYPE = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
EXT = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
REVERT_WAIT_S = 10.0   # a web revert waits this long for an in-flight write of the item, then queues itself
_warned = {"no_key": False}


def creds() -> tuple[str, dict] | None:
    base, key = os.environ.get("JELLYFIN_URL", "").strip(), os.environ.get(KEY_ENV, "").strip()
    if not (base and key):
        return None
    return base.rstrip("/"), {"Authorization": f"MediaBrowser Token={key}"}


def enabled() -> bool:
    """POSTERS=on and the write key is set. POSTERS=on without it: one clear log line, no writes."""
    if mp.mode() != "on":
        return False
    if creds() is None:
        if not _warned["no_key"]:
            _warned["no_key"] = True
            log.warning("posters: POSTERS=on but %s is not set: no Jellyfin writes, the local store is served only",
                        KEY_ENV)
        return False
    return True


class WriteError(RuntimeError):
    pass


def _ok(resp, what: str):
    if not 200 <= resp.status_code < 300:
        raise WriteError(f"{what}: HTTP {resp.status_code}")
    return resp


def _item(base: str, headers: dict, jf_id: str) -> dict:
    resp = _ok(upstream.session("jellyfin").get(f"{base}/Items/{jf_id}", headers=headers, timeout=TIMEOUT), "item")
    body = resp.json()
    if not isinstance(body, dict):
        raise WriteError("item: not an object")
    return body


def _tag(item: dict) -> str | None:
    tags = item.get("ImageTags") if isinstance(item.get("ImageTags"), dict) else {}
    return tags.get("Primary") or None


def _read_orig(base: str, headers: dict, jf_id: str) -> tuple[bytes, str]:
    resp = upstream.session("jellyfin").get(f"{base}/Items/{jf_id}/Images/Primary", headers=headers, timeout=TIMEOUT,
                                           stream=True)
    try:
        _ok(resp, "original")
        ctype = str(resp.headers.get("content-type", "")).split(";")[0].strip().lower()
        if ctype not in EXT:
            raise WriteError("original: not an image")
        body = bytearray()
        for chunk in resp.iter_content(64 * 1024):
            body += chunk or b""
            if len(body) > MAX_ORIG_BYTES:
                raise WriteError("original: too large")
        if not body:
            raise WriteError("original: empty")
        return bytes(body), EXT[ctype]
    finally:
        close = getattr(resp, "close", None)
        if close:
            close()


def _upload(base: str, headers: dict, jf_id: str, body: bytes, ctype: str) -> None:
    _ok(upstream.session("jellyfin").post(f"{base}/Items/{jf_id}/Images/Primary", data=base64.b64encode(body),
                                          headers={**headers, "Content-Type": ctype}, timeout=TIMEOUT), "upload")


def _set_lock(base: str, headers: dict, item: dict, on: bool) -> None:
    _ok(upstream.session("jellyfin").post(f"{base}/Items/{item['Id']}", json={**item, "LockData": on},
                                          headers=headers, timeout=TIMEOUT), "lock")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _due(stamp, now: datetime) -> bool:
    try:
        return now - datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) \
            >= timedelta(seconds=DRIFT_S)
    except ValueError:
        return True


def backup(base: str, headers: dict, jf_id: str, item: dict) -> None:
    """Save the current Primary image + its tag, once. Raises (and nothing is written) when it cannot."""
    tag = _tag(item)
    if tag is None:
        mp.set_state(jf_id, orig_ext="none", orig_tag="")
        return
    body, ext = _read_orig(base, headers, jf_id)
    store.save_orig(jf_id, body, ext)
    mp.set_state(jf_id, orig_ext=ext, orig_tag=tag)


def _fail(jf_id: str, exc: Exception, what: str) -> str:
    mp.record_failure(jf_id, type(exc).__name__ + (f": {exc}" if isinstance(exc, WriteError) else ""))
    log.warning("posters: %s failed: %s", what, type(exc).__name__)
    return "error"


def _finish(base: str, headers: dict, jf_id: str, row: dict) -> None:
    """After an upload: lock (when Jellyfin had not) and read back the new tag. Raises on failure (the next pass
    finishes it; `wrote` and `live_ver` are already recorded, so a revert restores the original meanwhile)."""
    item = _item(base, headers, jf_id)
    locked = bool(row.get("locked_by_us"))
    if not item.get("LockData"):
        mp.set_state(jf_id, locked_by_us=1)   # recorded first: a revert unlocks even if the lock answer was lost
        _set_lock(base, headers, item, True)
        locked = True
        item = _item(base, headers, jf_id)
    mp.set_state(jf_id, live_tag=_tag(item), locked_by_us=int(locked), checked_at=_now(), last_error=None, fails=0,
                 retry_at=None)


def _owner() -> str:
    return f"{os.getpid()}-{threading.get_ident()}-{uuid.uuid4().hex[:8]}"


def apply(jf_id: str) -> str:
    """Write one item's stored poster, under the item's lock. -> 'written', 'reapplied' (after drift), 'finished' (an
    earlier write's lock / read-back completed), 'unchanged', 'manual' (B. changed it in Jellyfin: left alone),
    'skipped' (incl. reverted, or the item is locked by a revert) or 'error'."""
    if creds() is None or mp.state(jf_id) is None:
        return "skipped"
    owner = _owner()
    if not mp.claim(jf_id, owner):
        return "skipped"   # a revert holds it: never write over it
    try:
        return _apply_locked(jf_id)
    finally:
        mp.release(jf_id, owner)


def _apply_locked(jf_id: str) -> str:
    row = mp.state(jf_id) or {}   # re-read under the lock: a revert that got in first is seen here
    if (row.get("reverted") or row.get("manual") or row.get("status") != "rendered"
            or store.current(jf_id) != row.get("ver")):
        return "skipped"
    master = store.master(jf_id, row["ver"])
    if master is None:
        return "skipped"
    base, headers = creds()
    ver = row["ver"]
    try:
        item = _item(base, headers, jf_id)
        live = _tag(item)
        drift = False
        if not row.get("pending_ver") and row.get("live_ver") == ver and not row.get("live_tag"):
            _finish(base, headers, jf_id, row)   # uploaded, but the lock / read-back did not complete
            return "finished"
        if not row.get("pending_ver") and row.get("live_tag"):
            if live == row["live_tag"]:
                if row.get("live_ver") == ver:
                    mp.set_state(jf_id, checked_at=_now())
                    return "unchanged"
            elif live not in (row.get("orig_tag") or None, None):
                # neither Joey's last upload nor the backed-up original: B. (or someone) set this poster by hand.
                # Orchestrator default (2026-10-28, B. may override): his change wins; Joey stops re-applying.
                mp.set_state(jf_id, manual=1, checked_at=_now())
                log.warning("posters: a Jellyfin poster was changed by hand; left alone (marked manual)")
                return "manual"
            else:
                drift = True   # back to the original (or no image): a refresh undid Joey's poster
        if row.get("orig_ext") is None:
            backup(base, headers, jf_id, item)   # the backup comes first: no backup, no write
        mp.set_state(jf_id, wrote=1, pending_ver=ver)   # recorded BEFORE the upload: a crash after it is still undone
        _upload(base, headers, jf_id, master.read_bytes(), "image/jpeg")
        mp.set_state(jf_id, live_ver=ver, live_tag=None, pending_ver=None, written_at=_now())
        _finish(base, headers, jf_id, mp.state(jf_id) or {})
        if drift:
            log.warning("posters: a Jellyfin poster had been reset under Joey; re-applied")
            return "reapplied"
        return "written"
    except Exception as exc:
        return _fail(jf_id, exc, "write")


def _confirm_restored(base: str, headers: dict, jf_id: str, row: dict) -> None:
    """Re-read Jellyfin after a restore: the original's bytes are back (or, when there was none, no Primary).
    Raises WriteError when they are not, so a revert is never reported done on faith."""
    if row.get("orig_ext") == "none":
        if _tag(_item(base, headers, jf_id)) is not None:
            raise WriteError("revert not confirmed: an image is still set")
        return
    body, _ = _read_orig(base, headers, jf_id)
    path = store.orig_path(jf_id)
    if path is None or hashlib.sha256(body).digest() != hashlib.sha256(path.read_bytes()).digest():
        raise WriteError("revert not confirmed: Jellyfin does not hold the original")


def _undo_locked(jf_id: str) -> str:
    """Put the original back in Jellyfin (the caller holds the item lock), confirmed by a re-read. -> 'reverted'
    (also when nothing was ever written), 'manual', 'skipped' or 'error'."""
    row = mp.state(jf_id) or {}
    if not row.get("reverted"):
        return "skipped"
    if not row.get("wrote"):
        return "reverted"
    if row.get("manual"):
        return "manual"
    c = creds()
    if c is None:
        return "skipped"
    base, headers = c
    try:
        if row.get("orig_ext") == "none":
            _ok(upstream.session("jellyfin").delete(f"{base}/Items/{jf_id}/Images/Primary", headers=headers,
                                                    timeout=TIMEOUT), "delete")
        else:
            path = store.orig_path(jf_id)
            if path is None:
                raise WriteError("no backup on disk")
            _upload(base, headers, jf_id, path.read_bytes(), CTYPE[path.suffix])
        if row.get("locked_by_us"):
            _set_lock(base, headers, _item(base, headers, jf_id), False)
        _confirm_restored(base, headers, jf_id, row)
        mp.set_state(jf_id, wrote=0, live_ver=None, live_tag=None, pending_ver=None, locked_by_us=0, manual=0,
                     written_at=_now(), last_error=None, fails=0, retry_at=None)
        return "reverted"
    except Exception as exc:
        return _fail(jf_id, exc, "revert")


def _undo(jf_id: str, wait_s: float = 0.0) -> str:
    """Run a revert under the item lock, waiting up to `wait_s` for an in-flight write. -> as _undo_locked, or
    'queued' (the lock stayed busy: the next pass restores it, the intent is already recorded)."""
    owner = _owner()
    deadline = time.monotonic() + wait_s
    while not mp.claim(jf_id, owner):
        if time.monotonic() >= deadline:
            return "queued"
        time.sleep(0.1)
    try:
        return _undo_locked(jf_id)
    finally:
        mp.release(jf_id, owner)


def revert(jf_id: str, restore_manual: bool = False) -> str:
    """The per-item revert (review page). The intent is recorded first and is sticky: `reverted` stays set, so no pass
    writes the Joey poster again until B.'s explicit re-apply. The Joey poster stops being served at once, and
    Jellyfin's original goes back whenever a Joey write may have happened (`wrote`, set before every upload), after
    any in-flight write of that item (the item lock). -> 'reverted' (only once nothing was written or the restore is
    confirmed by a re-read), 'queued' (a write was in flight: the next pass restores it), 'pending' (write-back off or
    no key: Jellyfin still has the Joey poster), 'manual' (a hand-set poster stays unless `restore_manual`), 'error'
    (retried by the next pass) or 'unknown'."""
    row = mp.state(jf_id)
    if row is None:
        return "unknown"
    fields = {"reverted": 1}
    if restore_manual and row.get("manual"):
        fields["manual"] = 0   # B. asked: the pre-Joey original goes back over his hand-set poster
    mp.set_state(jf_id, **fields)
    store.publish(jf_id, False)
    if row.get("manual") and not restore_manual:
        return "manual"
    if not enabled():
        return "pending" if (mp.state(jf_id) or {}).get("wrote") else "reverted"
    return _undo(jf_id, wait_s=REVERT_WAIT_S)


def retry(jf_id: str) -> str:
    """"Try again now" on a backed-off item: repeats what failed, nothing else. A reverted item retries its revert (it
    is never re-applied by this); any other item just leaves backoff for the next pass. -> revert's word, 'cleared'
    or 'unknown'."""
    row = mp.state(jf_id)
    if row is None:
        return "unknown"
    mp.set_state(jf_id, fails=0, retry_at=None)
    if row.get("reverted"):
        return revert(jf_id, restore_manual=False) if not row.get("manual") else "manual"
    return "cleared"


def reapply(jf_id: str) -> bool:
    """B.'s explicit "Re-apply the Joey poster" / "Use the Joey poster": clears manual / revert / backoff and writes on
    the next pass (a fresh write, so a hand-set tag is not mistaken for drift). The only way out of a revert."""
    if mp.state(jf_id) is None:
        return False
    mp.set_state(jf_id, manual=0, reverted=0, fails=0, retry_at=None, live_ver=None, live_tag=None)
    return store.publish(jf_id, True)


def restore(jf_id: str) -> bool:
    """Undo a revert: serve the Joey poster again (the next write pass writes it back)."""
    return reapply(jf_id)


def write_pass(limit: int, pause: float = 0.0, now: datetime | None = None) -> dict:
    """Write what is due, at most `limit` items: queued reverts first, then new / changed / unfinished writes and the
    daily drift check. Items in backoff (3 failures in a row: 24 h), reverted and hand-set (manual) ones are never
    written. -> counts; never raises."""
    if not enabled():
        return {"off": True}
    now = now or datetime.now(timezone.utc)
    counts = {k: 0 for k in ("written", "reapplied", "finished", "unchanged", "manual", "reverted", "queued", "error",
                             "skipped", "backoff")}
    live = []
    for r in mp.states().values():
        if mp.in_backoff(r, now):
            counts["backoff"] += 1
        else:
            live.append(r)
    reverts = [r for r in live if r.get("reverted") and r.get("wrote") and not r.get("manual")]
    writes = [r for r in live if not r.get("reverted") and not r.get("manual") and r.get("status") == "rendered"
              and (r.get("live_ver") != r.get("ver") or r.get("pending_ver") or not r.get("live_tag")
                   or _due(r.get("checked_at"), now))]
    done = 0
    for r in reverts + writes:
        if done >= limit:
            break
        got = _undo(r["jf_id"]) if r in reverts else apply(r["jf_id"])
        counts[got] += 1
        if got not in ("skipped", "unchanged", "manual", "queued"):
            done += 1
            if pause:
                time.sleep(pause)
    if done:
        log.info("posters write-back: %(written)s written, %(reapplied)s re-applied, %(reverted)s reverted, "
                 "%(error)s failed, %(backoff)s backing off", counts)
    return counts
