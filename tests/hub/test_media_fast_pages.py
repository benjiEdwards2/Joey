"""F2 fast item pages (2026-10-12): the film / show page renders from Jellyfin + the caches without waiting on
Jellyseerr or OMDb; the sections still waiting are placeholders the page's ONE part request fills; a cached title
renders whole; a link prefetch warms both sides; the parts never read Jellyfin again. Fakes only, no network."""
import threading
import time

import pytest
import requests

from hub import media_film, media_item, media_omdb
from tests.hub.conftest import main_of
from tests.hub.film_page import parts, parts_href, whole
from tests.hub.helpers import env, FakeResponse, SEERR_URL as SEERR, URL  # noqa: F401

OMDB = media_omdb.URL
TT = "tt0133093"


def seerr_calls(both):
    return [c[len(SEERR):] for c in both.calls if c.startswith(SEERR)]


def jf_calls(both):
    return [c[len(URL):] for c in both.calls if c.startswith(URL)]


@pytest.fixture()
def gated(env, monkeypatch):
    """A client whose background upstream read waits for `go` - so a test can look at the page before it has run -
    with an OMDb key and a fake OMDb answering Metascore 74."""
    monkeypatch.setenv("OMDB_API_KEY", "k-test")
    client, both = env()
    both.seerr.table["/api/v1/movie/603"] = {**both.seerr.table["/api/v1/movie/603"], "externalIds": {"imdbId": TT}}
    omdb_calls, real_get = [], both.get

    def get(url, params=None, headers=None, timeout=None, **kw):
        if url.startswith(OMDB):
            omdb_calls.append(dict(params or {}))
            return FakeResponse({"Metascore": "74"})
        return real_get(url, params=params, headers=headers, timeout=timeout)

    monkeypatch.setattr(requests, "get", get)
    go, real_load = threading.Event(), media_film._load_extras
    monkeypatch.setattr(media_film, "_load_extras", lambda *a: go.wait(5) and real_load(*a))
    return client, both, omdb_calls, go


# ---- the core renders first ----

def test_cold_item_page_waits_for_no_jellyseerr_or_omdb_call(gated):
    client, both, omdb_calls, go = gated
    with client:
        page = client.get("/media/item/mov1").text
        assert seerr_calls(both) == [] and omdb_calls == []                  # nothing upstream before the first byte
        b = main_of(page)
        assert "Harbour Lights" in b and "A ferry pilot returns home." in b  # Jellyfin: title, overview, file
        assert "4K" in b and 'id="fp-scores"' in b and ">Loading<" in b
        href = parts_href(page)
        assert href == ("/media/item/mov1/part/all?p=makers,actions,scores,collection,crew,dates,cast,providers,shelves")
        go.set()
        frag = client.get(href).text
    got = parts(frag)
    assert set(got) == set(media_film.PARTS)
    assert '<span class="sp-name">IMDb</span><b class="sp-val">7.9</b>' in got["scores"] and "sp-mc-good" in got["scores"]
    assert "tmdb:/ada.jpg" in got["cast"] and ">Netflix</a>" in got["providers"] and "Similar One" in got["shelves"]
    assert "Harbour Collection" in got["collection"] and "<dt>Cinematography</dt>" in got["crew"]
    assert "<dt>Cinema</dt>" in got["dates"] and omdb_calls and omdb_calls[0]["i"] == TT


def test_placeholders_hold_the_jellyfin_fallback_and_one_word_states(gated):
    client, both, _, go = gated
    with client:
        b = main_of(client.get("/media/item/mov1").text)
        go.set()
    # the cast / director cards are Jellyfin's while TMDB's are pending: nothing jumps when they are swapped
    cast = b.split('id="fp-cast"', 1)[1].split('id="fp-providers"', 1)[0]
    assert "castcard" in cast and 'id="fp-makers" aria-busy="true">' in b
    assert '<span class="scorepill sp-wait"><span class="sp-name">Loading</span></span>' in b
    for name in media_film.PARTS:
        assert f'<div class="fpart" id="fp-{name}" aria-busy="true">' in b
    assert b.count('class="fpart-load"') == 1                                # ONE request fills them all


def test_off_server_title_waits_for_its_one_title_body_only(gated):
    client, both, omdb_calls, go = gated
    with client:
        b = main_of(client.get("/media/title/movie/701").text)
        assert seerr_calls(both) == ["/api/v1/movie/701"] and omdb_calls == []
        assert "Plain Film" in b and 'id="request-block"' in b                # the body IS the page: Request inline
        assert 'id="fp-shelves"' in b and 'id="fp-actions"' not in b
        go.set()


def test_parts_never_read_jellyfin_again(env):
    client, both = env()
    with client:
        page = client.get("/media/item/ser1").text
        before = list(jf_calls(both))
        assert before.count("/Shows/ser1/Seasons") == 1
        href = parts_href(page)
        if href:
            client.get(href)
        for name in media_film.PARTS:
            client.get(f"/media/item/ser1/part/{name}")
            client.get(f"/media/title/tv/100/part/{name}")
    assert jf_calls(both) == before


def test_a_single_part_and_unknown_parts(env):
    client, _ = env()
    with client:
        client.get("/media/title/movie/603")
        one = client.get("/media/title/movie/603/part/cast")
        assert one.status_code == 200 and set(parts(one.text)) == {"cast"} and "Ada Actor" in one.text
        assert client.get("/media/title/movie/603/part/nope").status_code == 404
        assert client.get("/media/item/mov1/part/all?p=nope,cast,cast").text.count('id="fp-cast"') == 1
        assert client.get("/media/item/mov1/part/all").text.strip() == ""
        assert client.get("/media/item/bad$id/part/cast").status_code == 404


def test_a_cached_title_renders_whole_inline_with_no_new_call(env):
    client, both = env()
    with client:
        whole(client, "/media/item/mov1")
        media_film.drain_extras()
        n = len(both.calls)
        page = client.get("/media/item/mov1").text
    assert len(both.calls) == n                                               # Jellyfin, Jellyseerr: all cached
    assert "fpart" not in page and "aria-busy" not in page and parts_href(page) is None
    b = main_of(page)
    assert "Come home" in b and "tmdb:/ada.jpg" in b and "Similar One" in b and ">Netflix</a>" in b


def test_whole_page_equals_the_cached_page(env):
    """The deferred page, once its parts landed, draws what a cached render draws (bar the tagline)."""
    client, _ = env()
    with client:
        late = main_of(whole(client, "/media/item/mov1"))
        media_film.drain_extras()
        cached = main_of(client.get("/media/item/mov1").text)
    for want in ("castpic", "Cy Camera", "Harbour Collection", "Similar One", "Rec One", "sp-imdb", "sp-rt",
                 "<dt>Digital</dt>", ">Apple TV</a>"):
        assert (want in late) == (want in cached), want


# ---- prefetch ----

def test_prefetch_warms_both_sides_and_renders_nothing(env):
    client, both = env()
    with client:
        r = client.get("/media/item/mov1", headers={"X-Joey-Prefetch": "1"})
        assert r.status_code == 204 and r.content == b"" and "set-cookie" not in r.headers
        assert media_item.peek("mov1") is not None                            # the Jellyfin item is cached
        media_film.drain_extras()                                             # ... and the upstream read ran
        n = len(both.calls)
        page = client.get("/media/item/mov1").text                            # the real tap: one cache hit
    assert len(both.calls) == n and parts_href(page) is None and "Similar One" in page


def test_prefetch_of_a_title_page_too(env):
    client, both = env()
    with client:
        r = client.get("/media/title/movie/701", headers={"X-Joey-Prefetch": "1"})
        media_film.drain_extras()
        n = len(both.calls)
        page = client.get("/media/title/movie/701").text
    assert r.status_code == 204 and len(both.calls) == n and parts_href(page) is None


def test_prefetch_is_logged_without_the_path(env, caplog):
    client, _ = env()
    with client, caplog.at_level("INFO", logger="hub.media_film"):
        client.get("/media/item/mov1", headers={"X-Joey-Prefetch": "1"})
    lines = [r.getMessage() for r in caplog.records if r.name == "hub.media_film"]
    assert "film prefetch: item" in lines and not any("mov1" in x for x in lines)


def test_joey_js_prefetches_film_links_once_one_at_a_time(env):
    from tests.hub.conftest import shell_script
    client, _ = env()
    with client:
        js = shell_script(client, client.get("/media/item/mov1").text)
    block = js.split("F2 fast item pages", 1)[1]
    assert "'X-Joey-Prefetch': '1'" in block and 'a[href^="/media/item/"], a[href^="/media/title/"]' in block
    assert "touchstart" in block and "mouseover" in block and "60" in block
    assert "if (busy || done[href]) return;" in block                        # once per href, one in flight


# ---- one read per title ----

def test_concurrent_reads_of_one_item_share_one_call(env, monkeypatch):
    client, both = env()
    real = both.get

    def get(url, params=None, headers=None, timeout=None, **kw):
        time.sleep(0.2)
        return real(url, params=params, headers=headers, timeout=timeout)

    monkeypatch.setattr(requests, "get", get)
    with client:
        out = []
        threads = [threading.Thread(target=lambda: out.append(media_item._data("mov1"))) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert len(out) == 3 and all(o is out[0] for o in out)
    assert jf_calls(both).count("/Users/u1/Items/mov1") == 1
