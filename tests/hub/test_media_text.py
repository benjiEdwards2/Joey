"""W2 (2026-10-09): one copy of Media's text helpers (M-14), one status-word -> colour map (M-19) and the ceremony
orders read from the seed (M-21)."""
from datetime import date, timezone

from hub import media_awards_badges, media_awards_icons, media_awards_seed, media_status_words, media_text


def test_parse_accepts_z_and_jellyfin_fractions_and_rejects_junk():
    at = media_text.parse("2026-10-09T01:02:03.1234567Z")
    assert at.tzinfo is not None and at.utcoffset().total_seconds() == 0 and at.microsecond == 123456
    assert media_text.parse("2026-10-09T01:02:03").tzinfo == timezone.utc       # naive = UTC
    assert media_text.parse("not a date") is None and media_text.parse(None) is None


def test_dates_counts_and_lengths():
    this_year = date.today().year
    assert media_text.date_words("2001-03-14") == ("14 Mar 2001", False)
    assert media_text.date_words(f"{this_year}-03-14", short=True)[0] == "14 Mar"
    assert media_text.short_date("2001-03-02") == "2 Mar 2001" and media_text.short_date("junk") is None
    assert media_text.date_words("2999-01-01")[1] is True
    assert media_text.year("2026-03-14") == 2026 and media_text.year("") is None
    assert media_text.plural(1, "episode") == "1 episode" and media_text.plural(3, "episode") == "3 episodes"
    assert media_text.plural(2, "movie", "movies") == "2 movies"
    assert [media_text.duration(m) for m in (167, 47, 120, 0, None)] == ["2h 47m", "47m", "2h", "—", "—"]


def test_every_request_word_gets_a_colour_class():
    st = media_status_words.status
    assert st("Pending")["cls"] == st("Requested")["cls"] == "st-requested"
    assert st("Approved")["cls"] == st("Processing")["cls"] == "st-processing"
    assert st("Declined")["cls"] == "st-down" and st("On disk")["cls"] == st("Available")["cls"] == "st-available"
    assert st("Not on server") == {"word": "Not on server", "cls": "st-plain"}


def test_ceremony_orders_come_from_the_seed():
    by_sort = [b["id"] for b in sorted(media_awards_seed.BODIES, key=lambda b: b["sort"])]
    assert list(media_awards_icons.BODY_IDS) == by_sort
    assert media_awards_badges.PRESTIGE[0] == "oscars" and set(media_awards_badges.PRESTIGE) == set(by_sort)
    assert sorted(b["prestige"] for b in media_awards_seed.BODIES) == list(range(1, len(by_sort) + 1))


def test_log_reasons_are_status_or_type_only():
    """M-29 (W2): one `why` for every Media log line — never an exception's message (it can hold a URL and key)."""
    import requests
    assert media_text.why(RuntimeError("HTTP 503")) == "HTTP 503"
    assert media_text.why(RuntimeError("http://host/?apikey=SECRET")) == "RuntimeError"
    assert media_text.why(requests.ConnectionError("http://host/?apikey=SECRET")) == "ConnectionError"


def test_every_logging_media_module_has_its_own_logger():
    import re
    from pathlib import Path
    for path in sorted((Path(__file__).resolve().parents[2] / "hub").glob("media_*.py")):
        src = path.read_text(encoding="utf-8")
        assert "exc_info" not in src, path.name
        if re.search(r"\blog\.(warning|info|error)\(", src):
            assert f'logging.getLogger("hub.{path.stem}")' in src, path.name
        assert "md.log." not in src, path.name


def test_media_caches_start_empty_in_every_test():
    """M-60 (W2): tests/hub/conftest.py empties the module caches before each test — this test sees none of the
    entries an earlier test left."""
    from hub import media_discover, media_item, media_omdb
    assert len(media_discover._cache) == len(media_item._cache) == len(media_omdb._mem) == 0
    media_discover._cache["leak:x"] = (0, None)       # the next test must not see this


def test_media_caches_start_empty_in_every_test_again():
    from hub import media_discover
    assert "leak:x" not in media_discover._cache
