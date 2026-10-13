"""Awards ballot templates (WP-C2, 2026-10-14). The page is the films ballot: a sticky control row (picker sheet, edition
line, Films / Categories), the Next up fold, the progress ring, one chip row (filters | sorts) and one row per nominated
film; the category cards are the second view. These tests render `_award_body.html`, `_award_sheet.html`,
`_award_rows_part.html` and the `content` block of `media_awards.html` through the app's own Jinja environment with a
hand-built context. `BASE` below IS the contract (review/2026-10-13-awards-ux/BALLOT_CONTRACT.md section 2): the Python
side (media_awards_pages.awards_ctx) must produce exactly this shape, and these templates must read nothing else."""
import copy
import re


from hub import shell

ENV = shell.templates.env

BADGE = {"body_id": "oscars", "logo": None, "more": 0, "label": "Won Best Picture · Oscars 2025"}


def work(n, title, **kw):
    """One ballot row (contract `row`)."""
    base = {"title": title, "year": 2024, "href": f"/media/title/movie/{n}", "poster": None, "award": None,
            "seen": False, "on_server": False, "watchlisted": False,
            "w": {"tmdb_id": n, "kind": "movie", "title": title, "year": 2024, "poster": None},
            "wins": 0, "noms": 1, "won_any": False, "pills": [], "more": 0, "cats": [], "tally": "1 nomination"}
    base.update(kw)
    return base


ANORA = work(
    11, "Anora", award=BADGE, on_server=True, wins=3, noms=7, won_any=True, tally="3 wins · 7 nominations", more=2,
    pills=[{"name": "Picture", "won": True, "who": None}, {"name": "Director", "won": True, "who": "Sean Baker"},
           {"name": "Actress", "won": True, "who": "Mikey Madison"}, {"name": "Supp. Actor", "won": False, "who": "Yura Borisov"},
           {"name": "Editing", "won": False, "who": None}],
    cats=[{"name": "Best Picture", "won": True, "who": None, "lead": "film"},
          {"name": "Best Director", "won": True, "who": "Sean Baker", "lead": "person"},
          {"name": "Best Actress", "won": True, "who": "Mikey Madison", "lead": "person"},
          {"name": "Best Supporting Actor", "won": False, "who": "Yura Borisov", "lead": "person"},
          {"name": "Best Film Editing", "won": False, "who": "Sean Baker", "lead": "film"},
          {"name": "Best Original Screenplay", "won": False, "who": None, "lead": "film"},
          {"name": "Best Sound", "won": False, "who": None, "lead": "film"}])
BRUTALIST = work(12, "The Brutalist", seen=True, on_server=True, wins=1, noms=3, won_any=True, tally="1 win · 3 nominations",
                 pills=[{"name": "Actor", "won": True, "who": "Adrien Brody"}, {"name": "Picture", "won": False, "who": None}],
                 cats=[{"name": "Best Actor", "won": True, "who": "Adrien Brody", "lead": "person"},
                       {"name": "Best Picture", "won": False, "who": None, "lead": "film"}])
CONCLAVE = work(13, "Conclave", watchlisted=True, tally="1 nomination", noms=1,
                pills=[{"name": "Picture", "won": False, "who": None}],
                cats=[{"name": "Best Picture", "won": False, "who": None, "lead": "film"}])
NICKEL = work(14, "Nickel Boys", w=None, href=None, year=None, pills=[{"name": "Picture", "won": False, "who": None}],
              cats=[{"name": "Best Picture", "won": False, "who": None, "lead": "film"}])
SHORT = work(15, "Anuja", seen=False, tally="1 win · 1 nomination", wins=1, noms=1, won_any=True,
             pills=[{"name": "Live Action Short", "won": True, "who": None}],
             cats=[{"name": "Best Live Action Short Film", "won": True, "who": None, "lead": "film"}])

BASE = {
    "kind": "movie", "akind": "film", "base": "/media/movies/awards", "body": "oscars", "year": 2025, "unseen": False,
    "view": "films",
    "view_hrefs": {"films": "/media/movies/awards?body=oscars&year=2025",
                   "categories": "/media/movies/awards?body=oscars&year=2025&v=categories"},
    "bodies": [{"id": "oscars", "name": "Oscars", "on": True, "href": "/media/movies/awards?body=oscars&year=2025", "logo": None,
                "month": "Mar"},
               {"id": "bafta", "name": "BAFTA", "on": False, "href": "/media/movies/awards?body=bafta&year=2025", "logo": None,
                "month": "Feb"},
               {"id": "critics", "name": "Critics Choice", "on": False,
                "href": "/media/movies/awards?body=critics&year=2025", "logo": None, "month": "Jan"}],
    "years": [2026, 2025, 2024, 2023],
    "years_list": [{"year": 2026, "href": "/media/movies/awards?body=oscars&year=2026", "on": False, "has_data": True},
                   {"year": 2025, "href": "/media/movies/awards?body=oscars&year=2025", "on": True, "has_data": True},
                   {"year": 2024, "href": "/media/movies/awards?body=oscars&year=2024", "on": False, "has_data": True},
                   {"year": 2023, "href": "/media/movies/awards?body=oscars&year=2023", "on": False, "has_data": False}],
    "picker": {"name": "Oscars", "body_id": "oscars", "logo": None, "year": 2025},
    "year_note": None, "current": {"year": 2026, "href": "/media/movies/awards?body=oscars"},
    "body_name": "Oscars", "edition_line": "97th Academy Awards · 2 Mar 2025",
    "prev": {"year": 2024, "href": "/media/movies/awards?body=oscars&year=2024"},
    "next": {"year": 2026, "href": "/media/movies/awards?body=oscars&year=2026"},
    "unseen_href": "/media/movies/awards?body=oscars&year=2025&f=unseen", "empty": None,
    "sync": {"text": "Last updated 3 Oct 2026", "failed": False},
    "coming": [{"month": "Jan 2026", "events": [{"body_id": "globes", "name": "Golden Globes", "logo": None, "date": "11 Jan",
                                                 "next": True},
                                                {"body_id": "critics", "name": "Critics Choice", "logo": None, "date": None,
                                                 "next": False}]}],
    "next_up": {"body_id": "globes", "name": "Golden Globes", "logo": None, "date": "Sun 11 Jan 2026", "days": 90},
    "cats": [], "more": [], "rest": 0, "part_href": "", "all_href": "", "cats_rest": [], "more_all": [],
    "ballot": {
        "progress": {"pct": 25, "seen": 1, "total": 4, "headline": {"name": "Picture", "seen": 1, "total": 2},
                     "server_unseen": 1, "watchlisted": 1},
        "filters": [{"key": "all", "label": "All", "on": True, "href": "/f/all"},
                    {"key": "headline", "label": "Picture", "on": False, "href": "/f/headline"},
                    {"key": "acting", "label": "Acting", "on": False, "href": "/f/acting"},
                    {"key": "direction", "label": "Direction", "on": False, "href": "/f/direction"},
                    {"key": "craft", "label": "Craft", "on": False, "href": "/f/craft"},
                    {"key": "unseen", "label": "Not seen", "on": False, "href": "/f/unseen"},
                    {"key": "server", "label": "On your server", "on": False, "href": "/f/server"}],
        "sorts": [{"key": "wins", "label": "Most wins", "on": True, "href": "/s/wins"},
                  {"key": "noms", "label": "Most nominations", "on": False, "href": "/s/noms"},
                  {"key": "az", "label": "A to Z", "on": False, "href": "/s/az"}],
        "hidden_seen": None, "rows": [ANORA, BRUTALIST, CONCLAVE, NICKEL], "rest": 5,
        "part_rows_href": "/media/movies/awards/part/rows?body=oscars&year=2025", "shorts": [SHORT],
        "people": [{"name": "Mikey Madison", "cat": "Actress", "poster": "tmdb:/m.jpg", "href": "/media/person/1"},
                   {"name": "Sean Baker", "cat": "Director", "poster": None, "href": None}],
        "empty": None},
}


def ctx(**over):
    c = copy.deepcopy(BASE)
    for k, v in over.items():
        if k.startswith("ballot_"):
            c["ballot"][k[7:]] = v
        else:
            c[k] = v
    return c


def render(name, c):
    return ENV.get_template(name).render(**c)


def body(**over):
    return render("_award_body.html", ctx(**over))


def page(**over):
    t = ENV.get_template("media_awards.html")
    return "".join(t.blocks["content"](t.new_context(ctx(**over))))


def rows_of(html):
    """The .awfilm articles of a rendering, in order."""
    return re.findall(r'<article class="awfilm.*?</article>', html, re.S)


def row(title, html):
    return next(r for r in rows_of(html) if f">{title}</a>" in r or f">{title}</span>" in r)


# ---- the films view ----
def test_progress_head_is_a_ring_with_the_numbers_in_words():
    b = body()
    head = re.search(r'<div class="awprog">.*?</div>\s*</div>\s*</div>', b, re.S).group(0)
    ring = re.search(r'<svg class="awring"[^>]*aria-hidden="true"[^>]*>.*?</svg>', head, re.S).group(0)
    assert '<circle class="val" cx="36" cy="36" r="32" pathLength="100" stroke-dasharray="25 100"/>' in ring
    assert "<text x=\"36\" y=\"41\">25%</text>" in ring                       # the percentage as text inside
    assert "Seen 1 of 4 nominated films" in head                              # the words carry the numbers
    assert "<b>Picture:</b> 1 of 2 seen" in head
    assert "<b>1</b> on your server and unseen" in head and "<b>1</b> on your watchlist" in head
    assert "nominated shows" in body(kind="tv")                              # TV: shows, same code path
    zero = body(ballot_progress={**BASE["ballot"]["progress"], "pct": 0, "seen": 0})
    assert 'class="val"' not in zero and "0%" in zero                         # no round-cap dot at 0 %
    assert 'class="awprog"' not in body(ballot_progress=None)


def test_filter_chips_then_a_divider_then_sort_chips_in_one_row():
    b = body()
    row_ = re.search(r'<div class="chips awfilters" role="group" aria-label="Filter and sort">(.*?)</div>', b, re.S).group(1)
    chips = re.findall(r'<a class="chip( on)?" href="([^"]+)" aria-pressed="(true|false)">([^<]+)</a>', row_)
    assert [c[3] for c in chips] == ["All", "Picture", "Acting", "Direction", "Craft", "Not seen", "On your server",
                                     "Most wins", "Most nominations", "A to Z"]
    assert [(c[3], c[0] == " on", c[2]) for c in chips if c[0]] == [("All", True, "true"), ("Most wins", True, "true")]
    assert all(c[2] == "false" for c in chips if not c[0])                   # aria-pressed on every toggle
    assert chips[0][1] == "/f/all" and chips[-1][1] == "/s/az"                # hrefs come from the context, never built here
    assert row_.index("On your server") < row_.index('<span class="awdiv" aria-hidden="true">') < row_.index("Most wins")
    assert '<span class="vh">Sort by</span>' in row_
    on = body(ballot_filters=[{**f, "on": f["key"] == "unseen"} for f in BASE["ballot"]["filters"]])
    assert '<a class="chip on" href="/f/unseen" aria-pressed="true">Not seen</a>' in on


def test_hiding_line_only_when_the_filter_hides_seen_works():
    assert "Hiding" not in body()
    assert '<p class="metaline awhiding">Hiding 9 seen</p>' in body(ballot_hidden_seen=9)


def test_a_row_has_poster_title_tally_pills_and_a_details_fold():
    r = row("Anora", body())
    assert re.search(r'class="card-pic awframe awfilm-pic is-won" href="/media/title/movie/11" tabindex="-1" aria-hidden="true">'
                     r'<img class="poster "', r)                              # gold frame: it won something
    assert 'class="awbadge" role="img" aria-label="Won Best Picture · Oscars 2025"' in r      # the existing winner badge
    assert '<a class="awfilm-title" href="/media/title/movie/11">Anora</a><span class="awfilm-year">2024</span>' in r
    assert '3 wins · 7 nominations<span class="sep"> · </span><span class="awfilm-srv">On your server</span>' in r
    assert r.startswith('<article class="awfilm is-won"')
    names = re.findall(r'<span class="awchip( is-won)?">(?:<svg[^>]*>.*?</svg>)?<span class="vh">(Won|Nominated): </span>([^<]+)</span>',
                       r, re.S)
    assert [(n[1], n[2]) for n in names] == [("Won", "Picture"), ("Won", "Director · Sean Baker"),
                                             ("Won", "Actress · Mikey Madison"), ("Nominated", "Supp. Actor · Yura Borisov"),
                                             ("Nominated", "Editing")]
    assert [bool(n[0]) for n in names] == [True, True, True, False, False]   # won first, gold; nominated neutral
    assert r.count('class="awchip is-won"><svg class="awic awic-laurel"') == 3  # a shape too, not only gold
    assert '<span class="awchip awmore">+2<span class="vh"> more categories</span></span>' in r
    assert len(re.findall(r'<span class="awchip', r)) == 6                    # <= 5 pills + the +N chip


def test_details_fold_lists_every_category_with_a_word_and_the_people():
    r = row("Anora", body())
    fold = re.search(r'<details class="showmore awdetail"><summary>Details</summary>(.*?)</details>', r, re.S).group(1)
    got = re.findall(r'<span class="awdetail-k( is-won)?">(Won|Nominated)</span><span class="awdetail-v"><b>([^<]+)</b>(?: · ([^<]+))?</span>', fold)
    assert [(g[1], g[2], g[3]) for g in got] == [
        ("Won", "Best Picture", ""), ("Won", "Best Director", "Sean Baker"), ("Won", "Best Actress", "Mikey Madison"),
        ("Nominated", "Best Supporting Actor", "Yura Borisov"), ("Nominated", "Best Film Editing", "Sean Baker"),
        ("Nominated", "Best Original Screenplay", ""), ("Nominated", "Best Sound", "")]   # all 7, not only the 5 pills
    assert [bool(g[0]) for g in got][:3] == [True, True, True] and not any(g[0] for g in got[3:])
    assert "awdetail" not in row("Conclave", body(ballot_rows=[{**CONCLAVE, "cats": []}]))     # nothing to list: no fold


def test_on_your_server_words_only_while_unseen():
    b = body()
    assert "On your server</span>" in row("Anora", b)
    assert "On your server" not in row("The Brutalist", b).split('class="awfilm-act"')[0]   # seen: the tick replaces it
    assert "On your server" not in row("Conclave", b)                          # not on the server: no line


def test_action_column_seen_tick_or_watchlist_button():
    b = body()
    seen = row("The Brutalist", b)
    assert '<span class="awfilm-seen st-good">Seen ✓</span>' in seen
    assert "wlbtn" not in seen and '<span class="poster-tag is-seen">Seen ✓</span>' in seen
    anora = row("Anora", b)
    act = re.search(r'<div class="awfilm-act" hx-push-url="false">(.*?)</div>\s*<details', anora, re.S).group(1)
    assert '<span id="wl-movie-11" class="wlbtn compact">' in act              # _watchlist_btn.html, compact, off the list
    assert 'hx-post="/media/watchlist/add"' in act and 'name="tmdb_id" value="11"' in act
    assert 'class="btn-mini"' in act and "Seen" not in act
    conclave = row("Conclave", b)
    assert '<span class="awfilm-wl">✓ Watchlisted</span>' in conclave           # on the list: the compact button hides, so words
    assert 'id="wl-movie-13"' in conclave and "btn-mini" not in conclave
    nickel = row("Nickel Boys", b)                                             # no TMDB id: no button, plain title, no links
    assert "wlbtn" not in nickel and 'href=' not in nickel
    assert '<span class="card-pic awframe awfilm-pic">' in nickel and '<span class="awfilm-title">Nickel Boys</span>' in nickel
    assert "awfilm-year" not in nickel


def test_rows_leave_the_awmain_swap_for_other_pages_and_the_watchlist_post_does_not_push():
    r = row("Anora", body())
    assert r.startswith('<article class="awfilm is-won" hx-target="body" hx-select="unset" hx-swap="innerHTML show:window:top">')
    assert '<div class="awfilm-act" hx-push-url="false">' in r                  # the action posts, it never pushes a URL


def test_sentinel_loads_the_rest_of_the_rows_in_one_request():
    b = body()
    m = re.search(r'<div class="awrest" hx-get="([^"]+)" hx-trigger="revealed" hx-target="this" hx-select="unset" '
                  r'hx-swap="outerHTML" hx-push-url="false" hx-indicator="this">(.*?)</div>', b)
    assert m and m.group(1) == "/media/movies/awards/part/rows?body=oscars&amp;year=2025"
    assert "Show 5 more" in m.group(2) and 'hx-boost="false"' in m.group(2)
    assert b.index("awfilms-list") < b.index('class="awrest"') < b.index("Shorts ·")   # after the rows, before the folds
    assert "awrest" not in body(ballot_rest=0)


def test_shorts_fold_people_strip_and_empty_line():
    b = body()
    fold = re.search(r'<details class="showmore awshorts"><summary>Shorts · 1</summary>(.*?)</details>', b, re.S).group(1)
    assert ">Anuja</a>" in fold and 'class="awfilm is-won"' in fold
    assert ">Anuja<" not in b.split("Shorts · 1")[0]                           # shorts are not in the main list
    assert "Shorts" not in body(ballot_shorts=[])
    strip = re.search(r'<div class="awpeople"[^>]*>(.*?)</section>', b, re.S).group(1)
    assert '<h2 class="seclabel">Winners · people</h2>' in strip
    assert re.search(r'<a class="awperson" href="/media/person/1">\s*<span class="awframe is-won awperson-pic"><img class="poster " '
                     r'src="/img/tmdb:/m.jpg\?h=120', strip)
    assert '<span class="awperson-name">Mikey Madison</span>' in strip and '<span class="awperson-cat">Director</span>' in strip
    assert '<div class="awperson">' in strip                                    # no page: a plain block, not a dead link
    assert "awpeople" not in body(ballot_people=[])
    e = body(ballot_rows=[], ballot_rest=0, ballot_shorts=[], ballot_people=[], ballot_empty="Everything here is seen.")
    assert '<p class="empty">Everything here is seen.</p>' in e and "awfilm" not in e.replace("awfilms", "")
    assert '<p class="empty">Nothing matches that filter.</p>' in body(ballot_rows=[], ballot_empty="Nothing matches that filter.")


def test_rows_part_is_bare_rows_only():
    out = render("_award_rows_part.html", {"rows": [BRUTALIST, CONCLAVE], "kind": "movie"})
    assert [re.search(r'class="awfilm-title"[^>]*>([^<]+)<', r).group(1) for r in rows_of(out)] == ["The Brutalist", "Conclave"]
    assert "<html" not in out and "awrest" not in out and "awctl" not in out


# ---- the page: control row, note, Next up ----
def test_page_wraps_everything_in_one_awmain_that_boosts_into_itself():
    p = page()
    assert '<div id="awmain" class="awmain" hx-boost="true" hx-target="#awmain" hx-select="#awmain" ' \
           'hx-swap="outerHTML show:none" hx-push-url="true">' in p
    inner = p.split('<div id="awmain"', 1)[1]
    assert p.index('class="sec awhead"') < p.index('id="awmain"')              # the staleness line stays outside the swap
    for part in ('class="awctl"', "awnextup", 'class="sec awfilms"'):
        assert part in inner
    assert "Last updated 3 Oct 2026" in p.split('id="awmain"')[0]


def test_control_row_is_picker_then_edition_then_films_categories():
    p = page()
    row_ = re.search(r'<div class="awctl">(.*?)\n</div>', p, re.S).group(1)
    assert row_.index('<details class="awpick">') < row_.index('<span class="metaline awed">97th Academy Awards · 2 Mar 2025</span>') \
        < row_.index('<nav class="seg awview" aria-label="View">')
    seg = re.search(r'<nav class="seg awview" aria-label="View">(.*?)</nav>', row_, re.S).group(1)
    assert '<a href="/media/movies/awards?body=oscars&amp;year=2025" aria-current="page">Films</a>' in seg
    assert '<a href="/media/movies/awards?body=oscars&amp;year=2025&amp;v=categories">Categories</a>' in seg
    cat = page(view="categories")
    assert 'v=categories" aria-current="page">Categories</a>' in cat and ">Films</a>" in cat and 'aria-current="page">Films' not in cat


def test_year_note_sits_under_the_control_row():
    assert "awyearnote" not in page()
    p = page(year_note="No BAFTA in 2026 · showing 2025")
    assert '<p class="metaline awyearnote">No BAFTA in 2026 · showing 2025</p>' in p
    assert p.index('class="awctl"') < p.index("awyearnote") < p.index("awnextup")


def test_next_up_line_with_all_dates_fold_holding_the_coming_grid():
    p = page()
    d = re.search(r'<details class="awnextup">(.*?)</details>', p, re.S).group(1)
    summary = re.search(r"<summary>(.*?)</summary>", d, re.S).group(1)
    assert re.search(r'<b>Next up:</b> Golden Globes · <span class="aw-date">Sun 11 Jan 2026</span> · in 90 days', summary)
    assert '<span class="awnextup-all">All dates</span>' in summary
    grid = d.split("</summary>", 1)[1]                                          # today's Coming up grid, folded
    assert '<div class="stats awcoming">' in grid and "Jan 2026" in grid and 'class="awev is-next"' in grid
    assert '<span class="awnext">Next</span>' in grid and "Critics Choice" in grid
    for days, words in ((0, "today"), (1, "tomorrow")):
        assert f" · {words}</span>" in page(next_up={**BASE["next_up"], "days": days})
    undated = page(next_up={**BASE["next_up"], "date": None, "days": None})
    assert "Next up:</b> Golden Globes</span>" in undated
    only_grid = page(next_up=None)
    assert "<b>Coming up</b>" in only_grid and "Next up:" not in only_grid
    assert "awnextup" not in page(next_up=None, coming=[])


# ---- the picker sheet ----
def test_picker_button_shows_the_ceremony_and_year():
    s = render("_award_sheet.html", ctx())
    btn = re.search(r'<summary class="awpick-btn" aria-label="Choose ceremony and year: Oscars 2025">(.*?)</summary>', s, re.S).group(1)
    assert 'class="awic awic-oscars"' in btn and 'aria-hidden="true"' in btn
    assert '<span class="awpick-name">Oscars</span> <span class="awpick-year">2025</span>' in btn and "awchev" in btn
    assert s.startswith("\n") or s.lstrip().startswith('<details class="awpick">')


def test_sheet_ceremony_tiles_keep_the_marks_months_and_the_picked_one_current():
    s = render("_award_sheet.html", ctx())
    grid = re.search(r'<nav class="awtilegrid" aria-label="Ceremonies">(.*?)</nav>', s, re.S).group(1)
    tiles = re.findall(r'<a class="(awtile[^"]*)" href="([^"]+)"( aria-current="page")?><svg class="awic awic-(\w+)"[^>]*'
                       r'aria-hidden="true"[^>]*>.*?</svg><span class="awtile-name">([^<]+)</span>'
                       r'<span class="awtile-month">(\w+)</span></a>', grid, re.S)
    assert [(t[3], t[4], t[5]) for t in tiles] == [("oscars", "Oscars", "Mar"), ("bafta", "BAFTA", "Feb"),
                                                   ("critics", "Critics Choice", "Jan")]
    assert [(t[0], bool(t[2])) for t in tiles] == [("awtile on", True), ("awtile", False), ("awtile", False)]
    assert tiles[1][1] == "/media/movies/awards?body=bafta&amp;year=2025"       # the server's links, year kept


def test_sheet_year_strip_prev_years_next_latest():
    s = render("_award_sheet.html", ctx())
    strip = re.search(r'<nav class="awyears" aria-label="Ceremony year">(.*?)</nav>', s, re.S).group(1)
    items = re.findall(r'<(a|span) class="(chip[^"]*)"([^>]*)>([^<]+)</(?:a|span)>', strip)
    assert [i[3] for i in items] == ["‹ 2024", "2026", "2025", "2024", "2023", "2026 ›", "Latest"]
    by = {i[3]: i for i in items}
    assert 'aria-label="Previous ceremony, 2024"' in by["‹ 2024"][2] and 'aria-label="Next ceremony, 2026"' in by["2026 ›"][2]
    assert 'aria-current="true"' in by["2025"][2] and by["2025"][1] == "chip on"
    assert all("aria-current" not in i[2] for i in items if i[3] != "2025")   # only the picked year
    assert by["2023"][0] == "span" and 'aria-disabled="true"' in by["2023"][2] and "href" not in by["2023"][2]   # no data
    assert by["2024"][0] == "a" and 'href="/media/movies/awards?body=oscars&amp;year=2024"' in by["2024"][2]
    assert 'aria-label="Latest year, 2026"' in by["Latest"][2] and "awcur" in by["Latest"][1]
    bare = render("_award_sheet.html", ctx(prev=None, next=None, current=None))
    assert "‹" not in bare and "›" not in bare and "Latest" not in bare


def test_scrim_and_done_close_the_sheet_by_re_rendering_the_current_view():
    for view, href in (("films", "/media/movies/awards?body=oscars&amp;year=2025"),
                       ("categories", "/media/movies/awards?body=oscars&amp;year=2025&amp;v=categories")):
        s = render("_award_sheet.html", ctx(view=view))
        assert f'<a class="awscrim" href="{href}" hx-push-url="false" aria-label="Close"></a>' in s
        assert f'<a class="btn btn-glass btn-sm" href="{href}" hx-push-url="false">Done</a>' in s


# ---- the categories view ----
CARD = {"name": "Best Actor", "icon": "person", "dim": False, "shown": 4, "nominees": [],
        "winners": [{"title": "Adrien Brody", "href": "/media/person/2", "poster": None, "sub": "The Brutalist", "seen": True,
                     "portrait": True, "award": None}]}


def test_categories_view_keeps_todays_cards_more_categories_and_the_e7_sentinel():
    b = body(view="categories", ballot=None, cats=[CARD], more=[{**CARD, "name": "Best Sound"}], rest=3,
             part_href="/media/movies/awards/part/categories?body=oscars&year=2025",
             all_href="/media/movies/awards?body=oscars&year=2025&all=1")
    assert '<div class="awgrid">' in b and '<div class="awcat-name">Best Actor</div>' in b
    assert "<summary>More categories · 1</summary>" in b and '<div class="awcat-name">Best Sound</div>' in b
    assert 'class="panel awcat" hx-target="body" hx-select="unset"' in b       # a card's links leave #awmain
    s = re.search(r'<div class="awrest" hx-get="[^"]+" hx-trigger="revealed" hx-target="this" hx-select="unset" '
                  r'hx-swap="outerHTML" hx-push-url="false" hx-indicator="this">', b)
    assert s and ">All categories</a>" in b
    assert "awfilm" not in b and "awprog" not in b                              # none of the films view
    assert "Everything here is seen." in body(view="categories", ballot=None, unseen=True)
    assert "Nothing recorded for this ceremony yet." in body(view="categories", ballot=None)
    assert '<p class="empty">Nothing recorded for this ceremony yet.</p>' == \
        re.search(r'<p class="empty">[^<]*</p>', body(view="categories", ballot=None, empty="Nothing recorded for this ceremony yet.")).group(0)


def test_a_degraded_context_without_the_ballot_still_renders_its_empty_line():
    legacy = {"kind": "movie", "bodies": [], "years": [], "coming": [], "cats": [], "more": [], "rest": 0,
              "empty": "Awards are not synced yet.", "sync": {"text": "Not synced yet", "failed": False}}
    t = ENV.get_template("media_awards.html")
    p = "".join(t.blocks["content"](t.new_context(legacy)))
    assert '<p class="empty">Awards are not synced yet.</p>' in p and "awctl" not in p and "awnextup" not in p


def test_sync_failed_badge_stays_in_the_status_line():
    assert '<span class="badge badge-wait">Sync failed · retrying</span>' in page(sync={"text": "Last updated x", "failed": True})
