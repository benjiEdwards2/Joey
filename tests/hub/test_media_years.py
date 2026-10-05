"""Year rankings pages + write routes (2026-10-05). media.db lives in tmp_path; the pages
must also render with NO db file at all."""
import importlib
import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from hub import media_db
from tests.hub.test_registry import make_area, make_tile
from tests.hub.test_store import write_envelope

SAMPLES = Path(__file__).resolve().parents[2] / "config" / "sample_snapshots"
JELLY = json.loads((SAMPLES / "jellyfin.json").read_text(encoding="utf-8"))["data"]
HX = {"HX-Request": "true"}


def main_of(html):
    return html.split("<main", 1)[1]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    area = make_area("alpha", "play-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/playing")
    area["tiles"].append(make_tile("years-t", snapshot="jellyfin", stale_after_minutes=10,
                                   detail="/media/years", owner="you"))
    path = tmp_path / "areas.yaml"
    path.write_text(yaml.safe_dump({"areas": [area]}), encoding="utf-8")
    monkeypatch.setenv("AREAS_PATH", str(path))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "data" / "media.db"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    write_envelope(tmp_path / "snaps", "jellyfin", age_minutes=1, data=JELLY)
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as c:
        yield c


def rate_some():
    for key, title, year, score in (("tmdb:1", "Alpha Film", 2020, 10), ("tmdb:2", "Bravo Film", 2020, 8),
                                    ("tmdb:3", "Charlie Film", 2020, 7), ("tmdb:4", "Delta Film", 2020, 6),
                                    ("tmdb:5", "Echo Film", 2020, 5), ("tmdb:6", "Foxtrot Film", 2021, 9),
                                    ("tmdb:7", "Golf Film", None, 4)):
        media_db.set_rating(key, score, "movie", title, year, "tmdb:/p.jpg")


def rank_2020(n=4):
    rate_some()
    for k in ("tmdb:1", "tmdb:2", "tmdb:3", "tmdb:4", "tmdb:5")[:n]:
        media_db.place(2020, k)


def titles(year):
    return [r["title"] for r in media_db.year_list(year)["ranked"]]


def test_overview_empty_state_with_no_db(client, tmp_path):
    resp = client.get("/media/years")
    assert resp.status_code == 200
    assert "Rate something first" in resp.text and 'href="/media/history"' in resp.text
    assert not (tmp_path / "data" / "media.db").exists()


def test_overview_tiles_newest_first_unknown_last(client):
    rate_some()
    media_db.place(2020, "tmdb:2")
    body = main_of(client.get("/media/years").text)
    assert body.index("2021") < body.index("2020") < body.index("Unknown year")
    assert "#1 — Bravo Film" in body and "1 ranked" in body
    assert "4 to place" in body and "1 to place" in body
    assert 'href="/media/years/2020"' in body and 'href="/media/years/unknown"' in body
    assert "h=400" in body


def test_year_page_podium_then_rows_from_4(client):
    rank_2020(5)
    body = main_of(client.get("/media/years/2020").text)
    podium = body.split('class="podium"', 1)[1].split('>The rest<', 1)[0]
    assert podium.index("#1") < podium.index("#2") < podium.index("#3") and "#4" not in podium
    assert podium.index("Alpha Film") < podium.index("Bravo Film") < podium.index("Charlie Film")
    rest = body.split(">The rest<", 1)[1].split(">To place<", 1)[0]
    assert "#4" in rest and "Delta Film" in rest and "#5" in rest and "Echo Film" in rest
    assert "▲" not in body and 'href="/media/years/2020/countdown"' in body
    assert "To place" in body and "Everything rated this year is placed" in body


def test_place_via_htmx_appends_and_returns_partial(client):
    rate_some()
    media_db.place(2020, "tmdb:2")
    resp = client.post("/media/years/2020/place", content="item_key=tmdb%3A1", headers=HX)
    assert resp.status_code == 200 and resp.text.lstrip().startswith("<div id=\"yearlist\"")
    assert "<html" not in resp.text
    assert titles(2020) == ["Bravo Film", "Alpha Film"]


def test_place_plain_form_redirects(client):
    rate_some()
    resp = client.post("/media/years/2020/place", content="item_key=tmdb%3A1", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/media/years/2020"
    resp = client.post("/media/years/2020/place", content="item_key=tmdb%3A2&mode=rank", follow_redirects=False)
    assert resp.headers["location"] == "/media/years/2020?mode=rank"


def test_place_rejects_item_from_other_year(client):
    rate_some()
    assert client.post("/media/years/2020/place", content="item_key=tmdb%3A6", headers=HX).status_code == 422
    assert titles(2020) == []


def test_move_up_and_down(client):
    rank_2020(3)
    client.post("/media/years/2020/move", content="item_key=tmdb%3A3&delta=-1", headers=HX)
    assert titles(2020) == ["Alpha Film", "Charlie Film", "Bravo Film"]
    client.post("/media/years/2020/move", content="item_key=tmdb%3A1&delta=1", headers=HX)
    assert titles(2020) == ["Charlie Film", "Alpha Film", "Bravo Film"]
    assert client.post("/media/years/2020/move", content="item_key=tmdb%3A1&delta=5", headers=HX).status_code == 422


def test_unplace_and_reset(client):
    rank_2020(3)
    resp = client.post("/media/years/2020/unplace", content="item_key=tmdb%3A1", headers=HX)
    assert resp.status_code == 200 and titles(2020) == ["Bravo Film", "Charlie Film"]
    assert "Alpha Film" in resp.text.split(">To place<", 1)[1]
    client.post("/media/years/2020/reset", content="", headers=HX)
    assert titles(2020) == []


def test_rank_mode_renders_arrows_and_numbered_rows(client):
    rank_2020(4)
    body = main_of(client.get("/media/years/2020?mode=rank").text)
    assert 'class="podium"' not in body
    assert "▲" in body and "▼" in body and "✕ Unplace" in body
    assert body.count('class="rankno">#') == 4
    assert 'name="mode" value="rank"' in body and 'href="/media/years/2020"' in body  # "Done" link
    assert "hx-post=\"/media/years/2020/move\"" in body


def test_countdown_page_noscript_and_data(client):
    rank_2020(4)
    html = client.get("/media/years/2020/countdown").text
    ns = html.split("<noscript>", 1)[1].split("</noscript>", 1)[0]
    for n, t in enumerate(("Alpha Film", "Bravo Film", "Charlie Film", "Delta Film"), 1):
        assert f"#{n} — {t}" in ns
    data = json.loads(html.split('id="cddata">', 1)[1].split("</script>", 1)[0])
    assert [d["position"] for d in data] == [1, 2, 3, 4] and data[0]["score"] == 10
    assert "keydown" in html and "Escape" in html and "ArrowRight" in html


def test_unknown_year_page(client):
    rate_some()
    media_db.place(None, "tmdb:7")
    body = main_of(client.get("/media/years/unknown").text)
    assert "Unknown year" in body and "#1" in body and "Golf Film" in body
    client.post("/media/years/unknown/place", content="item_key=tmdb%3A7", headers=HX)
    assert titles(None) == ["Golf Film"]


def test_nothing_there_is_404(client):
    assert client.get("/media/years/1999").status_code == 404
    assert client.get("/media/years/banana").status_code == 404
    assert client.get("/media/years/unknown/countdown").status_code == 404
    rate_some()
    assert client.get("/media/years/2020/countdown").status_code == 200   # rated, even if unranked
    assert client.get("/media/years/1999/countdown").status_code == 404


def test_cross_site_write_refused(client):
    rate_some()
    for path in ("place", "move", "unplace", "reset"):
        resp = client.post(f"/media/years/2020/{path}", content="item_key=tmdb%3A1&delta=1",
                           headers={"Origin": "https://evil.example"})
        assert resp.status_code == 403, path
    assert titles(2020) == []
