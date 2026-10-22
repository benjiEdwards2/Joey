"""WP-U3 commit A (B., 2026-10-07: "silence parked alerts"): a connector is NOT CONFIGURED when
(a) its latest error is a MissingCredential, or (b) no visible area reads its snapshot. Not
configured ⇒ never an Attention item, never a Discord post, never the hub card's warn state;
the Sweeps (24 h) table says "Not configured" instead of "Failing"; stale seen-rows are purged.
An unconfigured LIVE connector (jellyseerr with its env unset) is a setup task, not an alert."""
import sqlite3
from datetime import datetime, timedelta, timezone

from hub import media_db, server, server_alerts
from hub.registry import load_registry
from tests.hub.helpers import AREAS_YAML, write_envelope, write_history
from tests.hub.test_server import ALL_UP, SYSTEM, _snaps, env, main_of, txt  # noqa: F401 (fixture)
from tests.hub.test_server_alerts import posts  # noqa: F401 (fixture)

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
MISSING = "MissingCredential: home_assistant: missing environment variable HA_URL"
SEERR_MISSING = "MissingCredential: jellyseerr: missing environment variable JELLYSEERR_API_KEY"
WUD_ERR = "RuntimeError: WUD containers failed (HTTP 401)"


def _stats(**latest):
    """sweep_stats over two failing runs per connector, `latest` = {cid: error}."""
    lines = [{"ran_at": (NOW - timedelta(minutes=m)).isoformat(),
              "results": {cid: {"status": "error", "error": e} for cid, e in latest.items()}}
             for m in (60, 30)]
    return server.sweep_stats(lines, NOW)


def live():
    return server.live_snapshot_ids(load_registry(AREAS_YAML))


def test_live_snapshot_ids_leave_out_parked_areas():
    ids = live()
    assert {"media_status", "system", "wud", "uptime_kuma", "gcal", "jellyseerr"} <= ids
    assert not ids & {"home_assistant", "macromates", "nas_stats", "money"}   # parked areas only
    assert server.live_snapshot_ids(None) is None


def test_rule_a_missing_credential_is_not_configured_even_on_a_visible_area():
    stats = _stats(home_assistant=MISSING, jellyseerr=SEERR_MISSING, wud=WUD_ERR)
    for lv in (None, live()):   # rule (a) alone suffices, registry or not
        items = server.attention_items({}, {"warning": None}, None, stats, lv)
        assert [i["key"] for i in items] == ["sweep:wud"]
    assert server.not_configured("jellyseerr", "runner-level MissingCredential: x")
    assert not server.not_configured("wud", WUD_ERR, live())


def test_rule_b_parked_or_unreferenced_connector_is_not_configured():
    stats = _stats(nas_stats="RuntimeError: NAS stats failed (HTTP 500)", clickup="RuntimeError: boom",
                   wud=WUD_ERR)
    keys = [i["key"] for i in server.attention_items({}, {"warning": None}, None, stats, live())]
    assert keys == ["sweep:wud"]
    # without a registry rule (b) stays off: the failures are real items again
    keys = [i["key"] for i in server.attention_items({}, {"warning": None}, None, stats)]
    assert keys == ["sweep:clickup", "sweep:nas_stats", "sweep:wud"]


def test_runner_fallback_also_skips_not_configured():
    runner = {"ran_at": NOW.isoformat(), "results": {
        "home_assistant": {"status": "error", "error": MISSING},
        "macromates": {"status": "error", "error": "RuntimeError: boom"},
        "wud": {"status": "error", "error": WUD_ERR}}}
    items = server.attention_items({}, {"warning": None}, runner, None, live())
    assert [i["key"] for i in items] == ["sweep:wud"]


def test_sweep_rows_say_not_configured_instead_of_failing():
    rows = {r["id"]: r for r in server.sweep_rows(_stats(home_assistant=MISSING, wud=WUD_ERR), NOW, live())}
    assert rows["home_assistant"]["failing"] and rows["home_assistant"]["not_configured"]
    assert rows["wud"]["failing"] and not rows["wud"]["not_configured"]


def test_hub_card_stays_ok_with_only_not_configured_failures(tmp_path):
    snaps = _snaps(tmp_path, media_status=ALL_UP, system=SYSTEM)
    hist = [{"ran_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(), "results": {
        "home_assistant": {"status": "error", "error": MISSING},
        "macromates": {"status": "error", "error": "MissingCredential: macromates: missing x"},
        "nas_stats": {"status": "error", "error": "RuntimeError: boom"},
        "jellyseerr": {"status": "error", "error": SEERR_MISSING}}}]
    assert server.hub_card(snaps, set(), {"warning": None}, None, hist, live=live())["state"] == "ok"


def _parked_history(snaps_dir):
    write_history(snaps_dir, [(30, {"home_assistant": ("error", MISSING), "nas_stats": ("error", MISSING),
                                    "jellyseerr": ("error", SEERR_MISSING), "system": "ok"}),
                              (5, {"home_assistant": ("error", MISSING), "nas_stats": ("error", MISSING),
                                   "jellyseerr": ("error", SEERR_MISSING), "system": "ok"})])


def test_page_and_hub_card_stay_clear_and_sweeps_say_not_configured(env, tmp_path):
    client = env(samples=False, media_status=ALL_UP, system=SYSTEM)
    _parked_history(tmp_path / "snaps")
    with client:
        body = main_of(client.get("/server").text)
        card = main_of(client.get("/").text).split('href="/a/server"', 1)[1].split("</a>", 1)[0]
    # E3 (U12, 2026-10-13): nothing to attend to = no Attention band; "All clear" is the sub-line, said once
    assert 'id="attention"' not in body and body.count("All clear") == 1
    assert '<p class="pagehead-sub">All clear</p>' in body
    # WP-T3 (2026-10-19, S5): System's sweeps line + the fold, open on a not-configured row
    assert "4 connectors · 3 not configured" in txt(body) and '<details class="fold" id="sweeps" open>' in body
    sweeps = body.split('id="sweeps"', 1)[1].split("</details>", 1)[0]
    assert ">home_assistant</div>" in sweeps and ">jellyseerr</div>" in sweeps
    assert txt(sweeps).count("Not configured") == 3 and "Failing" not in sweeps
    assert "Needs attention" not in card and "All up" in card


def test_no_discord_post_and_stale_seen_rows_are_purged(posts, tmp_path, monkeypatch):  # noqa: F811
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    monkeypatch.delenv("AREAS_PATH", raising=False)
    write_envelope(snaps, "media_status", age_minutes=1, data=ALL_UP)
    # rows pushed before this change, while the parked connectors were "failing"
    server_alerts.sync([{"key": "sweep:home_assistant", "text": "x"}, {"key": "sweep:jellyseerr", "text": "y"}])
    assert len(posts) == 2
    _parked_history(snaps)
    assert server_alerts.check_once() == 0 and len(posts) == 2          # registry read from config
    with sqlite3.connect(media_db.db_path()) as db:
        assert [r[0] for r in db.execute("SELECT key FROM server_attention_seen")] == []
    # a genuine failure of a configured connector later notifies again
    write_history(snaps, [(0, {"jellyseerr": ("error", "RuntimeError: Jellyseerr failed (HTTP 500)")})])
    assert server_alerts.check_once(live()) == 1
    assert posts[-1]["text"] == ("Joey Server: jellyseerr failed 3 of the last 3 sweeps · "
                                 "Jellyseerr failed (HTTP 500)")
