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
        "THE HUB'S TILES READ SNAPSHOTS ONLY",
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
