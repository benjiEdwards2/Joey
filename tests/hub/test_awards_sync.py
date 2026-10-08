"""Awards A3 (AWARDS_PLAN, 2026-10-08): the sync with `requests` faked (a fake Session — no network): a full pass over
three editions, 429 ends the pass and keeps state, a timeout leaves `pending`, no page shape -> `skipped`, no
AWARDS_CONTACT -> zero calls, the User-Agent, never two calls without the pause, a second pass is idempotent, discovery,
the cadence and the loop's gates."""
import json
import zlib
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs

import pytest
import requests

from hub import media_awards as ma
from hub import media_awards_db as adb
from hub import media_awards_parse as ap
from tests.hub.test_awards_fixtures import load

TODAY = date(2026, 10, 8)
CONTACT = "test-contact"
WP_BY_TITLE = {"78th British Academy Film Awards": "wp_bafta_78.json", "77th Primetime Emmy Awards": "wp_emmys_77.json",
               "82nd Golden Globe Awards": "wp_globes_82.json", "31st Screen Actors Guild Awards": "wp_sag_31.json"}


def qid_for(title: str) -> str:
    return f"Q{900000000 + zlib.crc32(title.encode('utf-8')) % 90000000}"


class Resp:
    def __init__(self, code=200, body=None, text=None, headers=None):
        self.status_code, self._body, self.headers = code, body, headers or {}
        self.text = text if text is not None else json.dumps(body)
        self.encoding = "utf-8"

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSession:
    """Routes like the real hosts; `override(kind) -> Resp | Exception | None` lets a test break one kind of call."""

    def __init__(self, override=None, log=None):
        self.calls, self.override, self.log = [], override or (lambda kind, params: None), log if log is not None else []

    def close(self):
        pass

    def get(self, url, params=None, headers=None, timeout=None):
        params = params or {}
        kind = self.kind(url, params)
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout, "kind": kind})
        self.log.append("call")
        got = self.override(kind, params)
        if isinstance(got, Exception):
            raise got
        if got is not None:
            return got
        return self.answer(kind, params)

    @staticmethod
    def kind(url, params):
        if "query.wikidata.org" in url:
            q = params["query"]
            return ("discovery" if "wdt:P179" in q else "edition" if "pq:P805" in q else
                    "winners" if "p:P1346" in q else "ids")
        return "parse" if params.get("action") == "parse" else "pageprops"

    def answer(self, kind, params):
        if kind == "discovery":
            return Resp(text=load("wd_discovery.csv"))
        if kind == "edition":
            return Resp(text=load("wd_oscars_97.csv"))
        if kind == "winners":
            if "wd:Q179808" in params["query"]:
                return Resp(text=load("wd_winners_cannes.csv"))
            return Resp(text="award,awardLabel,item,itemLabel,date,human,tm,tt,tp,imdb,tvdb,work,workLabel,wtm,wtt,wtvdb\r\n")
        if kind == "ids":
            qids = [w[3:] for w in params["query"].split() if w.startswith("wd:Q")]
            lines = ["item,human,tm,tt,tp,imdb,tvdb"]
            for i, q in enumerate(qids):
                n = int(q[1:]) % 1000000
                lines.append(f"http://www.wikidata.org/entity/{q},false,{n},,,," if i % 3 else
                             f"http://www.wikidata.org/entity/{q},true,,,{n},,")
            return Resp(text="\r\n".join(lines) + "\r\n")
        if kind == "parse":
            name = WP_BY_TITLE.get(params["page"])
            return Resp(body=load(name)) if name else Resp(body=load("wp_missing.json"))
        titles = params["titles"].split("|")
        return Resp(body={"batchcomplete": True, "query": {"pages": [
            {"pageid": i + 1, "ns": 0, "title": t, "pageprops": {"wikibase_item": qid_for(t)}} for i, t in enumerate(titles)]}})


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("AWARDS_CONTACT", CONTACT)
    monkeypatch.setenv("MEDIA_AWARDS", "on")

    def make(override=None, editions=True, discovered=True):
        log: list = []
        session = FakeSession(override, log)
        client = ma.Client(CONTACT, session=session, sleep=lambda s: log.append(("sleep", s)), pace=2.0)
        with closing(adb.ensure()) as db:
            if discovered:
                adb.set_sync(db, "discovered_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
            if editions:
                adb.upsert_editions(db, "oscars", [{"ordinal": 97, "year": 2025, "held_on": "2025-03-02", "wd_qid": "Q85315076"}])
                adb.upsert_editions(db, "bafta", [{"ordinal": 78, "year": 2025}])
                adb.upsert_editions(db, "emmys", [{"ordinal": 77, "year": 2025}])
        return client, session, log
    return make


def states():
    with closing(adb.ensure()) as db:
        return {(r["body_id"], r["ordinal"]): (r["state"], r["note"]) for r in db.execute("SELECT * FROM award_edition")}


def nom_count():
    with closing(adb.ensure()) as db:
        return db.execute("SELECT COUNT(*) AS n FROM award_nomination").fetchone()["n"]


def test_a_full_pass_over_three_editions(setup):
    client, session, _ = setup()
    counts = ma.run_pass(client=client, today=TODAY)
    assert counts["editions"] == 3 and counts["failed"] == 0 and not counts["rate_limited"]
    assert states()[("oscars", 97)][0] == states()[("bafta", 78)][0] == states()[("emmys", 77)][0] == "done"
    kinds = [c["kind"] for c in session.calls]
    assert kinds[0] == "edition" and kinds.count("parse") == 2 and "pageprops" in kinds and "ids" in kinds
    bafta = adb.edition_page("bafta", 2025, "film")
    best = next(c for c in bafta["categories"] if c["name"] == "Best Film")
    assert best["rank"] == 0 and best["entries"][0]["won"] and best["entries"][0]["work"]["title"] == "Conclave"
    assert best["entries"][0]["work"]["qid"] == qid_for("Conclave (film)")
    assert len(best["entries"]) == 5 and [p["name"] for p in best["entries"][0]["people"]][:1] == ["Tessa Ross"]
    emmys = adb.edition_page("emmys", 2025, "tv")
    drama = next(c for c in emmys["categories"] if c["name"] == "Outstanding Drama Series")
    assert drama["rank"] == 0 and drama["entries"][0]["work"]["title"] == "The Pitt"
    oscars = adb.edition_page("oscars", 2025, "film")
    assert len(oscars["categories"]) == 26 and oscars["categories"][0]["name"] == "Best Picture"
    assert counts["rows"] == nom_count()
    with closing(adb.ensure()) as db:
        assert adb.get_sync(db, "last_pass_ok") == "1" and adb.get_sync(db, "backlog") == "0"
    # an unlinked repeat mention reuses the page's link: SAG-style "Shōgun" rows never become '~shogun' when linked once
    assert adb.local_key("Conclave") not in {e["work"]["qid"] for e in best["entries"]}


def test_user_agent_timeout_and_pause_between_every_call(setup):
    client, session, log = setup()
    ma.run_pass(client=client, today=TODAY)
    assert {c["headers"]["User-Agent"] for c in session.calls} == {f"Joey/awards (+https://joeyhome.net; {CONTACT})"}
    assert {c["timeout"] for c in session.calls} == {30}
    assert all(c["url"] in (ma.WDQS, ma.WP_API) for c in session.calls)
    flat = ["call" if x == "call" else "sleep" for x in log]
    assert flat[0] == "call" and all(not (a == b == "call") for a, b in zip(flat, flat[1:]))   # never two calls back to back
    assert len(session.calls) >= 6


def test_429_waits_once_then_ends_the_pass_and_keeps_state(setup):
    resp429 = Resp(429, text=load("wdqs_429.html"), headers={"Retry-After": "1000"})
    client, session, log = setup(lambda kind, params: resp429)
    counts = ma.run_pass(client=client, today=TODAY)
    assert counts["rate_limited"] and counts["editions"] == 0
    assert len(session.calls) == 2                         # the call and its one retry, then the pass ended
    assert ("sleep", 120.0) in log                          # Retry-After honoured, capped at 120 s
    assert states()[("oscars", 97)] == ("pending", None) and states()[("bafta", 78)] == ("pending", None)
    with closing(adb.ensure()) as db:
        assert adb.get_sync(db, "last_pass_ok") == "0"
    assert adb.sync_status()["failed"] is True


def test_a_429_then_success_carries_on(setup):
    seen = {"n": 0}

    def once(kind, params):
        seen["n"] += 1
        return Resp(429, text="", headers={"Retry-After": "5"}) if seen["n"] == 1 else None
    client, _, log = setup(once)
    counts = ma.run_pass(client=client, today=TODAY)
    assert counts["editions"] == 3 and ("sleep", 5.0) in log


def test_timeout_and_5xx_leave_the_edition_pending_and_the_pass_goes_on(setup):
    def broken(kind, params):
        if kind == "parse" and params["page"].startswith("78th"):
            return requests.Timeout("slow")
        if kind == "parse" and params["page"].startswith("77th"):
            return Resp(503, text="down")
        return None
    client, _, _ = setup(broken)
    counts = ma.run_pass(client=client, today=TODAY)
    assert counts["editions"] == 1 and counts["pending"] == 2
    assert states()[("bafta", 78)] == ("pending", "timeout") and states()[("emmys", 77)] == ("pending", "HTTP 503")
    assert states()[("oscars", 97)][0] == "done"


def test_a_page_without_award_categories_is_skipped_and_a_missing_old_page_too(setup):
    def old_shape(kind, params):
        if kind == "parse" and params["page"].startswith("78th"):
            return Resp(body=load("wp_globes_40.json"))
        return None
    client, _, _ = setup(old_shape)
    with closing(adb.ensure()) as db:
        adb.upsert_editions(db, "sag", [{"ordinal": 12, "year": 2006}])   # no fixture -> missingtitle, old -> skipped
    counts = ma.run_pass(client=client, today=TODAY)
    assert states()[("bafta", 78)] == ("skipped", "no page shape (none)")
    assert states()[("sag", 12)] == ("skipped", "no page") and counts["skipped"] == 2
    second = ma.run_pass(client=setup(editions=False)[0], today=TODAY)
    assert second["skipped"] == 0                          # skipped editions are never retried


def test_a_parser_exception_marks_failed_and_logs_the_type_only(setup, monkeypatch, caplog):
    client, _, _ = setup()
    monkeypatch.setattr(ap, "parse_award_blocks", lambda text: (_ for _ in ()).throw(KeyError("secret title")))
    counts = ma.run_pass(client=client, today=TODAY)
    assert counts["failed"] == 2 and states()[("bafta", 78)] == ("failed", "KeyError")
    assert "secret title" not in caplog.text and "wikipedia.org" not in caplog.text


def test_no_contact_means_zero_calls(setup, monkeypatch):
    client, session, _ = setup()
    monkeypatch.delenv("AWARDS_CONTACT")
    counts = ma.run_pass(client=client, today=TODAY)
    assert counts.get("no_contact") and session.calls == []
    assert ma.tick(datetime(2026, 10, 11, 10, 0)) is None and session.calls == []


def test_a_second_pass_is_idempotent(setup):
    client, _, _ = setup()
    ma.run_pass(client=client, today=TODAY)
    first = nom_count()
    with closing(adb.ensure()) as db:
        with db:
            db.execute("UPDATE award_edition SET state = 'pending'")
    again = ma.run_pass(client=setup(editions=False)[0], today=TODAY)
    assert again["editions"] == 3 and nom_count() == first
    # titles already resolved are not asked again
    client3, session3, _ = setup(editions=False)
    with closing(adb.ensure()) as db:
        with db:
            db.execute("UPDATE award_edition SET state = 'pending' WHERE body_id = 'bafta'")
    ma.run_pass(client=client3, today=TODAY)
    assert [c["kind"] for c in session3.calls] == ["parse"]


def test_discovery_lists_editions_and_pulls_winners_only_bodies(setup):
    client, session, _ = setup(editions=False, discovered=False)
    counts = ma.run_pass(client=client, today=TODAY, cap=0)
    kinds = [c["kind"] for c in session.calls]
    assert kinds[0] == "discovery" and kinds.count("winners") == 4 and "parse" not in kinds
    st = states()
    assert ("bafta", 78) in st and ("globes", 83) in st and ("emmys", 78) in st      # offset editions
    with closing(adb.ensure()) as db:
        osc = dict(db.execute("SELECT * FROM award_edition WHERE body_id = 'oscars' AND ordinal = 97").fetchone())
        palme = db.execute("SELECT state FROM award_edition WHERE body_id = 'cannes' AND ordinal = 2024").fetchone()
        assert adb.get_sync(db, "discovered_at")
    assert osc["wd_qid"] == "Q85315076" and osc["held_on"] == "2025-03-02" and osc["year"] == 2025
    assert palme["state"] == "partial" and counts["editions"] == 4
    page = adb.edition_page("cannes", 2024, "film")
    assert page["categories"][0]["name"] == "Palme d'Or" and page["categories"][0]["entries"][0]["work"]["title"] == "Anora"


def test_discovery_failure_still_lets_wikipedia_editions_go_ahead(setup):
    client, _, _ = setup(lambda kind, params: Resp(500, text="x") if kind == "discovery" else None,
                         editions=False, discovered=False)
    counts = ma.run_pass(client=client, today=TODAY, cap=2)
    assert counts["discovery"] == "HTTP 500" and counts["editions"] + counts["skipped"] + counts["pending"] == 2
    with closing(adb.ensure()) as db:
        assert adb.get_sync(db, "discovered_at") is None


def test_backlog_is_newest_first_and_capped(setup):
    client, _, _ = setup(editions=False)
    with closing(adb.ensure()) as db:
        ma._insert_new(db, "bafta", ma.offset_editions(ma.seed.BY_ID["bafta"], TODAY))
        work, backlog = ma.select_work(db, TODAY, 40)
    assert backlog == 79 and len(work) == 40                 # 1st..79th (2026) pending; the 80th (2027) is future
    assert [w["year"] for w in work[:3]] == [2026, 2025, 2024]


def test_recent_editions_are_refreshed_weekly(setup):
    client, _, _ = setup()
    ma.run_pass(client=client, today=TODAY)
    with closing(adb.ensure()) as db:
        work, backlog = ma.select_work(db, TODAY, 40)
        assert backlog == 0 and work == []                   # just synced
        old = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
        with db:
            db.execute("UPDATE award_edition SET synced_at = ?", (old,))
        work, _ = ma.select_work(db, date(2025, 5, 1), 40)   # Mar / Feb 2025 within 120 days, Sep 2025 to come
        assert {(w["body_id"], w["ordinal"]) for w in work} == {("oscars", 97), ("bafta", 78), ("emmys", 77)}
        work, _ = ma.select_work(db, date(2025, 8, 1), 40)   # Feb / Mar now older than 120 days
        assert {(w["body_id"], w["ordinal"]) for w in work} == {("emmys", 77)}


def test_cadence():
    mel = timezone(timedelta(hours=11))
    sun10 = datetime(2026, 10, 11, 10, 0, tzinfo=mel)
    assert ma.due(datetime(2026, 10, 11, 23, 0, tzinfo=mel), None, 5) is False      # NAS off
    assert ma.due(datetime(2026, 10, 12, 6, 30, tzinfo=mel), None, 5) is False
    assert ma.due(sun10, None, 0) is True                                            # never ran
    last = (sun10 - timedelta(hours=5)).isoformat()
    assert ma.due(sun10, last, 3) is False and ma.due(sun10 + timedelta(hours=1), last, 3) is True   # 6-hourly backlog
    tue = datetime(2026, 10, 13, 10, 0, tzinfo=mel)
    assert ma.due(tue, (tue - timedelta(days=2)).isoformat(), 0) is False            # weekly, not Tuesday
    assert ma.due(sun10, (sun10 - timedelta(days=6)).isoformat(), 0) is True         # Sunday from 09:00
    assert ma.due(sun10.replace(hour=8), (sun10 - timedelta(days=6)).isoformat(), 0) is False
    assert ma.due(tue, (tue - timedelta(days=9)).isoformat(), 0) is True             # a missed Sunday


def test_tick_and_loop_gates(setup, monkeypatch):
    client, session, _ = setup()
    monkeypatch.setenv("MEDIA_AWARDS", "off")
    assert ma.disabled() and ma.tick(datetime(2026, 10, 11, 10, 0)) is None
    monkeypatch.setenv("MEDIA_AWARDS", "on")
    assert ma.tick(datetime(2026, 10, 11, 23, 0)) is None                            # off window: nothing opened
    called = []
    monkeypatch.setattr(ma, "run_pass", lambda **kw: called.append(kw) or {"editions": 0})
    assert ma.tick(datetime(2026, 10, 11, 10, 0)) == {"editions": 0} and called
    assert session.calls == []


def test_main_starts_no_awards_loop_when_disabled(monkeypatch):
    import inspect
    from hub import main
    src = inspect.getsource(main.lifespan)
    assert "media_awards.disabled()" in src and "_media_awards_loop" in src


def test_the_manual_script_parses_editions():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("awards_sync", Path(__file__).resolve().parents[2] / "scripts" / "awards_sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.parse_edition("oscars:97") == ("oscars", 97) and mod.parse_edition("cannes") == ("cannes", None)
    with pytest.raises(SystemExit):
        mod.parse_edition("nope:1")
    assert mod.main(["--edition", "oscars:97"]) == 2          # no AWARDS_CONTACT in tests: nothing called


def test_nominee_lines_keep_co_writers_together_and_actors_apart(setup):
    client, _, _ = setup()
    ma.run_pass(client=client, today=TODAY)
    cats = {c["name"]: c for c in adb.edition_page("bafta", 2025, "film")["categories"]}
    screenplay = cats["Best Original Screenplay"]["entries"]
    brutalist = next(e for e in screenplay if e["work"]["title"] == "The Brutalist")
    assert [p["name"] for p in brutalist["people"]] == ["Brady Corbet", "Mona Fastvold"]
    supporting = cats["Best Actress in a Supporting Role"]["entries"]
    emilia = [e for e in supporting if e["work"]["title"] == "Emilia Pérez"]
    assert [(e["people"][0]["name"], e["won"]) for e in emilia] == [("Zoe Saldaña", 1), ("Selena Gomez", 0)]
    oscars = {c["name"]: c for c in adb.edition_page("oscars", 2025, "film")["categories"]}
    adapted = oscars["Best Writing, Adapted Screenplay"]["entries"]
    unknown = [e for e in adapted if e["work"]["title"] == "A Complete Unknown"]
    assert len(unknown) == 1 and {p["name"] for p in unknown[0]["people"]} >= {"Jay Cocks", "James Mangold"}
