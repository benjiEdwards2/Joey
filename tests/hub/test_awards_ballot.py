"""Awards ballot WP-C1 (2026-10-14, BALLOT_CONTRACT.md §1-2): the films view's context - the edition pivoted by work
(rows ranked wins -> nominations -> title, five pills won first, the short-name rule), shorts folded apart, the filter
and sort keys, the Not seen count, progress, the people strip, the picker's year strip, Next up, every link carrying
v / f / s, the categories view kept, the rows part route and the degraded page. Built on the recorded 97th Oscars
(Wikidata answer, A0) loaded through the real parser, plus the small seeded edition of test_awards_pages."""
import re
import sqlite3
from contextlib import closing
from datetime import date, timedelta

import pytest

from hub import media_awards as ma
from hub import media_awards_db as adb
from hub import media_awards_icons as icons
from hub import media_awards_pages as ap
from hub import media_db, media_discover as md
from hub import media_watchlist_db as wl
from tests.hub.test_awards_db import FILM
from tests.hub.test_awards_pages import ALPHA, jelly, seeded
from tests.hub.test_awards_sync import FakeSession
from tests.hub.test_media_rate import env  # noqa: F401  (env is a fixture)


def load_edition(body="oscars", ordinal=97, year=2025, **ed):
    """One recorded edition through the real sync path (fake session, no network)."""
    with closing(adb.ensure()) as db:
        adb.upsert_editions(db, body, [{"ordinal": ordinal, "year": year, **ed}])
    client = ma.Client("test", session=FakeSession(), sleep=lambda s: None, pace=0)
    got = ma.run_pass(client=client, today=date(2026, 10, 8), only=(body, ordinal), discover_now=False)
    assert got["editions"] == 1 and not got["failed"]


@pytest.fixture
def oscars97(env, monkeypatch):
    monkeypatch.setenv("AWARDS_CONTACT", "test")
    monkeypatch.setenv("MEDIA_AWARDS", "on")
    load_edition(held_on="2025-03-02", wd_qid="Q85315076")
    return env


def ctx_of(kind="movie", body="oscars", year="2025", unseen=False, data=None, view="both", show_all=False, **state):
    return ap.awards_ctx(kind, body, year, unseen, data if data is not None else jelly(), view, show_all=show_all,
                         **state)[0]


def all_rows(**state):
    return ctx_of(show_all=True, **state)["ballot"]["rows"]


def titles(rows):
    return [r["title"] for r in rows]


def tmdb(title):
    return next(r["w"]["tmdb_id"] for r in all_rows() if r["title"] == title)


def lib(title, played=False, jf="jf1"):
    return {**ALPHA, "item_key": f"tmdb:{tmdb(title)}", "jf_id": jf, "title": title, "played": played,
            "poster": f"jf:{jf}", "year": 2024}


# ---- rows: the pivot, ranking, pills ----

def test_rows_rank_by_wins_then_nominations_then_title(oscars97):
    b = ctx_of()["ballot"]
    assert titles(b["rows"])[:5] == ["Anora", "The Brutalist", "Wicked", "Dune: Part Two", "Emilia Pérez"]
    a = b["rows"][0]
    assert (a["wins"], a["noms"], a["won_any"], a["tally"]) == (5, 6, True, "5 wins · 6 nominations")
    assert a["href"] == f"/media/title/movie/{a['w']['tmdb_id']}" and a["seen"] is False and a["on_server"] is False
    assert a["w"] == {"tmdb_id": a["w"]["tmdb_id"], "kind": "movie", "title": "Anora", "year": None, "poster": None}
    rows = all_rows()
    keys = [(-r["wins"], -r["noms"], r["title"].lower()) for r in rows]
    assert keys == sorted(keys) and len(rows) == 40
    nominated_only = next(r for r in rows if not r["wins"])
    assert nominated_only["tally"] == ap._count(nominated_only["noms"], "nomination") and not nominated_only["won_any"]


def test_five_pills_won_first_with_the_rest_counted(oscars97):
    rows = {r["title"]: r for r in all_rows()}
    anora = rows["Anora"]
    assert [(p["name"], p["won"], p["who"]) for p in anora["pills"]] == [
        ("Picture", True, None), ("Director", True, "Sean Baker"), ("Actress", True, "Mikey Madison"),
        ("Orig. Screenplay", True, None), ("Film Editing", True, None)]     # who: acting + directing pills only (C3)
    assert anora["more"] == 1 and len(anora["cats"]) == 6
    assert [c["won"] for c in anora["cats"]] == [True] * 5 + [False]
    assert anora["cats"][0] == {"name": "Best Picture", "won": True, "who": anora["cats"][0]["who"], "lead": "film"}
    assert anora["cats"][2]["lead"] == "person" and anora["cats"][2]["who"] == "Mikey Madison"
    assert "Sean Baker" in anora["cats"][3]["who"]                     # the screenplay pill drops its person; the fold keeps it
    assert all(p["who"] is None for r in rows.values() for p in r["pills"]
               if icons.cat_icon(p["name"]) not in ap.WHO_ICONS)       # no "Cinematography · Lol Crawley"
    brutalist = rows["The Brutalist"]
    won = [p["won"] for p in brutalist["pills"]]
    assert won == sorted(won, reverse=True) and won.count(True) == 3 and brutalist["more"] == brutalist["noms"] - 5
    assert all(len(r["pills"]) == min(5, r["noms"]) for r in rows.values())


@pytest.mark.parametrize("name, short", [
    ("Best Picture", "Picture"), ("Best Supporting Actress", "Supp. Actress"),
    ("Best Writing, Original Screenplay", "Orig. Screenplay"), ("Best Adapted Screenplay", "Adapt. Screenplay"),
    ("Writing (Original Screenplay)", "Orig. Screenplay"), ("Outstanding Writing for a Drama Series", "Writing for a Drama Series"),
    ("Best Animated Feature", "Animated"), ("Best International Feature Film", "International"),
    ("Outstanding Drama Series", "Drama Series"), ("Palme d'Or", "Palme d'Or"),
    ("Best Original Score", "Orig. Score"), ("Outstanding Supporting Actor in a Comedy Series", "Supp. Actor in a Comedy Series"),
])
def test_short_pill_names(name, short):
    assert ap.short_name(name) == short


def test_shorts_fold_apart_and_out_of_the_counts(oscars97):
    b = ctx_of(show_all=True)["ballot"]
    page = adb.edition_page("oscars", 2025, "film")
    short_cats = [c for c in page["categories"] if re.search(r"\bshort\b", c["name"], re.I)]
    assert [c["name"] for c in short_cats] == ["Best Animated Short Film", "Best Documentary (Short Subject)",
                                               "Best Live Action Short Film"]
    expected = list(dict.fromkeys(e["work"]["title"] for c in short_cats for e in c["entries"] if e.get("work")))
    assert titles(b["shorts"]) == expected and len(expected) == 15            # edition order
    assert not set(expected) & set(titles(b["rows"]))
    assert b["progress"]["total"] == len(b["rows"]) == 40
    assert all(not ap.is_short({"name": c["name"]}) for r in b["rows"] for c in r["cats"])
    for f in ap.FILTERS:                                                     # never filtered
        assert titles(ctx_of(f=f)["ballot"]["shorts"]) == expected


def test_a_work_in_a_short_and_a_feature_category_is_a_row_and_a_short(env):
    seeded()                                                                 # Beta: Best Picture + a live-action short
    b = ctx_of(data=jelly(ALPHA))["ballot"]
    beta = next(r for r in b["rows"] if r["title"] == "Beta")
    assert [c["name"] for c in beta["cats"]] == ["Best Picture", "Best Actor"]
    assert [(r["title"], [c["name"] for c in r["cats"]]) for r in b["shorts"]] == [("Beta", ["Best Live Action Short Film"])]


# ---- filters and sorts ----

def test_each_filter_keeps_its_rows(oscars97):
    page = adb.edition_page("oscars", 2025, "film")
    feature = [c for c in page["categories"] if not ap.is_short(c)]
    by_cat = {c["name"]: c for c in feature}

    def works(pred):
        return {e["work"]["title"] for c in feature if pred(c) for e in c["entries"] if e.get("work")}

    expect = {
        "headline": works(lambda c: c["rank"] == 0),
        "acting": works(lambda c: icons.cat_icon(c["name"]) == "person"),
        "direction": works(lambda c: icons.cat_icon(c["name"]) in ("clapper", "nib")),
        "craft": works(lambda c: c["rank"] != 0 and icons.cat_icon(c["name"]) not in ("person", "clapper", "nib")),
    }
    assert len(expect["headline"]) == 10 and "Best Picture" in by_cat
    for f, want in expect.items():
        assert set(titles(all_rows(f=f))) == want, f
    assert "The Substance" in expect["craft"] and "Conclave" in expect["direction"]
    assert set(titles(all_rows(f="all"))) == works(lambda c: True)


def test_unseen_and_server_filters_and_the_hidden_count(oscars97):
    data = jelly(lib("Anora", played=True, jf="jfanora"), lib("Wicked", jf="jfwicked"))
    media_db.add_manual_watch(f"tmdb:{tmdb('The Brutalist')}", "movie", "The Brutalist", 2024, None, "2025-01-01")
    every = ctx_of(data=data, show_all=True)["ballot"]
    assert every["hidden_seen"] is None
    rows = {r["title"]: r for r in every["rows"]}
    assert rows["Anora"]["seen"] and rows["Anora"]["on_server"] and rows["Anora"]["href"] == "/media/item/jfanora"
    assert rows["Anora"]["poster"] == "jf:jfanora" and rows["Anora"]["year"] == 2024
    assert rows["The Brutalist"]["seen"] and not rows["The Brutalist"]["on_server"]      # a diary row counts
    unseen = ctx_of(data=data, f="unseen", show_all=True)["ballot"]
    assert set(titles(unseen["rows"])) == set(rows) - {"Anora", "The Brutalist"} and unseen["hidden_seen"] == 2
    server = ctx_of(data=data, f="server")["ballot"]
    assert titles(server["rows"]) == ["Anora", "Wicked"] and server["hidden_seen"] is None


def test_legacy_unseen_flag_means_the_not_seen_filter(oscars97):
    data = jelly(lib("Anora", played=True))
    old = ctx_of(data=data, unseen=True)
    assert old["unseen"] is True and old["ballot"]["hidden_seen"] == 1
    assert [x["key"] for x in old["ballot"]["filters"] if x["on"]] == ["unseen"]
    assert "Anora" not in titles(old["ballot"]["rows"])
    assert old["bodies"][0]["href"] == "/media/movies/awards?body=oscars&year=2025&f=unseen"


def test_each_sort_key(oscars97):
    noms = all_rows(s="noms")
    assert noms[0]["title"] == "Emilia Pérez"
    keys = [(-r["noms"], -r["wins"], r["title"].lower()) for r in noms]
    assert keys == sorted(keys)
    az = titles(all_rows(s="az"))
    assert az == sorted(az, key=str.lower) and az[0] == "A Complete Unknown"
    assert titles(all_rows(s="junk")) == titles(all_rows(s="wins"))          # a bad sort is the default


def test_filter_and_sort_chips(oscars97):
    b = ctx_of(f="acting", s="az")["ballot"]
    assert [(x["key"], x["label"], x["on"]) for x in b["filters"]] == [
        ("all", "All", False), ("headline", "Best Picture", False), ("acting", "Acting", True),
        ("direction", "Direction & writing", False), ("craft", "Craft", False), ("unseen", "Not seen", False),
        ("server", "On your server", False)]
    assert [(x["key"], x["label"], x["on"]) for x in b["sorts"]] == [
        ("wins", "Most wins", False), ("noms", "Most nominations", False), ("az", "A to Z", True)]
    assert b["filters"][0]["href"] == "/media/movies/awards?body=oscars&year=2025&s=az"          # sort kept
    assert b["filters"][3]["href"] == "/media/movies/awards?body=oscars&year=2025&f=direction&s=az"
    assert b["sorts"][0]["href"] == "/media/movies/awards?body=oscars&year=2025&f=acting"        # filter kept
    assert b["sorts"][1]["href"] == "/media/movies/awards?body=oscars&year=2025&f=acting&s=noms"


def test_empty_wordings(oscars97):
    with closing(adb.ensure()) as db:                                        # a one-film BAFTA: Alpha, played
        adb.upsert_editions(db, "bafta", [{"ordinal": 78, "year": 2025}])
        adb.write_edition(db, "bafta", 78, [{"cat_key": "BF", "name": "Best Film", "kind": "film", "lead": "work",
                                             "rank": 0, "grp": "core"}],
                          [{"cat_key": "BF", "work_qid": "Q1001", "work_title": "Alpha", "won": 1, "pos": 0}],
                          {"Q1001": FILM}, "done", "wp")
    done = ctx_of(body="bafta", data=jelly(ALPHA), f="unseen")["ballot"]
    assert done["rows"] == [] and done["empty"] == "Everything here is seen." and done["hidden_seen"] == 1
    assert ctx_of(f="server")["ballot"]["empty"] == "Nothing matches that filter."
    assert ctx_of()["ballot"]["empty"] is None
    far = ctx_of(year="2030")                                                # no such year: the nearest one
    assert far["year"] == 2025 and far["year_note"] == "No Oscars in 2030 · showing 2025"


# ---- progress, people ----

def test_progress_counts_the_viewers_seen_set(oscars97):
    data = jelly(lib("Anora", played=True, jf="jfa"), lib("Wicked", jf="jfw"), lib("Flow", jf="jff"))
    media_db.add_manual_watch(f"tmdb:{tmdb('Conclave')}", "movie", "Conclave", 2024, None, "2025-01-01")
    wl.add("you", {"tmdb_id": tmdb("Nosferatu"), "kind": "movie", "title": "Nosferatu"})
    wl.add("you", {"tmdb_id": tmdb("Wicked"), "kind": "movie", "title": "Wicked"})
    wl.add("her", {"tmdb_id": tmdb("Flow"), "kind": "movie", "title": "Flow"})                 # someone else's list
    p = ctx_of(data=data)["ballot"]["progress"]
    assert p == {"pct": 5, "seen": 2, "total": 40,                                             # Anora + Conclave
                 "headline": {"name": "Best Picture", "seen": 2, "total": 10},
                 "server_unseen": 2, "watchlisted": 2}                                         # Wicked + Flow / Nosferatu + Wicked
    rows = {r["title"]: r for r in all_rows(data=data)}
    assert rows["Nosferatu"]["watchlisted"] and rows["Wicked"]["watchlisted"] and not rows["Flow"]["watchlisted"]
    her = ctx_of(data=data, view="her")["ballot"]["progress"]
    assert her["watchlisted"] == 1


def test_people_are_the_acting_and_directing_winners_in_edition_order(oscars97):
    with closing(adb.ensure()) as db:
        madison = db.execute("SELECT qid, tmdb_person FROM award_entity WHERE label = 'Mikey Madison'").fetchone()
    adb.set_poster(madison["qid"], "tmdb:/mikey.jpg")
    people = ctx_of()["ballot"]["people"]
    assert [(p["name"], p["cat"]) for p in people] == [
        ("Sean Baker", "Director"), ("Adrien Brody", "Actor"), ("Mikey Madison", "Actress"),
        ("Kieran Culkin", "Supp. Actor"), ("Zoe Saldaña", "Supp. Actress")]
    mikey = people[2]
    assert mikey["poster"] == "tmdb:/mikey.jpg"
    assert mikey["href"] == (f"/media/person/{madison['tmdb_person']}" if madison["tmdb_person"] else None)


# ---- picker, Next up, links ----

def test_years_list_marks_years_with_data(oscars97):
    with closing(adb.ensure()) as db:
        adb.upsert_editions(db, "oscars", [{"ordinal": 98, "year": 2026}, {"ordinal": 96, "year": 2024}])
    c = ctx_of(f="unseen")
    assert c["years_list"] == [
        {"year": 2026, "href": "/media/movies/awards?body=oscars&year=2026&f=unseen", "on": False, "has_data": False},
        {"year": 2025, "href": "/media/movies/awards?body=oscars&year=2025&f=unseen", "on": True, "has_data": True},
        {"year": 2024, "href": "/media/movies/awards?body=oscars&year=2024&f=unseen", "on": False, "has_data": False}]
    assert c["picker"] == {"name": "Oscars", "body_id": "oscars", "logo": None, "year": 2025}
    assert adb.data_years("oscars", "film") == {2025} and adb.data_years("oscars", "tv") == set()


def test_next_up_is_the_first_coming_event(oscars97):
    soon = date.today() + timedelta(days=20)
    with closing(adb.ensure()) as db:
        adb.upsert_editions(db, "oscars", [{"ordinal": 99, "year": soon.year, "held_on": soon.isoformat()}])
    c = ctx_of()
    first = c["coming"][0]["events"][0]
    assert c["next_up"]["body_id"] == first["body_id"] and c["next_up"]["name"] == first["name"]
    nxt = ap.next_up([{"month": adb.MONTHS[soon.month - 1], "year": soon.year, "events": [{"body_id": "oscars", "name": "Oscars",
                                                                      "date": f"{soon.day} {soon:%b}"}]}], date.today())
    assert nxt == {"body_id": "oscars", "name": "Oscars", "logo": None,
                   "date": f"{soon:%a} {soon.day} {soon:%b %Y}", "days": 20}
    assert ap.next_up([{"month": "JAN", "year": 2027, "events": [{"body_id": "globes", "name": "Golden Globes",
                                                                  "date": None}]}], date.today())["days"] is None
    assert ap.next_up([], date.today()) is None
    assert ap.next_up([{"month": "JAN", "year": 2027, "events": [{"body_id": "globes", "name": "Golden Globes",
                                                                  "date": "11 Jan"}]}], date(2026, 10, 14)) == {
        "body_id": "globes", "name": "Golden Globes", "logo": None, "date": "Mon 11 Jan 2027", "days": 89}


def test_every_link_carries_view_filter_and_sort(oscars97):
    with closing(adb.ensure()) as db:
        adb.upsert_editions(db, "oscars", [{"ordinal": 96, "year": 2024}, {"ordinal": 98, "year": 2026}])
    c = ctx_of(year="2024", f="acting", s="az")
    tail = "&f=acting&s=az"
    assert c["view"] == "films" and c["view_hrefs"] == {
        "films": "/media/movies/awards?body=oscars&year=2024" + tail,
        "categories": "/media/movies/awards?body=oscars&year=2024&v=categories" + tail}
    assert c["bodies"][1]["href"] == "/media/movies/awards?body=globes&year=2024" + tail
    assert all(y["href"].endswith(tail) for y in c["years_list"])
    assert c["prev"] is None and c["next"]["href"] == "/media/movies/awards?body=oscars&year=2025" + tail
    assert c["current"]["href"] == "/media/movies/awards?body=oscars" + tail
    assert c["unseen_href"] == "/media/movies/awards?body=oscars&year=2024&f=unseen&s=az"
    assert c["all_href"] == "/media/movies/awards?body=oscars&year=2024" + tail + "&all=1"
    cur = ctx_of(f="acting", s="az")
    assert cur["ballot"]["part_rows_href"] == "/media/movies/awards/part/rows?body=oscars&year=2025" + tail
    cats = ctx_of(v="categories", f="unseen", s="noms")
    assert cats["view"] == "categories" and cats["ballot"] is None
    assert cats["part_href"] == "/media/movies/awards/part/categories?body=oscars&year=2025&v=categories&f=unseen&s=noms"
    assert cats["unseen_href"] == "/media/movies/awards?body=oscars&year=2025&v=categories&s=noms"
    assert cats["bodies"][0]["href"] == "/media/movies/awards?body=oscars&year=2025&v=categories&f=unseen&s=noms"
    assert ctx_of(v="junk", f="junk")["view"] == "films"


def test_the_first_screen_holds_twelve_rows_and_the_rest_is_counted(oscars97):
    b = ctx_of()["ballot"]
    assert len(b["rows"]) == ap.FIRST_ROWS == 12 and b["rest"] == 28
    assert ctx_of(show_all=True)["ballot"]["rest"] == 0
    assert ctx_of(f="headline")["ballot"]["rest"] == 0


def test_categories_view_keeps_the_cards_with_the_headline_first(oscars97):
    c = ctx_of(v="categories")
    assert c["ballot"] is None and c["view"] == "categories"
    assert [x["name"] for x in c["cats"]] == ["Best Picture", "Best Director", "Best Actor", "Best Actress"]
    assert c["rest"] == len(c["cats_rest"]) + len(c["more_all"]) and c["more"] == []
    assert c["cats"][0]["winners"][0]["title"] == "Anora"
    films = ctx_of()
    assert films["cats"] == [] and films["more_all"] == [] and films["rest"] == 0       # cards only in their view


# ---- routes ----

def test_rows_part_brings_the_rows_after_the_first_twelve(oscars97):
    build, _ = oscars97
    want = titles(all_rows(f="craft", s="az"))
    assert len(want) > 12
    with build(jelly()) as client:
        r = client.get("/media/movies/awards/part/rows?body=oscars&year=2025&f=craft&s=az")
        plain = client.get("/media/movies/awards/part/rows?body=oscars&year=2025")
        legacy = client.get("/media/movies/awards/part/rows?body=oscars&year=2025&unseen=1")
        bad = client.get("/media/movies/awards/part/rows?body=%3Cscript%3E&year=zz&f=%3Ci%3E&s=1")
        tv = client.get("/media/tv/awards/part/rows?body=emmys&year=2025")
    assert r.status_code == 200 and "<html" not in r.text
    got = re.findall(r'class="awfilm-title"[^>]*>([^<]*)<', r.text)       # WP-C2's row macro (merge, 2026-10-14)
    assert [g.replace("&#39;", "'") for g in got] == want[12:] and got
    assert len(re.findall(r'<article class="awfilm', plain.text)) == 28
    assert len(re.findall(r'<article class="awfilm', legacy.text)) == 28
    assert bad.status_code == 200 and "<script" not in bad.text and "<i>" not in bad.text   # the Details fold uses <b> itself
    assert tv.status_code == 200 and tv.text.strip() == ""


def test_the_page_answers_every_view_filter_and_sort(oscars97):
    build, _ = oscars97
    with build(jelly()) as client:
        for q in ("", "?v=categories", "?f=acting&s=az", "?unseen=1", "?v=junk&f=junk&s=junk", "?all=1"):
            assert client.get("/media/movies/awards" + q).status_code == 200, q
        assert client.get("/media/tv/awards?f=headline").status_code == 200


def test_posters_fill_the_first_rows_works_first(oscars97, monkeypatch):
    build, _ = oscars97
    monkeypatch.setattr(md, "_creds", lambda: ("http://seerr.invalid", "k"))
    monkeypatch.setattr(md, "meta_get", lambda *a, **k: pytest.fail("a meta read before the render"))
    queued = []
    monkeypatch.setattr(ap, "fill_later", lambda ents: queued.append([e["qid"] for e in ents]))
    with build(jelly()) as client:
        assert client.get("/media/movies/awards?s=az").status_code == 200
    ents = queued[0]
    page = adb.edition_page("oscars", 2025, "film")
    qid = {e["work"]["title"]: e["work"]["qid"] for c in page["categories"] for e in c["entries"] if e.get("work")}
    with closing(adb.ensure()) as db:
        has_tmdb = {r["qid"] for r in db.execute("SELECT qid FROM award_entity WHERE tmdb_movie OR tmdb_person")}
    first = {qid[t] for t in titles(ctx_of(s="az")["ballot"]["rows"])} & has_tmdb
    assert first and set(ents[:len(first)]) == first
    assert len(ents) <= ap.POSTER_READS and len(set(ents)) == len(ents)


def test_degraded_page_keeps_every_key(env, monkeypatch):
    build, _ = env
    seeded()

    def boom(*a, **k):
        raise sqlite3.OperationalError("locked")

    monkeypatch.setattr(adb, "edition_page", boom)
    with build(jelly()) as client:
        assert client.get("/media/movies/awards").status_code == 200
        assert client.get("/media/movies/awards/part/rows").status_code == 200
    d = ap.degraded_ctx("movie", "films")
    assert d["ballot"] == ap.no_ballot(ap.EMPTY) and d["ballot"]["rows"] == [] and d["view"] == "films"
    for key in ("view_hrefs", "years_list", "picker", "next_up", "cats_rest", "more_all", "part_href", "all_href"):
        assert key in d
    assert ap.degraded_ctx("tv", "categories")["ballot"] is None


# ---- TV: the same shape with shows ----

def test_tv_ballot_uses_the_emmys_headline_and_tv_words(env, monkeypatch):
    monkeypatch.setenv("AWARDS_CONTACT", "test")
    monkeypatch.setenv("MEDIA_AWARDS", "on")
    load_edition("emmys", 77, 2025)
    b = ctx_of("tv", "emmys")["ballot"]
    assert b["rows"][0]["title"] == "Adolescence" and b["rows"][0]["tally"] == "6 wins · 6 nominations"
    assert b["progress"]["headline"] == {"name": "Outstanding Drama Series", "seen": 0, "total": 8}
    assert [(x["key"], x["label"]) for x in b["filters"]][1:4] == [
        ("headline", "Drama Series"), ("acting", "Acting"), ("direction", "Writing & directing")]
    assert {r["title"] for r in all_rows(kind="tv", body="emmys", f="headline")} >= {"The Pitt", "Severance"}
