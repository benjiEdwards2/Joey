"""WP23 step 6 — the contract doc must be actionable from repo contents alone.

A fresh agent following the add-a-connector checklist has to be able to open
every file it names, so the checklist is checked against the filesystem.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "connector-contract.md"


def doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def checklist() -> str:
    return doc_text().split("## Add-a-connector checklist", 1)[1]


def test_every_path_the_checklist_names_exists():
    # paths look like `connectors/stubs.py` or `connectors/fixtures/{id}/raw*.json`
    paths = set(re.findall(r"`([a-z][\w./{}*-]+\.(?:py|json|yaml|md|example))`", checklist()))
    assert paths, "the checklist stopped naming files"
    missing = []
    for raw in paths:
        concrete = raw.replace("{id}", "open_meteo").replace("raw*", "raw")
        if not (REPO_ROOT / concrete).exists():
            missing.append(raw)
    # .env.example is WP5/WP9's to create; it is named so a new credential is
    # never forgotten, and is the one allowed forward reference.
    assert missing == ["deploy/.env.example"] or missing == [], missing


def test_the_load_bearing_rules_are_stated():
    text = doc_text()
    for rule in [
        "TILES READ SNAPSHOTS; THE NUMBERED EXCEPTIONS BELOW ARE THE ONLY LIVE PATHS",
        "Notion is LINK tier",
        "2026-01-01T00:00:00+00:00",
        "you | her | shared",
        "≥ 3 triggers the notifier",
        "first engine-verify",
    ]:
        assert rule in text, f"contract doc no longer states: {rule}"


def test_money_special_case_is_documented():
    text = doc_text()
    assert "D14" in text
    assert "empty" in text and "status=ok" in text


def test_awards_exception_is_documented():
    """Awards (2026-10-08): the sixteenth exception names both hosts, the contact gate and the off switch."""
    text = doc_text()
    para = text.split("**Sixteenth exception (2026-10-08): Awards sync", 1)[1].split("\n\n", 1)[0]
    for needle in ("query.wikidata.org/sparql", "en.wikipedia.org/w/api.php", "AWARDS_CONTACT", "MEDIA_AWARDS=off",
                   "Retry-After", "award_nomination", "status / exception type only"):
        assert needle in para, needle
    assert "@" not in para          # the contact address itself never appears in the repo


def test_arr_wp_u1_fields_and_why_exception_are_documented():
    """WP-U1 (2026-10-21): the additive `upgrades` fields and the hub's interactive search + grab live paths."""
    text = doc_text()
    para = text.split("**Arr upgrades: honest words + last search (WP-U1, 2026-10-21).**", 1)[1].split("\n\n", 1)[0]
    for needle in ("WEB/Bluray 1080p", "`profile`", "`episode_id`", "`upgrades.last_search`", "GET /api/v3/command",
                   "CutoffUnmetEpisodeSearch", "MissingMoviesSearch", "200 characters", "no `partial_errors` entry"):
        assert needle in para, needle
    why = text.split("*Why? + Grab anyway (2026-10-21, WP-U1, `hub/media_upgrade_why.py`):*", 1)[1].split("\n\n", 1)[0]
    for needle in ("GET /api/v3/release?movieId=", "GET /api/v3/release?episodeId=", "90 s", "1 h", "POST /api/v3/release",
                   "never from the form", "same_origin", "The page render never calls"):
        assert needle in why, needle


def test_arr_library_sizes_are_documented():
    """P1a (2026-10-22): the additive `library_sizes` block and the field names it reads."""
    para = doc_text().split("**Arr library sizes (P1a, 2026-10-22).**", 1)[1].split("\n\n", 1)[0]
    for needle in ("`library_sizes`", "GET /api/v3/movie", "`hasFile`", "`sizeOnDisk`", "GET /api/v3/series",
                   "`statistics.sizeOnDisk`", "`ended`", "no extra call", "never by title", "`GET /server/space`"):
        assert needle in para, needle


def test_approve_decline_exception_and_jellyseerr_fields_are_documented():
    """WP-RQ1 (2026-10-22): the Approve / Decline live writes and the jellyseerr block's pending rule + new row fields."""
    text = doc_text()
    para = text.split("**Twentieth exception (2026-10-22): Approve / Decline a request", 1)[1].split("\n\n", 1)[0]
    for needle in ("GET /api/v1/request/{id}", "PUT /api/v1/request/{id}", "POST /api/v1/request/{id}/approve",
                   "POST /api/v1/request/{id}/decline", "serverId", "rootFolder", "languageProfileId", "userId", "202",
                   "same_origin", "filter=pending", "`profile_id`", "`requested_by_id`", "`seasons`", "capped at 60",
                   "status or exception type only"):
        assert needle in para, needle
