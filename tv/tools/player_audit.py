"""JY-307 phase 5: the Joey TV player overlay audit, on the device (the live check for the 1.0.5 release).

Takes one `uiautomator dump` (and a 1920x1080 `screencap`) of the player as it is on screen now and checks, with the
P1-P4 audit's JSON keys:
* `tiny`    - text views with words in them shorter than 27 px (the P2b text floor, 1.125rem at 24 px/rem);
* `outside` - player text, buttons, bar, tiles or chips outside the 72 x 40 px margins (tv.css --tv-mx / --tv-my);
* `focus`   - the element(s) carrying the player's focus ring. The player does not use Android focus: PlayerActivity mirrors
              its ring (isActivated, from PlayerUi) onto `selected`, which the dump shows. Exactly one per state with the
              controls, the pop-up or the up-next card up (`--expect-focus 1`, the default); 0 with everything hidden.

Run it from the repo root with adb connected (tv/README.md "Install with adb"), the player open in the state to check:

    python tv/tools/player_audit.py --label controls_film
    python tv/tools/player_audit.py --label hidden --expect-focus 0
    python tv/tools/player_audit.py --serial <tv-address>:<port> --label popup_subs --out %TEMP%\\player_audit

Each run prints one JSON line and writes <out>/<label>.json, <label>.xml and <label>.png; exit 0 = pass, 1 = fail.
`--xml FILE` audits a saved dump instead (no device; tests/tv/test_player_dimens.py uses it). Nothing is sent anywhere;
the dump holds on-screen words only (titles), no URL, token or user name.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

FLOOR_PX = 27
MARGIN_X = 72
MARGIN_Y = 40
BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
# full-bleed containers and the picture: they are meant to reach the edges
EDGE_IDS = {"player_root", "player_view", "player_bottom"}


def _bounds(node) -> tuple[int, int, int, int] | None:
    m = BOUNDS.fullmatch(node.get("bounds", ""))
    return tuple(int(x) for x in m.groups()) if m else None


def _rid(node) -> str:
    rid = node.get("resource-id", "")
    return rid.split(":id/", 1)[1] if ":id/" in rid else ""


def _player_nodes(root):
    """Every node under the player's root view (the dump also holds the system bars and other windows)."""
    for node in root.iter("node"):
        if _rid(node) == "player_root":
            return list(node.iter("node"))
    return []


def _name(node) -> str:
    return _rid(node) or (node.get("text") or "")[:40] or node.get("class", "?")


def audit(xml_text: str, width: int = 1920, height: int = 1080, expect_focus: int = 1, label: str = "") -> dict:
    """The audit of one dump; pure, so it is testable without a TV."""
    nodes = _player_nodes(ET.fromstring(xml_text))
    tiny, outside, focus = [], [], []
    for node in nodes:
        b = _bounds(node)
        if b is None:
            continue
        x0, y0, x1, y1 = b
        rid = _rid(node)
        text = node.get("text") or ""
        is_text = node.get("class", "").endswith("TextView") and text.strip()
        if is_text and y1 - y0 < FLOOR_PX:
            tiny.append([_name(node), y1 - y0, text[:40]])
        drawn = is_text or rid.startswith(("player_btn_", "player_bar", "player_upnext", "player_popup"))
        if drawn and rid not in EDGE_IDS and x1 > x0 and y1 > y0:
            if x0 < MARGIN_X or y0 < MARGIN_Y or x1 > width - MARGIN_X or y1 > height - MARGIN_Y:
                outside.append([_name(node), list(b)])
        if node.get("selected") == "true":
            focus.append(_name(node))
    ok = not tiny and not outside and len(focus) == expect_focus
    return {"label": label, "size": [width, height], "tiny": tiny, "outside": outside, "focus": focus,
            "expect_focus": expect_focus, "pass": ok}


def _adb(serial: str | None, *args: str, binary: bool = False):
    cmd = ["adb"] + (["-s", serial] if serial else []) + list(args)
    out = subprocess.run(cmd, capture_output=True, timeout=60, check=True).stdout
    return out if binary else out.decode("utf-8", "replace")


def _screen(serial: str | None) -> tuple[int, int]:
    m = re.search(r"(\d+)x(\d+)", _adb(serial, "shell", "wm", "size").splitlines()[-1])
    return (int(m.group(1)), int(m.group(2))) if m else (1920, 1080)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--serial", help="adb device (host:port); default: the only one connected")
    ap.add_argument("--label", default="player", help="name for this state's files, e.g. controls_episode")
    ap.add_argument("--expect-focus", type=int, default=1, help="focused elements expected (0 with everything hidden)")
    ap.add_argument("--out", default="player_audit", help="folder for <label>.json/.xml/.png")
    ap.add_argument("--xml", help="audit a saved uiautomator dump instead of the device")
    ap.add_argument("--size", default="1920x1080", help="screen size for --xml")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.xml:
        xml_text = Path(a.xml).read_text(encoding="utf-8")
        width, height = (int(v) for v in a.size.split("x"))
    else:
        width, height = _screen(a.serial)
        xml_text = _adb(a.serial, "exec-out", "sh", "-c",
                        "uiautomator dump /sdcard/joey_player_ui.xml >/dev/null 2>&1; cat /sdcard/joey_player_ui.xml")
        (out / f"{a.label}.png").write_bytes(_adb(a.serial, "exec-out", "screencap", "-p", binary=True))
    (out / f"{a.label}.xml").write_text(xml_text, encoding="utf-8")
    result = audit(xml_text, width, height, a.expect_focus, a.label)
    (out / f"{a.label}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
