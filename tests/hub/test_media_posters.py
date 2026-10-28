"""JY-260 phase 1 - the TMDB pick (Q3A: Jellyfin's RemoteImages), the POSTERS flag, the dry pass into the cache and
the household-only review page /media/posters (spec docs/specs/JY-260-posters.md).

Phase 1 writes nothing live: the fake Jellyfin / TMDB sessions answer GET only and fail the test on any other method,
and a source scan proves no write call exists in the poster modules. The page renders from local files only."""
import io
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from hub import media_posters as mp, media_posters_render as r, upstream
from tests.hub.test_media_frame import env  # noqa: F401  (frame env fixture)
from tests.hub.test_media_library_pages import jelly

REPO = Path(__file__).resolve().parents[2]
TMDB = "https://image.tmdb.org/t/p/original"


def img(lang, votes, w=2000, h=3000, name=None, rating=5.0, url=None):
    return {"ProviderName": "TheMovieDb", "Type": "Primary", "Language": lang, "VoteCount": votes,
            "CommunityRating": rating, "Width": w, "Height": h,
            "Url": url or f"{TMDB}/{name or (str(lang) + str(votes) + str(w))}.jpg"}


# ---- the pick ----

def test_text_less_beats_english_even_with_fewer_votes():
    got = mp.pick([img("en", 90, name="en"), img(None, 3, name="none"), img("fr", 200, name="fr")])
    assert got["url"].endswith("/none.jpg") and got["lang"] is None and got["fallback"] is None


def test_among_text_less_more_votes_then_more_pixels():
    got = mp.pick([img(None, 4, name="a"), img(None, 9, 1000, 1500, name="b"), img("", 9, 2000, 3000, name="c")])
    assert got["url"].endswith("/c.jpg")                                # "" counts as no language, as null
    assert got["votes"] == 9 and (got["width"], got["height"]) == (2000, 3000)


def test_english_then_other_languages_are_fallbacks():
    got = mp.pick([img("de", 50, name="de"), img("en", 2, name="en")])
    assert got["url"].endswith("/en.jpg") and got["fallback"] == "en"
    got = mp.pick([img("de", 50, name="de")])
    assert got["url"].endswith("/de.jpg") and got["fallback"] == "other"


def test_nothing_usable_is_none():
    assert mp.pick([]) is None
    assert mp.pick([img(None, 9, url="https://evil.example/x.jpg")]) is None   # art only from image.tmdb.org
    assert mp.pick([{"Url": None}, "junk", None]) is None


# ---- the flag ----

@pytest.mark.parametrize("value,want", [(None, "off"), ("", "off"), ("off", "off"), ("dry", "dry"), ("DRY", "dry"),
                                        ("on", "on"), ("yes", "off")])
def test_mode(monkeypatch, value, want):
    if value is None:
        monkeypatch.delenv("POSTERS", raising=False)
    else:
        monkeypatch.setenv("POSTERS", value)
    assert mp.mode() == want


# ---- the dry pass (fakes: GET only) ----

class Resp:
    def __init__(self, status=200, body=None, data=b"", ctype="application/json"):
        self.status_code, self._body, self._data = status, body, data
        self.headers = {"content-type": ctype, "content-length": str(len(data))}

    def json(self):
        return self._body

    def iter_content(self, n):
        yield self._data

    def close(self):
        pass


class GetOnly:
    """A stand-in for upstream.session(...): GET answers from `routes`, any other method fails the test."""
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, headers=None, timeout=None, stream=False):
        self.calls.append(url)
        for key, resp in self.routes.items():
            if key in url:
                return resp() if callable(resp) else resp
        return Resp(404)

    def __getattr__(self, name):   # post / put / delete / request / patch ...
        raise AssertionError(f"phase 1 must not call {name}")


def jpeg(colour=(90, 100, 110)):
    buf = io.BytesIO()
    Image.new("RGB", (2000, 3000), colour).save(buf, "JPEG")
    return buf.getvalue()


LIB = {
    "movies": [
        {"title": "Old Film", "year": 1999, "jf_id": "a" * 32, "item_key": "tmdb:1", "added_at": "2026-01-01T00:00:00Z"},
        {"title": "New Film", "year": 2024, "jf_id": "b" * 32, "item_key": "tmdb:2", "added_at": "2026-10-01T00:00:00Z"},
    ],
    "shows": [
        {"title": "A Show", "year": 2019, "jf_id": "c" * 32, "item_key": "tmdb:3", "added_at": "2026-01-01T00:00:00Z"},
    ],
}


@pytest.fixture()
def fakes(monkeypatch, tmp_path):
    monkeypatch.setenv("JELLYFIN_URL", "http://jf.test")
    monkeypatch.setenv("JELLYFIN_API_KEY", "k" * 32)
    monkeypatch.setenv("POSTERS", "dry")
    monkeypatch.setenv("POSTERS_DIR", str(tmp_path / "posters"))
    monkeypatch.setenv("POSTERS_TEMPLATE_DIR", str(tmp_path / "no-such-kit"))   # -> the starter kit
    monkeypatch.delenv("POSTERS_SERIES_SUB", raising=False)
    remote = {"Images": [img("en", 40, name="en"), img(None, 7, name="clean")], "TotalRecordCount": 2}
    jf = GetOnly({"/RemoteImages": Resp(body=remote)})
    tmdb = GetOnly({"/clean.jpg": lambda: Resp(data=jpeg(), ctype="image/jpeg")})
    sessions = {"jellyfin": jf, "tmdb": tmdb}

    def session(name):
        if name not in sessions:
            raise AssertionError(f"unexpected upstream {name}")
        return sessions[name]
    monkeypatch.setattr(upstream, "session", session)
    return jf, tmdb, tmp_path / "posters"


def test_dry_pass_renders_into_the_cache_with_gets_only(fakes):
    jf, tmdb, out = fakes
    counts = mp.dry_pass({"jellyfin": LIB}, pause=0)
    assert counts["rendered"] == 3 and counts["failed"] == 0
    assert all("/RemoteImages" in u for u in jf.calls) and len(jf.calls) == 3
    side = json.loads((out / ("b" * 32 + ".json")).read_text(encoding="utf-8"))
    assert side["title"] == "New Film" and side["sub"] == "2024" and side["status"] == "rendered"
    assert side["pick"]["lang"] is None and side["pick"]["votes"] == 7
    assert Image.open(out / ("b" * 32 + ".jpg")).size == (1000, 1500)
    show = json.loads((out / ("c" * 32 + ".json")).read_text(encoding="utf-8"))
    assert show["sub"] == ""                                            # the series sub-line is phase 2 (switch off)


def test_second_pass_is_cached_and_a_template_change_re_renders(fakes, monkeypatch, tmp_path):
    jf, tmdb, out = fakes
    mp.dry_pass({"jellyfin": LIB}, pause=0)
    jf.calls.clear()
    again = mp.dry_pass({"jellyfin": LIB}, pause=0)
    assert again["rendered"] == 0 and again["cached"] == 3 and jf.calls == []
    import shutil
    kit = tmp_path / "kit"
    shutil.copytree(r.STARTER, kit)
    data = json.loads((kit / "template.json").read_text(encoding="utf-8"))
    data["title"]["title_anchor"] = 0.70
    (kit / "template.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("POSTERS_TEMPLATE_DIR", str(kit))
    assert mp.dry_pass({"jellyfin": LIB}, pause=0)["rendered"] == 3


def test_pass_respects_the_per_pass_cap_newest_first(fakes, monkeypatch):
    jf, tmdb, out = fakes
    monkeypatch.setenv("POSTERS_PER_PASS", "1")
    assert mp.dry_pass({"jellyfin": LIB}, pause=0)["rendered"] == 1
    assert (out / ("b" * 32 + ".jpg")).exists()                         # Q9A: recently added first


def test_no_tmdb_poster_is_recorded_and_not_retried(fakes):
    jf, tmdb, out = fakes
    jf.routes["/RemoteImages"] = Resp(body={"Images": []})
    counts = mp.dry_pass({"jellyfin": LIB}, pause=0)
    assert counts["no_source"] == 3 and counts["rendered"] == 0
    jf.calls.clear()
    assert mp.dry_pass({"jellyfin": LIB}, pause=0)["cached"] == 3 and jf.calls == []


def test_an_upstream_failure_is_counted_and_retried_next_pass(fakes):
    jf, tmdb, out = fakes
    jf.routes["/RemoteImages"] = Resp(status=500)
    counts = mp.dry_pass({"jellyfin": LIB}, pause=0)
    assert counts["failed"] == 3 and not list(out.glob("*.json"))


def test_off_does_nothing(fakes, monkeypatch):
    jf, tmdb, out = fakes
    monkeypatch.setenv("POSTERS", "off")
    assert mp.dry_pass({"jellyfin": LIB}, pause=0) == {"off": True}
    assert jf.calls == [] and not out.exists()


def test_on_is_phase_2_and_behaves_as_dry(fakes, monkeypatch):
    jf, tmdb, out = fakes
    monkeypatch.setenv("POSTERS", "on")
    assert mp.dry_pass({"jellyfin": LIB}, pause=0)["rendered"] == 3     # still GET-only fakes: no write path


def test_a_bad_template_renders_nothing(fakes, monkeypatch, tmp_path):
    jf, tmdb, out = fakes
    kit = tmp_path / "badkit"
    kit.mkdir()
    (kit / "template.json").write_text("{ nope", encoding="utf-8")
    monkeypatch.setenv("POSTERS_TEMPLATE_DIR", str(kit))
    counts = mp.dry_pass({"jellyfin": LIB}, pause=0)
    assert counts.get("template_error") and counts["rendered"] == 0 and jf.calls == []


def test_no_jellyfin_write_call_exists_in_phase_1():
    """Source scan over every poster module: no POST / PUT / DELETE, no image upload path, no write key."""
    files = sorted((REPO / "hub").glob("media_posters*.py"))
    assert len(files) >= 3
    for path in files:
        src = path.read_text(encoding="utf-8")
        for bad in (r"\.post\(", r"\.put\(", r"\.delete\(", r"\.patch\(", r"\.request\(", r"method\s*=",
                    r"Images/Primary", r"LockData", r"JELLYFIN_POSTER_API_KEY"):
            assert not re.search(bad, src), (path.name, bad)


# ---- the review page ----

def seed(out: Path, rows):
    out.mkdir(parents=True, exist_ok=True)
    tpl = r.load_template(r.STARTER)
    for row in rows:
        Image.new("RGB", (1000, 1500), (10, 10, 10)).save(out / f"{row['jf_id']}.jpg", "JPEG")
        side = {"status": "rendered", "kind": "movie", "sub": "", "template": tpl.version, "text": "x",
                "rendered_at": "2026-10-28T00:00:00Z",
                "pick": {"lang": None, "votes": 7, "width": 2000, "height": 3000, "fallback": None}, **row}
        (out / f"{row['jf_id']}.json").write_text(json.dumps(side), encoding="utf-8")


ROWS = [
    {"jf_id": "a" * 32, "title": "Old Film", "added_at": "2026-01-01T00:00:00Z"},
    {"jf_id": "b" * 32, "title": "New Film", "added_at": "2026-10-01T00:00:00Z"},
    {"jf_id": "d" * 32, "title": "Bravo", "added_at": "2026-01-01T00:00:00Z", "status": "no_source"},
    {"jf_id": "e" * 32, "title": "English Pick", "added_at": "2026-05-01T00:00:00Z",
     "pick": {"lang": "en", "votes": 2, "width": 1000, "height": 1500, "fallback": "en"}},
]


@pytest.fixture()
def page_app(env, monkeypatch, tmp_path):  # noqa: F811
    def build(posters="dry"):
        if posters is None:
            monkeypatch.delenv("POSTERS", raising=False)
        else:
            monkeypatch.setenv("POSTERS", posters)
        monkeypatch.setenv("POSTERS_DIR", str(tmp_path / "posters"))
        monkeypatch.setenv("POSTERS_TEMPLATE_DIR", str(tmp_path / "no-such-kit"))
        seed(tmp_path / "posters", ROWS)
        main = env(jellyfin=jelly())
        return TestClient(main.app)
    return build


def test_review_page_lists_original_and_proposed_in_q9a_order(page_app):
    c = page_app()
    with c:
        resp = c.get("/media/posters")
    assert resp.status_code == 200
    body = resp.text.split("<main", 1)[1]
    titles = re.findall(r'class="row-title">([^<]+)<', body)
    assert titles == ["New Film", "English Pick", "Bravo", "Old Film"]  # newest first, then A-Z
    assert f'/img/jf:{"b" * 32}?h=600' in body
    assert f'/media/posters/img/{"b" * 32}' in body
    assert "English poster" in body and "No TMDB poster" in body       # the pick words
    assert "Dry run" in body                                             # the mode, in words


def test_proposed_image_is_served_and_bad_ids_404(page_app):
    c = page_app()
    with c:
        ok = c.get(f"/media/posters/img/{'b' * 32}")
        assert ok.status_code == 200 and ok.headers["content-type"] == "image/jpeg"
        assert c.get(f"/media/posters/img/{'f' * 32}").status_code == 404
        assert c.get("/media/posters/img/..%2Fmedia.db").status_code == 404


def test_review_page_does_no_network(page_app, monkeypatch):
    from hub import media_jellyfin
    c = page_app()

    def boom(*a, **k):
        raise AssertionError("network call on render")
    monkeypatch.setattr(upstream, "session", boom)
    monkeypatch.setattr(media_jellyfin, "get", boom)
    monkeypatch.setattr(mp, "remote_images", boom)
    monkeypatch.setattr(mp, "fetch_art", boom)
    with c:
        assert c.get("/media/posters").status_code == 200
        assert c.get(f"/media/posters/img/{'b' * 32}").status_code == 200


def test_off_means_404(page_app):
    c = page_app(posters=None)
    with c:
        assert c.get("/media/posters").status_code == 404
        assert c.get(f"/media/posters/img/{'b' * 32}").status_code == 404


def test_a_bad_template_is_shown_in_words(page_app, monkeypatch, tmp_path):
    kit = tmp_path / "badkit"
    kit.mkdir()
    (kit / "template.json").write_text('{"version": 1}', encoding="utf-8")
    c = page_app()
    monkeypatch.setenv("POSTERS_TEMPLATE_DIR", str(kit))
    with c:
        body = c.get("/media/posters").text
    assert "Template not used" in body and "canvas" in body


def test_routes_are_private_never_guest():
    from hub import guest
    for path in ("/media/posters", f"/media/posters/img/{'b' * 32}"):
        assert not guest.allows("GET", path)


def test_media_front_404_for_a_signed_in_friend(monkeypatch, tmp_path):
    from tests.hub.fake_jellyfin import FRIEND_ID
    from tests.hub.guest_pages import guest_client, sign_in
    monkeypatch.setenv("POSTERS", "dry")
    monkeypatch.setenv("POSTERS_DIR", str(tmp_path / "posters"))
    seed(tmp_path / "posters", ROWS)
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": jelly()})
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        missing = c.get("/no-such-page").text
        for path in ("/media/posters", f"/media/posters/img/{'b' * 32}"):
            resp = c.get(path, follow_redirects=False)
            assert resp.status_code == 404 and resp.text == missing, path


def test_handler_refuses_on_the_media_front_even_for_the_household(monkeypatch):
    from hub import guest, media_posters_pages as pages
    monkeypatch.setenv("POSTERS", "dry")
    monkeypatch.setattr(guest, "is_media", lambda: True)
    assert pages.allowed() is False
