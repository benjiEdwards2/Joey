"""media-ux4 items 5 / 5b / 5c (2026-10-08): an episode page's hero carries no "Episode of <Show>" line (the part-of
banner under the hero is the way to the show), only the EPISODE's Play button (the series-level "Next to watch" /
"Play" stays on the series page), and a watched toggle that reflects and acts on the episode itself."""
import re

from tests.hub.test_media_film import env, main_of  # noqa: F401  (env is a fixture)
from tests.hub.test_media_item import ITEMS, deep


def hero(html):
    return html.split('<header class="pagehead hero-detail">', 1)[1].split("</header>", 1)[0]


# ---- item 5: no "Episode of" line ----

def test_episode_hero_has_no_episode_of_line_but_keeps_the_rest(env):
    client, _ = env()
    with client:
        h = hero(client.get("/media/item/ep3").text)
        b = main_of(client.get("/media/item/ep3").text)
    assert "Episode of" not in h and 'href="/media/item/ser1"' not in h
    assert "S04E03 · Penny for Your Thoughts" in h and "Coins go missing." in h and "Quiet Show (2020)" in h
    assert 'href="/media/item/ser1#seasons"' in b                     # the banner still leads to the show
