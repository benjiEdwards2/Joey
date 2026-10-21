"""Joey TV WP-B8 step 6 (Q37 = public): hub/tv_app.py serves the published TV release on the media front without a
sign-in - /app (plain HTML), /app/version.json (no-cache), /app/latest.apk (302, no-store), /app/<versioned apk>
(immutable) - and everything else under /app, and every /app path on the private front, is the ordinary 404.
The tv-app dir is a tmp dir; fixture names are invented."""
import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub import guest
from hub.identity import IDENTITY_HEADER

REPO_ROOT = Path(__file__).resolve().parents[2]
CODE = 2026110302
APK = f"joey-media-1.4.0-{CODE}.apk"
APK_BYTES = b"PK\x03\x04" + bytes(range(256)) * 64   # > the gzip threshold, so a gzipped reply would show
DOC = {"version": "1.4.0", "versionCode": CODE, "min_version": 2026102101, "url": APK, "sha256": "a" * 64,
       "notes": "Faster start-up <b>& more</b>.", "size": len(APK_BYTES), "published": "2026-11-03T01:02:03Z"}
FORGED = {IDENTITY_HEADER: "forged@example.test"}
TRAVERSAL = ["/app/..%2f.env", "/app/..%2F..%2Fdeploy%2Fdeploy.sh", "/app/x.apk", "/app/version.json.bak",
             f"/app/{APK}.part", "/app/.staging/version.json", "/app/joey-media-1.4.0-2026110399.apk",
             "/app/joey-media-1.4-2026110302.apk", "/app/latest.apk/x", "/app/", "/app/index.html"]


@pytest.fixture()
def tv_dir(tmp_path, monkeypatch):
    d = tmp_path / "tv-app"
    d.mkdir()
    monkeypatch.setenv("TV_APP_DIR", str(d))
    return d


@pytest.fixture()
def published(tv_dir):
    (tv_dir / APK).write_bytes(APK_BYTES)
    (tv_dir / "version.json").write_text(json.dumps(DOC), encoding="utf-8")
    (tv_dir / ".staging").mkdir()
    (tv_dir / ".staging" / "version.json").write_text("{}", encoding="utf-8")
    return tv_dir


def _client(monkeypatch, front):
    monkeypatch.setenv("AREAS_PATH", str(REPO_ROOT / "config" / "areas.yaml"))
    monkeypatch.setenv("OWNER_EMAIL_YOU", "you@example.com")
    if front:
        monkeypatch.setenv("JOEY_FRONT", front)
    else:
        monkeypatch.delenv("JOEY_FRONT", raising=False)
    import hub.main
    importlib.reload(hub.main)
    return TestClient(hub.main.app)


@pytest.fixture()
def media(monkeypatch):
    with _client(monkeypatch, "media") as c:
        yield c


@pytest.fixture()
def private(monkeypatch):
    with _client(monkeypatch, None) as c:
        yield c


def get(c, path, **kw):
    return c.get(path, follow_redirects=False, **kw)


def test_app_paths_are_guest_and_public_on_the_media_front():
    for path in ("/app", "/app/version.json", "/app/latest.apk", f"/app/{APK}"):
        assert guest.allows("GET", path) and guest.allows("HEAD", path), path
        assert guest.is_public("GET", path), path
        assert not guest.allows("POST", path), path


def test_published_release_is_served_without_a_sign_in(published, media):
    page = get(media, "/app", headers=FORGED)   # a forged Access header changes nothing (Q23)
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    text = page.text
    assert "<script" not in text.lower()
    assert "Version 1.4.0 (2026110302)" in text and f'href="/app/{APK}"' in text
    assert "Faster start-up &lt;b&gt;&amp; more&lt;/b&gt;." in text           # notes escaped
    assert "https://media.joeyhome.net/app/latest.apk" in text and "Downloader" in text
    assert page.headers["cache-control"] == "no-store"

    vj = get(media, "/app/version.json")
    assert vj.status_code == 200 and vj.headers["content-type"] == "application/json"
    assert vj.headers["cache-control"] == "no-cache"
    assert vj.json() == DOC

    latest = get(media, "/app/latest.apk")
    assert latest.status_code == 302 and latest.headers["location"] == f"/app/{APK}"
    assert latest.headers["cache-control"] == "no-store"

    apk = get(media, f"/app/{APK}", headers={"Accept-Encoding": "gzip"})
    assert apk.status_code == 200 and apk.content == APK_BYTES
    assert apk.headers["content-type"] == "application/vnd.android.package-archive"
    assert apk.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "content-encoding" not in apk.headers                               # a zip is never gzipped again
    assert media.head(f"/app/{APK}").status_code == 200


def test_empty_dir_page_says_nothing_is_published(tv_dir, media):
    unknown = get(media, "/no-such-page-xyz")
    page = get(media, "/app")
    assert page.status_code == 200 and "No build published yet" in page.text
    for path in ("/app/version.json", "/app/latest.apk"):
        r = get(media, path)
        assert (r.status_code, r.content) == (404, unknown.content), path


def test_version_json_naming_a_missing_apk_does_not_redirect(tv_dir, media):
    (tv_dir / "version.json").write_text(json.dumps(DOC), encoding="utf-8")   # APK not there
    assert get(media, "/app/latest.apk").status_code == 404
    assert "No build published yet" in get(media, "/app").text


@pytest.mark.parametrize("path", TRAVERSAL)
def test_anything_else_under_app_is_the_ordinary_404(published, media, path):
    unknown = get(media, "/no-such-page-xyz")
    r = get(media, path)
    assert (r.status_code, r.content) == (404, unknown.content), path


def test_writes_are_refused(published, media):
    unknown = get(media, "/no-such-page-xyz")
    for path in ("/app", "/app/version.json", f"/app/{APK}"):
        r = media.post(path, follow_redirects=False)
        assert (r.status_code, r.content) == (404, unknown.content), path


@pytest.mark.parametrize("path", ["/app", "/app/version.json", "/app/latest.apk", f"/app/{APK}"])
def test_the_private_front_never_serves_app(published, private, path):
    r = get(private, path)
    assert r.status_code == 404
    assert APK_BYTES not in r.content and b"versionCode" not in r.content
