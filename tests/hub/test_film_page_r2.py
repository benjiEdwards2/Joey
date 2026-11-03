"""JY-280 P2 (B.'s pick A, 2026-11-03) + JY-286 (pick A): the movie page's two-column body. Scores in the right column
as a site's logo + number (no site words), each a link to that site's page for the film; the owner-only File drawer,
gated server-side (a friend, her and the guest front get no file text at all); where-to-watch as logos only under the
hero's buttons. Upstreams are the test_media_film fakes; no network."""
import pytest

from hub import media_db, media_film
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.film_page import whole
from tests.hub.helpers import env, FILM  # noqa: F401
from tests.hub.test_film_quality import film_source, rankdir, write_rank  # noqa: F401
from tests.hub.test_media_film import ITEMS

FILE_STRINGS = ("Harbour.Lights.2019.2160p", "20.0 GB", "4.7 Mb/s", "English · 2 tracks", "group FLUX", "filepanel",
                "File details", "Bitrate", "Subtitles")


def page(env, monkeypatch, path="/media/title/movie/603"):
    monkeypatch.setitem(ITEMS["mov1"], "MediaSources", film_source())
    client, _ = env()
    with client:
        return main_of(whole(client, path))


def test_body_is_two_columns_cast_left_scores_details_file_right(env, monkeypatch, rankdir):
    b = page(env, monkeypatch)
    cols = b.split('<div class="filmcols">', 1)[1]
    main, side = cols.split('<aside class="filmcol-side"', 1)
    assert ">Cast</h2>" in main and ">Scores<" not in main
    assert side.index(">Scores<") < side.index(">Details</h2>") < side.index("File details")
    assert '<section class="sec filedrawer"><details class="fold"><summary class="seclabel">File details</summary>' in side
    assert "<details class=\"fold\" open" not in side                      # closed by default
    assert "Harbour.Lights.2019.2160p.WEB-DL.DDP5.1.HEVC-FLUX.mkv" in side and "4.7 Mb/s" in side
    assert ">File</h2>" not in b and 'class="scorepill sitepill"' not in b   # the drawer replaces the section; no site row


def test_scores_are_logo_and_number_linked_to_each_site(env, monkeypatch, rankdir):
    b = page(env, monkeypatch)
    side = b.split('<aside class="filmcol-side"', 1)[1].split("</aside>", 1)[0]
    assert 'class="sp-name">IMDb' not in side and 'class="sp-name">TMDB' not in side and ">Letterboxd<" not in side
    assert '<a class="scorepill scorelink sp-tmdb" href="https://www.themoviedb.org/movie/603"' in side
    assert 'alt="TMDB" width="16" height="16"><b class="sp-val">7.8</b></a>' in side
    assert 'href="https://letterboxd.com/tmdb/603"' in side and 'alt="Letterboxd"' in side
    assert 'alt="IMDb" width="16" height="16"><b class="sp-val">7.9</b>' in side
    assert 'alt="Rotten Tomatoes" width="16" height="16"><b class="sp-val">92%</b></span>' in side   # no RT id: unlinked


def test_imdb_score_links_to_the_title_page_when_the_id_is_known(env, monkeypatch, rankdir):
    monkeypatch.setitem(ITEMS["mov1"], "ProviderIds", {**ITEMS["mov1"].get("ProviderIds", {}), "Imdb": "tt0000603"})
    b = page(env, monkeypatch)
    assert '<a class="scorepill scorelink sp-imdb" href="https://www.imdb.com/title/tt0000603/"' in b


@pytest.mark.parametrize("view", ["her"])
def test_her_view_gets_no_file_drawer_or_file_text(env, monkeypatch, rankdir, view):
    b = page(env, monkeypatch, f"/media/title/movie/603?owner_view={view}")
    for s in FILE_STRINGS:
        assert s not in b, s
    assert ">Cast</h2>" in b and ">Scores<" in b


def test_file_owner_gate():
    assert media_film.file_owner("you") and not media_film.file_owner("her") and not media_film.file_owner("jf:abc")


def test_where_to_watch_is_logos_only_under_the_cast(env, monkeypatch, rankdir):
    monkeypatch.setitem(FILM["watchProviders"][0], "flatrate", [{"name": "Netflix", "logoPath": "/nflx.jpg"},
                                                                {"name": "Kayo"}])
    monkeypatch.setitem(ITEMS["mov1"], "MediaSources", film_source())
    client, _ = env()
    with client:
        html = whole(client, "/media/title/movie/603")
    row = html.split('<div class="provlogos"', 1)[1].split("</div>", 1)[0]
    main = html.split('<div class="filmcol-main">', 1)[1].split("<aside class=\"filmcol-side\"", 1)[0]   # round-2 pick A: left column
    assert '<div class="provlogos"' in main and main.index(">Cast</h2>") < main.index('<div class="provlogos"')
    assert '<div class="provlogos"' not in html.split("</header>", 1)[0]
    assert 'src="/img/tmdb:/nflx.jpg?h=120&amp;t=' in row and 'alt="Netflix"' in row
    assert 'src="/img/none?h=120&amp;t=' in row and 'alt="Kayo"' in row      # no logo: the letters tile
    assert ">Netflix<" not in row and ">Kayo<" not in row and "Apple TV" not in html   # names never visible; streaming only
    assert 'href="https://www.justwatch.com/au/search?q=' in row
    assert ">Where to watch</h2>" not in main_of(html)


def test_guest_front_film_page_has_no_file_drawer_or_file_text(monkeypatch, tmp_path):
    from tests.hub.test_guest_detail import JF
    from tests.hub.guest_pages import guest_client, sign_in
    from tests.hub.fake_jellyfin import FRIEND_ID
    from tests.hub import test_guest_detail as gd
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": gd.LIB, "arr": gd.ARR})
    fake.items[JF] = {"Id": JF, "Type": "Movie", "Name": "Library Film", "ProductionYear": 1999,
                      "ProviderIds": {"Tmdb": "603"}, "RunTimeTicks": 120 * 600_000_000,
                      "MediaSources": [{"Container": "mkv", "Size": 21_500_000_000, "Bitrate": 4_700_000,
                                        "Path": "/x/Library.Film.1999.2160p.WEB-DL-FLUX.mkv", "MediaStreams": [
                          {"Type": "Video", "Height": 2160, "Width": 3840, "Codec": "hevc"},
                          {"Type": "Audio", "Codec": "truehd", "Channels": 8, "Language": "eng"}]}],
                      "MediaStreams": [{"Type": "Video", "Height": 2160, "Width": 3840, "Codec": "hevc"}]}
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        for path in (f"/media/item/{JF}", "/media/title/movie/603"):
            html = c.get(path).text
            for s in ("Library.Film.1999", "20.0 GB", "4.7 Mb/s", "filepanel", "File details", "filedrawer", "FLUX",
                      "<dt>Audio</dt>", "<dt>On disk</dt>", "3840 × 2160"):
                assert s not in html, (path, s)
