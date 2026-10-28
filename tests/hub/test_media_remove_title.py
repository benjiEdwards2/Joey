"""JY-265 phase 1: the title page's More fold carries "Remove…" for owner "you" with REMOVE_API on, when a Seerr
request exists in the cached rows - and for nobody else. Built on the film-page fixture (tests/hub/helpers.env)."""
from tests.hub.helpers import env  # noqa: F401  (the film-page fixture)

LINE = '<a class="btn btn-danger" href="/media/remove/movie/701">Remove…</a>'
ROW = {"id": 31, "kind": "movie", "tmdb_id": 701, "title": "Plain Film", "requested_by": "Sam", "when": "3 hours ago",
       "status_text": "Approved"}


def page(env, rows=(ROW,), headers=None):
    client, both = env(seerr_snap=list(rows))
    with client:
        return client.get("/media/title/movie/701", headers=headers or {}).text, both


def test_owner_sees_remove_in_the_more_fold(env, monkeypatch):
    monkeypatch.setenv("REMOVE_API", "on")
    html, _ = page(env)
    assert LINE in html
    fold = html.index('class="fold heromore"')
    assert fold < html.index(LINE) < html.index("</details>", fold)


def test_flag_off_no_line(env, monkeypatch):
    monkeypatch.delenv("REMOVE_API", raising=False)
    assert LINE not in page(env)[0]
    monkeypatch.setenv("REMOVE_API", "off")
    assert LINE not in page(env)[0]


def test_her_never_sees_the_line(env, monkeypatch):
    from hub.identity import IDENTITY_HEADER
    monkeypatch.setenv("REMOVE_API", "on")
    monkeypatch.setenv("OWNER_EMAIL_YOU", "you@example.invalid")
    assert LINE not in page(env, headers={IDENTITY_HEADER: "her@example.invalid"})[0]
    assert LINE in page(env, headers={IDENTITY_HEADER: "you@example.invalid"})[0]


def test_no_request_no_line_and_a_tv_request_does_not_match_a_film(env, monkeypatch):
    monkeypatch.setenv("REMOVE_API", "on")
    assert "/media/remove/" not in page(env, rows=())[0]
    assert "/media/remove/" not in page(env, rows=({**ROW, "kind": "tv"},))[0]


def test_the_line_adds_no_upstream_call(env, monkeypatch):
    """The More line reads the cached Seerr rows: no request, Radarr or Sonarr read is made for it."""
    monkeypatch.setenv("REMOVE_API", "on")
    html, both = page(env)
    assert LINE in html
    assert not [c for c in both.calls if "/api/v1/request" in c or "/api/v3/" in c]
