"""Who's looking (2026-10-06): the signed-in Cloudflare Access user.

Access admits exactly two people, so the header alone decides the owner: the address
in OWNER_EMAIL_YOU is "you", any other admitted address is "her". Only B.'s own address
is configured (NAS .env); the other person's address is never recorded anywhere.
No header (local dev, tests) = not signed in, and the old owner_view switch applies.
OWNER_EMAIL_YOU unset/blank = not configured (review H-38, 2026-10-09): a signed-in visitor gets
NO owner (the same "both" view as local dev) instead of every address writing as "her";
one warning is logged on first use.

Jellyfin owners (Joey TV WP-A2, 2026-10-18; D-P14 refines D-P6): `owner_for_jellyfin(user_id)` names the owner of a
Jellyfin user's play by user ID, never by the renamable display name — "her" = the JELLYFIN_USER_HER user, "you" = the
JELLYFIN_USER user or a JELLYFIN_USER_ALIASES user (comma-separated names), anyone else = `jf:<32 lowercase hex>`.

Media front (Joey TV WP-B1, 2026-10-21): with JOEY_FRONT=media the Access header is ignored entirely - the identity is
the one hub.guest.GuestGate stored at scope['state']['identity'] (WP-B2's Jellyfin sign-in), else not signed in.
`Identity(owner, name, email=None, jf_user_id=None, jf_token=None)` is FROZEN (Joey TV §4 rule 9): the new fields have
defaults so every private construction is unchanged; the token never appears in repr.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

IDENTITY_HEADER = "Cf-Access-Authenticated-User-Email"

OWNER_KEY_RE = r"^jf:[0-9a-f]{32}$"
"""The owner key of a non-household Jellyfin user: 'jf:' + the Jellyfin user id lowercased, dashes stripped. FROZEN
(Joey TV WP-A2, pinned by tests/hub/test_owner_keys.py::test_owner_key_format_frozen): media.db `owner` columns hold
it, so a change orphans every friend's recorded rows."""

_HEX32 = re.compile(r"[0-9a-f]{32}")

log = logging.getLogger(__name__)
_warned_unconfigured = False
_household: tuple[frozenset, str | None] | None = None   # (the "you" ids, the "her" id), resolved once from /Users


class OwnerUnresolved(RuntimeError):
    """The household's Jellyfin ids could not be read (/Users failed): no owner is decided; the caller retries later."""


def clear_jellyfin_owners() -> None:
    global _household
    _household = None


def _norm_id(user_id) -> str:
    """A Jellyfin user id as 32 lowercase hex (dashes stripped); ValueError for anything else."""
    text = user_id.replace("-", "").lower() if isinstance(user_id, str) else ""
    if not _HEX32.fullmatch(text):
        raise ValueError("not a Jellyfin user id")
    return text


def _read_users():
    from hub import media_jellyfin   # lazy: identity stays import-light for the shell
    creds = media_jellyfin.creds()
    if creds is None:
        raise OwnerUnresolved("Jellyfin not configured")
    return media_jellyfin.get(*creds, "/Users")


def _resolve(users_of) -> tuple[frozenset, str | None]:
    """The names in JELLYFIN_USER / JELLYFIN_USER_ALIASES / JELLYFIN_USER_HER as ids, read from /Users once. Logs carry
    no names (rule 20)."""
    try:
        users = (users_of or _read_users)()
    except OwnerUnresolved:
        raise
    except Exception as exc:
        raise OwnerUnresolved(type(exc).__name__) from None
    if not isinstance(users, list):
        raise OwnerUnresolved("unexpected /Users answer")
    ids = {}
    for u in users:
        if isinstance(u, dict) and isinstance(u.get("Name"), str):
            try:
                ids.setdefault(u["Name"], _norm_id(u.get("Id")))
            except ValueError:
                continue
    you_name = os.environ.get("JELLYFIN_USER", "").strip()
    her_name = os.environ.get("JELLYFIN_USER_HER", "").strip()
    aliases = [n.strip() for n in os.environ.get("JELLYFIN_USER_ALIASES", "").split(",") if n.strip()]
    if you_name in ids:
        you = frozenset([ids[you_name], *(ids[n] for n in aliases if n in ids)])
    else:
        you = frozenset()
        log.warning("identity: JELLYFIN_USER unset or not found in Jellyfin /Users - no Jellyfin user maps to 'you'")
    if you and any(n not in ids for n in aliases):
        log.warning("identity: %d JELLYFIN_USER_ALIASES name(s) not found in Jellyfin /Users",
                    sum(n not in ids for n in aliases))
    if her_name and her_name not in ids:
        log.warning("identity: JELLYFIN_USER_HER not found in Jellyfin /Users - no Jellyfin user maps to 'her'")
    return you, ids.get(her_name) if her_name else None


def owner_for_jellyfin(user_id, users_of=None) -> str:
    """'her' / 'you' / 'jf:<32 lowercase hex>' for a Jellyfin user id (any case, dashes allowed). ValueError for a
    malformed id; OwnerUnresolved while /Users cannot be read (never a default to 'you'). `users_of()` reads /Users
    (default: the admin-key GET); it runs once, the answer is cached for the process."""
    global _household
    uid = _norm_id(user_id)
    if _household is None:
        _household = _resolve(users_of)
    you, her = _household
    if her and uid == her:
        return "her"
    if uid in you:
        return "you"
    return f"jf:{uid}"


@dataclass(frozen=True)
class Identity:
    owner: str | None  # "you" | "her" | "jf:<id>" (media front) | None (not signed in)
    name: str
    email: str | None = None
    jf_user_id: str | None = None   # media front: the signed-in Jellyfin user (WP-B2)
    jf_token: str | None = field(default=None, repr=False)   # media front: that user's token - never logged


def resolve_identity(request) -> Identity:
    from hub import guest   # lazy: hub.guest imports this module
    if guest.is_media():
        return guest.identity_in_scope(getattr(request, "scope", None)) or Identity(owner=None, name="Not signed in")
    email = (request.headers.get(IDENTITY_HEADER) or "").strip() if request is not None else ""
    if not email:
        return Identity(email=None, owner=None, name="Not signed in")
    you = (os.environ.get("OWNER_EMAIL_YOU") or "").strip().lower()
    if not you:
        global _warned_unconfigured
        if not _warned_unconfigured:
            _warned_unconfigured = True
            log.warning("identity: OWNER_EMAIL_YOU not configured - signed-in users get no owner (both view)")
        return Identity(email=email, owner=None, name="Signed in")
    if email.lower() == you:
        return Identity(email=email, owner="you", name=os.environ.get("OWNER_NAME_YOU") or "Benji")
    return Identity(email=email, owner="her", name=os.environ.get("OWNER_NAME_HER") or "Georgina")
