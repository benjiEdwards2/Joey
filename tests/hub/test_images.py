"""Poster proxy GET /img/{ref} (2026-10-05): strict ref grammar, fallback card when
nothing is configured or upstream misbehaves, disk cache, size mapping, and the
no-URL/key-leak guarantee. requests.get is always monkeypatched — no network."""
import logging

import pytest
import requests
from fastapi.testclient import TestClient

from hub.main import app

JF_URL, JF_KEY = "http://jelly.example.invalid:8096", "JFSECRETkey"
JPEG = b"\xff\xd8\xff\xe0fakejpegbytes"


class Resp:
    def __init__(self, body=JPEG, code=200, ctype="image/jpeg"):
        self.content, self.status_code, self.headers = body, code, {"content-type": ctype}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    for name in ("JELLYFIN_URL", "JELLYFIN_API_KEY", "RADARR_URL", "RADARR_API_KEY",
                 "SONARR_URL", "SONARR_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("IMG_CACHE_DIR", str(tmp_path / "img"))
    return TestClient(app)


@pytest.fixture()
def jelly(monkeypatch):
    monkeypatch.setenv("JELLYFIN_URL", JF_URL + "/")
    monkeypatch.setenv("JELLYFIN_API_KEY", JF_KEY)


@pytest.fixture()
def upstream(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None, stream=False):
        calls.append({"url": url, "params": params or {}, "headers": headers or {}, "timeout": timeout,
                      "stream": stream})
        return fake_get.reply

    fake_get.reply = Resp()
    monkeypatch.setattr(requests, "get", fake_get)
    return calls, fake_get


def assert_fallback(r):
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert r.headers["cache-control"] == "public, max-age=3600"
    assert b"<svg" in r.content


@pytest.mark.parametrize("ref", ["jf:", "jf:../etc", "jf:a b", "bogus:1", "tmdb:abc.jpg", "tmdb:/a/b.jpg",
                                 "tmdb:/abc.gif", "jfb:a/b", "radarr:1.2"])
def test_bad_ref_is_404(client, ref):
    assert client.get(f"/img/{ref}").status_code == 404


def test_valid_ref_without_env_serves_the_fallback_card(client, upstream):
    r = client.get("/img/jf:abc123?t=Quiet Coast")
    assert_fallback(r)
    assert b">QU<" in r.content  # first two letters of the title
    assert upstream[0] == []  # nothing configured: no request at all


def test_none_ref_always_serves_the_fallback(client, jelly, upstream):
    assert_fallback(client.get("/img/none?t=Ab"))
    assert upstream[0] == []


def test_title_is_escaped_in_the_fallback(client):
    assert b"<script" not in client.get("/img/none?t=<script>").content


def test_fetch_is_cached_and_second_call_skips_upstream(client, jelly, upstream, tmp_path):
    calls, _ = upstream
    r = client.get("/img/jf:abc123?h=240")
    assert r.status_code == 200 and r.content == JPEG and r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "public, max-age=2592000, immutable"
    assert calls[0]["url"] == f"{JF_URL}/Items/abc123/Images/Primary"
    assert calls[0]["params"] == {"maxHeight": 240, "quality": 90}
    assert calls[0]["headers"] == {"Authorization": f"MediaBrowser Token={JF_KEY}"}
    assert calls[0]["timeout"] == 8
    again = client.get("/img/jf:abc123?h=240")
    assert again.content == JPEG and again.headers["cache-control"].endswith("immutable")
    assert len(calls) == 1
    assert len(list((tmp_path / "img").glob("*.jpg"))) == 1
    client.get("/img/jf:abc123?h=600")  # a different size is a different cache entry
    assert len(calls) == 2


def test_backdrop_uses_the_backdrop_endpoint(client, jelly, upstream):
    client.get("/img/jfb:abc123")
    assert upstream[0][0]["url"].endswith("/Items/abc123/Images/Backdrop/0")
    assert upstream[0][0]["params"] == {"maxWidth": 1280, "quality": 85}


def test_radarr_falls_back_to_poster_jpg(client, monkeypatch, upstream):
    monkeypatch.setenv("RADARR_URL", "http://radarr.example.invalid:7878")
    monkeypatch.setenv("RADARR_API_KEY", "RKEY")
    calls, get = upstream
    replies = [Resp(b"", 404, "text/html"), Resp()]
    get.reply = None
    monkeypatch.setattr(requests, "get", lambda url, params=None, headers=None, timeout=None, stream=False:
                        (calls.append({"url": url, "params": params}), replies.pop(0))[1])
    assert client.get("/img/radarr:21").content == JPEG
    assert [c["url"].rsplit("/", 1)[1] for c in calls] == ["poster-500.jpg", "poster.jpg"]
    assert calls[0]["url"].startswith("http://radarr.example.invalid:7878/api/v3/mediacover/21/")
    assert calls[0]["params"] == {"apikey": "RKEY"}


def test_tmdb_needs_no_key_and_maps_size(client, upstream):
    calls, _ = upstream
    for h, width in ((120, "w185"), (240, "w342"), (400, "w500"), (600, "w780"), (1280, "w1280")):
        assert client.get(f"/img/tmdb:/abc_1.jpg?h={h}").status_code == 200
        assert calls[-1]["url"] == f"https://image.tmdb.org/t/p/{width}/abc_1.jpg"
    client.get("/img/tmdb:/zzz.jpg?h=999")  # not an allowed size -> default 400
    assert calls[-1]["url"].endswith("/w500/zzz.jpg")


def test_non_image_content_type_is_the_fallback_and_not_cached(client, jelly, upstream, tmp_path):
    upstream[1].reply = Resp(b"<html>nope</html>", 200, "text/html")
    assert_fallback(client.get("/img/jf:abc123"))
    assert not (tmp_path / "img").exists() or not list((tmp_path / "img").glob("*"))


def test_upstream_error_status_is_the_fallback(client, jelly, upstream):
    upstream[1].reply = Resp(b"", 500, "text/plain")
    assert_fallback(client.get("/img/jf:abc123"))


def test_oversize_image_is_the_fallback(client, jelly, upstream):
    upstream[1].reply = Resp(b"x" * (5 * 1024 * 1024 + 1))
    assert_fallback(client.get("/img/jf:abc123"))


def test_upstream_exception_is_the_fallback_and_logs_no_url_or_key(client, jelly, monkeypatch, caplog):
    def boom(*a, **kw):
        raise requests.ConnectionError(f"HTTPConnectionPool({JF_URL}): key={JF_KEY}")
    monkeypatch.setattr(requests, "get", boom)
    with caplog.at_level(logging.WARNING, logger="hub.images"):
        assert_fallback(client.get("/img/jf:abc123"))
    assert "image upstream failed" in caplog.text
    assert "example.invalid" not in caplog.text and JF_KEY not in caplog.text


class Streamed:
    """A streamed upstream body: counts how many chunks were pulled."""
    def __init__(self, chunk, n, ctype="image/jpeg", length=None):
        self.status_code, self.pulled, self.closed = 200, 0, False
        self.headers = {"content-type": ctype, **({"content-length": str(length)} if length else {})}
        self._chunk, self._n = chunk, n

    @property
    def content(self):
        raise AssertionError("the body must be streamed, never buffered whole")

    def iter_content(self, size):
        for _ in range(self._n):
            self.pulled += 1
            yield self._chunk

    def close(self):
        self.closed = True


def test_download_is_streamed_and_stops_at_the_cap(client, jelly, upstream):
    """H-54: the cap is a running count — reading stops one chunk past 5 MB, never the whole body."""
    calls, get = upstream
    get.reply = Streamed(b"x" * (1024 * 1024), 50)  # a 50 MB body
    assert_fallback(client.get("/img/jf:abc123"))
    assert calls[0]["stream"] is True
    assert get.reply.pulled == 6 and get.reply.closed


def test_declared_oversize_is_refused_unread(client, jelly, upstream):
    get = upstream[1]
    get.reply = Streamed(b"x", 1, length=6 * 1024 * 1024)
    assert_fallback(client.get("/img/jf:abc123"))
    assert get.reply.pulled == 0


def test_streamed_image_under_the_cap_is_served_and_cached(client, jelly, upstream, tmp_path):
    get = upstream[1]
    get.reply = Streamed(b"y" * 102, 3)
    r = client.get("/img/jf:abc123")
    assert r.status_code == 200 and len(r.content) == 3 * 102
    assert len(list((tmp_path / "img").glob("*.jpg"))) == 1 and not list((tmp_path / "img").glob("*.tmp"))


def test_concurrent_stores_never_share_a_temp_file(tmp_path, monkeypatch):
    """H-62: request threads and the warm-up share one pid; each write gets its own temp path."""
    import os
    import threading

    from hub import images
    monkeypatch.setenv("IMG_CACHE_DIR", str(tmp_path / "img"))
    seen, real = [], os.replace

    def spy(src, dst):
        seen.append(str(src))
        real(src, dst)

    monkeypatch.setattr(images.os, "replace", spy)
    bodies = [bytes([i]) * 2000 for i in range(8)]
    threads = [threading.Thread(target=images._store, args=("samestem", ".jpg", b)) for b in bodies]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(seen) == 8 and len(set(seen)) == 8
    assert (tmp_path / "img" / "samestem.jpg").read_bytes() in bodies
    assert not list((tmp_path / "img").glob("*.tmp"))


def test_warm_and_get_share_one_cache_lookup(client, jelly, upstream, tmp_path):
    """H-28: warm() answers 'cached' from the same _cache_path the route reads."""
    from hub import images
    calls = upstream[0]
    assert images.warm("jf:abc123", 240) == "fetched"
    assert images.warm("jf:abc123", 240) == "cached"
    assert client.get("/img/jf:abc123?h=240").content == JPEG
    assert len(calls) == 1


def test_placeholder_url_carries_letters_only_and_serves_the_same_card(client):
    """N-33: `t=` is the card's two letters, so every 'Jellyfin…' title shares ONE cacheable placeholder URL."""
    from hub.images import fallback_letters
    from hub.shell import templates
    assert fallback_letters("the Quiet Coast") == "TH" and fallback_letters("  ") == "" and fallback_letters(None) == ""
    html = templates.env.from_string('{% from "_services.html" import services_row %}{{ services_row(s) }}').render(
        s=[{"href": "/x", "logo": None, "name": "Jellyfin Plus"}, {"href": "/y", "logo": "tmdb:/l.png", "name": "Neon"}])
    assert 'src="/img/none?h=120&amp;t=JE"' in html and 'src="/img/tmdb:/l.png?h=120&amp;t=NE"' in html
    whole, short = client.get("/img/none?h=120&t=Jellyfin Plus"), client.get("/img/none?h=120&t=JE")
    assert whole.content == short.content and short.headers["cache-control"] == "public, max-age=3600"
