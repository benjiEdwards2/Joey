"""Hub hero card (2026-10-05): hub_rank orders summary cards; a `layout: shelves` area's
card shows the media hero (poster, kind word, title, Jump-back-in deep link). Placement is
asserted inside <main>. Since the Apex hub (2026-10-06) the hero lives in the Media KPI card
(kind word as its label, title as its value) and the poster in the Continue watching shelf."""
import importlib
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hub.registry import load_registry
from tests.hub.test_media_shelves import LINK, JELLY, shelf_area, shelves_for
from tests.hub.test_registry import AREAS_YAML, make_area, write_registry
from tests.hub.test_store import write_envelope

SERVER = "srv-1"
NOW = datetime.now(timezone.utc)


def with_ids(**over):
    d = {**JELLY, "server_id": SERVER}
    d["now_playing"] = [{**d["now_playing"][0], "jf_id": "play-id"}]
    d["up_next"] = [{**d["up_next"][0], "jf_id": "resume-id"}]
    d["latest"] = [{**d["latest"][0], "jf_id": "new-id"}]
    return {**d, **over}


def deep(jf_id, server=SERVER):
    return f"{LINK}/web/#/details?id={jf_id}&serverId={server}"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, make_area("beta"), shelf_area())))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))

    def build(**data):
        for cid, d in data.items():
            write_envelope(snaps, cid, age_minutes=1, data=d)
        import hub.main
        importlib.reload(hub.main)
        return hub.main

    return build


def hub_main(main):
    with TestClient(main.app) as client:
        return client.get("/").text.split("<main", 1)[1]


def test_hub_rank_sorts_cards_and_defaults_to_100(tmp_path, monkeypatch):
    first, second, third = make_area("aa"), make_area("bb"), make_area("cc")
    second["hub_rank"] = 1
    reg = load_registry(write_registry(tmp_path, first, second, third))
    assert [a.hub_rank for a in reg.areas] == [100, 1, 100]
    assert [a.id for a in reg.areas] == ["aa", "bb", "cc"]  # area order untouched
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, first, second, third)))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    import hub.main
    importlib.reload(hub.main)
    html = hub_main(hub.main)
    assert [html.index(f'href="/a/{i}"') for i in ("bb", "aa", "cc")] == sorted(
        html.index(f'href="/a/{i}"') for i in ("bb", "aa", "cc"))
    assert [a.id for a in hub.main.shell.registry.areas] == ["aa", "bb", "cc"]


def test_real_registry_media_leads_the_hub():
    reg = load_registry(AREAS_YAML)
    by = {a.id: a for a in reg.areas}
    assert by["media"].hub_rank == 1
    assert all(a.hub_rank == 100 for a in reg.areas if a.id != "media")


@pytest.mark.parametrize("data,kind,title,jf", [
    (with_ids(), "Playing now", "Playing Now Title", "play-id"),
    (with_ids(now_playing=[]), "Jump back in", "Dust and Daylight", "resume-id"),
    (with_ids(now_playing=[], up_next=[]), "Newest arrival", "Fresh Film", "new-id"),
])
def test_hub_card_renders_hero_with_deep_link(env, data, kind, title, jf):
    html = hub_main(env(jellyfin=data))
    assert f'<div class="row-meta">{kind}' in html and f'>{title}</div>' in html
    assert "/img/jf:" in html or "/img/none" in html
    assert f'href="{deep(jf).replace("&", "&amp;")}" target="_blank" rel="noopener">Jump back in ↗' in html
    assert 'href="/a/alpha"' in html


def test_hub_card_has_no_jump_link_without_an_id(env):
    html = hub_main(env(jellyfin=JELLY))  # rows carry no jf_id
    assert '<div class="row-meta">Playing now' in html and "Jump back in ↗" not in html


def test_deep_link_omits_server_id_when_unknown(env):
    html = hub_main(env(jellyfin=with_ids(server_id=None)))
    assert f'href="{LINK}/web/#/details?id=play-id"' in html


def test_hub_card_falls_back_to_plain_tile_without_snapshot(env):
    html = hub_main(env())
    assert "herocard" not in html and "Jump back in" not in html
    # Apex hub (2026-10-06): the bento size class is gone; no hero -> a plain whole-card KPI link
    # a lone card now also carries the `span2` class (kpis few, 2026-10-06)
    assert re.search(r'<a class="panel tile( span2)?" href="/a/alpha"', html)


def test_no_nested_anchors_on_the_hub(env):
    html = hub_main(env(jellyfin=with_ids()))
    assert "Jump back in ↗" in html  # Apex hub (2026-10-06): the split Media KPI replaced .herocard
    for chunk in re.findall(r"<a\b.*?</a>", html, flags=re.S):
        assert chunk.count("<a ") == 1, chunk


def test_media_hero_and_shelves_hero_agree(env):
    main = env(jellyfin=with_ids())
    sh = shelves_for(main)
    hero = main.media_hero(with_ids(), LINK)
    assert hero["title"] == sh["hero"]["title"] == "Playing Now Title"
    assert hero["href"] == sh["hero"]["href"] == deep("play-id")
    resume = with_ids(now_playing=[])
    assert main.media_hero(resume, LINK)["title"] == shelves_for(env(jellyfin=resume))["hero"]["title"]
    assert main.media_hero({}, LINK) is None
    assert main.media_hero(with_ids(), None)["href"] is None  # no launcher -> no fabricated link
