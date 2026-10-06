"""Signed-in user (2026-10-06): the Cloudflare Access header decides who's looking.

Only placeholder addresses appear here (example.com) — the other person's real address is
never written into the repo. OWNER_EMAIL_YOU is monkeypatched to a placeholder too.
"""
import importlib
import re
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from hub import media_db
from hub.identity import IDENTITY_HEADER, resolve_identity
from tests.hub.test_media_rate import HX, env, rate_form  # noqa: F401  (env is a fixture)
from tests.hub.test_owner_filter import client  # noqa: F401  (fixture)

YOU = "you@example.com"
OTHER = "other@example.com"
AS_YOU = {IDENTITY_HEADER: YOU}
AS_HER = {IDENTITY_HEADER: OTHER}


@pytest.fixture(autouse=True)
def _owner_env(monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL_YOU", YOU)
    monkeypatch.delenv("OWNER_NAME_YOU", raising=False)
    monkeypatch.delenv("OWNER_NAME_HER", raising=False)


def req(**headers):
    return SimpleNamespace(headers=headers)


# ---- resolve_identity ----

def test_owner_address_is_you():
    who = resolve_identity(req(**{IDENTITY_HEADER: YOU}))
    assert (who.owner, who.name, who.email) == ("you", "Benji", YOU)


def test_owner_address_matches_case_insensitively():
    assert resolve_identity(req(**{IDENTITY_HEADER: "You@Example.COM"})).owner == "you"


def test_any_other_address_is_her():
    who = resolve_identity(req(**{IDENTITY_HEADER: OTHER}))
    assert (who.owner, who.name, who.email) == ("her", "Georgina", OTHER)


def test_no_header_is_not_signed_in():
    for r in (req(), req(**{IDENTITY_HEADER: "  "}), None):
        who = resolve_identity(r)
        assert (who.owner, who.name, who.email) == (None, "Not signed in", None)


def test_env_names_override(monkeypatch):
    monkeypatch.setenv("OWNER_NAME_YOU", "B")
    monkeypatch.setenv("OWNER_NAME_HER", "G")
    assert resolve_identity(req(**{IDENTITY_HEADER: YOU})).name == "B"
    assert resolve_identity(req(**{IDENTITY_HEADER: OTHER})).name == "G"


# ---- owner view follows the signed-in user ----

def test_signed_in_view_ignores_query_and_sets_no_cookie(client):  # noqa: F811
    resp = client.get("/a/mixed?owner_view=both", headers=AS_HER)
    assert "HER-VAL" in resp.text and "YOU-VAL" not in resp.text and "SHARED-VAL" in resp.text
    assert "owner_view" not in resp.headers.get("set-cookie", "")
    resp = client.get("/a/mixed?owner_view=her", headers=AS_YOU)
    assert "YOU-VAL" in resp.text and "HER-VAL" not in resp.text
    assert "owner_view" not in resp.headers.get("set-cookie", "")


def test_signed_in_view_ignores_cookie(client):  # noqa: F811
    client.get("/a/mixed?owner_view=her")          # local switch sets the cookie
    html = client.get("/a/mixed", headers=AS_YOU).text
    assert "YOU-VAL" in html and "HER-VAL" not in html


def test_without_header_the_query_still_works_and_sets_cookie(client):  # noqa: F811
    resp = client.get("/a/mixed?owner_view=you")
    assert "YOU-VAL" in resp.text and "HER-VAL" not in resp.text
    assert "owner_view=you" in resp.headers.get("set-cookie", "")


# ---- shell: top-bar chip, greeting, no switcher ----

def topbar_of(html):
    return re.search(r'<header class="topbar">.*?</header>', html, re.S).group(0)


def test_top_bar_chip_shows_the_signed_in_user(client):  # noqa: F811
    html = client.get("/", headers=AS_YOU).text
    bar = topbar_of(html)
    assert f'class="userchip" title="{YOU}"' in bar and '<span class="uname">Benji</span>' in bar
    assert '<span class="avatar" aria-hidden="true">B</span>' in bar and f"<small>{YOU}</small>" in bar
    assert bar.index("toplinks") < bar.index("userchip")   # section pills, then the chip at the right
    her = client.get("/", headers=AS_HER).text
    assert '<span class="uname">Georgina</span>' in topbar_of(her)


def test_not_signed_in_shell(client):  # noqa: F811
    html = client.get("/").text
    bar = topbar_of(html)
    assert '<span class="uname">Not signed in</span>' in bar and "<small>Local preview</small>" in bar
    assert '<div class="userchip">' in bar and "title=" not in bar.split("userchip", 1)[1]


def test_greeting_with_and_without_a_name(client, monkeypatch):  # noqa: F811
    import hub.main
    monkeypatch.setattr(hub.main, "_now_home",
                        lambda: datetime(2026, 10, 6, 19, 45, tzinfo=ZoneInfo("Australia/Melbourne")))
    signed = client.get("/", headers=AS_YOU).text
    anon = client.get("/").text
    assert "Good evening, Benji. Here&#39;s what&#39;s happening at home today, Tuesday 6 October." in signed
    assert "Good evening. Here&#39;s what&#39;s happening at home today, Tuesday 6 October." in anon
    assert "Benji" not in anon.split("<main", 1)[1]


def test_no_owner_switcher_in_shell_or_media_pages(client, env):  # noqa: F811
    pages = [client.get(p).text for p in ("/", "/a/mixed", "/weather")]
    build, _db = env
    with build() as media:
        pages += [media.get(p).text for p in ("/media/history", "/media/diary", "/media/playing")]
    for html in pages:
        assert 'class="switcher"' not in html and "owner_view=" not in html
        assert ">Both<" not in html


def test_brand_reads_just_joey(client):  # noqa: F811
    bar = topbar_of(client.get("/").text)
    brand = re.search(r'<a class="brand" href="/" aria-label="Joey home">(.*?)</a>', bar, re.S).group(1)
    assert "joeyhome.net" not in bar
    assert "/static/brand-joey.jpg?v=" in brand and "<b>Joey</b>" in brand


# ---- writes land as the signed-in user ----

def test_rating_write_under_her_header_lands_as_her(env):
    build, _db = env
    with build() as c:
        c.cookies.set("owner_view", "you")
        resp = c.post("/media/rate?owner_view=you", data=rate_form(score=4),
                      headers={**HX, **AS_HER})
        assert resp.status_code == 200
        c.post("/media/settings/rating_level?owner_view=you", data={"value": "episode"},
               headers={**HX, **AS_HER})
    assert media_db.get_rating("tmdb:1", "her")["score"] == 4
    assert media_db.get_rating("tmdb:1", "you") is None
    assert media_db.rating_level("her") == "episode" and media_db.rating_level("you") == "show"


def test_rating_write_under_you_header_lands_as_you(env):
    build, _db = env
    with build() as c:
        c.post("/media/rate?owner_view=her", data=rate_form(score=9), headers={**HX, **AS_YOU})
    assert media_db.get_rating("tmdb:1", "you")["score"] == 9
    assert media_db.get_rating("tmdb:1", "her") is None
