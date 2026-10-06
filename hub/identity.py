"""Who's looking (2026-10-06): the signed-in Cloudflare Access user.

Access admits exactly two people, so the header alone decides the owner: the address
in OWNER_EMAIL_YOU is "you", any other admitted address is "her". Only B.'s own address
is configured (NAS .env); the other person's address is never recorded anywhere.
No header (local dev, tests) = not signed in, and the old owner_view switch applies.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

IDENTITY_HEADER = "Cf-Access-Authenticated-User-Email"


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
    if you and email.lower() == you:
        return Identity(email=email, owner="you", name=os.environ.get("OWNER_NAME_YOU") or "Benji")
    return Identity(email=email, owner="her", name=os.environ.get("OWNER_NAME_HER") or "Georgina")
