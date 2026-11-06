"""JY-284 (B. 2026-11-06, picker PUSH, recommendation B on its defaults): file information is the owner's alone and
quicker to reach. Web: a "File" chip in the hero beside Rate opens a popover with the File panel (the closed drawer under
the content is gone); show, season and episode pages too. TV: a "Files" row under Scores - badges, Size, Sound,
Subtitles, never the file name or the release group - for B.'s own TV session only. The TV runs on the media front,
where file_owner is false, so the row has its own server-side gate (media_film.tv_file_owner). Her view, a friend (web
and TV) and B. on the media front's web pages get no file text. Fakes only; no network, no new upstream call."""
import re
from pathlib import Path

import pytest

from hub import media_film
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.film_page import whole
from tests.hub.helpers import env, EPISODES, ITEMS, SOURCES  # noqa: F401
from tests.hub.tv_css import design_px

WEB_FILE = ("tl-filepop", 'id="file"', "filepanel", "File details", "filedrawer")
TV_FILE = ("tv-files", ">Files</h2>", "fmtbadges")


def test_tv_file_owner_is_you_in_tv_mode_only(monkeypatch):
    monkeypatch.setattr("hub.media_front.tv_mode", lambda request: True)
    assert media_film.tv_file_owner("you", None)
    assert not media_film.tv_file_owner("her", None) and not media_film.tv_file_owner("jf:" + "f00d" * 8, None)
    monkeypatch.setattr("hub.media_front.tv_mode", lambda request: False)
    assert not media_film.tv_file_owner("you", None)


def test_tv_file_row_keeps_badges_size_sound_subtitles_only():
    fp = {"badges": [{"main": "4K"}], "grid": [{"label": "Size", "value": "20.0 GB", "key": "size"},
                                             {"label": "Bitrate", "value": "4.7 Mb/s", "key": "bitrate"}],
          "rows": [{"label": "Audio", "value": "English · 2 tracks"}, {"label": "Subtitles", "value": "English"},
                   {"label": "Release", "value": "group FLUX · MKV"}],
          "filename": "Some.Film.2160p-FLUX.mkv", "episodes": [{"code": "S1 E1", "filename": "x.mkv"}]}
    row = media_film.tv_file_row(fp)
    assert row == {"badges": [{"main": "4K"}], "size": "20.0 GB", "sound": "English · 2 tracks", "subs": "English"}
    assert media_film.tv_file_row(None) is None
    assert media_film.tv_file_row({"badges": [], "grid": [], "rows": []}) is None


# ---- web, private front ----

def test_episode_page_has_the_file_chip_and_no_drawer(env, monkeypatch):
    monkeypatch.setitem(EPISODES[2], "MediaSources", [{**SOURCES[0], "Path": "/tv/Quiet.Show.S04E03.1080p-GRP.mkv"}])
    client, _ = env()
    with client:
        b = main_of(whole(client, "/media/item/ep3"))
    hero = b.split("</header>", 1)[0]
    assert '<details class="tl-pop tl-file" id="file"><summary class="btn btn-glass">' in hero
    assert "filepanel" in hero and b.count("filepanel") == 1 and "filedrawer" not in b


@pytest.mark.parametrize("path", ["/media/title/movie/603", "/media/title/tv/100", "/media/item/ep3"])
def test_her_view_has_no_file_chip(env, monkeypatch, path):
    monkeypatch.setitem(ITEMS["mov1"], "MediaSources", [{**SOURCES[0], "Path": "/m/Harbour.Lights.2019-FLUX.mkv"}])
    for e in EPISODES[:3]:
        monkeypatch.setitem(e, "MediaSources", [{**SOURCES[0], "Path": "/tv/Quiet.Show.S04E01.1080p-GRP.mkv"}])
    client, _ = env()
    with client:
        b = main_of(whole(client, f"{path}?owner_view=her"))
    for s in WEB_FILE + TV_FILE + ("Harbour.Lights.2019", "Quiet.Show.S04E01"):
        assert s not in b, (path, s)


# ---- the media front: a friend (web + TV), B. on the web, B. on the TV ----

def media_front(monkeypatch, tmp_path):
    from tests.hub.guest_pages import guest_client
    from tests.hub import test_tv_series_episodes as t
    from tests.hub import test_guest_detail as gd
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": {**gd.LIB, "shows": t.LIB["shows"]}, "arr": gd.ARR})
    src = [{"Container": "mkv", "Size": 21_500_000_000, "Bitrate": 4_700_000,
            "Path": "/x/Library.Film.1999.2160p.WEB-DL-FLUX.mkv", "MediaStreams": [
                {"Type": "Video", "Height": 2160, "Width": 3840, "Codec": "hevc"},
                {"Type": "Audio", "Codec": "eac3", "Channels": 6, "Language": "eng"},
                {"Type": "Subtitle", "Codec": "subrip", "Language": "eng"}]}]
    fake.items[gd.JF] = {"Id": gd.JF, "Type": "Movie", "Name": "Library Film", "ProductionYear": 1999,
                         "ProviderIds": {"Tmdb": "603"}, "RunTimeTicks": 120 * 600_000_000, "MediaSources": src,
                         "MediaStreams": src[0]["MediaStreams"]}
    fake.items[t.SHOW] = {"Id": t.SHOW, "Type": "Series", "Name": "Sample Show", "ProductionYear": 2026,
                          "ProviderIds": {"Tmdb": "100"}}
    eps = [{**e, "MediaSources": [{**src[0], "Path": "/x/Sample.Show.S01E01.2160p-FLUX.mkv"}]} for e in t.EPISODES]
    for e in eps:
        fake.items[e["Id"]] = e
    fake.episodes[t.SHOW] = eps
    return client, fake, [f"/media/item/{gd.JF}", f"/media/item/{t.SHOW}"]


@pytest.mark.parametrize("tv", [False, True])
def test_friend_gets_no_file_chip_or_files_row(monkeypatch, tmp_path, tv):
    from tests.hub.guest_pages import TV_UA, sign_in
    from tests.hub.fake_jellyfin import FRIEND_ID
    client, fake, paths = media_front(monkeypatch, tmp_path)
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        for path in paths:
            html = c.get(path, headers={"User-Agent": TV_UA} if tv else {}).text
            assert "Library Film" in html or "Sample Show" in html, path
            for s in WEB_FILE + TV_FILE + ("20.0 GB", "FLUX", "Library.Film.1999", "Sample.Show.S01E01"):
                assert s not in html, (path, tv, s)


def test_owner_on_the_media_front_web_gets_no_file_chip(monkeypatch, tmp_path):
    from tests.hub.guest_pages import sign_in
    from tests.hub.fake_jellyfin import ALIAS_ID
    client, fake, paths = media_front(monkeypatch, tmp_path)
    with client as c:
        sign_in(c, fake, ALIAS_ID)   # "you" (JELLYFIN_USER_ALIASES), not in TV mode
        for path in paths:
            html = c.get(path).text
            for s in WEB_FILE + TV_FILE + ("20.0 GB", "FLUX"):
                assert s not in html, (path, s)


def test_owner_tv_session_gets_the_files_row_under_scores_without_name_or_release(monkeypatch, tmp_path):
    from tests.hub.guest_pages import TV_UA, sign_in
    from tests.hub.fake_jellyfin import ALIAS_ID
    client, fake, paths = media_front(monkeypatch, tmp_path)
    with client as c:
        sign_in(c, fake, ALIAS_ID)
        for path, size in zip(paths, ("20.0 GB", "80.1 GB")):   # a show: the total of its 4 episode files
            html = c.get(path, headers={"User-Agent": TV_UA}).text
            assert '<section class="sec tv-extras tv-files" aria-label="Files">' in html, path
            row = html.split('class="sec tv-extras tv-files"', 1)[1].split("</section>", 1)[0]
            assert '<div class="fmtbadges">' in row and "<b>4K</b>" in row, path
            words = re.sub(r"<[^>]+>", " ", row)
            assert "Size" in words and size in words and "Sound" in words and "Subtitles" in words, path
            assert "English" in words, path
            for s in ("Library.Film.1999", "Sample.Show.S01E01", "FLUX", "Release", "group ", ".mkv", "Bitrate"):
                assert s not in html, (path, s)
            for s in WEB_FILE:   # the web chip and drawer never reach the TV
                assert s not in html, (path, s)
            if 'aria-label="Scores"' in html:
                assert html.index('aria-label="Scores"') < html.index('aria-label="Files"'), path


def test_tv_css_pins_the_files_row():
    css = Path("hub/static/tv.css").read_text(encoding="utf-8")
    assert "html.tv .tv-files .fmtbadges { display: flex; flex-wrap: wrap; gap: .5rem 1.25rem; margin-top: .5rem; }" in css
    assert "html.tv .tv-files .fmt b { font-size: 1.25rem; }" in css
    assert "html.tv .tv-files .fmt small { font-size: 1.125rem; color: var(--tv-t3); }" in css
    assert "html.tv .tv-files .fmtimg { height: 1.75rem; }" in css
    block = design_px(css.split("/* JY-284:", 1)[1].split("/* JY-286:", 1)[0])
    sizes = [float(x) for x in re.findall(r"font-size:\s*([\d.]+)px", block)]
    assert sizes and min(sizes) >= 18 and ":hover" not in block


def test_web_css_scrolls_a_long_file_popover():
    css = Path("hub/static/control-surface.css").read_text(encoding="utf-8")
    assert "html:not(.tv) .tl-popin.tl-filepop { display: block; width: min(440px, calc(100vw - 32px)); max-height: min(70vh, 560px); overflow-y: auto; padding: 0; }" in css
    assert ".filedrawer" not in css
