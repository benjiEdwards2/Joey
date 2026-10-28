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

from hub import media_posters as mp, media_posters_render as r, media_posters_store as ms, upstream
from tests.hub.test_media_frame import env  # noqa: F401  (frame env fixture)
from tests.hub.test_media_library_pages import jelly

REPO = Path(__file__).resolve().parents[2]
TMDB = "https://image.tmdb.org/t/p/original"


def meta(out: Path, jf_id: str) -> dict:
    return json.loads((out / jf_id / "meta.json").read_text(encoding="utf-8"))


def img(lang, votes, w=2000, h=3000, name=None, rating=6.5, url=None):
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

@pytest.mark.parametrize("value,want", [(None, "dry"), ("", "dry"), ("off", "off"), ("dry", "dry"), ("DRY", "dry"),
                                        ("on", "on"), ("yes", "dry")])   # phase 2: the default is dry
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
        self.routes, self.calls, self.params = routes, [], []

    def get(self, url, params=None, headers=None, timeout=None, stream=False):
        self.calls.append(url)
        self.params.append(params)
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


def snaps(lib, free_gb=2.0):
    """The pass's snapshots: the library plus a system reading (the memory gate)."""
    return {"jellyfin": lib, "system": {"ram_free_gb": free_gb}}


LIB = {
    "movies": [
        {"title": "Old Film", "year": 1999, "jf_id": "a" * 32, "item_key": "tmdb:1", "added_at": "2026-01-01T00:00:00Z"},
        {"title": "New Film", "year": 2024, "jf_id": "b" * 32, "item_key": "tmdb:2", "added_at": "2026-10-01T00:00:00Z"},
    ],
    "shows": [
        {"title": "A Show", "year": 2019, "jf_id": "c" * 32, "item_key": "tmdb:3", "added_at": "2026-01-01T00:00:00Z"},
    ],
}


S1, S2 = "1" * 32, "2" * 32
SEASONS = {"Items": [   # Jellyfin /Shows/{id}/Seasons?isMissing=false: specials, an unnumbered and two real seasons
    {"Id": "0" * 32, "IndexNumber": 0, "Name": "Specials", "Type": "Season"},
    {"Id": S2, "IndexNumber": 2, "Name": "Season 2", "Type": "Season", "LocationType": "Virtual"},   # no folder
    {"Id": S1, "IndexNumber": 1, "Name": "Season 1", "Type": "Season", "LocationType": "FileSystem"},
    {"Id": "4" * 32, "Name": "No number", "Type": "Season"},
]}


@pytest.fixture()
def fakes(monkeypatch, tmp_path):
    monkeypatch.setenv("JELLYFIN_URL", "http://jf.test")
    monkeypatch.setenv("JELLYFIN_API_KEY", "k" * 32)
    monkeypatch.setenv("POSTERS", "dry")
    monkeypatch.setenv("POSTERS_DIR", str(tmp_path / "posters"))
    monkeypatch.setenv("POSTERS_TEMPLATE_DIR", str(tmp_path / "no-such-kit"))   # -> the starter kit
    monkeypatch.delenv("POSTERS_AUTO_MIN_RATING", raising=False)
    monkeypatch.setenv("POSTERS_BACKDROPS", "off")   # JY-262 follow-up: its own tests turn the backdrop step on
    remote = {"Images": [img("en", 40, name="en"), img(None, 7, name="clean")], "TotalRecordCount": 2}
    jf = GetOnly({"/Shows/": Resp(body=SEASONS), "/RemoteImages": Resp(body=remote)})
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
    counts = mp.dry_pass(snaps(LIB), pause=0)
    assert counts["rendered"] == 5 and counts["failed"] == 0            # 2 films, 1 series, its 2 real seasons
    assert sum("/RemoteImages" in u for u in jf.calls) == 5 and sum("/Shows/" in u for u in jf.calls) == 1
    side = meta(out, "b" * 32)
    assert side["title"] == "New Film" and side["sub"] == "2024" and side["status"] == "rendered"
    assert side["pick"]["lang"] is None and side["pick"]["votes"] == 7
    assert Image.open(ms.master("b" * 32)).size == (1000, 1500)
    show = meta(out, "c" * 32)
    assert show["sub"] == "Seasons 1–2"                                 # real seasons only, no years (B. 2026-10-28)
    s2 = meta(out, S2)
    assert (s2["kind"], s2["title"], s2["sub"], s2["series_id"]) == ("season", "A Show", "Season 2", "c" * 32)
    assert not (out / ("0" * 32)).exists()                    # specials are left alone
    assert not (out / ("4" * 32)).exists()


def test_second_pass_is_cached_and_a_template_change_re_renders(fakes, monkeypatch, tmp_path):
    jf, tmdb, out = fakes
    mp.dry_pass(snaps(LIB), pause=0)
    jf.calls.clear()
    again = mp.dry_pass(snaps(LIB), pause=0)
    assert again["rendered"] == 0 and again["cached"] == 5 and jf.calls == []   # season list cached a day too
    import shutil
    kit = tmp_path / "kit"
    shutil.copytree(r.STARTER, kit)
    data = json.loads((kit / "template.json").read_text(encoding="utf-8"))
    data["title"]["title_anchor"] = 0.70
    (kit / "template.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("POSTERS_TEMPLATE_DIR", str(kit))
    assert mp.dry_pass(snaps(LIB), pause=0)["rendered"] == 5


def test_a_season_without_a_tmdb_season_poster_uses_the_series_poster(fakes):
    jf, tmdb, out = fakes
    jf.routes = {"/Shows/": Resp(body=SEASONS), f"/Items/{S1}/RemoteImages": Resp(body={"Images": []}),
                 "/RemoteImages": Resp(body={"Images": [img(None, 7, name="clean")]})}
    mp.dry_pass(snaps(LIB), pause=0)
    s1 = meta(out, S1)
    assert s1["status"] == "rendered" and s1["pick"]["fallback"] == "series" and s1["sub"] == "Season 1"
    assert s1["auto"] is True                                           # phase 2: every poster (floor 0)


@pytest.mark.parametrize("rating,env,auto", [(6.0, None, True), (5.9, None, True), (None, None, True),   # default 0
                                             (6.0, "6.0", True), (5.9, "6", False), (None, "6", False),
                                             (7.2, "7.5", False), (7.5, "7.5", True), (4.0, "junk", True)])
def test_auto_approve_defaults_to_every_poster_and_the_floor_is_a_lever(monkeypatch, rating, env, auto):
    if env is None:
        monkeypatch.delenv("POSTERS_AUTO_MIN_RATING", raising=False)
    else:
        monkeypatch.setenv("POSTERS_AUTO_MIN_RATING", env)
    chosen = mp.pick([img(None, 1, rating=rating, name="x")])
    assert chosen["rating"] == rating
    assert mp.auto_approves(chosen) is auto
    assert mp.auto_approves(None) is (env in (None, "junk"))


def test_a_set_rating_floor_holds_a_poster_back_from_serving(fakes, monkeypatch):
    jf, tmdb, out = fakes
    monkeypatch.setenv("POSTERS_AUTO_MIN_RATING", "6")
    jf.routes["/RemoteImages"] = Resp(body={"Images": [img(None, 7, name="clean", rating=5.5)]})
    mp.dry_pass(snaps(LIB), pause=0)
    side = meta(out, "b" * 32)
    assert side["pick"]["rating"] == 5.5 and side["auto"] is False
    assert ms.master("b" * 32) is not None and ms.lookup("b" * 32, 240) is None   # rendered, not served


def test_season_list_drops_specials_and_asks_for_seasons_on_disk_only(fakes):
    jf, tmdb, out = fakes
    assert mp.seasons_of("c" * 32) == [{"jf_id": S1, "n": 1}, {"jf_id": S2, "n": 2}]   # "Virtual" S2 kept
    assert jf.params[-1] == {"isMissing": "false"}                      # missing seasons filtered by Jellyfin


def test_a_title_past_the_size_floor_is_flagged_and_logged(fakes, caplog):
    jf, tmdb, out = fakes
    lib = {"movies": [{"title": "Word " * 60, "year": 2001, "jf_id": "f" * 32, "added_at": "2026-01-01T00:00:00Z"}]}
    with caplog.at_level("WARNING", logger="hub.media_posters"):
        counts = mp.dry_pass(snaps(lib), pause=0)
    assert counts["truncated"] == 1
    assert meta(out, "f" * 32)["truncated"] is True
    assert any("cut short" in rec.getMessage() for rec in caplog.records)
    assert "WORD" not in caplog.text and "Word" not in caplog.text      # counts only, never a title


def test_pass_respects_the_per_pass_cap_newest_first(fakes, monkeypatch):
    jf, tmdb, out = fakes
    monkeypatch.setenv("POSTERS_PER_PASS", "1")
    assert mp.dry_pass(snaps(LIB), pause=0)["rendered"] == 1
    assert ms.master("b" * 32) is not None and ms.master("a" * 32) is None                         # Q9A: recently added first


def test_no_tmdb_poster_is_recorded_and_not_retried(fakes):
    jf, tmdb, out = fakes
    jf.routes["/RemoteImages"] = Resp(body={"Images": []})
    counts = mp.dry_pass(snaps(LIB), pause=0)
    assert counts["no_source"] == 5 and counts["rendered"] == 0
    jf.calls.clear()
    assert mp.dry_pass(snaps(LIB), pause=0)["cached"] == 5 and jf.calls == []


def test_an_upstream_failure_is_counted_and_retried_next_pass(fakes):
    jf, tmdb, out = fakes
    jf.routes["/RemoteImages"] = Resp(status=500)
    counts = mp.dry_pass(snaps(LIB), pause=0)
    assert counts["failed"] == 6 and not list(out.glob("*/meta.json"))   # 5 titles + the season art plan


def test_off_does_nothing(fakes, monkeypatch):
    jf, tmdb, out = fakes
    monkeypatch.setenv("POSTERS", "off")
    assert mp.dry_pass(snaps(LIB), pause=0) == {"off": True}
    assert jf.calls == [] and not out.exists()


def test_on_without_the_write_key_renders_and_writes_nothing(fakes, monkeypatch, caplog):
    jf, tmdb, out = fakes
    monkeypatch.setenv("POSTERS", "on")
    monkeypatch.delenv("JELLYFIN_POSTER_API_KEY", raising=False)
    from hub import media_posters_write as w
    monkeypatch.setitem(w._warned, "no_key", False)
    with caplog.at_level("WARNING", logger="hub.media_posters_write"):
        first = mp.dry_pass(snaps(LIB), pause=0)
        mp.dry_pass(snaps(LIB), pause=0)
    assert first["rendered"] == 5 and first["write"] == {"off": True}   # GET-only fakes: any write fails the test
    lines = [rec.getMessage() for rec in caplog.records if "JELLYFIN_POSTER_API_KEY" in rec.getMessage()]
    assert len(lines) == 1 and "no Jellyfin writes" in lines[0]


def test_a_bad_template_falls_back_to_the_starter_kit(fakes, monkeypatch, tmp_path):
    jf, tmdb, out = fakes
    kit = tmp_path / "badkit"
    kit.mkdir()
    (kit / "template.json").write_text("{ nope", encoding="utf-8")
    monkeypatch.setenv("POSTERS_TEMPLATE_DIR", str(kit))
    counts = mp.dry_pass(snaps(LIB), pause=0)
    assert counts["template_error"] == 1 and counts["rendered"] == 5
    side = meta(out, "b" * 32)
    assert side["template"] == r.load_template(r.STARTER).version


@pytest.mark.parametrize("free_gb,why", [(1.2, "1229 MB is under 1300"), (None, "unknown")])
def test_low_or_unknown_memory_skips_the_pass_and_logs_it(fakes, caplog, free_gb, why):
    jf, tmdb, out = fakes
    s = snaps(LIB, free_gb) if free_gb is not None else {"jellyfin": LIB}
    with caplog.at_level("WARNING", logger="hub.media_posters"):
        counts = mp.dry_pass(s, pause=0)
    assert counts["skipped_memory"] and counts["rendered"] == 0 and jf.calls == []
    assert any(why in rec.getMessage() for rec in caplog.records)


def test_memory_reading_is_the_system_snapshot():
    class Snap:
        def __init__(self, data, age):
            self.data, self.age_minutes = data, age
    assert mp.memory_mb({"system": Snap({"ram_free_gb": 1.5}, 2)}) == pytest.approx(1536)
    assert mp.memory_mb({"system": Snap({"ram_free_gb": 1.5}, 60)}) is None      # stale
    assert mp.memory_mb({"system": Snap({}, 1)}) is None
    assert mp.memory_mb({}) is None


def test_only_the_write_back_module_can_write_to_jellyfin():
    """Source scan over every poster module but media_posters_write.py: no POST / PUT / DELETE, no image upload path,
    no write key (phase 2 keeps every Jellyfin write in the one module that is gated on the key)."""
    files = sorted(p for p in (REPO / "hub").glob("media_posters*.py") if p.name != "media_posters_write.py")
    assert len(files) >= 4
    for path in files:
        src = path.read_text(encoding="utf-8")
        for bad in (r"(?<!router)\.post\(", r"\.put\(", r"\.delete\(", r"\.patch\(", r"\.request\(", r"method\s*=",
                    r"Images/Primary", r"LockData", r"JELLYFIN_POSTER_API_KEY"):
            assert not re.search(bad, src), (path.name, bad)


# ---- the review page ----

def seed(out: Path, rows):
    """Store layout (phase 2): <out>/<jf_id>/<ver>.full.jpg + variants, meta.json, current; + its media.db row."""
    tpl = r.load_template(r.STARTER)
    for row in rows:
        side = {"status": "rendered", "kind": "movie", "sub": "", "template": tpl.version, "text": "x", "ver": "v1",
                "rendered_at": "2026-10-28T00:00:00Z", "auto": True,
                "pick": {"lang": None, "votes": 7, "width": 2000, "height": 3000, "fallback": None}, **row}
        buf = io.BytesIO()
        Image.new("RGB", (1000, 1500), (10, 10, 10)).save(buf, "JPEG")
        ms.save(row["jf_id"], "v1", buf.getvalue(), publish=side["status"] == "rendered")
        ms.write_meta(row["jf_id"], side)
        mp.set_state(row["jf_id"], kind=side["kind"], ver="v1", template=tpl.version, status=side["status"])


ROWS = [
    {"jf_id": "a" * 32, "title": "Old Film", "added_at": "2026-01-01T00:00:00Z", "truncated": True},
    {"jf_id": "b" * 32, "title": "New Film", "added_at": "2026-10-01T00:00:00Z"},
    {"jf_id": "d" * 32, "title": "Bravo", "added_at": "2026-01-01T00:00:00Z", "status": "no_source"},
    {"jf_id": "e" * 32, "title": "English Pick", "added_at": "2026-05-01T00:00:00Z", "auto": True,
     "pick": {"lang": "en", "votes": 2, "rating": 6.4, "width": 1000, "height": 1500, "fallback": "en"}},
    {"jf_id": "9" * 32, "title": "English Pick", "added_at": "2026-05-01T00:00:00Z", "kind": "season",
     "season": 2, "sub": "Season 2", "series_id": "e" * 32},
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
    assert titles == ["New Film", "English Pick", "English Pick", "Bravo", "Old Film"]  # newest first, A-Z; seasons follow
    assert f'/img/jf:{"b" * 32}?h=600' in body
    assert f'/media/posters/img/{"b" * 32}' in body
    assert "English poster" in body and "No TMDB poster" in body       # the pick words
    assert "Rated 6.4" in body and "Revert to the original" in body
    assert "Season 2" in body and ">Season<" not in body
    assert "served from the local store" in body                         # the mode, in words
    assert body.count("Title cut short") == 1                           # a title past the size floor is flagged


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
    c = page_app(posters="off")
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
    assert "Your template was rejected" in body and "canvas" in body
    assert "starter template" in body


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
