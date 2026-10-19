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
    assert out["attention"] == [{"text": forecast["text"], "href": None, "action": None, "new_tab": False}]
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
    for key in ("disk:/volume1", "backup", "forecast:/volume1"):
        assert act(key)["href"] is None and act(key)["action"] is None


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
