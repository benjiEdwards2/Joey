"""Server clean-up (WP-T3, 2026-10-19): findings S3–S9 of review/2026-10-19-server/SERVER_REVIEW.md that need tests
of their own (S1 + S2 live in test_server_library_health.py). Real registry + sample snapshots; page assertions inside
<main>."""
from pathlib import Path

from hub import server
from hub.registry import load_registry
from tests.hub.helpers import AREAS_YAML
from tests.hub.test_server import env, main_of, txt  # noqa: F401  (env is a fixture)
from tests.hub.test_server_history import NOW, _samples

JS = (Path(server.__file__).resolve().parent / "static" / "joey.js").read_text(encoding="utf-8")


def area():
    return next(a for a in load_registry(AREAS_YAML).areas if a.layout == server.SERVER_LAYOUT)


# ---- S6: the disk projection reaches Attention under 30 days; Last 24 h folds -----------------------------------

FAST = [168, 120, 72, 23, 12, 0]                  # a week of samples


def test_disk_projection_under_30_days_joins_the_page_attention_only():
    band = server.history_band(_samples(lambda i: [60, 62, 64, 67.5, 69, 70][i], FAST), NOW)
    assert band["forecast"]["key"] == "forecast:/volume1"
    assert band["forecast"]["text"].startswith("/volume1 reaches 85% in ") and band["forecast"]["text"].endswith(
        " days at this rate")
    days = server.disk_days([(s["at"], s["volumes"][0]["pct_used"])
                             for s in _samples(lambda i: [60, 62, 64, 67.5, 69, 70][i], FAST)])
    assert 0 < days < server.FORECAST_ATTENTION_DAYS


def test_disk_projection_over_30_days_or_flat_stays_out():
    slow = server.history_band(_samples(lambda i: [8.0, 8.1, 8.2, 8.3, 8.35, 8.4][i], FAST), NOW)
    assert slow["forecast"] is None and "days to 85 % at this rate" in slow["trend"]   # the trend line still says it
    assert server.history_band(_samples(lambda i: 8.0, [168, 72, 10, 0]), NOW)["forecast"] is None
    assert server.history_band([], NOW)["forecast"] is None


def test_build_server_puts_the_forecast_in_attention_but_not_in_the_keyed_items(monkeypatch):
    """The keyed items feed the hub card and the Discord push; the hub loop has no samples, so the forecast stays a
    page item (else the loop would purge and the render re-post it)."""
    forecast = {"key": "forecast:/volume1", "text": "/volume1 reaches 85% in 12 days at this rate"}
    monkeypatch.setattr(server, "history_band", lambda samples, now=None: {
        "collecting": True, "text": "", "sparks": [], "trend": None, "forecast": forecast})
    out = server.build_server(area(), {}, {"warning": None})
    # P1a (2026-10-22): the forecast's action is Free space (was no action, WP-T3)
    assert out["attention"] == [{"text": forecast["text"], "href": "/server/space", "action": "Free space",
                                 "new_tab": False}]
    assert out["attention_items"] == []


def test_last_24h_is_marked_to_close_on_a_phone():
    hook = JS.split("Server clean-up (WP-T3, 2026-10-19)", 1)[1].split("})();", 1)[0]
    assert "matchMedia('(max-width: 639px)')" in hook and "details[data-phone-closed]" in hook
    assert "addEventListener('htmx:load'" in hook
    assert JS.index("Server clean-up (WP-T3") < JS.index("F2 fast item pages")   # the node harness runs F2 alone


# ---- S7: Attention items carry their action ---------------------------------------------------------------------

def test_attention_action_mapping():
    cards = {"prowlarr": {"href": "http://nas.example.invalid:9696"}, "sonarr": {"href": None}}
    act = lambda key: server.attention_action({"key": key, "text": "t"}, cards)  # noqa: E731
    assert act("down:prowlarr") == {"text": "t", "href": "http://nas.example.invalid:9696", "action": "Open",
                                    "new_tab": True}
    assert act("down:sonarr")["href"] == "#services" and act("down:sonarr")["action"] == "Services"
    assert act("down:unknown")["href"] == "#services"
    assert (act("kuma:Prowlarr")["href"], act("kuma:Prowlarr")["action"]) == ("#services", "Services")
    assert (act("sweep:wud")["href"], act("sweep:wud")["action"]) == ("#system", "Sweeps")
    for key in ("disk:/volume1", "backup"):
        assert act(key)["href"] is None and act(key)["action"] is None
    # P1a (2026-10-22): the forecast opens Free space (was no action, WP-T3)
    assert (act("forecast:/volume1")["href"], act("forecast:/volume1")["action"]) == ("/server/space", "Free space")


def test_attention_panel_renders_the_action_links(env):
    with env() as client:
        body = main_of(client.get("/server").text)
    att = body.split('id="attention"', 1)[1].split("</section>", 1)[0]
    assert ('<p class="st-warn attn-item">Prowlarr is Down (timeout) <a class="btn btn-ghost btn-sm" '
            'href="http://nas.local:9696" target="_blank" rel="noopener">Open</a></p>') in att
    assert '<p class="st-warn attn-item">Uptime Kuma: Prowlarr is Down <a class="btn btn-ghost btn-sm" ' \
           'href="#services">Services</a></p>' in att


# ---- S8: five bands, in order -----------------------------------------------------------------------------------

def test_five_bands_in_order_and_nothing_shown_twice(env):
    with env() as client:
        body = main_of(client.get("/server").text).split("</main>", 1)[0]
    bands = ['id="attention"', 'id="system"', 'id="services"', 'id="updates"', 'id="history"']
    assert [body.index(b) for b in bands] == sorted(body.index(b) for b in bands)
    for gone in ('id="counts"', 'class="tiles areatiles', '<section class="sec" id="sweeps"', 'microlabel">Last sweep<'):
        assert gone not in body, gone
    system = body.split('id="system"', 1)[1].split('id="services"', 1)[0]
    assert body.count('class="bar" role="img"') == system.count('class="bar" role="img"') == 3   # System's volumes only


# ---- S9: the Updates line says when WUD was checked; "Stale" only past the tile's interval --------------------------

def _updates_line(body):
    band = body.split('id="updates"', 1)[1].split("</section>", 1)[0]
    return next(line for line in band.split("</p>") if "monitored" in line)


def test_updates_line_says_checked_n_ago(env):
    with env() as client:
        line = _updates_line(main_of(client.get("/server").text))
    assert txt(line).strip().endswith("17 monitored · 2 updates · checked 1m ago")
    assert "Stale" not in line and "Updated" not in line


def test_updates_line_is_stale_only_past_the_tiles_interval(env, tmp_path):
    import json

    from tests.hub.helpers import write_envelope
    from tests.hub.test_server import SAMPLES
    wud = json.loads((SAMPLES / "wud.json").read_text(encoding="utf-8"))["data"]
    client = env()
    stale_after = next(t for t in area().tiles if t.id == "updates").stale_after_minutes      # 180
    for age, stale in ((stale_after - 1, False), (stale_after + 60, True)):
        write_envelope(tmp_path / "snaps", "wud", age_minutes=age, data=wud)
        with client:
            line = _updates_line(main_of(client.get("/server").text))
        words = f"checked {server.ago_text(age)}"
        if stale:
            assert f'<span class="st-warn">Stale · {words}</span>' in line
        else:
            assert words in txt(line) and "Stale" not in line


# ---- S3 / S5 and the hub card -----------------------------------------------------------------------------------

def test_portainer_is_a_lan_link_card_in_services_system(env):
    with env(lan=False) as client:
        body = main_of(client.get("/server").text)
    system = body.split('id="services"', 1)[1].split('<h2 class="seclabel">System</h2>', 1)[1].split("</section>", 1)[0]
    card = next(c for c in system.split("</a>") if '<span class="svc-name">Portainer</span>' in c)
    assert '<a class="svc-card" href="http://nas.local:9000" target="_blank" rel="noopener">' in card
    assert '<span class="svc-sub">Docker management · LAN</span>' in card


def test_sweep_summary_words():
    row = lambda cid, failing=False, nc=False: {"id": cid, "failing": failing, "not_configured": nc}  # noqa: E731
    last = {"text": "12m ago", "stale": False}
    ok = server.sweep_summary([row("a"), row("b")], last)
    assert ok == {"parts": ["2 connectors", "all sweeps OK"], "failing": None, "not_configured": None,
                  "last": "Last sweep 12m ago", "stale": False, "open": False}
    bad = server.sweep_summary([row("gcal", True), row("ha", True, True), row("x")], {"text": "2h ago", "stale": True})
    assert bad["parts"] == ["3 connectors"] and bad["failing"] == "1 failing: gcal"
    assert bad["not_configured"] == "1 not configured" and bad["stale"] and bad["open"]
    assert server.sweep_summary([], None) is None
    assert server.sweep_summary([], last)["parts"] == [] and server.sweep_summary(None, last)["last"]


def test_hub_card_is_unchanged_on_the_samples():
    """The hub card (hub_card) is pinned on the committed sample snapshots: WP-T3 changed the page, not the card."""
    import shutil
    import tempfile

    from hub.store import get_snapshots
    from tests.hub.test_server import SAMPLES
    with tempfile.TemporaryDirectory() as d:
        for p in SAMPLES.glob("*.json"):
            if not p.stem.startswith("_"):
                shutil.copy(p, Path(d) / p.name)
        card = server.hub_card(get_snapshots(Path(d)), set(), {"warning": None})
    assert card == {"summary": "1 down · Prowlarr", "secondary": "2 updates · disk 74% · 1 monitor down",
                    "state": "warn"}
