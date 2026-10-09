"""media-ux5 item 5 (B.'s explicit choice, 2026-10-09): zoom kept getting stuck on the iPhone, so the page cannot zoom.
Viewport meta forbids scaling (viewport-fit=cover kept), CSS turns off double-tap zoom and text inflation and gives
every form control 16 px on a phone (iOS zooms in on focus below 16 px), and base.html cancels Safari's pinch events
(Safari ignores user-scalable=no). The accessibility trade-off is documented in hub/README.md."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.hub.conftest import shell_script
from tests.hub.test_media_frame import env  # noqa: F401  (env is a fixture)
from tests.hub.helpers import ARR, JELLY

ROOT = Path(__file__).resolve().parents[2]
CSS = (ROOT / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
META = ('<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, '
        'viewport-fit=cover">')


@pytest.mark.parametrize("route", ["/", "/a/alpha", "/media/movies", "/media/diary", "/weather"])
def test_viewport_meta_forbids_zoom_on_every_page(env, route):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        head = c.get(route).text.split("</head>", 1)[0]
    assert re.findall(r'<meta name="viewport"[^>]*>', head) == [META]


def test_css_turns_off_double_tap_zoom_and_text_inflation():
    assert "html { touch-action: manipulation; -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }" in CSS


def test_form_controls_are_16px_on_a_phone_after_the_base_rules():
    rule = "@media (max-width: 767px) { input, select, textarea, .input, .select, .textarea { font-size: 16px; } }"
    assert rule in CSS
    # the phone rule must come AFTER the 14 px .input / .select rules or they would win
    assert CSS.index(rule) > CSS.index(".input, .textarea { width: 100%;") and CSS.index(rule) > CSS.index(".select { height: 36px;")
    after = CSS[CSS.index(rule) + len(rule):]
    assert not re.search(r"(?:input|select|textarea|\.input|\.select|\.textarea)[^{}]*\{[^}]*font-size", after)


def test_base_cancels_safari_pinch_gestures(env):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        head = shell_script(c, c.get("/media/movies").text)   # H-57: /static/joey.js
    assert "['gesturestart', 'gesturechange'].forEach(function (t) {" in head
    assert "document.addEventListener(t, function (e) { e.preventDefault(); }, {passive: false});" in head


def test_trade_off_documented():
    readme = (ROOT / "hub" / "README.md").read_text(encoding="utf-8")
    assert "No zoom (media-ux5" in readme and "accessibility" in readme and "2026-10-09" in readme
