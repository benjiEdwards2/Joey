"""Jellyfin, server-side (W2, 2026-10-09; M-12): the one place that reads JELLYFIN_URL / JELLYFIN_API_KEY, GETs a
path and resolves an owner's Jellyfin user id. media_files, media_item, media_plays, media_resume and the warm-up use
it; nothing here logs a URL or a key (callers log the exception type only).

Owners: "you" = JELLYFIN_USER by name, else the first administrator, else the first user; "her" = exactly
JELLYFIN_USER_HER — never a fallback to the admin (None while it is unset).
"""

from __future__ import annotations

import os
import time

import requests  # noqa: F401 - kept: tests fake upstreams at hub.media_jellyfin.requests (E1: via tests/hub/conftest)

from hub import upstream

TIMEOUT = 8
UID_TTL = 3600

_uid: dict[str, tuple[float, str, str]] = {}   # owner -> (fetched_at, the name it was resolved for, user id)


def clear_cache() -> None:
    _uid.clear()


def creds() -> tuple[str, dict] | None:
    """(base URL, auth headers), or None when Jellyfin isn't configured."""
    base, key = os.environ.get("JELLYFIN_URL", "").strip(), os.environ.get("JELLYFIN_API_KEY", "").strip()
    if not (base and key):
        return None
    return base.rstrip("/"), {"Authorization": f"MediaBrowser Token={key}"}


def get(base: str, headers: dict, path: str, params: dict | None = None):
    """GET a Jellyfin JSON path; raises on no answer, and RuntimeError("HTTP nnn") on a non-2xx."""
    resp = upstream.session("jellyfin").get(f"{base}{path}", params=params, headers=headers, timeout=TIMEOUT)
    if not 200 <= resp.status_code < 300:
        raise RuntimeError(f"HTTP {resp.status_code}")
    return resp.json()


def her_name() -> str:
    """JELLYFIN_USER_HER ('' while Georgina's account isn't set up)."""
    return os.environ.get("JELLYFIN_USER_HER", "").strip()


def pick_user(users, preferred: str | None) -> str | None:
    """JELLYFIN_USER by name, else the first administrator, else the first user."""
    users = [u for u in users if isinstance(u, dict) and u.get("Id")] if isinstance(users, list) else []
    for u in users:
        if preferred and u.get("Name") == preferred:
            return u["Id"]
    for u in users:
        if (u.get("Policy") or {}).get("IsAdministrator"):
            return u["Id"]
    return users[0]["Id"] if users else None


def user_id(owner: str, base: str, headers: dict, users_of=None) -> str | None:
    """The owner's Jellyfin user id (cached UID_TTL per owner and wanted name). `users_of(base, headers)` reads
    /Users (default: get)."""
    name = her_name() if owner == "her" else os.environ.get("JELLYFIN_USER", "").strip()
    if owner == "her" and not name:
        return None
    hit = _uid.get(owner)
    if hit and hit[1] == name and time.time() - hit[0] < UID_TTL:
        return hit[2]
    users = (users_of or (lambda b, h: get(b, h, "/Users")))(base, headers)
    if owner == "her":
        uid = next((u["Id"] for u in users if isinstance(u, dict) and u.get("Name") == name and u.get("Id")), None) \
            if isinstance(users, list) else None
    else:
        uid = pick_user(users, name or None)
    if uid:
        _uid[owner] = (time.time(), name, uid)
    return uid
