"""JY-051: the study page (hub/static/jy051/study.html) and the Joey Study app's test set. The page's pure logic block
runs under node when available (skipped in the gate, runs in CI) and is checked against player_study.decision()."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import player_study as ps  # noqa: E402

PAGE = REPO_ROOT / "hub" / "static" / "jy051" / "study.html"
KOTLIN = REPO_ROOT / "docs" / "joeyv2" / "research" / "jy051" / "android" / "app" / "src" / "main" / "java" / "net" \
    / "joeyhome" / "study" / "Study.kt"
HTML = PAGE.read_text(encoding="utf-8")
KEY = "0123456789abcdef0123456789abcdef"


def page_items():
    return [(m.group(2), None if m.group(3) == "null" else int(m.group(3)), None if m.group(4) == "null" else int(m.group(4)))
            for m in re.finditer(r'\{n: (\d+), id: "([0-9a-f]{32})", tests: "[^"]*", a: (null|\d+), s: (null|\d+)\}', HTML)]


def test_page_items_match_test_items():
    assert page_items() == [(i, a, s) for i, _, a, s in ps.TEST_ITEMS]


def test_kotlin_items_match_test_items():
    if not KOTLIN.exists():
        pytest.skip("docs/ is not in the gate image")
    src = KOTLIN.read_text(encoding="utf-8")
    found = [(m.group(2), None if m.group(3) == "null" else int(m.group(3)), None if m.group(4) == "null" else int(m.group(4)))
             for m in re.finditer(r'TestItem\((\d+), "([0-9a-f]{32})", (null|\d+), (null|\d+)\)', src)]
    assert found == [(i, a, s) for i, _, a, s in ps.TEST_ITEMS]


def test_page_keeps_no_credential_and_talks_only_to_the_edge():
    assert 'DEFAULT_JF = "https://jellyfin.joeyhome.net:8443"' in HTML
    assert "media.joeyhome.net" not in HTML and "preview.joeyhome.net" not in HTML    # never the tunnel
    assert not re.search(r"(?i)api_key", HTML)                                         # the APK secret scan pattern
    assert "JELLYFIN_API_KEY" not in HTML
    # the sign-in token lives in memory: no storage write of it, no token input field
    assert not re.search(r'store\.set\("token",\s*(?!\s|null)', HTML)
    assert 'id="token"' not in HTML
    assert "console.log" not in HTML                                                   # WebView console -> logcat
    assert re.search(r'cdn\.jsdelivr\.net/npm/hls\.js@\d+\.\d+\.\d+/dist/hls\.min\.js', HTML)


def logic_js() -> str:
    m = re.search(r'<script id="jy051-logic">(.*?)</script>', HTML, re.S)
    assert m, "logic block missing"
    return m.group(1)


def run_node(tmp_path, body: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = tmp_path / "t.js"
    script.write_text(logic_js() + "\nconst JY = globalThis.JY;\n" + body, encoding="utf-8")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def tc(reasons, **q):
    query = "&".join(f"{k}={v}" for k, v in q.items())
    return f"/videos/abc/master.m3u8?ApiKey={KEY}&TranscodeReasons={reasons}&{query}"


def test_js_classify_matches_python_decision(tmp_path):
    sources = [
        {"SupportsDirectPlay": True},
        {"SupportsDirectStream": True},
        {"TranscodingUrl": tc("ContainerNotSupported", VideoCodec="h264", AudioCodec="aac")},
        {"TranscodingUrl": tc("ContainerNotSupported,AudioCodecNotSupported", VideoCodec="hevc", AudioCodec="aac")},
        {"TranscodingUrl": tc("SubtitleCodecNotSupported", SubtitleMethod="Encode")},
        {"TranscodingUrl": tc("")},
        {},
    ]
    got = run_node(tmp_path, f"console.log(JSON.stringify({json.dumps(sources)}.map(JY.classify)));")
    want = [ps.decision(s) for s in sources]
    assert got == want
    assert all(KEY not in json.dumps(g) for g in got)


def test_js_helpers(tmp_path):
    caps = {"mp4": {"h264": True, "hevc": True, "av1": False, "vp9": True}, "mkv": False,
            "audio": {"aac": True, "mp3": True, "opus": True, "flac": True, "ac3": False, "eac3": False, "dts": False},
            "mse": {"h264": True, "hevc": False, "ac3": False, "eac3": True}, "hdr": False, "label": "PC"}
    body = f"""
const p = JY.buildProfile({json.dumps(caps)});
const item = JY.ITEMS[9];
console.log(JSON.stringify({{
  med: [JY.median([3, 1, 2]), JY.median([4, 1]), JY.median([])],
  direct: p.DirectPlayProfiles.map(d => [d.Container, d.VideoCodec, d.AudioCodec]),
  hls: [p.TranscodingProfiles[0].VideoCodec, p.TranscodingProfiles[0].AudioCodec],
  hevcRange: p.CodecProfiles[1].Conditions[1].Value,
  body: JY.w2Body("u1", p, item, "ms1"),
  key: [JY.keyParamOf("/x?ApiKey=1"), JY.keyParamOf("/x?a=1")],
  auth: [JY.authHeader("TV", "d1", ""), JY.authHeader("TV", "d1", "t")],
  sub: [JY.subKind([{{Index: 2, Type: "Subtitle", Codec: "PGSSUB"}}], 2), JY.subKind([], null)],
  summary: JY.rowSummary([{{kind: "run", n: 1, engine: "W1", ok: true, ms_frame: 1000, method: "Direct (as is)"}},
                          {{kind: "run", n: 1, engine: "W1", ok: false, err: "x"}}], 1, "W1")
}}));"""
    r = run_node(tmp_path, body)
    assert r["med"] == [2, 2.5, None]
    assert r["direct"] == [["mp4,m4v", "h264,hevc,vp9", "aac,mp3,opus,flac"]]      # no mkv entry when not claimed
    assert r["hls"] == ["h264", "aac,eac3"]                                       # MSE decides the HLS codecs
    assert r["hevcRange"] == "SDR"
    b = r["body"]
    assert b["EnableDirectPlay"] is False and b["EnableDirectStream"] is False and b["AutoOpenLiveStream"] is False
    assert b["AudioStreamIndex"] == 2 and "SubtitleStreamIndex" not in b and b["UserId"] == "u1"
    assert r["key"] == ["ApiKey", None]
    assert "Token=" not in r["auth"][0] and r["auth"][1].endswith('Token="t"')
    assert r["sub"] == ["image", "none"]
    assert r["summary"] == "1.00 s Direct (as is) (1/2 ok)"


def test_page_main_script_parses(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    scripts = re.findall(r"<script>(.*?)</script>", HTML, re.S)
    assert len(scripts) == 1
    f = tmp_path / "main.js"
    f.write_text(scripts[0], encoding="utf-8")
    out = subprocess.run([node, "--check", str(f)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
