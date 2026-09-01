"""WP9 drill (b): a deliberately failing test — proves deploy.sh aborts at the
full-suite gate with the live stack untouched and no PASS line. Deleted (with
its revert commit) immediately after the drill; this is NOT a suite weakening,
the file exists only to be red."""


def test_drill_b_deliberate_failure():
    assert False, "WP9 drill (b): the gate must stop this deploy"
