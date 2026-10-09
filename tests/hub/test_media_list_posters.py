"""media-ux2 item 1 (2026-10-08): bigger posters on the Movies / TV Shows list pages only — 55 px on a phone
(+25%), 66 px from 640 px (+50%), fetched at h=240 so they stay sharp, and the library warm-up warms that size."""
import re
from pathlib import Path

import requests
from fastapi.testclient import TestClient

from hub import images, media_warmup
from tests.hub.test_media_frame import env as frame_env  # noqa: F401  (fixture)
from tests.hub.test_media_library_pages import MOVIES, SHOWS, jelly, body
from tests.hub.helpers import env, JELLY  # noqa: F401  (re-export: defined in tests/hub/helpers.py)
from tests.hub.test_media_speed import Img

CSS = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")


def _listboxes(main_html):
    return re.findall(r'<div class="listbox libposters">(.*?)</div>\s*</section>', main_html, re.S)


def test_movies_and_tv_lists_ask_for_the_bigger_poster(frame_env):
    main = frame_env(jellyfin=jelly())
    with TestClient(main.app) as c:
        _, mv = body(c, "/media/movies?view=list")    # media-ux4: the rows are the List view (grid is the default)
        _, tv = body(c, "/media/tv?view=list")
    for page, items in ((mv, MOVIES), (tv, SHOWS)):
        boxes = "".join(_listboxes(page))
        assert boxes, "the list rows sit in .listbox.libposters"
        assert boxes.count('class="poster row-poster') == len(items)
        assert "?h=120" not in boxes
        for it in items:
            assert f'src="/img/{it["poster"]}?h=240&amp;' in boxes
        assert 'width="160" height="240"' in boxes


def test_other_row_lists_keep_the_small_poster(frame_env):
    main = frame_env(jellyfin=JELLY)
    with TestClient(main.app) as c:
        hist = c.get("/media/history").text
    # media-ux4 (2026-10-08, B.): the To rate inbox rows on History now use the list size too; Recently watched keeps 44 px
    recent = hist.split(">Recently watched</div>", 1)[1].split("</section>", 1)[0]
    assert "libposters" not in recent and "?h=120&amp;" in recent


def test_css_scales_list_posters_25_and_50_percent_and_keeps_the_guide_size():
    assert ".poster.row-poster { width: 44px;" in CSS                      # every other row stays 44 px
    assert ".listbox.libposters .poster.row-poster { width: 55px; }" in CSS  # phone: 44 x 1.25
    m = re.search(r"@media \(min-width: 640px\) \{ \.listbox\.libposters \.poster\.row-poster \{ width: 66px; \}"
                  r" \.listbox\.libposters \.row \{ padding: 10px;", CSS)
    assert m, "desktop: 44 x 1.5 = 66 px with a taller row"
    assert ".listbox.libposters .row { padding: 10px 8px; }" in CSS


def test_library_warmup_warms_the_list_poster_size(env, monkeypatch, tmp_path):
    assert media_warmup.LIST_POSTER_H == 240 and 240 in images.SIZES
    client, _both = env(jelly_extra={
        "movies": [{"item_key": "tmdb:603", "jf_id": "mov1", "title": "Harbour Lights", "poster": "jf:mov1"}],
        "shows": [{"item_key": "tmdb:100", "jf_id": "ser1", "title": "Quiet Show", "poster": "jf:ser1",
                   "episodes": 2, "unplayed": 1}]})
    monkeypatch.setenv("IMG_CACHE_DIR", str(tmp_path / "img"))
    real = requests.get

    def get(url, params=None, headers=None, timeout=None, **kw):
        if "/Images/" in url or url.startswith("https://image.tmdb.org/"):
            return Img()
        return real(url, params=params, headers=headers, timeout=timeout)

    monkeypatch.setattr(requests, "get", get)
    media_warmup.warm_library(pause=0)
    with client:
        pages = client.get("/media/movies").text + client.get("/media/tv").text
    rendered = set(re.findall(r'/img/(jf:[A-Za-z0-9-]+)\?h=240&', pages))
    assert rendered == {"jf:mov1", "jf:ser1"}
    for ref in rendered:
        assert images.warm(ref, 240) == "cached", ref
