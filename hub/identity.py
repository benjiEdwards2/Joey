"""Who's looking (2026-10-06): the signed-in Cloudflare Access user.

Access admits exactly two people, so the header alone decides the owner: the address
in OWNER_EMAIL_YOU is "you", any other admitted address is "her". Only B.'s own address
is configured (NAS .env); the other person's address is never recorded anywhere.
No header (local dev, tests) = not signed in, and the old owner_view switch applies.
OWNER_EMAIL_YOU unset/blank = not configured (review H-38, 2026-10-09): a signed-in visitor gets
NO owner (the same "both" view as local dev) instead of every address writing as "her";
one warning is logged on first use.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

IDENTITY_HEADER = "Cf-Access-Authenticated-User-Email"

log = logging.getLogger(__name__)
_warned_unconfigured = False


@dataclass(frozen=True)
class Identity:
    email: str | None
    owner: str | None  # "you" | "her" | None (not signed in)
    name: str


def resolve_identity(request) -> Identity:
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
