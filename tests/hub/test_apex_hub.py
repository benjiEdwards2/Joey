"""Apex hub page (2026-10-06; restyle Phase 4): a row of summary tiles (one per registry area + Weather), Band A
(Next 7 days rows + the weather glimpse), Band B (Continue watching / Recently watched carousels). Runs the REAL
registry against the committed sample snapshots (re-stamped fresh); placement asserted inside <main>. Only real
snapshot data: not-connected tiles carry no spark, owners are words."""
import importlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.hub.helpers import write_envelope

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "config" / "sample_snapshots"
SAMPLE_DATA = {p.stem: json.loads(p.read_text(encoding="utf-8"))["data"]
               for p in SAMPLES.glob("*.json") if not p.stem.startswith("_")}


def all_day(title, offset, owner):
    """An all-day event `offset` days from today (clock-independent: never 'already over')."""
    day = datetime.now().astimezone().date() + timedelta(days=offset)
    return {"title": title, "start": day.isoformat(), "end": (day + timedelta(days=1)).isoformat(),
            "all_day": True, "owner": owner}


EVENTS = [all_day("Bins out", 0, "shared"), all_day("YOU-ONLY trip", 1, "you"),
          all_day("Her netball", 2, "her")]


@pytest.fixture()
def hub(tmp_path, monkeypatch):
    monkeypatch.delenv("AREAS_PATH", raising=False)  # the real config/areas.yaml
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))

    def get(view="both", drop=(), **override):
        data = {**SAMPLE_DATA, "gcal": {**SAMPLE_DATA["gcal"], "events": EVENTS}, **override}
        for cid, d in data.items():
            if cid not in drop:
                write_envelope(snaps, cid, age_minutes=1, data=d)
        import hub.main
        importlib.reload(hub.main)
        with TestClient(hub.main.app) as client:
            html = client.get(f"/?owner_view={view}").text
        return hub.main, html.split("<main", 1)[1].split("</main>", 1)[0]

    return get


def kpis_of(body):
    return re.search(r'<section class="tiles[^"]*".*?</section>', body, re.S).group(0)


def cards_of(body):
    """href -> tile html, for whole-tile links and split (div) tiles alike."""
    k = kpis_of(body)
    out = {href: inner for href, inner in re.findall(r'<a class="panel tile[^"]*" href="([^"]+)"[^>]*>(.*?)</a>', k, re.S)}
    for chunk in re.findall(r'<div class="panel tile split.*?</div>\s*(?=<a class="panel tile|<div class="panel tile|</section>)', k, re.S):
        out[re.search(r'class="tile-body" href="([^"]+)"', chunk).group(1)] = chunk
    return out


def test_every_registry_area_is_a_kpi_card_and_weather_links_to_its_page(hub):
    main, body = hub()
    cards = cards_of(body)
    for a in main.shell.registry.visible_areas:   # parked (hidden) areas have no hub card (2026-10-06)
        assert f"/a/{a.id}" in cards, a.id
        assert f'<div class="microlabel">{a.name}</div>' in cards[f"/a/{a.id}"]
    assert '<a class="panel tile" href="/weather"' in kpis_of(body)
    assert '<div class="microlabel">Weather</div>' in cards["/weather"]
    assert len(cards) == len(main.shell.registry.visible_areas) + 1


def test_not_connected_card_keeps_the_anatomy_without_a_spark(hub):
    _, body = hub(drop=("gcal",))   # money is parked now (hidden) — calendar is the not-connected card
    cards = cards_of(body)
    for href in ("/a/calendar",):
        card = cards[href]
        assert '<div class="tile-value stat-word st-off">Not connected</div>' in card   # a muted word, never amber
        assert "badge" not in card and "spark" not in card


def test_calendar_card_has_seven_real_day_bars(hub):
    _, body = hub()
    card = cards_of(body)["/a/calendar"]
    spark = re.search(r'<svg class="tile-spark".*?</svg>', card, re.S).group(0)
    assert spark.count("<rect ") == 7
    assert "Events per day, next 7 days: 1, 1, 1, 0, 0, 0, 0" in card


def test_media_card_carries_the_hero_title_and_a_sibling_jump_link(hub):
    main, body = hub()
    np = SAMPLE_DATA["jellyfin"]["now_playing"][0]
    card = cards_of(body)["/a/media"]
    assert "Playing now" in card and f">{np['title']}</div>" in card
    assert 'class="btn btn-ghost btn-sm"' in card and "Jump back in ↗" in card
    assert f"details?id={np['jf_id']}" in card
    body_link = re.search(r'<a class="tile-body".*?</a>', card, re.S).group(0)
    assert "<a " not in body_link[3:] and "Jump back in" not in body_link   # siblings, never nested
    assert f'aria-label="{np["progress_pct"]}% watched"' in card            # real progress only
    for chunk in re.findall(r"<a\b.*?</a>", body, flags=re.S):
        assert chunk.count("<a ") == 1, chunk


def test_next_seven_days_rows_have_day_words_and_text_owners(hub):
    _, body = hub()
    table = re.search(r'<section class="sec upcoming".*?</section>', body, re.S).group(0)
    assert '<span class="upc-day">Today</span><span class="sep"> · </span>All day' in table
    assert '<span class="upc-day">Tomorrow</span>' in table
    assert '<div class="upc-head seclabel"' in table                       # the column heads (desktop)
    for word in ("Shared", "You", "Her"):
        assert f'<span class="row-side">{word}</span>' in table
    assert 'href="/a/calendar">All</a>' in body


def test_next_seven_days_empty_sentence(hub):
    _, body = hub(gcal={"summary": "Nothing on", "events": []})
    assert "Nothing in the next 7 days" in body


def test_her_view_hides_you_only_rows(hub):
    _, body = hub(view="her")
    table = re.search(r'<section class="sec upcoming".*?</section>', body, re.S).group(0)
    assert "YOU-ONLY trip" not in table and "Her netball" in table and "Bins out" in table


def test_weather_band_card_shows_glyph_word_and_today_range(hub):
    _, body = hub()
    wx = re.search(r'<section class="sec wxglimpse".*?</section>', body, re.S).group(0)
    d = SAMPLE_DATA["open_meteo"]
    assert '<div class="glyph">' in wx and f'<div class="wxword">{d["condition_text"]}</div>' in wx
    assert f'{d["today_min_c"]} °C' in wx and f'{d["today_max_c"]} °C' in wx and f'{d["rain_prob_pct"]}%' in wx


def test_continue_watching_shelf_renders_up_next_with_posters(hub):
    """media-ux2 (2026-10-08, B.): Continue watching left the hub (Media home keeps it); Recently watched stays."""
    _, body = hub()
    assert 'id="continue"' not in body and "Continue watching" not in body
    assert "/media/resume/" not in body                         # no Move on actions on the hub
    band = body.split('id="recent"', 1)[1]
    assert "Recently watched" in band and 'class="card-poster"' in band


def test_continue_watching_her_view_and_empty_sentence(hub):
    _, her = hub(view="her")
    assert 'id="continue"' not in her and "Nothing up next" not in her
    jelly = {**SAMPLE_DATA["jellyfin"], "up_next": [], "her": None}
    _, body = hub(jellyfin=jelly)
    assert '<p class="empty">Nothing up next</p>' not in body


def test_hub_main_has_no_literal_hex_colour(hub):
    _, body = hub()
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", re.sub(r'href="[^"]*"', "", body))
