"""JY-051: scripts/player_study.py - stream facts, combination keys, hard flags, the play-method decision from a
PlaybackInfo MediaSource, the tables, and the token handling. No network, no ssh."""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import player_study as ps  # noqa: E402

KEY = "0123456789abcdef0123456789abcdef"


def source(container="mkv", vcodec="hevc", depth=10, vrange="SDR", w=1920, h=1080, audio=(("eac3", 6),),
           subs=(), bitrate=5_000_000):
    streams = [{"Type": "Video", "Codec": vcodec, "BitDepth": depth, "VideoRangeType": vrange, "Width": w,
                "Height": h, "Profile": "Main 10", "Level": 120, "Index": 0}]
    for i, (codec, ch) in enumerate(audio):
        streams.append({"Type": "Audio", "Codec": codec, "Channels": ch, "Language": "eng", "IsDefault": i == 0,
                        "Index": 1 + i})
    for codec, external in subs:
        streams.append({"Type": "Subtitle", "Codec": codec, "IsExternal": external, "Index": len(streams)})
    return {"Container": container, "Bitrate": bitrate, "Size": 10, "MediaStreams": streams, "Path": "/x/y.mkv"}


def tc_url(**q):
    query = "&".join(f"{k}={v}" for k, v in q.items())
    return f"/videos/abc/master.m3u8?api_key={KEY}&{query}"


# ---------------------------------------------------------------- stream facts

def test_container_normalised():
    assert ps.norm_container("mov,mp4,m4a,3gp,3g2,mj2") == "mp4"
    assert ps.norm_container("mkv") == "mkv"
    assert ps.norm_container("matroska,webm") == "mkv"
    assert ps.norm_container("webm") == "webm"
    assert ps.norm_container("avi") == "avi"
    assert ps.norm_container(None) == "?"


@pytest.mark.parametrize("w,h,label", [(3840, 2160, "2160p"), (3840, 1608, "2160p"), (1920, 804, "1080p"),
                                       (1920, 1080, "1080p"), (1280, 720, "720p"), (720, 480, "SD"),
                                       (None, None, "?")])
def test_resolution_class(w, h, label):
    assert ps.res_class(w, h) == label


def test_describe_keeps_facts_and_drops_the_path():
    d = ps.describe(source(audio=(("EAC3", 6), ("aac", 2)), subs=(("PGSSUB", False), ("subrip", True))))
    assert d["container"] == "mkv" and d["vcodec"] == "hevc" and d["bitdepth"] == 10
    assert d["acodec"] == "eac3" and d["achannels"] == "5.1"
    assert d["audio_tracks"] == ["eac3 5.1", "aac 2.0"]
    assert d["sub_formats"] == ["pgssub", "subrip"] and d["subs"] == "image+text" and d["sub_external"]
    assert d["has_av"] is True
    assert "/x/y.mkv" not in repr(d)


def test_describe_without_audio_is_not_playable_evidence():
    s = source()
    s["MediaStreams"] = [m for m in s["MediaStreams"] if m["Type"] != "Audio"]
    assert ps.describe(s)["has_av"] is False


def test_combo_key():
    d = ps.describe(source(subs=(("subrip", False),)))
    assert ps.combo_key(d) == "mkv | hevc 10-bit SDR 1080p | eac3 5.1 | subs text"


def test_hard_flags():
    d = ps.describe(source(vrange="DOVIWithHDR10", w=3840, h=2160, audio=(("dts", 6), ("truehd", 8)),
                           subs=(("dvdsub", False), ("ass", True)), bitrate=45_000_000))
    flags = ps.hard_flags(d)
    for f in ("HEVC 10-bit HDR", "Dolby Vision", "DTS", "TrueHD", "7.1 audio", "multi-audio", "VobSub subs",
              "ASS subs", "external subs", "bitrate > 40 Mbps"):
        assert f in flags, f
    assert "HEVC 10-bit SDR" not in flags
    plain = ps.hard_flags(ps.describe(source(container="mp4", vcodec="h264", depth=8, audio=(("aac", 2),))))
    assert plain == []
    assert "AV1" in ps.hard_flags(ps.describe(source(vcodec="av1")))
    assert "container avi" in ps.hard_flags(ps.describe(source(container="avi")))


# ---------------------------------------------------------------- decision parsing

def test_url_facts_never_return_the_key():
    facts = ps.url_facts(tc_url(VideoCodec="h264", AudioCodec="aac", TranscodeReasons="ContainerNotSupported"))
    assert facts == {"VideoCodec": "h264", "AudioCodec": "aac", "TranscodeReasons": "ContainerNotSupported",
                     "Endpoint": "hls"}
    assert KEY not in repr(facts)
    assert ps.url_facts(None) == {}
    assert ps.url_facts(f"/videos/abc/stream.mp4?api_key={KEY}")["Endpoint"] == "progressive"


def test_direct_play():
    d = ps.decision({"SupportsDirectPlay": True, "SupportsDirectStream": True})
    assert d["method"] == "DirectPlay" and d["reasons"] == []


def test_direct_stream_without_transcoding_url():
    assert ps.decision({"SupportsDirectPlay": False, "SupportsDirectStream": True})["method"] == "DirectStream"


def test_container_only_is_a_remux():
    d = ps.decision({"SupportsDirectPlay": False, "SupportsDirectStream": False,
                     "TranscodingUrl": tc_url(VideoCodec="hevc", AudioCodec="aac",
                                              TranscodeReasons="ContainerNotSupported")})
    assert d["method"] == "Remux" and d["vcodec_out"] == "hevc" and d["endpoint"] == "hls"


def test_audio_only_is_remux_plus_audio():
    d = ps.decision({"TranscodingUrl": tc_url(TranscodeReasons="ContainerNotSupported,AudioCodecNotSupported")})
    assert d["method"] == "Remux+Audio"
    assert d["reasons"] == ["ContainerNotSupported", "AudioCodecNotSupported"]


@pytest.mark.parametrize("reasons", ["VideoRangeTypeNotSupported", "SubtitleCodecNotSupported",
                                     "ContainerNotSupported,VideoBitDepthNotSupported,AudioCodecNotSupported",
                                     "ContainerBitrateExceedsLimit", ""])
def test_anything_else_is_a_video_transcode(reasons):
    d = ps.decision({"TranscodingUrl": tc_url(TranscodeReasons=reasons, SubtitleMethod="Encode")})
    assert d["method"] == "Transcode"
    assert d["sub_method"] == "Encode"


def test_nothing_offered():
    assert ps.decision({})["method"] == "None"


# ---------------------------------------------------------------- tables

def test_inventory_summary_and_table():
    rows = [("a" * 32, "Episode", ps.describe(source(subs=(("subrip", False),)))),
            ("b" * 32, "Episode", ps.describe(source(subs=(("subrip", False),)))),
            ("c" * 32, "Movie", ps.describe(source(vrange="DOVIWithHDR10", w=3840, h=2160, audio=(("dts", 6),))))]
    inv = ps.summarise_inventory(rows)
    assert inv["total"] == 3
    assert inv["combos"][0] == ("mkv | hevc 10-bit SDR 1080p | eac3 5.1 | subs text", 2)
    assert dict(inv["flags"])["DTS"] == 1 and inv["flag_ids"]["DTS"][0]["id"] == "c" * 32
    assert dict(inv["fields"]["type"]) == {"Episode": 2, "Movie": 1}
    table = ps.render_inventory(inv)
    assert "| 1 | mkv | hevc 10-bit SDR 1080p | eac3 5.1 | subs text | 2 | 66.7 % | 66.7 % |" in table
    assert "top 2 cover 100.0 %" in table


def test_samples_are_capped():
    rows = [(f"{i:032x}", "Episode", ps.describe(source())) for i in range(10)]
    inv = ps.summarise_inventory(rows)
    assert len(next(iter(inv["combo_ids"].values()))) == ps.SAMPLES


def test_bitrate_bucket():
    assert ps.bitrate_bucket(None) == "?"
    assert ps.bitrate_bucket(1_500_000) == "< 2 Mbps"
    assert ps.bitrate_bucket(45_600_000) == ">= 40 Mbps"


def test_playback_table():
    rows = [{"id": "a" * 32, "tests": "control", "decision": ps.decision({"SupportsDirectPlay": True})},
            {"id": "b" * 32, "tests": "PGS on", "decision": ps.decision(
                {"TranscodingUrl": tc_url(VideoCodec="h264", AudioCodec="aac", SubtitleMethod="Encode",
                                          TranscodeReasons="SubtitleCodecNotSupported")})},
            {"id": "c" * 32, "tests": "x", "error": "HTTP 400"}]
    out = ps.render_playback(rows)
    assert "| DirectPlay (file as is) | - | - | - |" in out
    assert "| Transcode (video transcoded) | SubtitleCodecNotSupported | h264 / aac | Encode |" in out
    assert "| ERROR | HTTP 400 |" in out
    assert KEY not in out


def test_error_hint():
    assert ps.error_hint(b'{"title": "One or more validation errors occurred.", "errors": {"b": [], "a": []}}') \
        == ": One or more validation errors occurred. [a, b]"
    assert ps.error_hint(b"Error processing request.") == ": Error processing request."
    assert "http" not in ps.error_hint(b"see http://jellyfin:8096/x for more")
    assert ps.error_hint(b"") == ""


# ---------------------------------------------------------------- request body, items, token

def test_playback_body():
    b = ps.playback_body(2, 5)
    assert b["AudioStreamIndex"] == 2 and b["SubtitleStreamIndex"] == 5
    assert b["AutoOpenLiveStream"] is False and b["DeviceProfile"] is ps.CHROME_PROFILE
    assert "AudioStreamIndex" not in ps.playback_body(None, None)


def test_test_items_cover_the_brief():
    assert 8 <= len(ps.TEST_ITEMS) <= 12
    assert all(ps.ID_RE.match(i) for i, *_ in ps.TEST_ITEMS)
    assert ps.test_items([]) == ps.TEST_ITEMS
    assert ps.test_items(["f" * 32]) == [("f" * 32, "ad hoc", None, None)]


def test_token_is_injected_only_into_the_piped_copy(tmp_path):
    src = Path(ps.__file__).read_text(encoding="utf-8")
    assert 'STUDY_TOKEN = ""' in src
    piped = ps.inject_token(src, KEY)
    assert f'STUDY_TOKEN = "{KEY}"' in piped and piped.count(KEY) == 1
    assert ps.inject_token(src, "") == src
    with pytest.raises(SystemExit):
        ps.inject_token(src, 'x"; import os #')
    f = tmp_path / "tok"
    f.write_text(KEY + "\n", encoding="utf-8")
    assert ps.read_token(str(f)) == KEY
    f.write_text("not a token", encoding="utf-8")
    with pytest.raises(SystemExit):
        ps.read_token(str(f))


def test_dry_run_sends_nothing(capsys, monkeypatch):
    monkeypatch.setattr(ps, "run_remote", lambda *a, **k: pytest.fail("dry run must not ssh"))
    assert ps.main(["playback", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("DRY RUN: nothing is sent.")
    assert "Items (12):" in out and "http" not in out
    assert ps.main(["inventory", "--dry-run"]) == 0


def test_playback_needs_a_token_file(monkeypatch):
    monkeypatch.delenv("JY051_TOKEN_FILE", raising=False)
    monkeypatch.setattr(ps, "run_remote", lambda *a, **k: pytest.fail("must not ssh without a token"))
    with pytest.raises(SystemExit):
        ps.main(["playback", "--token-file", ""])


def test_bad_ids_refused():
    with pytest.raises(SystemExit):
        ps.main(["playback", "--dry-run", "not-an-id"])
