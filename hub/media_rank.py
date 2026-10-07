"""Library rank for the film page's File panel (film-quality, 2026-10-07): "Smaller than 93% of your films",
"Lower than 90% of your films".

Data: ONE Jellyfin read of every film's MediaSources (size + bitrate), at most once per 24 h, made by the media
warm-up loop (hub/media_warmup.py run_pass) — never by a page load. The result is a small JSON file in the meta
cache dir ({jf_id: [size_bytes, bitrate_bps]}), so it survives deploys; the page reads it through a 10 min
in-process cache. Fewer than MIN_FILMS films with data -> no rank line. MEDIA_WARMUP=off -> no data, no line.
Logs carry exception TYPES only, never a URL or key.
"""

from __future__ import annotations

import json
import logging
import time

from hub import media_discover as md, media_files

log = logging.getLogger("hub.media_rank")

FILE = "library_rank.json"
EVERY_S = 24 * 3600
READ_TTL = 600
MIN_FILMS = 20
LIMIT = 5000

_mem: list = [0.0, None]  # [read_at, {jf_id: (size, bitrate)}]


def clear_cache() -> None:
    _mem[:] = [0.0, None]


def _path():
    return md.meta_dir() / FILE


def _stamp() -> float | None:
    try:
        return float(json.loads(_path().read_text(encoding="utf-8"))["at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def due(now: float | None = None) -> bool:
    at = _stamp()
    return at is None or (time.time() if now is None else now) - at >= EVERY_S


def rows_from(items) -> dict[str, list]:
    """Jellyfin movie items -> {jf_id: [size_bytes | None, bitrate_bps | None]} (first media source)."""
    out = {}
    for it in items or []:
        if not isinstance(it, dict) or not it.get("Id"):
            continue
        sources = it.get("MediaSources") or []
        src = sources[0] if sources and isinstance(sources[0], dict) else {}
        size = src.get("Size") if isinstance(src.get("Size"), (int, float)) and src.get("Size") > 0 else None
        rate = media_files.bitrate_bps(src, it)
        if size or rate:
            out[str(it["Id"])] = [size, rate]
    return out


def refresh() -> int | None:
    """Re-read every film's size + bitrate from Jellyfin into the rank file. -> films stored, or None."""
    creds = media_files._creds()
    if not creds:
        return None
    base, headers = creds
    try:
        uid = media_files._user_id(base, headers)
        body = media_files._get(base, headers, f"/Users/{uid}/Items", {
            "IncludeItemTypes": "Movie", "Recursive": "true", "Fields": "MediaSources", "Limit": LIMIT,
            "EnableImages": "false", "EnableUserData": "false"}) if uid else None
        rows = rows_from(body.get("Items") if isinstance(body, dict) else None)
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"at": time.time(), "films": rows}), encoding="utf-8")
    except Exception as exc:  # type only — requests errors embed the URL
        log.warning("library rank refresh failed: %s", type(exc).__name__)
        return None
    clear_cache()
    log.info("library rank: %s films", len(rows))
    return len(rows)


def _films() -> dict:
    if _mem[1] is not None and time.time() - _mem[0] < READ_TTL:
        return _mem[1]
    try:
        films = json.loads(_path().read_text(encoding="utf-8")).get("films") or {}
    except (OSError, ValueError, AttributeError):
        films = {}
    _mem[:] = [time.time(), films if isinstance(films, dict) else {}]
    return _mem[1]


def phrase(value, others: list, words: tuple[str, str]) -> str | None:
    """'Smaller than 93% of your films' — whichever side holds the larger share; None under MIN_FILMS.
    `others` excludes this film; ties count on neither side."""
    others = [v for v in others if isinstance(v, (int, float)) and v > 0]
    if not isinstance(value, (int, float)) or value <= 0 or len(others) + 1 < MIN_FILMS:
        return None
    above = sum(1 for v in others if v > value)
    below = sum(1 for v in others if v < value)
    word, share = (words[0], above) if above >= below else (words[1], below)
    return f"{word} than {round(100 * share / len(others))}% of your films"


def rank(jf_id: str | None, size, bitrate) -> dict:
    """{'size': phrase | None, 'bitrate': phrase | None} for one film against the rest of the library."""
    films = _films()
    others = [v for k, v in films.items() if k != jf_id and isinstance(v, list) and len(v) == 2]
    return {"size": phrase(size, [v[0] for v in others], ("Smaller", "Larger")),
            "bitrate": phrase(bitrate, [v[1] for v in others], ("Lower", "Higher"))}
