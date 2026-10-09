"""Request / availability status words -> their colour class (W2, 2026-10-09; M-19). The words stay where they are
made (Jellyseerr's status codes, the requests snapshot, the watchlist, follows); this is the ONE place a word becomes a
class, so Pending / Approved / Declined are coloured like Requested / Processing instead of rendering plain.
Templates call the Jinja global `status_of(word)` -> {word, cls}. The classes are the stylesheet's existing ones.
"""

from __future__ import annotations

GOOD, WAITING, BAD, PLAIN = "st-available", "st-requested", "st-down", "st-plain"   # st-plain: no colour

CLASSES = {
    "available": GOOD, "on disk": GOOD, "on server": GOOD, "already there": GOOD,
    "partly available": "st-partly-available",
    "requested": WAITING, "pending": WAITING,
    "processing": "st-processing", "approved": "st-processing",
    "declined": BAD, "failed": BAD,
}


def status(word) -> dict:
    """{word, cls}: the word as given and its colour class (st-plain, uncoloured, for e.g. Not on server)."""
    text = str(word or "")
    return {"word": text, "cls": CLASSES.get(text.strip().lower(), PLAIN)}
