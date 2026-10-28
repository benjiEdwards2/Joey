"""JY-260 (2026-10-28): every season of a show gets a different picture. Spec: docs/specs/JY-260-posters.md
("Distinct images per season").

B., 2026-10-28: "If a season has more than 2 seasons. Can you continue to grab new images or closely related images?"
Order: the season's own TMDB poster; else the next unused series poster (the series keeps #1); else a series TMDB
backdrop cropped to 2:3 (the ones not used as the show's Home / title backdrops first). Stable across passes; a new
season takes the next unused picture. GET-only fakes; no network on render."""
import io
import json

import pytest
from PIL import Image

from hub import media_posters as mp, media_posters_store as ms, upstream
from tests.hub.test_media_posters import Resp, snaps

TMDB = "https://image.tmdb.org/t/p/original"
SHOW = "c" * 32
SEASONS = [("5ea%d" % n) * 8 for n in range(1, 6)]   # 5 seasons


def poster(name, lang=None, votes=5):
    return {"Type": "Primary", "Language": lang, "VoteCount": votes, "CommunityRating": 5.0, "Width": 2000,
            "Height": 3000, "Url": f"{TMDB}/{name}.jpg"}


def backdrop(name, rating):
    return {"Type": "Backdrop", "Language": "", "VoteCount": 3, "CommunityRating": rating, "Width": 3840,
            "Height": 2160, "Url": f"{TMDB}/{name}.jpg"}


def jpeg(w=2000, h=3000, colour=(90, 100, 110)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, "JPEG")
    return buf.getvalue()


class Fake:
    """Jellyfin (GET): seasons, per-item poster lists, the series' backdrop list; TMDB: any jpg."""
    def __init__(self, n_seasons=5):
        self.seasons = SEASONS[:n_seasons]
        self.own = {SEASONS[0]: [poster("s1-own")], SEASONS[3]: [poster("s4-own")]}   # 2 of 5 have their own art
        self.series = [poster("series-1", votes=9), poster("series-2", votes=7), poster("series-en", "en", 99)]
        self.backdrops = [backdrop("bd-a", 8.0), backdrop("bd-b", 7.0), backdrop("bd-c", 6.0), backdrop("bd-d", 5.0)]
        self.calls = []
        self.backdrop_size = (3840, 2160)

    def get(self, url, params=None, headers=None, timeout=None, stream=False):
        self.calls.append((url, dict(params or {})))
        if "image.tmdb.org" in url:
            if "/bd-" in url:
                size = (1280, 720) if "/w1280/" in url else self.backdrop_size
                return Resp(data=jpeg(*size), ctype="image/jpeg")
            return Resp(data=jpeg(2000, 3000), ctype="image/jpeg")
        if "/Shows/" in url:
            return Resp(body={"Items": [{"Id": s, "IndexNumber": i + 1} for i, s in enumerate(self.seasons)]})
        item = url.split("/Items/", 1)[1].split("/", 1)[0]
        if (params or {}).get("type") == "Backdrop":
            return Resp(body={"Images": self.backdrops if item == SHOW else []})
        return Resp(body={"Images": self.series if item == SHOW else self.own.get(item, [])})

    def __getattr__(self, name):
        raise AssertionError(f"GET only, not {name}")

    def jellyfin_reads(self):
        return [c for c in self.calls if "image.tmdb.org" not in c[0]]


LIB = {"shows": [{"title": "Long Show", "year": 2015, "jf_id": SHOW, "added_at": "2026-01-01T00:00:00Z"}]}


@pytest.fixture()
def fake(monkeypatch, tmp_path):
    monkeypatch.setenv("JELLYFIN_URL", "http://jf.test")
    monkeypatch.setenv("JELLYFIN_API_KEY", "k" * 32)
    monkeypatch.setenv("POSTERS", "dry")
    monkeypatch.setenv("POSTERS_DIR", str(tmp_path / "posters"))
    monkeypatch.setenv("POSTERS_TEMPLATE_DIR", str(tmp_path / "no-kit"))
    monkeypatch.setenv("POSTERS_BACKDROPS", "off")
    f = Fake()
    monkeypatch.setattr(upstream, "session", lambda name: f)
    return f


def art_of(jf_id):
    return ((ms.read_meta(jf_id) or {}).get("pick") or {}).get("url", "").rsplit("/", 1)[-1]


def test_five_seasons_two_with_own_art_get_five_different_pictures(fake):
    counts = mp.dry_pass(snaps(LIB), pause=0)
    assert counts["failed"] == 0 and counts["rendered"] == 6
    got = [art_of(s) for s in SEASONS]
    assert got == ["s1-own.jpg", "series-2.jpg", "series-en.jpg", "s4-own.jpg", "bd-c.jpg"]
    assert art_of(SHOW) == "series-1.jpg" and len(set(got + [art_of(SHOW)])) == 6     # no repeats in the show
    assert ms.read_meta(SEASONS[4])["pick"]["fallback"] == "backdrop"                # cropped 2:3 by the renderer
    with Image.open(ms.master(SEASONS[4])) as im:
        assert im.size == (1000, 1500)


def test_backdrops_not_used_for_home_or_title_come_first(fake):
    fake.series = [poster("series-1")]                                              # no spare series posters
    mp.dry_pass(snaps(LIB), pause=0)
    assert [art_of(s) for s in SEASONS] == ["s1-own.jpg", "bd-c.jpg", "bd-d.jpg", "s4-own.jpg", "bd-a.jpg"]


def test_the_order_is_stable_across_passes_and_settled_shows_read_nothing(fake, monkeypatch):
    mp.dry_pass(snaps(LIB), pause=0)
    first = [art_of(s) for s in SEASONS]
    fake.calls.clear()
    assert mp.dry_pass(snaps(LIB), pause=0)["rendered"] == 0 and fake.jellyfin_reads() == []   # cached, no reads
    monkeypatch.setattr(mp, "SEASONS_TTL_S", 0)                                     # the daily re-read
    fake.series = [poster("series-1", votes=9), poster("new-top", votes=50), poster("series-2", votes=7),
                   poster("series-en", "en", 99)]                                   # TMDB re-ranks
    assert mp.dry_pass(snaps(LIB), pause=0)["rendered"] == 0
    assert [art_of(s) for s in SEASONS] == first                                    # nobody's picture moved


def test_a_season_that_gets_its_own_poster_takes_it(fake, monkeypatch):
    mp.dry_pass(snaps(LIB), pause=0)
    monkeypatch.setattr(mp, "SEASONS_TTL_S", 0)
    fake.own[SEASONS[1]] = [poster("s2-own")]
    mp.dry_pass(snaps(LIB), pause=0)
    assert art_of(SEASONS[1]) == "s2-own.jpg" and art_of(SEASONS[2]) == "series-en.jpg"   # the others stay


def test_a_new_season_gets_the_next_unused_picture(monkeypatch, tmp_path, fake):
    fake.seasons = SEASONS[:4]
    mp.dry_pass(snaps(LIB), pause=0)
    before = [art_of(s) for s in SEASONS[:4]]
    fake.seasons = SEASONS
    monkeypatch.setattr(mp, "SEASONS_TTL_S", 0)
    mp.dry_pass(snaps(LIB), pause=0)
    assert [art_of(s) for s in SEASONS[:4]] == before and art_of(SEASONS[4]) == "bd-c.jpg"
    plan = ms.read_meta(SHOW)["season_art"]
    assert set(plan) == set(SEASONS) and plan[SEASONS[4]]["source"] == "backdrop"


def test_a_show_with_nothing_left_falls_back_to_the_series_poster(fake):
    fake.series, fake.backdrops = [poster("series-1")], []
    mp.dry_pass(snaps(LIB), pause=0)
    assert art_of(SEASONS[1]) == "series-1.jpg"                                     # as before: a repeat, not a gap


def test_a_plan_failure_keeps_the_previous_plan(fake, monkeypatch):
    mp.dry_pass(snaps(LIB), pause=0)
    first = [art_of(s) for s in SEASONS]
    monkeypatch.setattr(mp, "SEASONS_TTL_S", 0)
    monkeypatch.setattr(mp, "plan_season_art", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    counts = mp.dry_pass(snaps(LIB), pause=0)
    assert counts["failed"] == 1 and [art_of(s) for s in SEASONS] == first


def test_no_network_on_the_review_page_render(fake, monkeypatch):
    from fastapi.testclient import TestClient

    from hub import main
    mp.dry_pass(snaps(LIB), pause=0)

    def boom(*a, **k):
        raise AssertionError("network on render")
    monkeypatch.setattr(upstream, "session", boom)
    monkeypatch.setattr(mp, "remote_images", boom)
    monkeypatch.setattr(mp, "remote_backdrops", boom)
    monkeypatch.setattr(mp, "fetch_art", boom)
    with TestClient(main.app) as c:
        assert c.get("/media/posters").status_code == 200
        assert c.get(f"/media/posters/img/{SEASONS[4]}").status_code == 200
    assert json.loads((ms.out_dir() / SHOW / "meta.json").read_text())["season_art"]


def test_a_backdrop_over_the_decode_cap_but_under_5_mb_retries_at_w1280(fake):
    """Review of #264: a 4096 x 2304 original (9.4 M pixels, a small file) is refused by the decode cap; the season
    then renders from TMDB's 1280-wide copy instead of never getting a poster."""
    fake.backdrop_size = (4096, 2304)
    counts = mp.dry_pass(snaps(LIB), pause=0)
    assert counts["failed"] == 0 and art_of(SEASONS[4]) == "bd-c.jpg" and ms.master(SEASONS[4]) is not None
    assert any("/w1280/bd-c.jpg" in u for u, _ in fake.calls)


def test_a_failing_season_plan_backs_off_after_three_tries(fake, monkeypatch):
    monkeypatch.setattr(mp, "plan_season_art", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    for _ in range(3):
        assert mp.dry_pass(snaps(LIB), pause=0)["failed"] >= 1
    meta = ms.read_meta(SHOW)
    assert meta["season_art_fails"] == 3 and meta["season_art_retry_at"]
    calls = []
    monkeypatch.setattr(mp, "plan_season_art", lambda *a, **k: calls.append(1) or {})
    got = mp.dry_pass(snaps(LIB), pause=0)
    assert calls == [] and got["backoff"] >= 1                                     # passed over for 24 h
    monkeypatch.setattr(mp, "in_backoff_until", lambda retry_at, now=None: False)  # a day later
    mp.dry_pass(snaps(LIB), pause=0)
    assert calls == [1] and "season_art_fails" not in ms.read_meta(SHOW)           # a success clears the count
