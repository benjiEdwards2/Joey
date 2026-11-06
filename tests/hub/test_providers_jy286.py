"""JY-286 (B., 2026-11-02: "only by showing the logo. I don't need to see the text of it."; TV: "Similar with the where
to watch"): the streaming services as logos only on every title page - the web episode page too (it drew name chips),
and the TV (it drew the names as words). Alt text carries the name; the TV has no off-site link."""
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.film_page import whole
from tests.hub.helpers import env, SHOW  # noqa: F401
from tests.hub.test_tv_extras_jy270 import rich  # noqa: F401 - the TV film fixture with Netflix (stream) + Apple TV (rent)
from tests.hub.test_tv_p3_jy259 import after_header, tv_whole
from tests.hub.test_tv_p3_jy259 import film_friend as _ff  # noqa: F401 - rich's base fixture


def test_web_episode_page_shows_logos_not_names(env):
    client, both = env()
    both.seerr.table["/api/v1/tv/100"] = {**SHOW, "watchProviders": [{"iso_3166_1": "AU", "flatrate": [
        {"name": "Stan", "logoPath": "/stan.jpg"}, {"name": "Kayo"}], "rent": [{"name": "Apple TV"}]}]}
    with client:
        b = main_of(whole(client, "/media/item/ep3"))
    row = b.split('<div class="provlogos"', 1)[1].split("</div>", 1)[0]
    assert 'aria-label="Where to watch"' in row
    assert 'src="/img/tmdb:/stan.jpg?h=120&amp;t=' in row and 'alt="Stan"' in row
    assert 'src="/img/none?h=120&amp;t=' in row and 'alt="Kayo"' in row          # no logo: the letters tile
    assert ">Stan<" not in b and ">Kayo<" not in b and "Apple TV" not in b      # names never visible; streaming only
    assert 'class="chip"' not in row and ">Where to watch</h2>" not in b
    assert 'href="https://www.justwatch.com/au/search?q=' in row


def test_tv_film_page_shows_logos_without_links(rich):
    body = after_header(tv_whole(rich, "/media/title/movie/603"))
    prov = body.split("tv-extras tv-providers", 1)[1].split("</section>", 1)[0]
    assert 'class="prov-logo"' in prov and 'alt="Netflix"' in prov
    assert ">Netflix<" not in prov and "Netflix</p>" not in prov and "Apple TV" not in prov
    assert "<a " not in prov                                                     # JY-270: no off-site links on the TV


def test_tv_css_sizes_the_logos():
    from pathlib import Path
    css = Path("hub/static/tv.css").read_text(encoding="utf-8")
    assert "html.tv .tv-providers .prov-logo { width: 2.5rem; height: 2.5rem;" in css
