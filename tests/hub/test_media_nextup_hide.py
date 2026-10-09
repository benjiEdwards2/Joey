"""media-ux2 item 6 (2026-10-08): "Hide" a Next Up suggestion without marking it watched. Stored per owner in
media.db (series + the suggested episode id), no Jellyfin call; hidden everywhere until Next Up suggests a different
episode of that series. Fixtures are test_media_resume's (Jellyfin faked, no network)."""
import json
from datetime import datetime, timedelta, timezone

from hub import media_backup, media_db, media_hidden, media_resume
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.test_media_resume import env, ORIGIN_BAD, MINE  # noqa: F401  (env fixture)


def hide(client, jf="ep5", series="jf:ser1", back="/media/playing", **extra):
    return client.post(f"/media/resume/{jf}/hide", data={"back": back, "series": series, **extra},
                       follow_redirects=False)


def rewrite_snapshot(snaps, up_next=None, her_up_next=None, newer=True):
    """A later jellyfin sweep: optionally a new up_next list, stamped well after any in-memory hide."""
    doc = json.loads((snaps / "jellyfin.json").read_text(encoding="utf-8"))
    if up_next is not None:
        doc["data"]["up_next"] = up_next
    if her_up_next is not None:
        doc["data"]["her"]["up_next"] = her_up_next
    if newer:
        ts = (datetime.now(timezone.utc) + timedelta(seconds=media_hidden.GRACE_S + 5)).isoformat()
        doc["updated_at"] = doc["fetched_at"] = ts
    (snaps / "jellyfin.json").write_text(json.dumps(doc), encoding="utf-8")


def test_next_up_rows_offer_hide_and_resume_rows_do_not(env):
    client, _, _ = env()
    with client:
        body = main_of(client.get("/media/playing").text)
        home = main_of(client.get("/a/alpha").text)
    rows = body.split('<div class="rowwrap resumerow">')
    first, second = rows[1], rows[2]
    assert "/media/resume/mov1/hide" not in first                      # a resume row: Mark watched + Reset only
    acts = second.split("</a>", 1)[1]
    assert 'action="/media/resume/ep5/hide"' in acts and ">Hide</button>" in acts
    assert 'name="series" value="jf:ser1"' in acts and 'action="/media/resume/ep5/watched"' in acts
    move_on = home.split('action="/media/resume/ep5/hide"', 1)
    assert len(move_on) == 2 and "Move on" in move_on[0].rsplit('<div class="card-wrap">', 1)[1]


def test_hide_flashes_hidden_and_makes_no_jellyfin_call(env):
    client, fake, _ = env()
    with client:
        r = hide(client)
        page = main_of(client.get(r.headers["location"]).text)
        home = main_of(client.get("/a/alpha").text)
        hub_page = main_of(client.get("/").text)
    assert r.status_code == 303 and r.headers["location"] == "/media/playing?done=hide"
    assert '<p class="metaline st-good" role="status">Hidden</p>' in page
    for html in (page, home, hub_page):
        assert "Quiet Show" not in html
        assert "Dust and Daylight" in html                              # the resume row stays
    assert fake.posts == []
    assert media_db.next_up_hidden() == {("you", "jf:ser1"): "ep5"}


def test_hide_persists_across_newer_snapshots_with_the_same_suggestion(env):
    client, _, snaps = env()
    with client:
        hide(client)
        media_hidden.clear()                                            # not the in-memory hide-until-sweep
        rewrite_snapshot(snaps)                                         # a later sweep, same Next Up
        assert "Quiet Show" not in main_of(client.get("/media/playing").text)


def test_reappears_when_next_up_suggests_a_different_episode(env):
    client, _, snaps = env()
    with client:
        hide(client)
        nxt = [dict(MINE[0]), {**MINE[1], "title": "Quiet Show · S04E06 · Six", "jf_id": "ep6"}]
        rewrite_snapshot(snaps, up_next=nxt)
        body = main_of(client.get("/media/playing").text)
    assert "Quiet Show · S04E06 · Six" in body


def test_resume_row_of_the_hidden_episode_is_never_dropped(env):
    client, _, snaps = env()
    with client:
        hide(client)
        resumed = [{**MINE[1], "remaining_text": "20 min left"}]       # B. started ep5: now a resume row
        rewrite_snapshot(snaps, up_next=resumed)
        assert "Quiet Show" in main_of(client.get("/media/playing").text)


def test_per_owner_isolation(env):
    client, _, snaps = env()
    her_next = [{"title": "Quiet Show · S04E05 · Five", "kind": "episode", "remaining_text": "Next episode",
                 "poster": "jf:ser1", "item_key": "jf:ser1", "jf_id": "ep5", "show_key": "jf:ser1"}]
    rewrite_snapshot(snaps, her_up_next=her_next, newer=False)
    with client:
        hide(client)                                                    # B. (default you view) hides it
        client.cookies.set("owner_view", "her")
        her = main_of(client.get("/media/playing").text)
        hide(client, owner="you")                                       # her view: the form can't pick "you"
    assert "Quiet Show" in her                                          # her suggestion untouched by his hide
    assert media_db.next_up_hidden() == {("you", "jf:ser1"): "ep5", ("her", "jf:ser1"): "ep5"}


def test_hide_requires_same_origin_and_valid_input(env):
    client, _, _ = env()
    with client:
        assert client.post("/media/resume/ep5/hide", data={"series": "jf:ser1"}, headers=ORIGIN_BAD,
                           follow_redirects=False).status_code == 403
        assert hide(client, series="javascript:x").status_code == 422
        assert hide(client, jf="bad id!").status_code == 404
        r = hide(client, back="https://evil.invalid/")
    assert r.headers["location"] == "/media/playing?done=hide"
    assert media_db.next_up_hidden() == {("you", "jf:ser1"): "ep5"}


def test_no_db_file_needed_to_read(env, tmp_path):
    client, _, _ = env()
    with client:
        assert client.get("/media/playing").status_code == 200
    assert media_db.next_up_hidden() == {} and not (tmp_path / "media.db").exists()


def test_drop_dismissed_helper():
    rows = [{"jf_id": "e1", "show_key": "jf:s", "remaining_text": "Next episode"},
            {"jf_id": "e1", "show_key": "jf:s", "remaining_text": "3 min left"},
            {"jf_id": "e2", "item_key": "jf:t", "remaining_text": "Next episode"}]
    out = media_resume.drop_dismissed(rows, "you", {("you", "jf:s"): "e1", ("her", "jf:t"): "e2"})
    assert out == rows[1:]
    assert media_resume.series_of({"item_key": "jf:t"}) == "jf:t" and media_resume.series_of({}) is None


def test_backup_copies_the_whole_db_including_the_hide_table(env, tmp_path):
    media_db.hide_next_up("you", "jf:ser1", "ep5")
    dest = tmp_path / "bk"
    dest.mkdir()
    out = media_backup.backup_now(media_db.db_path(), dest, datetime.now(timezone.utc))
    import gzip
    import sqlite3
    raw = tmp_path / "restored.db"
    raw.write_bytes(gzip.decompress(out.read_bytes()))
    with sqlite3.connect(raw) as db:
        assert db.execute("SELECT owner, series_key, episode_id FROM nextup_hidden").fetchall() == [
            ("you", "jf:ser1", "ep5")]
