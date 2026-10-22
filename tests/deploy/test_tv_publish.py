"""Joey TV WP-B8 step 4: deploy/tv_publish.py against a loopback fake of the GitHub API (works under --network none:
127.0.0.1 only). Eight plan cases: published (version.json written last), current (no HTTP), pending (dir unchanged),
hash mismatch (dir unchanged, staging cleaned), versionCode mismatch, downgrade refused, 401 naming the token,
retention 3 - plus the token never following the storage redirect, a half-uploaded release, and no token."""
import hashlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "deploy"))
import tv_publish  # noqa: E402

SLUG = "benjiEdwards2/life-dashboard"
CODE = 2026110302
APK = f"joey-media-1.4.0-{CODE}.apk"
APK_BYTES = b"PK\x03\x04 fake apk body " * 100
TOKEN = "github_pat_TESTONLY"


def version_doc(**over):
    doc = {"version": "1.4.0", "versionCode": CODE, "min_version": 2026102101, "url": APK,
           "sha256": hashlib.sha256(APK_BYTES).hexdigest(), "notes": "n", "size": len(APK_BYTES),
           "published": "2026-11-03T01:02:03Z"}
    doc.update(over)
    return doc


class FakeGitHub:
    """/repos/<slug>/releases/tags/tv-<code> -> release JSON; /assets/<name> -> 302 /dl/<name>; /dl/<name> -> bytes."""

    def __init__(self):
        self.requests: list[tuple[str, str | None]] = []   # (path, Authorization header)
        self.status = 200
        self.assets = {APK: APK_BYTES, "version.json": json.dumps(version_doc()).encode()}
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                fake.requests.append((self.path, self.headers.get("Authorization")))
                if self.path.startswith(f"/repos/{SLUG}/releases/tags/"):
                    if fake.status != 200:
                        return self._send(fake.status, b'{"message":"nope"}')
                    tag = self.path.rsplit("/", 1)[1]
                    if tag != f"tv-{CODE}":
                        return self._send(404, b'{"message":"Not Found"}')
                    assets = [{"name": n, "url": f"{fake.base}/assets/{n}"} for n in fake.assets]
                    return self._send(200, json.dumps({"tag_name": tag, "assets": assets}).encode())
                if self.path.startswith("/assets/"):
                    assert self.headers.get("Accept") == "application/octet-stream"
                    self.send_response(302)
                    self.send_header("Location", f"{fake.base}/dl/{self.path.rsplit('/', 1)[1]}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None
                if self.path.startswith("/dl/"):
                    return self._send(200, fake.assets[self.path.rsplit("/", 1)[1]])
                return self._send(404, b"")

            def _send(self, status, body):
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def gh():
    fake = FakeGitHub()
    yield fake
    fake.close()


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "tv").mkdir(parents=True)
    (root / "tv" / "VERSION").write_text(f"versionName=1.4.0\nversionCode={CODE}\nminVersionCode=2026102101\n",
                                         encoding="utf-8")
    (root / "tv" / "NOTES.txt").write_text("n\n", encoding="utf-8")
    return root


@pytest.fixture()
def out(tmp_path):
    d = tmp_path / "tv-app"
    d.mkdir()
    return d


def run(repo, out, gh, monkeypatch, capsys, token=TOKEN):
    if token is None:
        monkeypatch.delenv("GH_TV_TOKEN", raising=False)
    else:
        monkeypatch.setenv("GH_TV_TOKEN", token)
    rc = tv_publish.main(["--repo", str(repo), "--out", str(out), "--api", gh.base, "--slug", SLUG])
    captured = capsys.readouterr()
    lines = captured.out.strip().splitlines()
    assert len(lines) == 1 and " " not in lines[0], captured.out   # one space-free status token
    assert TOKEN not in captured.out + captured.err
    return rc, lines[0], captured.err


def listing(d: Path) -> dict:
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in d.rglob("*") if p.is_file()}


def test_published_writes_version_json_last(repo, out, gh, monkeypatch, capsys):
    order = []
    real = tv_publish.os.replace
    monkeypatch.setattr(tv_publish.os, "replace", lambda a, b: (order.append(Path(b).name), real(a, b)))
    rc, status, _ = run(repo, out, gh, monkeypatch, capsys)
    assert (rc, status) == (0, f"published:{CODE}")
    assert order == [APK, "version.json"]
    assert (out / APK).read_bytes() == APK_BYTES
    assert json.loads((out / "version.json").read_text())["versionCode"] == CODE
    assert not (out / ".staging").exists()


def test_the_token_never_follows_the_storage_redirect(repo, out, gh, monkeypatch, capsys):
    run(repo, out, gh, monkeypatch, capsys)
    auth = {path.split("/")[1]: header for path, header in gh.requests}
    assert auth["repos"] == f"Bearer {TOKEN}" and auth["assets"] == f"Bearer {TOKEN}"
    assert auth["dl"] is None


def test_current_makes_no_http_call(repo, out, gh, monkeypatch, capsys):
    (out / "version.json").write_text(json.dumps(version_doc()), encoding="utf-8")
    rc, status, _ = run(repo, out, gh, monkeypatch, capsys)
    assert (rc, status) == (0, "current")
    assert gh.requests == []


def test_pending_leaves_the_dir_unchanged(repo, out, gh, monkeypatch, capsys):
    old = version_doc(versionCode=2026102101, url="joey-media-0.1.0-2026102101.apk", version="0.1.0")
    (out / "version.json").write_text(json.dumps(old), encoding="utf-8")
    (repo / "tv" / "VERSION").write_text("versionName=1.5.0\nversionCode=2026110401\nminVersionCode=2026102101\n",
                                         encoding="utf-8")
    before = listing(out)
    rc, status, _ = run(repo, out, gh, monkeypatch, capsys)
    assert (rc, status) == (0, "pending:2026110401")
    assert listing(out) == before


def test_a_half_uploaded_release_is_pending(repo, out, gh, monkeypatch, capsys):
    del gh.assets["version.json"]
    rc, status, _ = run(repo, out, gh, monkeypatch, capsys)
    assert (rc, status) == (0, f"pending:{CODE}") and listing(out) == {}


def test_hash_mismatch_leaves_the_dir_unchanged_and_cleans_staging(repo, out, gh, monkeypatch, capsys):
    gh.assets["version.json"] = json.dumps(version_doc(sha256="0" * 64)).encode()
    rc, status, err = run(repo, out, gh, monkeypatch, capsys)
    assert (rc, status) == (1, "FAIL:verify-sha256") and "sha256" in err
    assert listing(out) == {} and not (out / ".staging").exists()


def test_version_code_mismatch_fails(repo, out, gh, monkeypatch, capsys):
    gh.assets["version.json"] = json.dumps(version_doc(versionCode=2026110303, url="joey-media-1.4.0-2026110303.apk",
                                                       min_version=2026102101)).encode()
    rc, status, _ = run(repo, out, gh, monkeypatch, capsys)
    assert (rc, status) == (1, "FAIL:verify-code")
    assert listing(out) == {}


def test_downgrade_is_refused_without_http(repo, out, gh, monkeypatch, capsys):
    newer = version_doc(versionCode=2026120101, url="joey-media-2.0.0-2026120101.apk", version="2.0.0")
    (out / "version.json").write_text(json.dumps(newer), encoding="utf-8")
    before = listing(out)
    rc, status, err = run(repo, out, gh, monkeypatch, capsys)
    assert (rc, status) == (1, "FAIL:downgrade") and "HIGHER versionCode" in err
    assert listing(out) == before and gh.requests == []


def test_401_names_the_token(repo, out, gh, monkeypatch, capsys):
    gh.status = 401
    rc, status, err = run(repo, out, gh, monkeypatch, capsys)
    assert (rc, status) == (2, "FAIL:auth")
    assert "token" in err and "GH_TV_TOKEN" in err
    assert listing(out) == {}


def test_retention_keeps_the_newest_three(repo, out, gh, monkeypatch, capsys):
    for code in (2026090101, 2026100101, 2026102101, 2026102201):
        (out / f"joey-media-0.{code % 100}.0-{code}.apk").write_bytes(b"old")
    (out / "notes.txt").write_text("not an apk")
    rc, status, _ = run(repo, out, gh, monkeypatch, capsys)
    assert status == f"published:{CODE}"
    apks = sorted(p.name for p in out.glob("*.apk"))
    assert apks == sorted([APK, "joey-media-0.1.0-2026102201.apk", "joey-media-0.1.0-2026102101.apk"])
    assert (out / "notes.txt").exists()


def test_no_token_skips(repo, out, gh, monkeypatch, capsys):
    rc, status, _ = run(repo, out, gh, monkeypatch, capsys, token=None)
    assert (rc, status) == (0, "skipped:no-token") and gh.requests == []


def test_unreachable_github_is_a_network_failure(repo, out, monkeypatch, capsys):
    dead = type("Dead", (), {"base": "http://127.0.0.1:9"})()   # discard port: connection refused
    rc, status, _ = run(repo, out, dead, monkeypatch, capsys)
    assert (rc, status) == (1, "FAIL:network") and listing(out) == {}
