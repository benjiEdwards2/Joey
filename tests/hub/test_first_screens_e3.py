"""WP E3 "first screens" (2026-10-13; B. approved 2026-10-13, EVALUATION_2026-10-12 §4.2 / §4.4, review_ui.md U3, U4,
U9 (a), U10, U12, U14, U17, U27): the hub's first screen, Media page heads and phone chrome, the weather page on a phone,
toolbar auto-apply, the Server page order, copy fixes and SHELF_MAX as a Jinja global. Rendered pages where the
behaviour is in the markup; stylesheet pins where it is in the CSS."""
import re
from pathlib import Path

from tests.hub.test_hub_page import SAMPLE_DATA, cards_of, hub, kpis_of  # noqa: F401  (fixture: hub(view=..., **data))

HUB = Path(__file__).resolve().parents[2] / "hub"
TEMPLATES = HUB / "templates"
CSS = (HUB / "static" / "control-surface.css").read_text(encoding="utf-8")


def tpl(name):
    return (TEMPLATES / name).read_text(encoding="utf-8")


def rules(css=CSS):
    """Flattened `selector{body}` text with comments stripped (one space between tokens)."""
    return re.sub(r"\s+", " ", re.sub(r"/\*.*?\*/", "", css, flags=re.S))


def head_of(body):
    return re.search(r'<header class="pagehead">.*?</header>', body, re.S).group(0)


# 1. Hub first screen (U3) -----------------------------------------------------------------------------------------

def test_hub_h1_is_the_greeting_and_the_sub_is_the_date_with_no_feed_count_when_all_live(hub):
    main, body = hub()
    head = head_of(body)
    assert re.search(r"<h1>Good (morning|afternoon|evening)</h1>", head)        # not signed in: no name, no full stop
    sub = re.search(r'<p class="pagehead-sub">(.*?)</p>', head, re.S).group(1)
    now = main.shell._now_home()
    assert sub.startswith(f"{now:%a} {now.day} {now:%b}")                       # "Mon 13 Oct"
    assert "Feeds" not in sub and "." not in sub and "Here" not in sub          # every feed live: no count


def test_hub_sub_lists_feed_problems_only_when_present(hub):
    main, body = hub(drop=("gcal",))                                             # one feed down
    sub = re.search(r'<p class="pagehead-sub">(.*?)</p>', head_of(body), re.S).group(1)
    st = main.shell.build_status(main.shell.get_snapshots())
    assert st["feeds_ok"] < st["feeds_total"]
    assert f" · Feeds {st['feeds_ok']}/{st['feeds_total']} live" in sub


def test_hub_sub_names_a_stale_feed(tmp_path, monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    from tests.hub.helpers import write_envelope
    monkeypatch.delenv("AREAS_PATH", raising=False)
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    for cid, d in SAMPLE_DATA.items():
        write_envelope(snaps, cid, age_minutes=(24 * 60 if cid == "gcal" else 1), data=d)
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as c:
        body = c.get("/").text.split("<main", 1)[1]
    sub = re.search(r'<p class="pagehead-sub">(.*?)</p>', head_of(body), re.S).group(1)
    assert sub.endswith(" · Calendar stale") and "Feeds" not in sub             # stale is still live: no count


def test_calendar_tile_is_marked_dup_and_hidden_on_a_phone(hub):
    """Re-pointed 2026-10-19 (WP-T2): the Weather tile left the hub row, so Calendar is the only .dup card (three cards)."""
    _, body = hub()
    tiles = kpis_of(body)
    assert '<a class="panel tile dup" href="/a/calendar"' in tiles and 'href="/weather"' not in tiles
    classes = re.findall(r'<(?:a|div) class="(panel tile[^"]*)"', tiles)
    assert len(classes) == 3 and sum("dup" in c.split() for c in classes) == 1   # Media and Server stay on a phone
    assert "@media (max-width: 639px) { .tiles > .dup { display: none; } }" in rules()
    assert body.index('class="tiles') < body.index('class="band hubband"')         # the band follows the tiles


def test_calendar_card_value_is_the_title_and_the_day_time_is_meta(hub):
    _, body = hub()
    card = cards_of(body)["/a/calendar"]
    assert '<div class="tile-value stat-word">Bins out</div>' in card
    assert '<div class="row-meta">Next up<span class="sep"> · </span>Today · All day</div>' in card
    assert re.search(r'<svg class="tile-spark".*?</svg>', card, re.S).group(0).count("<rect ") == 7   # bars stay


def test_no_shared_owner_word_on_hub_tiles_or_rows(hub):
    _, body = hub()
    assert "Shared" not in kpis_of(body)
    assert ">Shared<" not in body
    assert "@media (max-width: 639px)" in CSS


def test_hub_comment_no_longer_says_calendar_is_last():
    src = tpl("hub.html")
    assert "the last card (Calendar) last" not in src and "Order: the area cards in hub_rank order" in src


# 2. Media page heads (U4) -----------------------------------------------------------------------------------------

import pytest  # noqa: E402

from tests.hub.helpers import env  # noqa: E402,F401  (fixture: the film-page env, Jellyfin + Jellyseerr faked)
from tests.hub.test_shell import sample_client  # noqa: E402,F401  (fixture: the real registry on the sample snapshots)


def h1s(html):
    return re.findall(r"<h1\b[^>]*>(.*?)</h1>", html.split("<main", 1)[1], re.S)


@pytest.mark.parametrize("route, title", [
    ("/media/movies", "My films"), ("/media/tv", "My shows"), ("/media/movies/watchlist", "My films"),
    ("/media/diary", "History"), ("/media/history", "To rate"), ("/media/requests", "Requests"),
    ("/media/playing", "Live"), ("/media/discover", "Discover"), ("/media/following", "Following"),
    ("/media/movies/awards", "Awards")])
def test_media_page_head_is_the_active_tab_label(sample_client, route, title):
    # nav-tidy (2026-10-13): the Diary is Activity › History, To rate is sentence case, and the Watchlist (no tab of its
    # own) lights My films, so its head reads the lit tab
    with sample_client as c:
        html = c.get(route).text
    assert h1s(html) == [title], route                                            # one H1, and it names the page


def test_media_nav_carries_the_title():
    from types import SimpleNamespace

    from hub import media_nav
    req = lambda path: SimpleNamespace(url=SimpleNamespace(path=path), state=SimpleNamespace())  # noqa: E731
    assert media_nav.nav_context(req("/media/movies"), None, {})["title"] == "My films"
    assert media_nav.nav_context(req("/media/requests"), None, {})["title"] == "Requests"
    assert media_nav.nav_context(req("/media/person/5"), None, {})["title"] == "Discover"    # no tab: the section
    assert media_nav.nav_context(req("/elsewhere"), None, {})["title"] is None


def test_person_page_h1_is_the_name(env):
    from tests.hub.test_media_person import seed
    client, both = env()
    seed(both)
    with client:
        html = client.get("/media/person/55").text
    assert h1s(html) == ["Ada Actor"]
    assert '<h1 class="hero-detail-title">Ada Actor</h1>' in html
    assert '<nav class="sectabs sectabs-page" aria-label="Media sections">' in html  # the band still carries the tabs


def test_awards_page_has_no_second_title():
    assert "awtitle" not in tpl("media_awards.html") and ".awtitle" not in CSS


def test_eyebrow_is_dropped_when_it_repeats_the_title():
    from hub import shell
    render = lambda src: shell.templates.env.from_string('{% from "_pagehead.html" import pagehead %}' + src).render()  # noqa: E731
    assert "eyebrow" not in render('{{ pagehead("Media", eyebrow="Media") }}')
    assert '<span class="eyebrow">Up next</span>' in render('{{ pagehead("Film", eyebrow="Up next") }}')
    bare = render("{{ pagehead(none) }}")
    assert "<h1" not in bare and "pagehead-foot" not in bare


def test_plain_page_head_css():
    flat = rules()
    assert ".pagehead:not(.hero-detail, :has(> .pagehead-bd)) { min-height: 0; }" in flat
    assert ".pagehead:not(.hero-detail, :has(> .pagehead-bd)) h1 { font-size: 24px; font-weight: 600; line-height: 1.25; }" in flat
    assert "min-height: 170px" in flat and ".pagehead h1 { font-size: 48px; line-height: 1.05; }" in flat   # backdrop keeps it


# 2b. Phone: no section pill row in Media, the to-rate count on the bar's Activity icon (nav-tidy, 2026-10-13) -----------------------------------

def test_phone_hides_the_media_section_pills_but_keeps_sub_tabs():
    flat = rules()
    assert "@media (max-width: 767px) { .sectabs:not(.sub) { display: none; } .sectabs + .sectabs.sub { margin-top: 0; } }" in flat
    assert ".tabbar > a { position: relative; }" in flat
    assert ".tabbar > a > .waitcount { position: absolute;" in flat


def test_activity_slot_of_the_phone_bar_carries_the_to_rate_count(tmp_path, monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    from tests.hub.helpers import ARR, JELLY, shelf_area, write_envelope, write_registry
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, shelf_area())))   # test_media_frame's env, by hand
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    for cid, d in (("jellyfin", JELLY), ("arr", ARR)):
        write_envelope(tmp_path / "snaps", cid, age_minutes=1, data=d)
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as c:
        html = c.get("/media/movies").text
    row = re.search(r'<nav class="sectabs sectabs-page" aria-label="Media sections">.*?</nav>', html, re.S).group(0)
    n = re.search(r'href="/media/playing"[^>]*>Activity <span class="waitcount">(\d+)<', row)
    assert n, "the sample needs something to rate"
    bar = re.search(r'<nav class="tabbar"[^>]*>.*?</nav>', html, re.S).group(0)
    slot = re.search(r'<a href="/media/playing"[^>]*>(.*?)</a>', bar, re.S).group(1)
    assert f'<span class="waitcount">{n.group(1)}<span class="vh"> to rate</span></span><span>Activity</span>' in slot
    assert bar.count('class="waitcount"') == 1                                      # only the Activity slot


# 3. The way out of Media on a phone (U9 option a) ---------------------------------------------------------------

def test_media_brand_reads_back_to_joey_and_the_phone_bar_is_sticky(sample_client):
    with sample_client as c:
        media = c.get("/media/movies").text
        hub_page = c.get("/").text
    brand = lambda h: re.search(r'<a class="brand" href="/" aria-label="Joey home">(.*?)</a>', h, re.S).group(1)  # noqa: E731
    assert brand(media).startswith('<span class="brand-back" aria-hidden="true">‹</span><img class="mark"')
    assert "<b>Joey</b>" in brand(media)
    assert "brand-back" not in brand(hub_page)                                      # outside Media: unchanged
    flat = rules()
    assert ".brand-back { display: none; }" in flat
    # nav-tidy (2026-10-13) removed .topswap with the docking, so the Media-mode hook is the brand's .brand-back
    assert ("@media (max-width: 767px) { .topbar:has(.brand-back) { position: sticky; top: 0; } "
            ".topbar:has(.brand-back) .topbar-in { height: 48px; } .brand-back { display: inline;") in flat


# 4. Weather page on a phone (U10 remainder) -----------------------------------------------------------------------

def test_weather_today_strip_fits_a_phone_and_labels_drop_the_place(sample_client):
    with sample_client as c:
        html = c.get("/weather").text
    body = html.split("<main", 1)[1]
    assert '<h2 class="seclabel">Today</h2>' in body and '<h2 class="seclabel">Rain radar</h2>' in body
    place = re.search(r'<p class="pagehead-sub">(.*?)</p>', body).group(1)            # the place stays in the head
    assert place and place not in body.split('<h2 class="seclabel">Today</h2>', 1)[1].split("</section>", 1)[0]
    assert '<div class="stats wxstats">' in body
    flat = rules()
    assert ".wxstats .stat-number, .wxstats .stat-word { white-space: nowrap; }" in flat
    assert "@media (max-width: 639px) { .wxstats { grid-template-columns: repeat(2, minmax(0, 1fr)); } }" in flat


# 5. Toolbars apply themselves (U14) -------------------------------------------------------------------------------

AUTO = ('hx-target="body" hx-swap="innerHTML show:none" hx-push-url="true"')


def test_library_toolbar_applies_on_change_and_apply_is_noscript_only(sample_client):
    with sample_client as c:
        for path in ("/media/movies", "/media/tv"):
            html = c.get(path).text
            form = re.search(r'<form class="toolbar"([^>]*)>(.*?)</form>', html, re.S)
            attrs, inner = form.group(1), form.group(2)
            assert f'hx-get="{path}" {AUTO}' in attrs, path
            assert 'hx-trigger="submit, change, search, keyup changed delay:400ms from:find input[type=search]"' in attrs
            assert '<input class="input" id="libq" type="search" name="q"' in inner          # focus survives the swap
            assert '<noscript><button type="submit" class="btn btn-secondary">Apply</button></noscript>' in inner
            assert inner.count("<a ") == 1 and 'aria-label="Show as list"' in inner         # one icon toggle
            assert 'name="view"' not in inner                                              # the cookie keeps the choice


def test_watchlist_sort_applies_on_change(sample_client):
    with sample_client as c:
        html = c.get("/media/movies/watchlist").text
    src = tpl("media_watchlist.html")
    assert f'hx-get="{{{{ request.url.path }}}}" {AUTO}' in src and 'hx-trigger="submit, change"' in src
    assert '<noscript><button type="submit" class="btn btn-secondary">Apply</button></noscript>' in src
    if '<form class="toolbar"' in html:                                                    # rows present
        assert 'hx-get="/media/movies/watchlist"' in html


def test_libview_cookie_route_still_sets_the_choice(sample_client):
    with sample_client as c:
        r = c.get("/media/movies?view=list")
        assert "media_libview=list" in r.headers.get("set-cookie", "")
        again = c.get("/media/movies?sort=title").text                                    # what the toolbar sends
    assert "listbox libposters" in again and 'aria-label="Show as grid"' in again


# 6. Server page (U12) ----------------------------------------------------------------------------------------------

from tests.hub.test_server import env as server_env  # noqa: E402,F401  (the Server page env; fixture named `env` there)


def server_page(tmp_path, monkeypatch, lan, headers=None):
    """The real registry on the sample snapshots, /server asked from a LAN or an outside address."""
    import importlib
    import json

    from fastapi.testclient import TestClient

    from tests.hub.helpers import write_envelope
    from tests.hub.test_server import SAMPLES
    monkeypatch.delenv("AREAS_PATH", raising=False)
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    for p in SAMPLES.glob("*.json"):
        if not p.stem.startswith("_"):
            write_envelope(snaps, p.stem, age_minutes=1, data=json.loads(p.read_text(encoding="utf-8"))["data"])
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app, client=("192.168.68.20" if lan else "203.0.113.9", 50000)) as c:
        return c.get("/server", headers=headers or {}).text.split("<main", 1)[1]


def test_attention_leads_the_server_page(tmp_path, monkeypatch):
    body = server_page(tmp_path, monkeypatch, lan=True)
    assert "Prowlarr is Down (timeout)" in body
    assert body.index("</header>") < body.index('id="attention"') < body.index('id="system"')
    # WP-T3 (2026-10-19, S3): the tile row (was hidden on phones, .srvtiles) is gone from the Server page altogether
    assert "srvtiles" not in body and "srvtiles" not in rules()


def test_update_now_is_secondary_and_update_all_the_one_primary(tmp_path, monkeypatch):
    body = server_page(tmp_path, monkeypatch, lan=True)
    assert body.count("btn-primary") == 1 and ">Update all</a>" in body
    assert 'class="btn btn-secondary btn-sm" href="/server/updates/vaultwarden/run?step=confirm">Update now' in body


def test_lan_only_links_show_on_the_lan_only(tmp_path, monkeypatch):
    """2026-10-19 (WP-H1, B.): the Services CARDS now show from anywhere and link to their LAN address with the "LAN"
    word — this reverses E3's off-LAN hiding (back to the 2026-10-10 rule). WP-T3 (2026-10-19, S3): the tile row is
    gone, so the LAN-only Portainer TILE is too; Portainer is its Services › System card, shown like every card."""
    on = server_page(tmp_path, monkeypatch, lan=True)
    off = server_page(tmp_path, monkeypatch, lan=False)
    tunnel = server_page(tmp_path, monkeypatch, lan=True, headers={"Cf-Access-Authenticated-User-Email": "a@b.c"})
    assert "svc-sub\">Media server · LAN<" in on
    for page in (on, off, tunnel):                               # outside, or through the tunnel from a LAN-ish hop
        assert '<div class="microlabel">Portainer</div>' not in page      # no tile row, no Portainer tile
        portainer = re.search(r'<a class="svc-card[^"]*" href="[^"]+"[^>]*>(?:(?!</a>).)*>Portainer<(?:(?!</a>).)*</a>',
                              page, re.S)
        assert portainer and "Docker management · LAN<" in portainer.group(0)   # a link card saying "LAN"
    for page in (off, tunnel):
        assert page.count('class="svc-card') == on.count('class="svc-card')     # every card shows
        assert "svc-sub\">Media server · LAN<" in page                    # ... with its LAN word
        lan_cards = re.findall(r'<a class="svc-card[^>]*href="[^"]+"[^>]*>(?:(?!</a>).)*· LAN<', page, re.S)
        assert lan_cards                                                  # ... as a link to the LAN address
    assert "192.168." not in tpl("server.html") and "10." not in re.sub(r"\d+\.\d+\.\d+", "", tpl("server.html"))


def test_from_lan_helper():
    from types import SimpleNamespace

    from hub import shell
    req = lambda host, hdr=None: SimpleNamespace(client=SimpleNamespace(host=host) if host else None,  # noqa: E731
                                                 headers=hdr or {})
    assert shell.from_lan(req("192.168.68.20")) and shell.from_lan(req("10.0.0.4")) and shell.from_lan(req("172.20.0.3"))
    assert shell.from_lan(req("127.0.0.1"))
    assert not shell.from_lan(req("203.0.113.9")) and not shell.from_lan(req("1.1.1.1"))
    assert not shell.from_lan(req("testclient")) and not shell.from_lan(req(None))
    assert shell.from_lan(req("fd12::1")) and not shell.from_lan(req("2606:4700::1111"))
    assert not shell.from_lan(req("172.20.0.3", {"Cf-Access-Authenticated-User-Email": "a@b.c"}))   # via the tunnel
    assert not shell.from_lan(None)
    assert shell.templates.env.globals["from_lan"] is shell.from_lan


# 7. Copy (U27 new items) -------------------------------------------------------------------------------------------

def test_duration_global_and_the_sweep_line():
    from hub import shell
    d = shell.templates.env.globals["duration"]
    assert (d(167), d(4), d(120)) == ("2h 47m", "4m", "2h")
    src = tpl("_arr_sweep.html")
    assert 'Started {{ duration(s.since) ~ " ago" if s.since >= 1 else "just now" }} · run again?' in src
    assert "min ago" not in src


def test_uptime_reads_the_guide_way():
    from hub import server
    assert [server.uptime_text(s) for s in (1052400, 7500, 2400)] == ["12d 4h", "2h 5m", "40m"]


def test_words_start_with_a_capital_and_say_and_not_plus():
    assert '"Rewatch" if row.rewatch' in tpl("_diary_row.html") and "↻ rewatch" not in tpl("_diary_row.html")
    srv = tpl("server.html")
    assert '"Last OK " ~ w.last_ok_text' in srv and "last ok" not in srv
    assert ">Update and restart media stack</a>" in srv and "Restart + update" not in srv
    assert "Restart + update" not in tpl("server_stack.html")


def test_rated_line_says_the_number_once():
    src = tpl("_rate.html")
    assert '<span class="microlabel">Rated</span>' in src and "Rated {{ score }} out of 10</span><button" not in src
    assert '<span class="microlabel">Rated {{ score }} out of 10</span>' not in src


def test_to_rate_label_matches_the_tab_and_the_guide_records_it():
    assert '<h2 class="seclabel">To rate</h2>' in tpl("media_history.html")          # nav-tidy (2026-10-13): sentence case
    guide = (HUB.parent / "docs" / "style-guide.md").read_text(encoding="utf-8").split("# MediaHub style guide", 1)[0]
    flat = " ".join(guide.split())
    assert ('nav-tidy (B., 2026-10-13) superseded it: every section and tab label is sentence case again ("To rate", '
            '"TV shows"), including the section label under that tab.') in flat           # the dated supersession line


def test_requests_counts_leave_out_zero_parts():
    from hub import shell
    src = tpl("media_requests.html")
    block = src[src.index("{% set nz"):src.index("{% endif %}", src.index("{% set nz")) + len("{% endif %}")]
    render = lambda t: shell.templates.env.from_string(block).render(counts_text=t).strip()  # noqa: E731
    assert render("0 pending · 2 approved · 1 available · 0 declined") == '<p class="metaline">2 approved · 1 available</p>'
    assert render("10 pending · 0 approved") == '<p class="metaline">10 pending</p>'
    assert render("0 pending · 0 approved · 0 available · 0 declined") == ""


# 8. SHELF_MAX as a Jinja global (U17) ----------------------------------------------------------------------------

def test_full_hub_shelf_prints_no_count_and_a_short_one_does(hub):
    from hub.media_home import SHELF_MAX
    full = [{"title": f"Film {i}", "kind": "movie", "watched_at": "2026-10-01T10:00:00Z", "when": "today",
             "item_key": f"tmdb:{i}"} for i in range(SHELF_MAX + 3)]
    jf = {**SAMPLE_DATA["jellyfin"], "history": {**SAMPLE_DATA["jellyfin"]["history"], "recent": full}}
    _, body = hub(jellyfin=jf)
    head = re.search(r'<section class="sec" id="recent">.*?</h2>', body, re.S).group(0)
    assert re.search(r">Recently watched</h2>", head)                                   # 15 of more: no count
    _, body = hub(jellyfin={**jf, "history": {**jf["history"], "recent": full[:3]}})
    head = re.search(r'<section class="sec" id="recent">.*?</h2>', body, re.S).group(0)
    n = re.search(r'Recently watched<span class="sep"> · </span>(\d+)</h2>', head)   # her rows join in the both view
    assert n and 3 <= int(n.group(1)) < SHELF_MAX


def test_calendar_card_looks_past_the_week_for_the_next_event(hub):
    from datetime import datetime, timedelta
    day = datetime.now().astimezone().date() + timedelta(days=20)
    far = [{"title": "Dentist", "start": f"{day.isoformat()}T09:30:00+11:00", "end": f"{day.isoformat()}T10:00:00+11:00",
            "all_day": False, "owner": "you"}]
    _, body = hub(gcal={**SAMPLE_DATA["gcal"], "summary": "Dentist · long form", "events": far})
    card = cards_of(body)["/a/calendar"]
    assert '<div class="tile-value stat-word">Dentist</div>' in card and "long form" not in card
    assert re.search(r'<div class="row-meta">Next up<span class="sep"> · </span>\w{3} \d{1,2} \w{3} · \d\d:\d\d<', card)
    assert "Nothing in the next 7 days" in body                                          # the band keeps its week
