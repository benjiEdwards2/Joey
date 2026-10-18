"""Joey TV WP-A2 (2026-10-18; D-P6 refined by D-P14, Q8): the owner rule for a Jellyfin user id.

`hub.identity.owner_for_jellyfin(user_id)`: 'her' = the JELLYFIN_USER_HER user's id; 'you' = the JELLYFIN_USER user's id
or a JELLYFIN_USER_ALIASES user's id; anyone else = 'jf:' + the id lowercased, dashes stripped. The names are resolved to
ids ONCE through /Users and cached (a rename never turns B. into a friend); a failed /Users read is never 'you'.
Invented names only (rule 20)."""
import logging
import re

import pytest

from hub import identity

YOU_ID = "11111111111111111111111111111111"
HER_ID = "22222222222222222222222222222222"
ALIAS_ID = "33333333333333333333333333333333"
FRIEND_ID = "ABCDEF0123456789ABCDEF0123456789"
USERS = [{"Name": "Sample Person", "Id": YOU_ID, "Policy": {"IsAdministrator": True}},
         {"Name": "Sample Partner", "Id": HER_ID},
         {"Name": "Sample Outside", "Id": ALIAS_ID},
         {"Name": "Sample Friend", "Id": FRIEND_ID.lower()}]


class Users:
    """A fake /Users read: counts calls; `error` raises instead."""

    def __init__(self, users=USERS, error=None):
        self.users, self.error, self.calls = users, error, 0

    def __call__(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.users


@pytest.fixture(autouse=True)
def names(monkeypatch):
    monkeypatch.setenv("JELLYFIN_USER", "Sample Person")
    monkeypatch.setenv("JELLYFIN_USER_HER", "Sample Partner")
    monkeypatch.delenv("JELLYFIN_USER_ALIASES", raising=False)
    identity.clear_jellyfin_owners()
    yield
    identity.clear_jellyfin_owners()


def test_owner_key_format_frozen():
    assert identity.OWNER_KEY_RE == r"^jf:[0-9a-f]{32}$"


def test_friend_id_becomes_a_lowercase_jf_key():                                           # (a)
    owner = identity.owner_for_jellyfin(FRIEND_ID, users_of=Users())
    assert owner == "jf:abcdef0123456789abcdef0123456789" and re.match(identity.OWNER_KEY_RE, owner)


def test_dashed_guid_is_stripped_to_32_hex():
    dashed = "abcdef01-2345-6789-ABCD-ef0123456789"
    assert identity.owner_for_jellyfin(dashed, users_of=Users()) == "jf:abcdef0123456789abcdef0123456789"


def test_household_names_map_to_you_and_her():                                             # (b)
    users = Users()
    assert identity.owner_for_jellyfin(YOU_ID, users_of=users) == "you"
    assert identity.owner_for_jellyfin(HER_ID, users_of=users) == "her"
    assert identity.owner_for_jellyfin(YOU_ID.upper(), users_of=users) == "you"     # ids compare normalised


def test_unset_jellyfin_user_means_nobody_is_you_with_one_warning(monkeypatch, caplog):   # (e)
    monkeypatch.delenv("JELLYFIN_USER")
    users = Users()
    with caplog.at_level(logging.WARNING, logger="hub.identity"):
        assert identity.owner_for_jellyfin(YOU_ID, users_of=users) == f"jf:{YOU_ID}"
        assert identity.owner_for_jellyfin(YOU_ID, users_of=users) == f"jf:{YOU_ID}"
        assert identity.owner_for_jellyfin(HER_ID, users_of=users) == "her"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "JELLYFIN_USER" in warnings[0].getMessage()
    assert "Sample" not in caplog.text                                                   # never a name in a log


def test_unresolvable_jellyfin_user_means_nobody_is_you(monkeypatch, caplog):
    monkeypatch.setenv("JELLYFIN_USER", "Nobody Here")
    with caplog.at_level(logging.WARNING, logger="hub.identity"):
        assert identity.owner_for_jellyfin(YOU_ID, users_of=Users()) == f"jf:{YOU_ID}"
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1
    assert "Nobody Here" not in caplog.text


@pytest.mark.parametrize("bad", ["", "xyz", "1" * 31, "1" * 33, "g" * 32, f"jf:{YOU_ID}", None, 123,
                                 "abcdef01-2345-6789-abcd-ef012345678"])
def test_malformed_id_is_a_value_error_never_you(bad):                                     # (f)
    with pytest.raises(ValueError):
        identity.owner_for_jellyfin(bad, users_of=Users())


def test_alias_id_and_jellyfin_user_id_are_both_you(monkeypatch):                           # (g)
    monkeypatch.setenv("JELLYFIN_USER_ALIASES", " Sample Outside , ,Missing Alias")
    users = Users()
    assert identity.owner_for_jellyfin(ALIAS_ID, users_of=users) == "you"
    assert identity.owner_for_jellyfin(YOU_ID, users_of=users) == "you"
    assert identity.owner_for_jellyfin(FRIEND_ID, users_of=users).startswith("jf:")


def test_rename_keeps_b_as_you_with_no_re_resolution(monkeypatch):                          # (h)
    first = Users()
    assert identity.owner_for_jellyfin(YOU_ID, users_of=first) == "you"
    renamed = Users([{"Name": "Brand New Name", "Id": YOU_ID}, *USERS[1:]])
    assert identity.owner_for_jellyfin(YOU_ID, users_of=renamed) == "you"
    assert (first.calls, renamed.calls) == (1, 0)                                         # resolved once, cached


def test_failed_users_read_is_never_you_and_the_next_call_retries():                       # (i)
    down = Users(error=ConnectionError("http://jf.invalid secret"))
    with pytest.raises(identity.OwnerUnresolved):
        identity.owner_for_jellyfin(YOU_ID, users_of=down)
    up = Users()
    assert identity.owner_for_jellyfin(YOU_ID, users_of=up) == "you"
    assert (down.calls, up.calls) == (1, 1)


def test_users_read_that_is_not_a_list_is_unresolved():
    with pytest.raises(identity.OwnerUnresolved):
        identity.owner_for_jellyfin(YOU_ID, users_of=Users(users={"error": "nope"}))
