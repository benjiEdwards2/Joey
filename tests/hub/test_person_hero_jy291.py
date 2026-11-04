"""JY-291 (person hero A): large portrait, backdrop photo (tagged image with TMDB_API_KEY, else the most popular
credit's backdrop), the phone bio wrap, and the TV person page unchanged. No network: upstreams are faked."""
from pathlib import Path

from hub import media_person_photo as photo
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.helpers import env  # noqa: F401
from tests.hub.test_media_person import CREDITS, PERSON, seed
from tests.hub.test_tv_shelves_tmdb import actor, friend, page  # noqa: F401 - the TV friend fixtures

POPULAR = {"cast": CREDITS["cast"] + [
    {"id": 700, "mediaType": "movie", "title": "Big Hit", "releaseDate": "2015-01-01", "backdropPath": "/big.jpg", "voteCount": 9000},
    {"id": 701, "mediaType": "movie", "title": "Small One", "releaseDate": "2016-01-01", "backdropPath": "/small.jpg", "voteCount": 20}],
    "crew": CREDITS["crew"]}
TAGGED = {"results": [
    {"file_path": "/tall.jpg", "aspect_ratio": 0.667, "vote_average": 9, "vote_count": 50, "width": 1000},
    {"file_path": "/wide-low.jpg", "aspect_ratio": 1.778, "vote_average": 5.1, "vote_count": 3, "width": 1920},
    {"file_path": "/wide-best.jpg", "aspect_ratio": 1.778, "vote_average": 5.6, "vote_count": 2, "width": 1280}]}


def _patch(monkeypatch, sess):
    real = photo.upstream.session
    monkeypatch.setattr(photo.upstream, "session", lambda name: sess if name == "tmdb" else real(name))


class _Resp:
    def __init__(self, code, body):
        self.status_code, self._body = code, body

    def json(self):
        return self._body


class _Sess:
    def __init__(self, code=200, body=TAGGED):
        self.calls, self.code, self.body = [], code, body

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return _Resp(self.code, self.body)


def test_large_portrait_requested_not_round_crop(env):
    client, both = env()
    seed(both)
    with client:
        b = client.get("/media/person/55").text
    assert 'class="personportrait" src="/img/tmdb:/ada.jpg?h=600"' in b and "?h=240" not in b.split("personhead")[1][:400]


def test_backdrop_falls_back_to_most_popular_credit_without_key(env, monkeypatch):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    sess = _Sess()
    _patch(monkeypatch, sess)
    client, both = env()
    seed(both, credits=POPULAR)
    with client:
        b = client.get("/media/person/55").text
    assert "person-hero-bd" in b and "/img/tmdb:/big.jpg?h=1280" in b and "small.jpg" not in b
    assert sess.calls == []   # no new upstream call on the no-key path


def test_tagged_image_used_with_key(env, monkeypatch, tmp_path):
    monkeypatch.setenv("TMDB_API_KEY", "k-test")
    sess = _Sess()
    _patch(monkeypatch, sess)
    client, both = env()
    seed(both, credits=POPULAR)
    with client:
        b = client.get("/media/person/55").text
        client.get("/media/person/55")
    assert "/img/tmdb:/wide-best.jpg?h=1280" in b and "big.jpg" not in b
    assert len(sess.calls) == 1 and sess.calls[0][0].endswith("/person/55/tagged_images")   # cached after one read
    assert "k-test" not in b


def test_key_but_no_tagged_image_or_failure_falls_back(env, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "k-test")
    _patch(monkeypatch, _Sess(500, None))
    client, both = env()
    seed(both, credits=POPULAR)
    with client:
        b = client.get("/media/person/55").text
    assert "/img/tmdb:/big.jpg?h=1280" in b
    assert photo.pick_tagged({"results": [{"file_path": "/t.jpg", "aspect_ratio": 0.667}]}) is None


def test_no_credit_backdrop_means_no_backdrop_layer(env, monkeypatch):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    client, both = env()
    seed(both, credits={"cast": [], "crew": []})
    with client:
        b = client.get("/media/person/55").text
    assert "person-hero" in b and "person-hero-bd" not in b


def test_phone_bio_wrap_rule_present():
    css = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
    assert ".person-hero .hero-detail-text { flex: 1 1 auto; min-width: 0;" in css
    assert ".person-hero .overview { overflow-wrap: anywhere; }" in css


def test_tv_person_page_keeps_round_crop(actor):
    b = page(actor, "/media/person/55", tv=True)
    assert "person-hero" not in b and "personportrait" not in b and 'class="personpic' in b
