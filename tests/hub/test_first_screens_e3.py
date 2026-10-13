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


def test_calendar_and_weather_tiles_are_marked_dup_and_hidden_on_a_phone(hub):
    _, body = hub()
    tiles = kpis_of(body)
    assert '<a class="panel tile dup" href="/a/calendar"' in tiles and '<a class="panel tile dup" href="/weather"' in tiles
    classes = re.findall(r'<(?:a|div) class="(panel tile[^"]*)"', tiles)
    assert len(classes) == 4 and sum("dup" in c.split() for c in classes) == 2   # Media and Server stay on a phone
    assert "@media (max-width: 639px) { .tiles > .dup { display: none; } }" in rules()
    assert body.index('class="tiles') < body.index('class="band a"')            # the band follows the tiles


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
