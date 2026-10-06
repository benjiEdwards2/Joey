"""WP23 step 1 — the fixtures pack is safe, parseable, and covers the ICS cases."""

import json
import re
from pathlib import Path

import icalendar
import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "connectors" / "fixtures"

EXPECTED_FEEDS = {
    "open_meteo", "gcal", "macromates", "home_assistant", "jellyfin", "nas_stats",
    "media_status", "arr", "jellyseerr", "qbittorrent", "system", "wud", "uptime_kuma",
}

EMAIL = re.compile(r"[\w.+-]+@[\w.-]+")
# 24+ chars of mixed letters AND digits reads like a key or bearer token
TOKEN_SHAPED = re.compile(
    r"\b(?=[A-Za-z0-9_\-]*[A-Za-z])(?=[A-Za-z0-9_\-]*[0-9])[A-Za-z0-9_\-]{24,}\b"
)
URL = re.compile(r"https?://\S+")


def fixture_files() -> list[Path]:
    return sorted(p for p in FIXTURES.rglob("*") if p.is_file())


def test_every_v1_feed_has_a_fixture_and_clickup_has_none():
    dirs = {p.name for p in FIXTURES.iterdir() if p.is_dir()}
    assert dirs == EXPECTED_FEEDS
    assert "clickup" not in dirs, "ClickUp was removed from v1 (2026-08-25)"


@pytest.mark.parametrize("path", fixture_files(), ids=lambda p: p.name)
def test_no_real_identifiers_leak_into_fixtures(path):
    text = path.read_text(encoding="utf-8")
    for address in EMAIL.findall(text):
        assert address.endswith("@example.invalid"), f"real-looking email {address}"
    assert not URL.findall(text), "no URL belongs in a fixture — secret ICS URLs live in .env"
    assert not TOKEN_SHAPED.findall(text), "token-shaped string in a fixture"


def test_json_fixtures_parse():
    files = [p for p in fixture_files() if p.suffix == ".json"]
    assert files
    for path in files:
        json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["raw_you.ics", "raw_her.ics"])
def test_ics_fixtures_parse_and_carry_the_three_hard_cases(name):
    calendar = icalendar.Calendar.from_ical(
        (FIXTURES / "gcal" / name).read_text(encoding="utf-8")
    )
    events = list(calendar.walk("VEVENT"))
    assert len(events) == 3

    assert any("RRULE" in e for e in events), "no recurring event"
    assert any(
        e["DTSTART"].params.get("VALUE") == "DATE" for e in events
    ), "no all-day event"
    assert any(
        str(e["DTSTART"].to_ical()).endswith("Z'") for e in events
    ), "no UTC/offset event"


def test_her_calendar_is_outlook_generated():
    text = (FIXTURES / "gcal" / "raw_her.ics").read_text(encoding="utf-8")
    assert "Microsoft Exchange" in text          # Outlook/Exchange PRODID
    assert "X-MICROSOFT-CDO-ALLDAYEVENT" in text  # the CDO all-day quirk
    assert "UNTIL=" in text                       # UTC UNTIL against a TZID DTSTART


def test_nas_fixture_is_a_real_directory_tree():
    tree = FIXTURES / "nas_stats" / "tree"
    shares = {p.name for p in tree.iterdir() if p.is_dir()}
    assert shares == {"media", "documents", "photos"}
    assert len([p for p in tree.rglob("*") if p.is_file()]) == 6
