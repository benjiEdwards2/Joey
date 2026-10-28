"""JY-263: who may fetch a Jellyfin-sourced image from `/img` on the media front.

The private front and a household member (`you`, `her`) get everything, as before. A friend gets a `jf:` / `jfb:` image
only for an id their own Jellyfin user has been shown, never one a page of theirs could not have drawn. "Shown" is two
sets, both filled by data the hub already holds - no Jellyfin call is made for an image:

* the shared library snapshot's ids (movies, shows, latest: the rows every friend's lists and Home draw), re-read at
  most every SNAPSHOT_TTL seconds;
* ids noted from the friend's OWN reads (`note`): the item read (hub.media_item: the title, its show, seasons,
  episodes, cast) and the Continue watching / Recently watched shelves. Jellyfin answered those as that user.

The set is per viewer and bounded. After a restart a friend's set is empty until their next page reads (that read runs
before the page's images are asked for), so the cost of the rule is a fallback card, never a wrong image. Tradeoff: an
id the snapshot carries is visible to every friend (the snapshot is server-wide; per-user Jellyfin library rules do not
narrow it, as they do not narrow the Home shelves built from it today).
"""
from __future__ import annotations

import re
import threading
import time

SNAPSHOT_TTL = 30.0
VIEWER_MAX = 256        # friends tracked
IDS_MAX = 20000         # ids per friend; over it the friend's set restarts from the next read
_ID = re.compile(r"^[A-Za-z0-9-]+$")

_lock = threading.Lock()
_viewers: dict = {}     # jellyfin user id -> set of ids
_snap: list = [0.0, frozenset()]   # [read at (monotonic), ids]


def clear() -> None:
    with _lock:
        _viewers.clear()
        _snap[:] = [0.0, frozenset()]


def _ref_id(value) -> str | None:
    """The id in an image ref (`jf:<id>`, `jfb:<id>[/n]`), else None."""
    if not isinstance(value, str):
        return None
    kind, _, rest = value.partition(":")
    if kind not in ("jf", "jfb"):
        return None
    ident = rest.partition("/")[0]
    return ident if _ID.match(ident) else None


def ids_in(data) -> set:
    """Every Jellyfin id a read carries: `id` / `jf_id` / `show_id` values and the id inside any `jf:` / `jfb:` ref."""
    out: set = set()
    stack = [data]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for key, val in cur.items():
                if key in ("id", "jf_id", "show_id") and isinstance(val, str) and _ID.match(val):
                    out.add(val)
                elif isinstance(val, (dict, list)):
                    stack.append(val)
                elif (ident := _ref_id(val)):
                    out.add(ident)
        elif isinstance(cur, list):
            stack.extend(x if isinstance(x, (dict, list)) else {"ref": x} for x in cur)
    return out


def note(viewer, data) -> None:
    """Record the ids of a read made as this friend. Never raises."""
    if not isinstance(viewer, str) or not viewer:
        return
    try:
        ids = ids_in(data)
    except Exception:   # a odd shape must never break a page read
        return
    with _lock:
        mine = _viewers.get(viewer)
        if mine is None or len(mine) + len(ids) > IDS_MAX:
            if mine is None and len(_viewers) >= VIEWER_MAX:
                _viewers.clear()
            mine = _viewers[viewer] = set()
        mine |= ids


def _snapshot_ids() -> frozenset:
    now = time.monotonic()
    with _lock:
        if _snap[0] and now - _snap[0] < SNAPSHOT_TTL:
            return _snap[1]
    from hub import shell
    snap = shell.get_snapshots().get("jellyfin")   # the media front's scrubbed view: shared library keys only
    data = snap.data if snap is not None and isinstance(snap.data, dict) else {}
    ids = frozenset(ids_in([r for key in ("movies", "shows", "latest") for r in data.get(key) or []
                            if isinstance(r, dict)]))
    with _lock:
        _snap[:] = [now, ids]
    return ids


def friend_may_see(viewer, ident: str) -> bool:
    """A set lookup (the snapshot set is re-read at most every SNAPSHOT_TTL). `ident` is the ref's id, backdrop index
    already removed."""
    with _lock:
        if ident in _viewers.get(viewer, ()):
            return True
    return ident in _snapshot_ids()


def allowed(request, kind: str, ident: str) -> bool | None:
    """True: serve. False: a friend asking for an id they were not shown. None: not a signed-in viewer on the media
    front (the caller answers the ordinary 404 page). Kinds other than jf / jfb (arr covers, TMDB) are not checked."""
    from hub import guest, media_jellyfin, player_api
    if not guest.is_media() or kind not in ("jf", "jfb"):
        return True
    who = guest.identity_in_scope(request.scope)
    if who is None:
        return None
    if who.owner in player_api.HOUSEHOLD:
        return True
    return friend_may_see(media_jellyfin.viewer() or who.jf_user_id, ident.partition("/")[0])
