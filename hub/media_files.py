"""File-quality strip (2026-10-06): what is ON DISK for a title, read live from Jellyfin
(env JELLYFIN_URL + JELLYFIN_API_KEY, header `Authorization: MediaBrowser Token=`), server-side only.

Words, not logos or colours: each badge is a generic icon id plus a plain word. Any upstream
failure returns None (the strip simply doesn't render); logs carry the exception TYPE only,
never a URL or key.
"""

from __future__ import annotations

import logging
import os
import time

import requests

log = logging.getLogger("hub.media_files")

TIMEOUT = 8
CACHE_TTL = 600
UID_TTL = 3600
ITEM_FIELDS = "MediaStreams,MediaSources,Path,Width,Height,Container,RunTimeTicks"
ITEM_LIMIT = 500

_cache: dict[tuple[str, int], tuple[float, dict]] = {}
_uid: list = [0.0, None]  # [fetched_at, uid]


def clear_cache() -> None:
    _cache.clear()
    _uid[:] = [0.0, None]


def _creds() -> tuple[str, dict] | None:
    base, key = os.environ.get("JELLYFIN_URL", "").strip(), os.environ.get("JELLYFIN_API_KEY", "").strip()
    if not (base and key):
        return None
    return base.rstrip("/"), {"Authorization": f"MediaBrowser Token={key}"}


def _get(base: str, headers: dict, path: str, params: dict | None = None):
    resp = requests.get(f"{base}{path}", params=params, headers=headers, timeout=TIMEOUT)
    if not 200 <= resp.status_code < 300:
        raise RuntimeError(f"HTTP {resp.status_code}")
    return resp.json()


def _pick_user(users, preferred: str | None) -> str | None:
    """JELLYFIN_USER by name, else the first administrator, else the first user."""
    users = [u for u in users if isinstance(u, dict) and u.get("Id")] if isinstance(users, list) else []
    for u in users:
        if preferred and u.get("Name") == preferred:
            return u["Id"]
    for u in users:
        if (u.get("Policy") or {}).get("IsAdministrator"):
            return u["Id"]
    return users[0]["Id"] if users else None


def _user_id(base: str, headers: dict) -> str | None:
    if _uid[1] and time.time() - _uid[0] < UID_TTL:
        return _uid[1]
    uid = _pick_user(_get(base, headers, "/Users"), os.environ.get("JELLYFIN_USER", "").strip() or None)
    if uid:
        _uid[:] = [time.time(), uid]
    return uid


# ---- facts -> words ----

AUDIO_WORDS = {"eac3": "Dolby Digital Plus", "ac3": "Dolby Digital", "truehd": "TrueHD", "aac": "AAC",
               "flac": "FLAC", "opus": "Opus", "mp3": "MP3", "vorbis": "Vorbis", "alac": "ALAC"}
VIDEO_WORDS = {"h264": "H.264", "avc": "H.264", "hevc": "HEVC", "h265": "HEVC", "av1": "AV1",
               "vp9": "VP9", "mpeg2video": "MPEG-2", "vc1": "VC-1", "mpeg4": "MPEG-4"}
CHANNEL_WORDS = {1: "Mono", 2: "Stereo", 6: "5.1", 8: "7.1"}


def _resolution(stream: dict, source: dict) -> str:
    h = stream.get("Height") or source.get("Height") or 0
    w = stream.get("Width") or source.get("Width") or 0
    if h >= 2000 or w >= 3800:
        return "4K"
    return "1080p" if h >= 1000 or w >= 1900 else "720p" if h >= 700 or w >= 1200 else "SD"


def _hdr(stream: dict) -> str | None:
    rng = str(stream.get("VideoRangeType") or stream.get("VideoRange") or "").lower().replace(" ", "")
    if rng.startswith("dovi"):
        return "Dolby Vision"
    for key, word in (("hdr10plus", "HDR10+"), ("hdr10", "HDR10"), ("hlg", "HLG")):
        if key in rng:
            return word
    return None


def _audio_word(stream: dict) -> str:
    codec = str(stream.get("Codec") or "").lower()
    if codec == "dts":
        return "DTS-HD" if "DTS-HD" in str(stream.get("Profile") or "") else "DTS"
    return AUDIO_WORDS.get(codec) or codec.upper() or "Audio"


def _size_text(n) -> str | None:
    if not isinstance(n, (int, float)) or n <= 0:
        return None
    gb = n / 1024 ** 3
    return f"{gb:.1f} GB" if gb >= 1 else f"{n / 1024 ** 2:.0f} MB"


def _facts(item: dict) -> dict | None:
    sources = item.get("MediaSources") or []
    source = sources[0] if sources and isinstance(sources[0], dict) else {}
    streams = [s for s in (source.get("MediaStreams") or item.get("MediaStreams") or []) if isinstance(s, dict)]
    video = next((s for s in streams if s.get("Type") == "Video"), None)
    audios = [s for s in streams if s.get("Type") == "Audio"]
    if video is None and not audios:
        return None
    audio = next((a for a in audios if a.get("IsDefault")), audios[0] if audios else None)
    f: dict = {"size": source.get("Size") if isinstance(source.get("Size"), (int, float)) else 0,
               "container": str(source.get("Container") or item.get("Container") or "").upper() or None}
    if video:
        codec = str(video.get("Codec") or "").lower()
        f.update(res=_resolution(video, source), hdr=_hdr(video),
                 codec=VIDEO_WORDS.get(codec) or codec.upper() or None)
    if audio:
        f.update(audio=_audio_word(audio), channels=CHANNEL_WORDS.get(audio.get("Channels")),
                 atmos="atmos" in str(audio.get("Profile") or "").lower())
    return f


def _ordered(values, order=()) -> list[str]:
    seen = {v for v in values if v}
    return [v for v in order if v in seen] + sorted(seen - set(order))


def _badges(files: list[dict]) -> tuple[list[dict], list[dict]]:
    def col(key):
        return [f.get(key) for f in files]

    video = [{"word": w, "icon": "res"} for w in _ordered(col("res"), ("SD", "720p", "1080p", "4K"))]
    video += [{"word": w, "icon": "hdr"} for w in _ordered(col("hdr"), ("HDR10", "HDR10+", "HLG", "Dolby Vision"))]
    video += [{"word": w, "icon": "codec"} for w in _ordered(col("codec"))]
    video += [{"word": w, "icon": "box"} for w in _ordered(col("container"))]
    audio = [{"word": w, "icon": "audio"} for w in _ordered(col("audio"))]
    audio += [{"word": w, "icon": "channels"} for w in _ordered(col("channels"), ("Mono", "Stereo", "5.1", "7.1"))]
    if any(f.get("atmos") for f in files):
        audio.append({"word": "Atmos", "icon": "atmos"})
    return video, audio


def _summarise(kind: str, items: list) -> dict | None:
    files = [f for f in (_facts(i) for i in items if isinstance(i, dict)) if f]
    if kind == "movie":
        files = files[:1]
    if not files:
        return None
    video, audio = _badges(files)
    note = " · ".join(b["word"] for b in video if b["icon"] == "res") if len(files) > 1 else None
    return {"kind": kind, "files": len(files), "video": video, "audio": audio,
            "size_text": _size_text(sum(f["size"] for f in files)), "note": note,
            "episodes_on_disk": len(files) if kind == "tv" else None}


def _items(base: str, headers: dict, uid: str, kind: str, tmdb_id: int):
    path = f"/Users/{uid}/Items"
    common = {"Recursive": "true", "Fields": ITEM_FIELDS, "Limit": ITEM_LIMIT}
    if kind == "movie":
        body = _get(base, headers, path, {"AnyProviderIdEquals": f"Tmdb.{tmdb_id}",
                                          "IncludeItemTypes": "Movie", **common})
    else:
        # Episodes don't carry the show's TMDB id: find the Series first, then its episodes.
        series = _get(base, headers, path, {"AnyProviderIdEquals": f"Tmdb.{tmdb_id}",
                                            "IncludeItemTypes": "Series", "Recursive": "true", "Limit": 1})
        first = (series.get("Items") or [None])[0] if isinstance(series, dict) else None
        if not isinstance(first, dict) or not first.get("Id"):
            return None
        body = _get(base, headers, path, {"ParentId": first["Id"], "IncludeItemTypes": "Episode", **common})
    items = body.get("Items") if isinstance(body, dict) else None
    return items if isinstance(items, list) else None


def file_summary(kind: str, tmdb_id: int) -> dict | None:
    """Quality facts for what is on disk, or None (not in Jellyfin / not configured / any failure)."""
    if kind not in ("movie", "tv"):
        return None
    hit = _cache.get((kind, tmdb_id))
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    creds = _creds()
    if not creds:
        return None
    base, headers = creds
    try:
        uid = _user_id(base, headers)
        items = _items(base, headers, uid, kind, tmdb_id) if uid else None
        out = _summarise(kind, items) if items else None
    except Exception as exc:  # type only — requests errors embed the URL
        log.warning("jellyfin file lookup failed: %s", type(exc).__name__)
        return None
    if out is not None:
        _cache[(kind, tmdb_id)] = (time.time(), out)
    return out
