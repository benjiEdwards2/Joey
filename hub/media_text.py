"""Media's words for times, dates and counts (W2, 2026-10-09; M-14): one copy of the helpers that were written three
times. Style guide §9: '2h 47m' lengths, '14 Mar 2026' dates ('14 Mar' in the current year where asked), '—' for a
missing value, counts with their noun ('3 episodes').
"""

from __future__ import annotations

import re
from datetime import date, datetime

from hub.store import parse_utc

_HTTP = re.compile(r"HTTP \d{3}")


def parse(value) -> datetime | None:
    """An ISO timestamp as an aware datetime (naive = UTC; 'Z' and Jellyfin's 7-digit fractions accepted), or None."""
    return parse_utc(value)


def year(value) -> int | None:
    """The leading four-digit year of a date string ('2026-03-14' -> 2026), or None."""
    text = str(value or "")[:4]
    return int(text) if text.isdigit() else None


def date_words(value, short: bool = False) -> tuple[str | None, bool]:
    """'2026-03-14' -> ('14 Mar 2026', is_future); with `short`, the current year is left out ('14 Mar').
    Junk -> (None, False)."""
    try:
        d = date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None, False
    today = date.today()
    text = f"{d.day} {d.strftime('%b')}" + ("" if short and d.year == today.year else f" {d.year}")
    return text, d > today


def short_date(value) -> str | None:
    """'2025-03-02' -> '2 Mar 2025' ('2 Mar' this year); junk -> None."""
    return date_words(value, short=True)[0]


def plural(n: int, singular: str, many: str | None = None) -> str:
    """'1 episode' / '3 episodes' (`many` for an irregular plural)."""
    return f"{n} {singular if n == 1 else (many or singular + 's')}"


def why(exc: BaseException) -> str:
    """Log-safe words for a failure (M-29): 'HTTP 503' for our own status RuntimeErrors, else the exception TYPE —
    never its message (requests errors embed the URL, and a URL can carry a key)."""
    return str(exc) if isinstance(exc, RuntimeError) and _HTTP.fullmatch(str(exc)) else type(exc).__name__


def duration(minutes) -> str:
    """Lengths as the guide writes them: 112 -> '1h 52m', 47 -> '47m', 120 -> '2h', missing -> '—'."""
    if not isinstance(minutes, (int, float)) or isinstance(minutes, bool) or minutes <= 0:
        return "—"
    h, m = divmod(int(minutes), 60)
    return " ".join(x for x in (f"{h}h" if h else "", f"{m}m" if m else "") if x)
