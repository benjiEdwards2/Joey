"""JY-051 player options study: library inventory and PC-browser PlaybackInfo decisions. Stdlib only, read only.

    python scripts/player_study.py inventory [--json]             what the library holds (counts + sample item ids)
    python scripts/player_study.py playback [--dry-run] [--json] [--token-file F] [ids ...]
                                                                 Jellyfin's play decision per test file for the
                                                                 Chrome-class desktop DeviceProfile below

Both run INSIDE joey-hub on the NAS (Jellyfin is reached only from there): this file is piped to
`docker exec -i joey-hub python - --payload ...` over ssh, as scripts/budgets.py does. The NAS login comes from
JOEY_NAS (default root@nas.local), the key from JOEY_NAS_KEY (default ~/.ssh/joey_nas). Nothing printed names the
login, the Jellyfin address, the key, a user, a title or a file path; only item ids, counts and codec facts.

What it sends to Jellyfin (env JELLYFIN_URL, else http://jellyfin:8096):
- inventory: GET /Items (Movie + Episode, paged, Fields=MediaSources,MediaStreams) with the container's
  JELLYFIN_API_KEY (`MediaBrowser Token=`). GETs only.
- playback: with the study account's access token (12.2 answers PlaybackInfo-with-DeviceProfile only for a user;
  the API key has none and gets HTTP 400). The token is read from a local file (--token-file or env
  JY051_TOKEN_FILE), travels only inside the piped copy over ssh, and is never written or printed. Per item one
  GET /Items?Ids=<id> (guard: skip an item with no probed audio/video streams, because PlaybackInfo would then
  trigger a media probe, which is a library write), then POST /Items/<id>/PlaybackInfo with the DeviceProfile and
  AutoOpenLiveStream=false. PlaybackInfo only answers what the server would do; no stream is requested, so no
  transcode job starts, no user is made and nothing is marked played (the study account's last-activity time is
  the only thing that moves). The TranscodingUrl it returns carries the token: only whitelisted query values
  (reasons, codecs, subtitle method) are read from it and the URL itself is never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

HUB_CONTAINER = "joey-hub"
DEFAULT_JELLYFIN = "http://jellyfin:8096"
PAGE = 200
ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")
TOKEN_RE = re.compile(r"^[0-9a-fA-F]{32}$")
STUDY_TOKEN = ""       # filled in the piped copy only (from --token-file); never written to disk or printed
SAMPLES = 3            # item ids kept per combination / flag
TOP = 15

# The test-file set (JY-051 inventory). (item id, property under test, audio stream index, subtitle stream index).
# Stream indexes are Jellyfin MediaStream.Index values; None = server default (no subtitle selected).
TEST_ITEMS: list[tuple[str, str, int | None, int | None]] = [
    ("dcd12e5bf6856e60c225472186cd6cb6", "control: MP4 H.264 8-bit + AAC 2.0, no subs", None, None),
    ("d64f611c17a8d1e628dc0baf8625c536", "top combo: MKV H.264 + EAC3 5.1, SRT on", None, 2),
    ("ff2240b0477c0f0e53772543e772988d", "MKV HEVC 10-bit SDR + EAC3 5.1, SRT on", None, 2),
    ("8e272a6eab2388ea32b247333da9794a", "MKV HEVC 10-bit + AAC 5.1, PGS on", None, 2),
    ("91c55b10825a46ea01cdf50ea760a6ea", "MP4 HEVC 10-bit + AAC 5.1", None, None),
    ("2da3a189e2c7f9d7166cb63aeb849b23", "MP4 2160p Dolby Vision/HDR10 + EAC3, mov_text on", None, 3),
    ("0fc19ee50e310c68987dd14714e824da", "MKV 2160p DV/HDR10 34 Mbps + DTS-HD MA, PGS on", None, 5),
    ("fdbb56885c9e44e039ca5c0aa056d2d4", "MKV H.264 + DTS 5.1, external SRT on", None, 0),
    ("910c6153145342b775e9fbaa911d11aa", "MKV HEVC 10-bit + AAC, VobSub on", None, 3),
    ("75bd8094149b87b7ea659542df28341f", "multi-audio: second track (eng) chosen", 2, None),
    ("51a2003ebcbce12e58ae829bf58d7e58", "AAC 7.1 (8 ch)", None, None),
    ("b171da2503dbcb65d7e9aeffee75b9f0", "MKV H.264 45.6 Mbps + DTS-HD MA 7.1, PGS default on", None, 7),
]

# Desktop Chrome-class browser (Chrome/Edge on Windows, hardware HEVC decode, SDR monitor). Modelled on
# jellyfin-web's browserDeviceProfile for Chrome; stated, not detected. MKV is NOT direct-play (Chrome does not
# claim video/x-matroska), AC3/EAC3/DTS/TrueHD are not decodable, HDR needs an HDR display (assumed absent), PGS
# and VobSub have no renderer (burn-in). The real browser sitting checks these assumptions.
CHROME_PROFILE: dict = {
    "Name": "Joey study: desktop Chrome (SDR display)",
    "MaxStreamingBitrate": 120_000_000,
    "MaxStaticBitrate": 100_000_000,
    "MusicStreamingTranscodingBitrate": 384_000,
    "DirectPlayProfiles": [
        {"Container": "mp4,m4v", "Type": "Video", "VideoCodec": "h264,hevc,vp9,av1",
         "AudioCodec": "aac,mp3,opus,flac,alac"},
        {"Container": "webm", "Type": "Video", "VideoCodec": "vp8,vp9,av1", "AudioCodec": "vorbis,opus"},
        {"Container": "mp3,aac,flac,opus,webm,ogg,wav", "Type": "Audio"},
    ],
    "TranscodingProfiles": [
        {"Container": "mp4", "Type": "Video", "VideoCodec": "hevc,h264", "AudioCodec": "aac,mp3,opus,flac",
         "Context": "Streaming", "Protocol": "hls", "MaxAudioChannels": "6", "MinSegments": "1",
         "BreakOnNonKeyFrames": True},
        {"Container": "ts", "Type": "Video", "VideoCodec": "h264", "AudioCodec": "aac,mp3",
         "Context": "Streaming", "Protocol": "hls", "MaxAudioChannels": "6", "MinSegments": "1",
         "BreakOnNonKeyFrames": True},
        {"Container": "mp3", "Type": "Audio", "AudioCodec": "mp3", "Context": "Streaming", "Protocol": "http",
         "MaxAudioChannels": "2"},
    ],
    "ContainerProfiles": [],
    "CodecProfiles": [
        {"Type": "Video", "Codec": "h264", "Conditions": [
            {"Condition": "EqualsAny", "Property": "VideoProfile",
             "Value": "high|main|baseline|constrained baseline", "IsRequired": False},
            {"Condition": "LessThanEqual", "Property": "VideoLevel", "Value": "52", "IsRequired": False},
            {"Condition": "LessThanEqual", "Property": "VideoBitDepth", "Value": "8", "IsRequired": False},
            {"Condition": "EqualsAny", "Property": "VideoRangeType", "Value": "SDR", "IsRequired": False}]},
        {"Type": "Video", "Codec": "hevc", "Conditions": [
            {"Condition": "EqualsAny", "Property": "VideoProfile", "Value": "main|main 10", "IsRequired": False},
            {"Condition": "LessThanEqual", "Property": "VideoLevel", "Value": "183", "IsRequired": False},
            {"Condition": "EqualsAny", "Property": "VideoRangeType", "Value": "SDR", "IsRequired": False}]},
        {"Type": "Video", "Codec": "av1", "Conditions": [
            {"Condition": "EqualsAny", "Property": "VideoRangeType", "Value": "SDR", "IsRequired": False}]},
        {"Type": "VideoAudio", "Conditions": [
            {"Condition": "LessThanEqual", "Property": "AudioChannels", "Value": "6", "IsRequired": False}]},
    ],
    "SubtitleProfiles": [
        {"Format": "vtt", "Method": "External"},
        {"Format": "srt", "Method": "External"},
        {"Format": "subrip", "Method": "External"},
        {"Format": "ass", "Method": "External"},
        {"Format": "ssa", "Method": "External"},
    ],
    "ResponseProfiles": [{"Type": "Video", "Container": "m4v", "MimeType": "video/mp4"}],
}

TEXT_SUBS = {"srt", "subrip", "ass", "ssa", "vtt", "webvtt", "mov_text", "text", "smi", "sub", "ttml"}
IMAGE_SUBS = {"pgssub", "pgs", "dvdsub", "vobsub", "dvbsub", "dvb_subtitle", "hdmv_pgs_subtitle", "xsub"}
CONTAINER_ONLY = {"ContainerNotSupported", "DirectPlayError", "ContainerBitrateExceedsLimit_static"}
AUDIO_REASONS = {"AudioCodecNotSupported", "AudioChannelsNotSupported", "AudioProfileNotSupported",
                 "AudioSampleRateNotSupported", "AudioBitDepthNotSupported", "AudioBitrateNotSupported",
                 "AudioIsExternal", "SecondaryAudioNotSupported", "UnknownAudioStreamInfo"}
URL_KEEP = ("TranscodeReasons", "VideoCodec", "AudioCodec", "SubtitleMethod", "SegmentContainer")


# ---------------------------------------------------------------- pure helpers (unit-tested, no network)

def norm_container(c: str | None) -> str:
    c = (c or "").lower().strip()
    if not c:
        return "?"
    parts = [p for p in c.split(",") if p]
    if "mp4" in parts or "mov" in parts:
        return "mp4"
    if "matroska" in parts or "mkv" in parts:
        return "mkv"
    return parts[0]


def res_class(width: int | None, height: int | None) -> str:
    w, h = width or 0, height or 0
    if w >= 3200 or h >= 1900:
        return "2160p"
    if w >= 1800 or h >= 1000:
        return "1080p"
    if w >= 1200 or h >= 700:
        return "720p"
    return "SD" if (w or h) else "?"


def channels_label(ch: int | None) -> str:
    return {1: "1.0", 2: "2.0", 6: "5.1", 8: "7.1"}.get(ch or 0, f"{ch or '?'}ch")


def sub_kind(codec: str | None) -> str:
    c = (codec or "").lower()
    if c in IMAGE_SUBS:
        return "image"
    if c in TEXT_SUBS:
        return "text"
    return "other"


def range_label(stream: dict) -> str:
    return stream.get("VideoRangeType") or stream.get("VideoRange") or "SDR"


def describe(source: dict) -> dict:
    """Facts for one MediaSource (no path, no title)."""
    streams = source.get("MediaStreams") or []
    video = next((s for s in streams if s.get("Type") == "Video"), {})
    audio = [s for s in streams if s.get("Type") == "Audio"]
    subs = [s for s in streams if s.get("Type") == "Subtitle"]
    a0 = next((s for s in audio if s.get("IsDefault")), audio[0] if audio else {})
    sub_formats = sorted({(s.get("Codec") or "?").lower() for s in subs})
    kinds = sorted({sub_kind(s.get("Codec")) for s in subs})
    return {
        "container": norm_container(source.get("Container")),
        "vcodec": (video.get("Codec") or "none").lower(),
        "vprofile": video.get("Profile") or "",
        "vlevel": video.get("Level"),
        "bitdepth": video.get("BitDepth"),
        "range": range_label(video) if video else "-",
        "res": res_class(video.get("Width"), video.get("Height")),
        "bitrate": source.get("Bitrate") or video.get("BitRate"),
        "size": source.get("Size"),
        "acodec": (a0.get("Codec") or "none").lower(),
        "achannels": channels_label(a0.get("Channels")) if a0 else "-",
        "audio_tracks": [f"{(s.get('Codec') or '?').lower()} {channels_label(s.get('Channels'))}" for s in audio],
        "audio_langs": sorted({(s.get("Language") or "und").lower() for s in audio}),
        "sub_formats": sub_formats,
        "sub_external": any(s.get("IsExternal") for s in subs),
        "subs": "+".join(kinds) if kinds else "none",
        "has_av": bool(video) and bool(audio),
    }


def combo_key(d: dict) -> str:
    depth = f" {d['bitdepth']}-bit" if d.get("bitdepth") else ""
    return (f"{d['container']} | {d['vcodec']}{depth} {d['range']} {d['res']} | "
            f"{d['acodec']} {d['achannels']} | subs {d['subs']}")


def hard_flags(d: dict) -> list[str]:
    tracks = " ".join(d["audio_tracks"])
    flags = []
    if d["vcodec"] == "hevc" and (d.get("bitdepth") or 8) >= 10 and d["range"] != "SDR":
        flags.append("HEVC 10-bit HDR")
    if "DOVI" in d["range"].upper():
        flags.append("Dolby Vision")
    if d["vcodec"] == "hevc" and (d.get("bitdepth") or 8) >= 10 and d["range"] == "SDR":
        flags.append("HEVC 10-bit SDR")
    if d["vcodec"] == "av1":
        flags.append("AV1")
    if d["vcodec"] == "h264" and (d.get("bitdepth") or 8) >= 10:
        flags.append("H.264 10-bit")
    if d["vcodec"] in {"mpeg2video", "mpeg4", "vc1", "msmpeg4v3", "wmv3"}:
        flags.append("legacy video codec")
    if "dts" in tracks:
        flags.append("DTS")
    if "truehd" in tracks:
        flags.append("TrueHD")
    if re.search(r"\b(ac3|eac3)\b", tracks):
        flags.append("AC3/EAC3")
    if "7.1" in tracks:
        flags.append("7.1 audio")
    if len(d["audio_tracks"]) > 1:
        flags.append("multi-audio")
    if any(f in {"pgssub", "pgs", "hdmv_pgs_subtitle"} for f in d["sub_formats"]):
        flags.append("PGS subs")
    if any(f in {"dvdsub", "vobsub"} for f in d["sub_formats"]):
        flags.append("VobSub subs")
    if any(f in {"ass", "ssa"} for f in d["sub_formats"]):
        flags.append("ASS subs")
    if d["sub_external"]:
        flags.append("external subs")
    if d["container"] not in {"mkv", "mp4"}:
        flags.append(f"container {d['container']}")
    if (d.get("bitrate") or 0) > 40_000_000:
        flags.append("bitrate > 40 Mbps")
    return flags


def url_facts(url: str | None) -> dict:
    """Whitelisted query values of a TranscodingUrl (never the URL: it carries the key)."""
    if not url:
        return {}
    parsed = urllib.parse.urlsplit(url)
    q = {k.lower(): v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
    out = {k: q[k.lower()] for k in URL_KEEP if k.lower() in q}
    out["Endpoint"] = "hls" if parsed.path.endswith(".m3u8") else "progressive"
    return out


def decision(source: dict) -> dict:
    """Play method Jellyfin offers for one MediaSource of a PlaybackInfo answer.

    DirectPlay: the file as is. DirectStream: the file as is through the stream endpoint. Otherwise the
    TranscodingUrl decides, by its TranscodeReasons: container-only = remux (video and audio copied), audio-only
    = remux + audio transcode (video copied), anything about video, subtitles (burn-in) or bitrate = video
    transcode."""
    facts = url_facts(source.get("TranscodingUrl"))
    reasons = [r for r in (facts.get("TranscodeReasons") or "").split(",") if r]
    if source.get("SupportsDirectPlay"):
        method, detail = "DirectPlay", "file as is"
    elif source.get("SupportsDirectStream") and not source.get("TranscodingUrl"):
        method, detail = "DirectStream", "file as is via stream endpoint"
    elif source.get("TranscodingUrl"):
        rs = set(reasons)
        if rs and rs <= CONTAINER_ONLY:
            method, detail = "Remux", "video + audio copied"
        elif rs and rs <= (CONTAINER_ONLY | AUDIO_REASONS):
            method, detail = "Remux+Audio", "video copied, audio transcoded"
        else:
            method, detail = "Transcode", "video transcoded"
    else:
        method, detail = "None", "no play method offered"
    return {"method": method, "detail": detail, "reasons": reasons,
            "vcodec_out": facts.get("VideoCodec", ""), "acodec_out": facts.get("AudioCodec", ""),
            "sub_method": facts.get("SubtitleMethod", ""), "endpoint": facts.get("Endpoint", "")}


def summarise_inventory(described: list[tuple[str, str, dict]]) -> dict:
    """(item id, type, describe()) rows -> counters and sample ids. Pure."""
    combos, flags, fields = Counter(), Counter(), {k: Counter() for k in (
        "type", "container", "vcodec", "bitdepth", "range", "res", "acodec_any", "achannels_any", "audio_lang",
        "sub_format", "subs", "bitrate")}
    combo_ids: dict[str, list] = {}
    flag_ids: dict[str, list] = {}
    for item_id, typ, d in described:
        key = combo_key(d)
        combos[key] += 1
        combo_ids.setdefault(key, [])
        sample = {"id": item_id, "type": typ, "bitrate": d.get("bitrate"), "size": d.get("size"),
                  "audio": d["audio_tracks"], "subs": d["sub_formats"]}
        if len(combo_ids[key]) < SAMPLES:
            combo_ids[key].append(sample)
        for f in hard_flags(d):
            flags[f] += 1
            flag_ids.setdefault(f, [])
            if len(flag_ids[f]) < SAMPLES:
                flag_ids[f].append(dict(sample, combo=key))
        fields["type"][typ] += 1
        fields["container"][d["container"]] += 1
        fields["vcodec"][d["vcodec"]] += 1
        fields["bitdepth"][str(d.get("bitdepth") or "?")] += 1
        fields["range"][d["range"]] += 1
        fields["res"][d["res"]] += 1
        for t in set(d["audio_tracks"]):
            codec, ch = t.rsplit(" ", 1)
            fields["acodec_any"][codec] += 1
            fields["achannels_any"][ch] += 1
        for lang in d["audio_langs"]:
            fields["audio_lang"][lang] += 1
        for f in d["sub_formats"]:
            fields["sub_format"][f] += 1
        fields["subs"][d["subs"]] += 1
        fields["bitrate"][bitrate_bucket(d.get("bitrate"))] += 1
    return {"total": len(described), "combos": combos.most_common(), "combo_ids": combo_ids,
            "flags": flags.most_common(), "flag_ids": flag_ids,
            "fields": {k: v.most_common() for k, v in fields.items()}}


def bitrate_bucket(bps: int | None) -> str:
    if not bps:
        return "?"
    mbps = bps / 1e6
    for edge in (2, 5, 10, 20, 40):
        if mbps < edge:
            return f"< {edge} Mbps"
    return ">= 40 Mbps"


def pct(n: int, total: int) -> str:
    return f"{100 * n / total:.1f} %" if total else "-"


def render_inventory(inv: dict, top: int = TOP) -> str:
    total = inv["total"]
    lines = [f"Items with a media source: {total}", "",
             "| # | Container, video, audio (default track), subtitles | Items | % | Cum % | Sample id |",
             "|---|---|---|---|---|---|"]
    cum = 0
    for i, (key, n) in enumerate(inv["combos"][:top], 1):
        cum += n
        sample = (inv["combo_ids"].get(key) or [{}])[0].get("id", "")
        lines.append(f"| {i} | {key} | {n} | {pct(n, total)} | {pct(cum, total)} | `{sample}` |")
    lines += ["", f"Combinations in all: {len(inv['combos'])}; top {min(top, len(inv['combos']))} cover "
              f"{pct(cum, total)}.", "", "| Hard property | Items | % | Sample ids |", "|---|---|---|---|"]
    for flag, n in inv["flags"]:
        ids = ", ".join(f"`{s['id']}`" for s in inv["flag_ids"].get(flag, []))
        lines.append(f"| {flag} | {n} | {pct(n, total)} | {ids} |")
    for field, counts in inv["fields"].items():
        lines += ["", f"**{field}:** " + ", ".join(f"{k} {v}" for k, v in counts)]
    return "\n".join(lines)


def render_playback(rows: list[dict]) -> str:
    lines = ["| Item id | Tests | Method | Reasons | Out video / audio | Subs |", "|---|---|---|---|---|---|"]
    for r in rows:
        if r.get("error"):
            lines.append(f"| `{r['id']}` | {r.get('tests', '')} | ERROR | {r['error']} | | |")
            continue
        d = r["decision"]
        out = f"{d['vcodec_out'] or '-'} / {d['acodec_out'] or '-'}" if d["method"] not in ("DirectPlay",) else "-"
        lines.append(f"| `{r['id']}` | {r.get('tests', '')} | {d['method']} ({d['detail']}) | "
                     f"{', '.join(d['reasons']) or '-'} | {out} | {d['sub_method'] or '-'} |")
    return "\n".join(lines)


def playback_body(audio_index: int | None, sub_index: int | None) -> dict:
    body = {"DeviceProfile": CHROME_PROFILE, "MaxStreamingBitrate": CHROME_PROFILE["MaxStreamingBitrate"],
            "StartTimeTicks": 0, "EnableDirectPlay": True, "EnableDirectStream": True,
            "EnableTranscoding": True, "AllowVideoStreamCopy": True, "AllowAudioStreamCopy": True,
            "AutoOpenLiveStream": False}
    if audio_index is not None:
        body["AudioStreamIndex"] = audio_index
    if sub_index is not None:
        body["SubtitleStreamIndex"] = sub_index
    return body


def error_hint(body: bytes) -> str:
    """': <title>; <field names>' from an ASP.NET problem-details body; nothing else of the body is shown."""
    try:
        doc = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        line = body.decode("utf-8", "replace").strip().splitlines()[:1]
        return (": " + re.sub(r"https?://\S+|[^\w .,'-]", "", line[0])[:60]) if line else ""
    if not isinstance(doc, dict):
        return ""
    title = re.sub(r"[^\w .,'-]", "", str(doc.get("title") or ""))[:80]
    fields = ", ".join(sorted(str(k) for k in (doc.get("errors") or {}))[:5]) if isinstance(
        doc.get("errors"), dict) else ""
    return (f": {title}" if title else "") + (f" [{fields}]" if fields else "")


def test_items(ids: list[str]) -> list[tuple[str, str, int | None, int | None]]:
    if not ids:
        return list(TEST_ITEMS)
    known = {t[0]: t for t in TEST_ITEMS}
    return [known.get(i, (i, "ad hoc", None, None)) for i in ids]


# ---------------------------------------------------------------- inside joey-hub (payload)

def _jf(user_token: str = ""):
    """GET/POST caller. Default credential: the container's JELLYFIN_API_KEY. PlaybackInfo with a DeviceProfile
    needs a user (12.2 looks the caller's user up and an API key has none: HTTP 400), so playback passes the
    study account's token instead."""
    base = (os.environ.get("JELLYFIN_URL") or DEFAULT_JELLYFIN).strip().rstrip("/")
    key = user_token or (os.environ.get("JELLYFIN_API_KEY") or "").strip()
    if not key:
        raise SystemExit("JELLYFIN_API_KEY is not set in this container")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    headers = {"Authorization": f'MediaBrowser Token="{key}"', "Accept": "application/json"}

    def call(path: str, body: dict | None = None, timeout: float = 120.0):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(base + path, data=data, headers=dict(
            headers, **({"Content-Type": "application/json"} if data else {})),
            method="POST" if data is not None else "GET")
        try:
            with opener.open(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}{error_hint(exc.read())}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(type(exc).__name__) from None
    return call


def payload_inventory() -> dict:
    call = _jf()
    described, start = [], 0
    while True:
        q = urllib.parse.urlencode({"Recursive": "true", "IncludeItemTypes": "Movie,Episode",
                                    "Fields": "MediaSources,MediaStreams", "EnableImages": "false",
                                    "EnableUserData": "false", "StartIndex": start, "Limit": PAGE,
                                    "SortBy": "SortName"})
        page = call(f"/Items?{q}")
        items = page.get("Items") or []
        for it in items:
            sources = it.get("MediaSources") or []
            if sources:
                described.append((it.get("Id", ""), it.get("Type", "?"), describe(sources[0])))
        start += len(items)
        if not items or start >= (page.get("TotalRecordCount") or 0):
            break
    inv = summarise_inventory(described)
    inv["no_source"] = start - len(described)
    inv["multi_version"] = 0
    return inv


def payload_playback(items: list[tuple[str, str, int | None, int | None]]) -> list[dict]:
    if not TOKEN_RE.match(STUDY_TOKEN):
        raise SystemExit("playback needs the study account's token (--token-file)")
    call = _jf(STUDY_TOKEN)
    rows = []
    for item_id, tests, a_idx, s_idx in items:
        row = {"id": item_id, "tests": tests, "audio_index": a_idx, "sub_index": s_idx}
        try:
            q = urllib.parse.urlencode({"Ids": item_id, "Fields": "MediaSources,MediaStreams",
                                        "EnableImages": "false", "EnableUserData": "false"})
            found = (call(f"/Items?{q}").get("Items") or [])
            sources = (found[0].get("MediaSources") or []) if found else []
            if not sources or not describe(sources[0])["has_av"]:
                row["error"] = "skipped: no probed audio/video streams (PlaybackInfo would probe = write)"
            else:
                row["source"] = describe(sources[0])
                ans = call(f"/Items/{item_id}/PlaybackInfo", playback_body(a_idx, s_idx))
                ms = ans.get("MediaSources") or []
                if ans.get("ErrorCode") or not ms:
                    row["error"] = f"ErrorCode {ans.get('ErrorCode') or 'none'}, sources {len(ms)}"
                else:
                    row["decision"] = decision(ms[0])
                    row["play_session"] = bool(ans.get("PlaySessionId"))
        except RuntimeError as exc:
            row["error"] = str(exc)
        rows.append(row)
    return rows


# ---------------------------------------------------------------- laptop side (ssh)

def scrub(text: str, nas: str = "") -> str:
    last = next((ln.strip() for ln in reversed(text.splitlines()) if ln.strip()), "")
    if nas:
        last = last.replace(nas, "<nas>").replace(nas.split("@", 1)[-1], "<nas>")
    last = re.sub(r"[\w.+-]+@[\w.-]+", "<nas>", last)
    last = re.sub(r"https?://\S+", "<url>", last)
    return last[:160]


def read_token(path: str) -> str:
    """The study account's Jellyfin access token from a local file (32 hex characters, nothing else)."""
    try:
        token = Path(os.path.expanduser(path)).read_text(encoding="utf-8").strip()
    except OSError:
        raise SystemExit("token file not readable") from None
    if not TOKEN_RE.match(token):
        raise SystemExit("token file must hold one Jellyfin access token (32 hex characters)")
    return token


def inject_token(src: str, token: str) -> str:
    """The piped copy carries the token (over ssh, on stdin); the file on disk never does."""
    marker = 'STUDY_TOKEN = ""'
    if not token:
        return src
    if src.count(marker) < 1 or not TOKEN_RE.match(token):
        raise SystemExit("cannot inject the token")
    return src.replace(marker, f'STUDY_TOKEN = "{token}"', 1)


def run_remote(args: list[str], nas: str, key: str, token: str = "", timeout: float = 900.0) -> object:
    remote = f"docker exec -i {HUB_CONTAINER} python - --payload " + " ".join(args)
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    if key and os.path.isfile(key):
        cmd += ["-i", key]
    cmd += [nas, remote]
    src = inject_token(Path(__file__).read_text(encoding="utf-8"), token).encode("utf-8")
    proc = subprocess.run(cmd, input=src, capture_output=True, timeout=timeout)
    out, err = proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")
    if proc.returncode != 0:
        raise SystemExit(f"remote run failed (exit {proc.returncode}): {scrub(err, nas)}")
    return json.loads(out)


def plan_text(items: list[tuple[str, str, int | None, int | None]]) -> str:
    p = CHROME_PROFILE
    lines = ["DRY RUN: nothing is sent.",
             f"Route: ssh <nas> docker exec -i {HUB_CONTAINER} python - --payload playback (this file on stdin)",
             "Per item, inside joey-hub, to Jellyfin with header MediaBrowser Token=<study account token>:",
             "  1. GET /Items?Ids=<id>&Fields=MediaSources,MediaStreams (skip if no probed audio/video streams)",
             "  2. POST /Items/<id>/PlaybackInfo  body: DeviceProfile + AutoOpenLiveStream=false, no stream request",
             f"DeviceProfile: {p['Name']}; max streaming {p['MaxStreamingBitrate'] // 1_000_000} Mbps",
             "  direct play: " + "; ".join(f"{d['Container']} [{d.get('VideoCodec', '-')} / {d.get('AudioCodec', '-')}]"
                                            for d in p["DirectPlayProfiles"] if d["Type"] == "Video"),
             "  transcode to: " + "; ".join(f"{t['Protocol']} {t['Container']} [{t['VideoCodec']} / {t['AudioCodec']}]"
                                             for t in p["TranscodingProfiles"] if t["Type"] == "Video"),
             "  subtitles external: " + ", ".join(s["Format"] for s in p["SubtitleProfiles"]) + "; others burn in",
             f"Items ({len(items)}):"]
    for item_id, tests, a_idx, s_idx in items:
        extra = "".join([f", audio #{a_idx}" if a_idx is not None else "",
                         f", subtitle #{s_idx}" if s_idx is not None else ""])
        lines.append(f"  {item_id}  {tests}{extra}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="JY-051 player study (read only).")
    ap.add_argument("mode", choices=("inventory", "playback"))
    ap.add_argument("ids", nargs="*", help="playback: item ids (default: the TEST_ITEMS set)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, send nothing")
    ap.add_argument("--json", action="store_true", help="print raw JSON")
    ap.add_argument("--token-file", default=os.environ.get("JY051_TOKEN_FILE", ""),
                    help="playback: local file holding the study account's Jellyfin access token "
                         "(default env JY051_TOKEN_FILE)")
    ap.add_argument("--payload", action="store_true", help=argparse.SUPPRESS)   # inside joey-hub
    args = ap.parse_args(argv)
    bad = [i for i in args.ids if not ID_RE.match(i)]
    if bad:
        ap.error("item ids are 32 hex characters")
    items = test_items(args.ids)

    if args.payload:
        print(json.dumps(payload_inventory() if args.mode == "inventory" else payload_playback(items)))
        return 0
    if args.dry_run:
        print(plan_text(items) if args.mode == "playback" else
              "DRY RUN: inventory = paged GET /Items (Movie,Episode; Fields=MediaSources,MediaStreams) inside "
              f"{HUB_CONTAINER}; prints counts and item ids only.")
        return 0
    if args.mode == "playback" and not items:
        ap.error("no test items: pass ids or fill TEST_ITEMS")
    if args.mode == "playback" and not args.token_file:
        ap.error("playback needs --token-file (PlaybackInfo with a DeviceProfile needs a user; the API key has none)")
    token = read_token(args.token_file) if args.mode == "playback" else ""
    nas = os.environ.get("JOEY_NAS", "root@nas.local")
    key = os.path.expanduser(os.environ.get("JOEY_NAS_KEY", "~/.ssh/joey_nas"))
    remote_args = [args.mode] + [i for i, *_ in items] if args.mode == "playback" else [args.mode]
    data = run_remote(remote_args, nas, key, token)
    if args.json:
        print(json.dumps(data, indent=2))
    elif args.mode == "inventory":
        print(render_inventory(data))
    else:
        print(render_playback(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
