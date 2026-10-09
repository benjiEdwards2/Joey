"""File-quality strip (2026-10-06): what is ON DISK for a title, read live from Jellyfin
(env JELLYFIN_URL + JELLYFIN_API_KEY, header `Authorization: MediaBrowser Token=`), server-side only.

Words, not logos or colours: each badge is a generic icon id plus a plain word. Any upstream
failure returns None (the strip simply doesn't render); logs carry the exception TYPE only,
never a URL or key.
"""

from __future__ import annotations

import logging
import os
import re
import time

import requests

from hub.media_cache import LRU

log = logging.getLogger("hub.media_files")

TIMEOUT = 8
CACHE_TTL = 600
UID_TTL = 3600
ITEM_FIELDS = "MediaStreams,MediaSources,Path,Width,Height,Container,RunTimeTicks"
ITEM_LIMIT = 500

_cache: LRU = LRU()   # (kind, tmdb) / item keys -> (fetched_at, summary); bounded (M-42)
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
    if rng == "doviinvalid":  # broken DV layer: playback falls back to the HDR10 base
        return "HDR10"
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


# Dolby / DTS badge (2026-10-06): the ONE mapping from an audio word or raw codec string to a
# brand badge. The label is always written out — the double-D glyph is extra, never the only encoding.
BRAND_BADGES = {
    "atmos": ("Dolby Atmos", True), "dolbyatmos": ("Dolby Atmos", True),
    "eac3": ("Dolby Digital Plus", True), "ddp": ("Dolby Digital Plus", True),
    "dolbydigitalplus": ("Dolby Digital Plus", True),
    "ac3": ("Dolby Digital", True), "dolbydigital": ("Dolby Digital", True),
    "truehd": ("Dolby TrueHD", True), "dolbytruehd": ("Dolby TrueHD", True),
    "dts": ("DTS", False), "dtshd": ("DTS-HD", False), "dtshdma": ("DTS-HD MA", False), "dtsx": ("DTS:X", False),
}


def brand_badge(text) -> dict | None:
    """'E-AC-3' / 'Dolby Digital Plus' -> {'label': 'Dolby Digital Plus', 'glyph': True}; unknown -> None."""
    key = "".join(ch for ch in str(text or "").lower() if ch.isalnum())
    hit = BRAND_BADGES.get(key)
    return {"label": hit[0], "glyph": hit[1]} if hit else None


LANG_WORDS = {"eng": "English", "fra": "French", "fre": "French", "deu": "German", "ger": "German",
              "spa": "Spanish", "ita": "Italian", "jpn": "Japanese", "kor": "Korean", "zho": "Chinese",
              "chi": "Chinese", "rus": "Russian", "por": "Portuguese", "hin": "Hindi", "nld": "Dutch",
              "dut": "Dutch", "swe": "Swedish", "nor": "Norwegian", "dan": "Danish", "ara": "Arabic"}


def _lang_word(code) -> str | None:
    code = str(code or "").strip().lower()
    return None if not code or code == "und" else LANG_WORDS.get(code) or code.upper()


# Quality pills (F10): ONE mapping from a badge word to {id, label, tone, glyph}. `id` names the optional
# override image in hub/static/badges/; `tone` picks the pill style (dolby / dts black; hdr dark; plain).
PILL_IDS = {"Dolby Vision": ("dolby-vision", "dolby", True), "Dolby Atmos": ("dolby-atmos", "dolby", True),
            "Atmos": ("dolby-atmos", "dolby", True), "Dolby Digital Plus": ("dolby-digital-plus", "dolby", True),
            "Dolby Digital": ("dolby-digital", "dolby", True), "TrueHD": ("dolby-truehd", "dolby", True),
            "Dolby TrueHD": ("dolby-truehd", "dolby", True), "DTS-HD": ("dts-hd", "dts", False),
            "DTS-HD MA": ("dts-hd", "dts", False), "DTS": ("dts", "dts", False),
            "HDR10": ("hdr10", "hdr", False), "HDR10+": ("hdr10plus", "hdr", False), "HLG": ("hlg", "hdr", False)}


def badge_pill(word: str, icon: str = "") -> dict:
    """A badge word -> the pill to draw. Dolby words read as 'Dolby ...' (Atmos / TrueHD included)."""
    hit = PILL_IDS.get(word)
    label = {"Atmos": "Dolby Atmos", "TrueHD": "Dolby TrueHD"}.get(word, word)
    if hit:
        return {"id": hit[0], "label": label, "tone": hit[1], "glyph": hit[2], "icon": icon}
    return {"id": None, "label": word, "tone": "plain", "glyph": False, "icon": icon}


def _size_text(n) -> str | None:
    if not isinstance(n, (int, float)) or n <= 0:
        return None
    gb = n / 1024 ** 3
    return f"{gb:.1f} GB" if gb >= 1 else f"{n / 1024 ** 2:.0f} MB"


# ---- File panel (film-quality, 2026-10-07): bitrate, picture shape, subtitles kind, source + release group ----

TEXT_SUBS = {"subrip": "SRT", "srt": "SRT", "ass": "ASS", "ssa": "SSA", "mov_text": "MOV text", "webvtt": "WebVTT",
             "text": "Text"}
PICTURE_SUBS = {"pgs": "PGS", "pgssub": "PGS", "hdmv_pgs_subtitle": "PGS", "vobsub": "VobSub", "dvdsub": "VobSub",
                "dvd_subtitle": "VobSub", "dvb_subtitle": "DVB", "dvbsub": "DVB"}
SOURCES = (("remux", "Remux"), ("uhd.?blu.?ray", "UHD Blu-ray"), ("blu.?ray|bdrip|brrip", "Blu-ray"),
           ("web.?dl", "WEB-DL"), ("webrip", "WEBRip"), ("hdtv", "HDTV"), ("dvd.?rip|dvd", "DVD"), ("web", "WEB"))
NOT_GROUPS = {"dl", "rip", "hd", "ma", "x", "uhd", "sdr", "hdr", "dts", "ac3", "aac", "hevc", "avc", "web"}


def subtitle_kind(codec) -> tuple[str, str] | None:
    """('Text'|'Picture', format word) from a subtitle codec; None when unknown."""
    c = str(codec or "").strip().lower()
    if c in TEXT_SUBS:
        return "Text", TEXT_SUBS[c]
    if c in PICTURE_SUBS:
        return "Picture", PICTURE_SUBS[c]
    return None


def basename(path) -> str | None:
    """The file NAME of a media path (either slash) — never the folders, which describe the host's layout."""
    name = re.split(r"[\\/]", str(path or "").strip())[-1]
    return name[:240] or None


def source_word(filename) -> str | None:
    """'...[Bluray-1080p]...' -> 'Blu-ray'; also Remux, UHD Blu-ray, WEB-DL, WEBRip, HDTV, DVD, WEB; else None."""
    name = str(filename or "").lower()
    for pattern, word in SOURCES:
        if re.search(rf"(?<![a-z])(?:{pattern})(?![a-z])", name):
            return word
    return None


def release_group(filename) -> str | None:
    """The trailing '-Group' of a scene-style file name ('...[AAC 5.1]-Tigole.mkv' -> 'Tigole'), else None."""
    stem = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", str(filename or "").strip())
    m = re.search(r"-([A-Za-z0-9][A-Za-z0-9_]{1,19})$", stem)
    if not m or m.group(1).lower() in NOT_GROUPS or re.fullmatch(r"\d+p?|[xh]26[45]", m.group(1).lower()):
        return None
    return m.group(1)


def bitrate_bps(source: dict, item: dict) -> int | None:
    """MediaSource Bitrate (bits/s), else size * 8 / runtime; None when neither is known."""
    rate = source.get("Bitrate")
    if isinstance(rate, (int, float)) and not isinstance(rate, bool) and rate > 0:
        return int(rate)
    size = source.get("Size")
    ticks = source.get("RunTimeTicks") or item.get("RunTimeTicks")
    if isinstance(size, (int, float)) and size > 0 and isinstance(ticks, (int, float)) and ticks > 0:
        return int(size * 8 / (ticks / 10_000_000))
    return None


def bitrate_text(bps) -> str | None:
    return f"{bps / 1_000_000:.1f} Mb/s" if isinstance(bps, (int, float)) and bps > 0 else None


def _ratio(stream: dict) -> float | None:
    w, h = stream.get("Width") or 0, stream.get("Height") or 0
    declared = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*", str(stream.get("AspectRatio") or ""))
    if stream.get("IsAnamorphic") and declared and float(declared.group(2)) > 0:
        return float(declared.group(1)) / float(declared.group(2))  # stored pixels aren't the shape shown
    return w / h if w and h else None


def picture(stream: dict | None) -> dict | None:
    """{'ratio': '2.40 : 1', 'sub': 'Scope · 1920 × 800'} from the video stream; None without a size."""
    r = _ratio(stream or {})
    if not r:
        return None
    shape = ("Scope" if r >= 2.2 else "Wide" if r >= 1.9 else "Flat" if r >= 1.83
             else "Widescreen" if r >= 1.6 else "Full frame")
    w, h = (stream or {}).get("Width"), (stream or {}).get("Height")
    return {"ratio": f"{r:.2f} : 1", "shape": shape, "sub": f"{shape} · {w} × {h}" if w and h else shape}


def _first_seen(values) -> list:
    out = []
    for v in values:
        if v and v not in out:
            out.append(v)
    return out


def subs_text(subs: list[dict]) -> str | None:
    """[{lang, kind, format}] -> 'English + 4 more · Picture (VobSub)'; None without subtitles."""
    if not subs:
        return None
    langs = _first_seen(s.get("lang") for s in subs)
    lead = (langs[0] + (f" + {len(langs) - 1} more" if len(langs) > 1 else "")) if langs \
        else f"{len(subs)} track{'s' if len(subs) != 1 else ''}"
    kinds = _first_seen(s.get("kind") for s in subs)
    if len(kinds) == 1:
        formats = _first_seen(s.get("format") for s in subs)
        return f"{lead} · {kinds[0]}" + (f" ({', '.join(formats)})" if formats else "")
    return f"{lead} · " + " + ".join(kinds) if kinds else lead


def audio_text(audios: list[dict]) -> str | None:
    """'English · 2 tracks' (languages in track order, the default track's first)."""
    if not audios:
        return None
    ordered = sorted(audios, key=lambda a: not a.get("IsDefault"))
    langs = _first_seen(_lang_word(a.get("Language")) for a in ordered)
    n = len(audios)
    tracks = f"{n} track{'s' if n != 1 else ''}"
    return f"{', '.join(langs[:3])} · {tracks}" if langs else tracks


def _detail(item: dict, source: dict, streams: list[dict], video: dict | None, audios: list[dict]) -> dict:
    """The File panel's one-file facts (a film or an episode file). The Path becomes the file NAME only."""
    name = basename(source.get("Path") or item.get("Path"))
    subs = []
    for st in streams:
        if st.get("Type") != "Subtitle":
            continue
        kind = subtitle_kind(st.get("Codec"))
        if kind is None:
            text = st.get("IsTextSubtitleStream")
            kind = ("Text" if text else "Picture", None) if isinstance(text, bool) else (None, None)
        subs.append({"lang": _lang_word(st.get("Language")), "kind": kind[0], "format": kind[1]})
    bps = bitrate_bps(source, item)
    group = release_group(name)
    container = str(source.get("Container") or item.get("Container") or "").upper() or None
    return {"jf_id": str(item.get("Id") or "") or None, "filename": name, "source": source_word(name),
            "group": group, "container": container,
            "release": " · ".join(p for p in ((f"group {group}" if group else None), container) if p) or None,
            "bitrate": bps, "bitrate_text": bitrate_text(bps), "picture": picture(video),
            "audio_text": audio_text(audios), "subs_text": subs_text(subs)}


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
    f["alangs"] = [w for a in audios for w in (_lang_word(a.get("Language")),) if w]
    f["slangs"] = [w for st in streams if st.get("Type") == "Subtitle" for w in (_lang_word(st.get("Language")),) if w]
    if audio:
        f.update(audio=_audio_word(audio), channels=CHANNEL_WORDS.get(audio.get("Channels")),
                 atmos="atmos" in str(audio.get("Profile") or "").lower())
    f["detail"] = _detail(item, source, streams, video, audios)
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
    for b in audio:
        b["brand"] = brand_badge(b["word"]) if b["icon"] in ("audio", "atmos") else None
    return video, audio


def _summarise(kind: str, items: list) -> dict | None:
    pairs = [(i, f) for i in items if isinstance(i, dict) for f in (_facts(i),) if f]
    files = [f for _, f in pairs]
    if kind == "movie":
        files = files[:1]
    if not files:
        return None
    video, audio = _badges(files)
    note = " · ".join(b["word"] for b in video if b["icon"] == "res") if len(files) > 1 else None
    sources = _first_seen(f["detail"]["source"] for f in files)
    return {"kind": kind, "files": len(files), "video": video, "audio": audio,
            "source": sources[0] if len(sources) == 1 else None,
            "file": files[0]["detail"] if kind == "movie" else None, "size": sum(f["size"] for f in files),
            "languages": _ordered(w for f in files for w in f.get("alangs") or []),
            "subtitles": _ordered(w for f in files for w in f.get("slangs") or []),
            "size_text": _size_text(sum(f["size"] for f in files)), "note": note,
            "episodes_on_disk": len(files) if kind == "tv" else None,
            "episode_keys": _episode_keys(pairs) if kind == "tv" else None}


def _episode_keys(pairs) -> list[tuple[int, int]]:
    """(season, episode) for every episode file on disk — from Jellyfin's ParentIndexNumber/IndexNumber."""
    keys = {(i.get("ParentIndexNumber"), i.get("IndexNumber")) for i, _ in pairs}
    return sorted(k for k in keys if all(isinstance(n, int) for n in k))


def _tmdb_match(items, tmdb_id: int) -> list[dict]:
    """Jellyfin 12.x ignores AnyProviderIdEquals, so filter on ProviderIds.Tmdb ourselves."""
    out = []
    for i in items or []:
        ids = i.get("ProviderIds") if isinstance(i, dict) else None
        if isinstance(ids, dict) and any(str(k).lower() == "tmdb" and str(v) == str(tmdb_id) for k, v in ids.items()):
            out.append(i)
    return out


JF_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")   # media_item.ITEM_RE (not imported: media_item imports this module)


def jf_for(kind: str, tmdb_id: int, snaps=None) -> str | None:
    """The Jellyfin id of a film / show from the jellyfin snapshot's library lists (both profiles), or None when the
    title isn't there (off-server, or no snapshot)."""
    from hub.ids import JELLYFIN_SNAPSHOT_ID
    from hub.store import data_of, get_snapshots

    data = data_of((get_snapshots() if snaps is None else snaps).get(JELLYFIN_SNAPSHOT_ID))
    field, key = ("movies" if kind == "movie" else "shows"), f"tmdb:{tmdb_id}"
    for prof in (data, data.get("her") if isinstance(data.get("her"), dict) else {}):
        for r in prof.get(field) or []:
            if isinstance(r, dict) and r.get("item_key") == key and JF_ID_RE.match(str(r.get("jf_id") or "")):
                return str(r["jf_id"])
    return None


def _by_id(base: str, headers: dict, uid: str, kind: str, jf_id: str):
    """M-45: the reads for a known Jellyfin id — a film is one item read, a series' files come from
    /Shows/{id}/Episodes — instead of listing the whole library (multi-MB, and capped at ITEM_LIMIT)."""
    if kind == "movie":
        item = _get(base, headers, f"/Users/{uid}/Items/{jf_id}", {"Fields": ITEM_FIELDS})
        return [item] if isinstance(item, dict) else None
    body = _get(base, headers, f"/Shows/{jf_id}/Episodes", {"UserId": uid, "Fields": ITEM_FIELDS})
    items = body.get("Items") if isinstance(body, dict) else None
    return items if isinstance(items, list) else None


def _items(base: str, headers: dict, uid: str, kind: str, tmdb_id: int):
    """The fallback for a title without a known Jellyfin id (off-server per the snapshot): list and match."""
    path = f"/Users/{uid}/Items"
    common = {"Recursive": "true", "Fields": ITEM_FIELDS, "Limit": ITEM_LIMIT}
    wanted = {"AnyProviderIdEquals": f"Tmdb.{tmdb_id}"}
    if kind == "movie":
        body = _get(base, headers, path, {**wanted, "IncludeItemTypes": "Movie", **common,
                                          "Fields": ITEM_FIELDS + ",ProviderIds"})
        items = body.get("Items") if isinstance(body, dict) else None
        return _tmdb_match(items, tmdb_id)
    # Episodes don't carry the show's TMDB id: find the Series first, then its episodes.
    series = _get(base, headers, path, {**wanted, "IncludeItemTypes": "Series", "Recursive": "true",
                                        "Fields": "ProviderIds", "Limit": ITEM_LIMIT})
    found = _tmdb_match(series.get("Items") if isinstance(series, dict) else None, tmdb_id)
    if not found or not found[0].get("Id"):
        return None
    body = _get(base, headers, path, {"ParentId": found[0]["Id"], "IncludeItemTypes": "Episode", **common})
    items = body.get("Items") if isinstance(body, dict) else None
    return items if isinstance(items, list) else None


def file_summary(kind: str, tmdb_id: int, jf_id: str | None = None, snaps=None) -> dict | None:
    """Quality facts for what is on disk, or None (not in Jellyfin / not configured / any failure). `jf_id` (the film,
    or the SERIES for tv) when the caller knows it, else the snapshot's library lists are asked (jf_for); only a
    title found in neither falls back to listing the library."""
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
        jf_id = jf_id if jf_id and JF_ID_RE.match(str(jf_id)) else jf_for(kind, tmdb_id, snaps)
        items = (_by_id(base, headers, uid, kind, jf_id) if jf_id else _items(base, headers, uid, kind, tmdb_id))             if uid else None
        out = _summarise(kind, items) if items else None
    except Exception as exc:  # type only — requests errors embed the URL
        log.warning("jellyfin file lookup failed: %s", type(exc).__name__)
        return None
    if out is not None:
        _cache[(kind, tmdb_id)] = (time.time(), out)
    return out


def file_summary_from_item(jf_id: str, item: dict) -> dict | None:
    """file_summary_for_item from an item body already read WITH ITEM_FIELDS (the film page's own read):
    no second Jellyfin call. Shares file_summary_for_item's cache entry."""
    key = (f"item:{jf_id}", 0)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    out = _summarise("movie", [item]) if isinstance(item, dict) else None
    if out is not None:
        _cache[key] = (time.time(), out)
    return out


def file_summary_for_item(jf_id: str) -> dict | None:
    """Quality facts for ONE Jellyfin item (a film or an episode file), or None on any failure."""
    key = (f"item:{jf_id}", 0)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    creds = _creds()
    if not creds:
        return None
    base, headers = creds
    try:
        uid = _user_id(base, headers)
        item = _get(base, headers, f"/Users/{uid}/Items/{jf_id}", {"Fields": ITEM_FIELDS}) if uid else None
        out = _summarise("movie", [item]) if isinstance(item, dict) else None
    except Exception as exc:  # type only — requests errors embed the URL
        log.warning("jellyfin item file lookup failed: %s", type(exc).__name__)
        return None
    if out is not None:
        _cache[key] = (time.time(), out)
    return out
