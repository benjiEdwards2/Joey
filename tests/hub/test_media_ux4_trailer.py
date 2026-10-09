"""media-ux4 item 9 (2026-10-08): trailers embedded. The Trailer button keeps a plain link to the video (no JS) and, when it
is a YouTube video, carries its key; a click opens an in-page <dialog> into which the script creates a
youtube-nocookie.com iframe (autoplay, rel=0) — nothing in the initial HTML loads from YouTube — and closing removes it.
Keys come from Jellyfin RemoteTrailers, then Jellyseerr's TMDB relatedVideos."""
import re
from pathlib import Path

import pytest

from hub import media_film, media_item
from tests.hub.helpers import env, FILM, ITEMS  # noqa: F401  (re-export: defined in tests/hub/helpers.py)
from tests.hub.conftest import main_of  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
CSS = (ROOT / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
CONTRACT = (ROOT / "docs" / "connector-contract.md").read_text(encoding="utf-8")
KEY = "dQw4w9WgXcQ"


def with_video(both, **video):
    both.seerr.table["/api/v1/movie/603"] = {**FILM, "relatedVideos": [
        {"url": f"https://www.youtube.com/watch?v={KEY}", "site": "YouTube", "type": "Trailer", "key": KEY, **video}]}


def button(b):
    m = re.search(r'<a class="btn btn-glass trailer-btn" href="([^"]+)" target="_blank" rel="noopener"([^>]*)>(.*?)</a>', b, re.S)
    return m and (m.group(1), m.group(2), re.sub(r"<svg.*?</svg>", "", m.group(3), flags=re.S))


def test_button_is_a_word_link_with_the_youtube_key(env):
    client, both = env()
    with_video(both)
    with client:
        b = main_of(client.get("/media/title/movie/603").text)
    href, attrs, words = button(b)
    assert href == f"https://www.youtube.com/watch?v={KEY}" and words == "Trailer"
    assert f'data-yt="{KEY}"' in attrs and 'aria-haspopup="dialog"' in attrs
    hero = b.split("</header>", 1)[0]
    assert "trailer-btn" in hero and '<svg class="ic"' in hero.split("trailer-btn", 1)[1].split("</a>", 1)[0]


def test_dialog_ships_empty_and_no_iframe_is_in_the_initial_html(env):
    client, both = env()
    with_video(both)
    with client:
        html = client.get("/media/title/movie/603").text
    dlg = html.split('<dialog class="trailerdlg" id="trailer"', 1)[1].split("</dialog>", 1)[0]
    assert 'aria-label="Trailer: Harbour Lights"' in dlg and '<form method="dialog">' in dlg and ">Close</button>" in dlg
    assert '<div class="trailerframe"></div>' in dlg
    assert "<iframe" not in html                                      # created only on click
    assert not re.search(r'(src|href)="https://www\.youtube-nocookie\.com', html)


def test_script_builds_the_nocookie_embed_on_click_and_removes_it_on_close(env):
    client, both = env()
    with_video(both)
    with client:
        html = client.get("/media/title/movie/603").text
    script = html.split("</dialog>", 1)[1].split("</script>", 1)[0]
    assert "'https://www.youtube-nocookie.com/embed/' + a.getAttribute('data-yt') + '?autoplay=1&rel=0'" in script
    assert "createElement('iframe')" in script and "dlg.showModal()" in script and "e.preventDefault()" in script
    assert "document.addEventListener('close'" in script and ".replaceChildren()" in script
    assert "/^[A-Za-z0-9_-]{11}$/" in script and "window.joeyTrailer" in script     # validated; bound once per tab


def test_jellyfin_trailer_wins_and_short_or_foreign_urls_stay_plain_links(env, monkeypatch):
    client, both = env()
    with_video(both)
    monkeypatch.setitem(ITEMS["mov1"], "RemoteTrailers", [{"Url": "https://youtu.be/AAAAAAAAAAA"}])
    with client:
        b = main_of(client.get("/media/item/mov1").text)
        assert button(b)[0] == "https://youtu.be/AAAAAAAAAAA" and 'data-yt="AAAAAAAAAAA"' in button(b)[1]
        monkeypatch.setitem(ITEMS["mov1"], "RemoteTrailers", [{"Url": "https://vimeo.com/12345"}])
        media_item.clear_cache()
        b = main_of(client.get("/media/item/mov1").text)
    assert button(b)[0] == f"https://www.youtube.com/watch?v={KEY}"     # the keyed Jellyseerr video beats a non-YouTube link


def test_no_key_means_a_plain_link_and_no_dialog(env):
    client, _ = env()                                                    # FILM's video id "seerr1" is not a YouTube id
    with client:
        html = client.get("/media/title/movie/603").text
    href, attrs, _ = button(main_of(html))
    assert href == "https://www.youtube.com/watch?v=seerr1" and "data-yt" not in attrs
    assert "<dialog" not in html and "youtube-nocookie" not in html


@pytest.mark.parametrize("url, key", [
    (f"https://www.youtube.com/watch?v={KEY}", KEY), (f"https://youtube.com/watch?v={KEY}&t=3", KEY),
    (f"https://youtu.be/{KEY}", KEY), (f"https://www.youtube.com/embed/{KEY}", KEY),
    (f"https://m.youtube.com/shorts/{KEY}", KEY), (f"https://www.youtube-nocookie.com/embed/{KEY}", KEY),
    ("https://www.youtube.com/watch?v=short", None), ("https://evil.example/watch?v=" + KEY, None),
    ("https://vimeo.com/123", None), ("", None), (None, None),
    ("https://www.youtube.com/watch?v=" + KEY[:10] + '"', None)])
def test_youtube_key(url, key):
    assert media_film.youtube_key(url) == key


def test_trailer_prefers_the_relatedvideos_key_field():
    raw = {"relatedVideos": [{"url": "https://www.youtube.com/watch?v=xx", "site": "YouTube", "type": "Trailer", "key": KEY},
                             {"url": "https://www.youtube.com/watch?v=BBBBBBBBBBB", "site": "YouTube", "type": "Teaser"}]}
    assert media_film._trailer(None, raw) == ("https://www.youtube.com/watch?v=xx", KEY)
    assert media_film._trailer(None, {}) == (None, None)


def test_player_css_and_the_recorded_privacy_exception():
    assert ".trailerdlg::backdrop { background: var(--scrim); }" in CSS
    assert ".trailerframe { aspect-ratio: 16 / 9;" in CSS and ".trailerframe iframe { display: block; width: 100%;" in CSS
    assert "Trailer player (media-ux4, 2026-10-08) — a recorded privacy exception" in CONTRACT
    assert "only when the user presses Trailer" in CONTRACT and "frame-src https://www.youtube-nocookie.com" in CONTRACT
