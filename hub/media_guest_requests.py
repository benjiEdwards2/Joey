"""Friend requests through Seerr on the media front (Joey TV WP-B4, 2026-10-21; DECISIONS B #19, Q29, Q30).

Every friend request waits for B.'s approval. The W3 probe (JoeyTV DECISIONS 2026-10-21, Seerr 3.5.0) proved how:

* the request is sent with the admin `X-Api-Key` AND `X-Api-User: <the friend's Seerr user id>`, so Seerr creates it AS
  the friend, with the friend's permissions (32 = REQUEST only -> status 1, pending). Never the bare key for a friend:
  that request would be the admin's and auto-approve.
* the Seerr id comes from `GET /api/v1/user?take=500`, matched on `jellyfinUserId` (compared dash-less, lower case),
  the whole map cached USER_TTL. A friend with no Seerr user is imported on their FIRST REQUEST - never on a page view
  - by `POST /api/v1/user/import-from-jellyfin` `{"jellyfinUserIds": [<that friend only>]}` (201 with only the new
  users), then looked up once more; still none -> NOREQUESTS ("Requests aren't set up for you yet").
* pending only: a friend whose Seerr user could approve (ADMIN, MANAGE_REQUESTS, AUTO_APPROVE*, see NEVER) is refused
  before anything is sent (NOREQUESTS); B. fixes the permissions in Seerr (runbook R1).
* decline is B.'s, in Seerr: nothing here declines, approves or removes. A friend sees their own requests' state (their
  `GET /api/v1/request?requestedBy=<id>` list, MINE_TTL) as Requested / Approved / Declined.

This module only reads Seerr and, for a request, imports one user; the request POST itself stays in
hub.media_discover._send (one call path). Failures log the exception TYPE only (requests errors embed the URL)."""
from __future__ import annotations

import logging
import re
import time

from hub import media_discover as md

log = logging.getLogger("hub.media_guest_requests")

USER_TTL = 3600          # the Seerr user map (MASTER_PLAN WP-B4 step 2: cached 1 h)
MINE_TTL = 60            # a friend's own request list (a decline shows within a minute)
NOREQUESTS = "norequests"
USERS_PATH = "/api/v1/user?take=500"
IMPORT_PATH = "/api/v1/user/import-from-jellyfin"

# Seerr permission bits (Overseerr's Permission enum, unchanged in Seerr 3.5): a friend holding any of these could
# approve their own request, so they are refused instead (pending only, DECISIONS B #19).
ADMIN, MANAGE_REQUESTS, AUTO_APPROVE, AUTO_APPROVE_MOVIE, AUTO_APPROVE_TV = 2, 16, 128, 256, 512
NEVER = ADMIN | MANAGE_REQUESTS | AUTO_APPROVE | AUTO_APPROVE_MOVIE | AUTO_APPROVE_TV

JF_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_clock = time.monotonic   # test seam
_users: dict = {}         # {"at": t, "map": {jf id: {"id", "permissions"}}}
_mine: dict[int, tuple[float, dict]] = {}


class Refused(Exception):
    """A media-front request with no usable identity: nothing is sent."""


def clear() -> None:
    _users.clear()
    _mine.clear()


def norm_id(value) -> str:
    return str(value or "").replace("-", "").strip().lower()


# ---- who is asking ----

def friend_id(request) -> str | None:
    """The friend's Jellyfin id when the signed-in user of this MEDIA-FRONT request is a `jf:` owner; None for the
    private front and for the household (`you` / `her`). Refused for a media-front request without a usable identity
    (GuestGate never lets one through; this is the fail-closed backstop)."""
    from hub import guest, identity
    if not guest.is_media():
        return None
    ident = identity.resolve_identity(request)
    if ident.owner in ("you", "her"):
        return None
    jf = norm_id(ident.jf_user_id)
    if not (isinstance(ident.owner, str) and ident.owner == f"jf:{jf}" and JF_ID_RE.match(jf)):
        raise Refused("no friend identity")
    return jf


def viewer_friend() -> str | None:
    """The bound viewer's Jellyfin id when it is a friend (page rendering: hub.media_jellyfin.viewer(), which GuestGate
    binds to the signed-in user); None otherwise or when the owner cannot be resolved (shows no own-request state)."""
    from hub import guest, identity, media_jellyfin
    if not guest.is_media():
        return None
    jf = norm_id(media_jellyfin.viewer())
    if not JF_ID_RE.match(jf):
        return None
    try:
        return jf if identity.owner_for_jellyfin(jf) == f"jf:{jf}" else None
    except Exception as exc:   # OwnerUnresolved while /Users cannot be read
        log.warning("viewer owner unresolved: %s", type(exc).__name__)
        return None


# ---- the Seerr user ----

def _read_users() -> dict | None:
    body = md._get(USERS_PATH)
    rows = body.get("results") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return None
    out = {}
    for u in rows:
        sid = u.get("id") if isinstance(u, dict) else None
        jf = norm_id(u.get("jellyfinUserId")) if isinstance(u, dict) else ""
        if isinstance(sid, int) and not isinstance(sid, bool) and sid > 0 and JF_ID_RE.match(jf):
            perms = u.get("permissions")
            out.setdefault(jf, {"id": sid, "permissions": perms if isinstance(perms, int) else 0})
    _users.update(at=_clock(), map=out)
    return out


def _user_map(fresh: bool = False) -> dict | None:
    if not fresh and "map" in _users and _clock() - _users["at"] < USER_TTL:
        return _users["map"]
    return _read_users()


def _import(jf: str) -> bool:
    """POST the import for this one friend -> True on a 2xx answer."""
    creds = md._creds()
    if not creds:
        return False
    try:
        resp = md.upstream.session("seerr").post(f"{creds[0]}{IMPORT_PATH}", json={"jellyfinUserIds": [jf]},
                                                 headers={"X-Api-Key": creds[1]}, timeout=md.TIMEOUT)
    except Exception as exc:  # type only
        log.warning("seerr user import failed: %s", type(exc).__name__)
        return False
    if not 200 <= resp.status_code < 300:
        log.warning("seerr user import refused: HTTP %s", resp.status_code)
        return False
    log.info("seerr user imported for a friend")   # never the id or the name (DECISIONS G)
    return True


def seerr_user(jf: str) -> tuple[int | None, str | None]:
    """(the friend's Seerr id, None) or (None, error code): "network" when the user list cannot be read (no import, no
    request - never the bare key), NOREQUESTS when the friend has no Seerr user after one import or could approve."""
    users = _user_map()
    if users is None:
        return None, "network"
    hit = users.get(jf)
    if hit is None:
        _import(jf)
        users = _user_map(fresh=True)
        if users is None:
            return None, "network"
        hit = users.get(jf)
        if hit is None:
            log.warning("seerr: friend has no Seerr user after the import")
            return None, NOREQUESTS
    if hit["permissions"] & NEVER:
        log.warning("seerr: friend's Seerr user may approve requests (permissions %s) - refused", hit["permissions"])
        return None, NOREQUESTS
    return hit["id"], None


def known_seerr_id(jf: str | None) -> int | None:
    """The friend's Seerr id from the (cached) user list - never an import; None when unknown or unreadable."""
    users = _user_map() if jf else None
    hit = (users or {}).get(jf)
    return hit["id"] if hit else None


# ---- the friend's own requests ----

def mine(seerr_id: int | None) -> dict[tuple[str, int], int]:
    """{(kind, tmdb id): request status} of this Seerr user's requests (the newest per title; 1 pending, 2 approved,
    3 declined), cached MINE_TTL; {} when unknown or unreadable."""
    if not seerr_id:
        return {}
    hit = _mine.get(seerr_id)
    if hit and _clock() - hit[0] < MINE_TTL:
        return hit[1]
    body = md._get(f"/api/v1/request?take=100&skip=0&filter=all&sort=added&requestedBy={seerr_id}", md.SHELF_TIMEOUT)
    rows = body.get("results") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return {}
    out: dict[tuple[str, int], int] = {}
    for r in rows:   # sort=added: newest first, so the first row per title wins
        media = r.get("media") if isinstance(r, dict) else None
        kind = r.get("type") if isinstance(r, dict) else None
        tmdb = media.get("tmdbId") if isinstance(media, dict) else None
        status = r.get("status") if isinstance(r, dict) else None
        if kind in ("movie", "tv") and isinstance(tmdb, int) and isinstance(status, int):
            out.setdefault((kind, tmdb), status)
    _mine[seerr_id] = (_clock(), out)
    return out


def forget_mine(seerr_id: int | None) -> None:
    _mine.pop(seerr_id, None)


def viewer_mine() -> dict[tuple[str, int], int]:
    """The signed-in friend's own requests ({} for the household, the private front, or a friend not yet in Seerr)."""
    return mine(known_seerr_id(viewer_friend()))


# ---- the words ----

MINE_STATE = {1: "pending", 2: "approved", 3: "declined"}
CHIP = {"lib": "In library", "pending": "Requested", "approved": "Requested", "requested": "Requested",
        "declined": "Declined", "request": "Request"}
PANEL = {"lib": "Already in the library", "pending": "Requested — waiting for approval",
         "approved": "Approved — on its way", "requested": "Already requested — on its way", "declined": "Declined"}


def state(status_word: str | None, mine_status: int | None) -> str:
    """One title's state for a friend: in the library first, then their own request, then anyone's request."""
    if status_word in md.ON_DISK:
        return "lib"
    if mine_status in MINE_STATE:
        return MINE_STATE[mine_status]
    if status_word in ("Requested", "Processing"):
        return "requested"
    return "request"


def with_states(rows: list[dict], own: dict) -> list[dict]:
    """Discover rows plus `req_state` and `chip` (the grid's state chip)."""
    out = []
    for r in rows:
        s = state(r.get("status_word"), own.get((r["kind"], r["tmdb_id"])))
        out.append({**r, "req_state": s, "chip": CHIP[s]})
    return out


def title_mine(kind, tmdb_id) -> str | None:
    """'pending' / 'approved' / 'declined' for the signed-in friend's own request of this title, else None."""
    if kind not in ("movie", "tv") or not tmdb_id:
        return None
    return MINE_STATE.get(viewer_mine().get((kind, int(tmdb_id))))
