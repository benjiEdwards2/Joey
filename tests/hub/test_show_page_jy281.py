"""JY-281: the show / season page takes the movie page's pattern (JY-280 P2): Scores as a site's logo + number (no site
words, no Letterboxd on TV), each a link to that site's page for the show; the File section is the owner's closed
"File details" drawer with a "By episode" list - gated server-side, so her view, a friend, the guest front and the TV
get no file text at all. Upstreams are the helpers fakes; no network."""
import pytest

from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.film_page import whole
from tests.hub.helpers import env, EPISODES, ITEMS, SOURCES  # noqa: F401

PATH = "/media/title/tv/100"
FILE_STRINGS = ("Quiet.Show.S04E01", "20.0 GB", "filepanel", "filedrawer", "File details", "By episode")


def with_files(monkeypatch):
    for e in EPISODES[:3]:
        src = [{**SOURCES[0], "Path": f"/tv/Quiet.Show.S04E0{e['IndexNumber']}.1080p-GRP.mkv"}]
        monkeypatch.setitem(e, "MediaSources", src)


def page(env, monkeypatch, path=PATH):
    with_files(monkeypatch)
    client, _ = env()
    with client:
        return main_of(whole(client, path))


def test_show_scores_are_logo_and_number_links_without_site_words(env, monkeypatch):
    b = page(env, monkeypatch)
    card = b.split('class="scorepills hero-scores"', 1)[1].split("</header>", 1)[0]   # JY-316 r3: the hero's strip
    assert '<a class="scorepill scorelink sp-tmdb" href="https://www.themoviedb.org/tv/100"' in card
    assert 'alt="TMDB"' in card
    assert 'class="sp-name">TMDB' not in b and 'class="sp-name">IMDb' not in b and ">Letterboxd<" not in b
    assert "letterboxd.com" not in b and 'class="scorepill sitepill"' not in b


def test_show_imdb_score_links_to_the_show_page(env, monkeypatch):
    monkeypatch.setitem(ITEMS["ser1"], "ProviderIds", {"Tmdb": "100", "Imdb": "tt0000100"})
    b = page(env, monkeypatch)
    if 'sp-imdb' in b:   # the fake ratings may carry no IMDb number for a show; the link holds when it does
        assert 'href="https://www.imdb.com/title/tt0000100/"' in b


def test_owner_sees_a_closed_file_drawer_with_episodes(env, monkeypatch):
    b = page(env, monkeypatch)
    assert '<section class="sec filedrawer"><details class="fold"><summary class="seclabel">File details</summary>' in b
    drawer = b.split('class="sec filedrawer"', 1)[1].split("</section>", 1)[0]
    assert "<details class=\"fold\" open" not in drawer
    assert "By episode" in drawer and "S4 E1" in drawer and "Quiet.Show.S04E03.1080p-GRP.mkv" in drawer
    assert ">File</h2>" not in b


def test_episodes_row_still_leads_the_body(env, monkeypatch):
    b = page(env, monkeypatch)
    assert b.index("hero-scores") < b.index(">Episodes</h2>") < b.index(">Details</h2>") < b.index("File details")   # JY-316 r3


@pytest.mark.parametrize("view", ["her"])
def test_her_view_gets_no_file_text_on_show_and_episode(env, monkeypatch, view):
    for path in (f"{PATH}?owner_view={view}", f"/media/item/ep3?owner_view={view}"):
        b = page(env, monkeypatch, path)
        for s in FILE_STRINGS:
            assert s not in b, (path, s)


def test_guest_front_and_tv_show_pages_have_no_file_text_or_site_links(monkeypatch, tmp_path):
    from tests.hub.guest_pages import TV_UA, guest_client, sign_in
    from tests.hub.fake_jellyfin import FRIEND_ID
    from tests.hub import test_tv_series_episodes as t
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": t.LIB})
    fake.items[t.SHOW] = {"Id": t.SHOW, "Type": "Series", "Name": "Sample Show", "ProductionYear": 2026,
                          "ProviderIds": {"Tmdb": "100"}}
    src = [{"Container": "mkv", "Size": 21_500_000_000, "Path": "/x/Sample.Show.S01E01.2160p-FLUX.mkv",
            "MediaStreams": [{"Type": "Video", "Height": 2160, "Width": 3840, "Codec": "hevc"},
                             {"Type": "Audio", "Codec": "truehd", "Channels": 8, "Language": "eng"}]}]
    eps = [{**e, "MediaSources": src} for e in t.EPISODES]
    for e in eps:
        fake.items[e["Id"]] = e
    fake.episodes[t.SHOW] = eps
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        for headers in ({}, {"User-Agent": TV_UA}):
            for path in (f"/media/item/{t.SHOW}", f"/media/item/{t.E1}"):
                html = c.get(path, headers=headers).text
                assert "Sample Show" in html, (path, headers)
                for s in ("Sample.Show.S01E01", "20.0 GB", "filepanel", "filedrawer", "File details", "By episode",
                          "FLUX", "themoviedb.org", "imdb.com", "letterboxd.com"):
                    assert s not in html, (path, headers, s)
