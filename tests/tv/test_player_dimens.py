"""JY-307 phase 5: the Joey TV player overlay at the P2b scale, checked statically (the device audit is
tv/tools/player_audit.py, the release's live check).

Sizes are px at 1920x1080 / 2 on the TCL (960x540 dp): text floor 27 px = 13.5sp, buttons 84 px = 42dp, margins
72 x 40 px = 36/20dp. The top scrim is gone (one bottom block). Parses the resource XML only; no Android build needed.
"""
import importlib.util
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "tv" / "app" / "src" / "main" / "res"
A = "{http://schemas.android.com/apk/res/android}"
FLOOR_SP = 13.5


def _xml(rel):
    return ET.parse(RES / rel).getroot()


DIMENS = {d.get("name"): d.text.strip() for d in _xml("values/dimens.xml").iter("dimen")}
STYLES = {s.get("name"): s for s in _xml("values/styles.xml").iter("style")}
LAYOUT = _xml("layout/activity_player.xml")


def value(raw: str) -> tuple[float, str]:
    """'@dimen/x' or '13.5sp' -> (13.5, 'sp')."""
    while raw.startswith("@dimen/"):
        raw = DIMENS[raw[len("@dimen/"):]]
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)(sp|dp)", raw)
    assert m, raw
    return float(m.group(1)), m.group(2)


def style_items(name: str) -> dict:
    """A style's items with its parents' (explicit `parent` or the dotted name), child wins."""
    s = STYLES[name]
    parent = s.get("parent") or (name.rsplit(".", 1)[0] if "." in name else None)
    items = style_items(parent) if parent in STYLES else {}
    items.update({i.get("name").replace("android:", ""): i.text.strip() for i in s.iter("item")})
    return items


def views():
    """Every view in the player layout with its attributes resolved through its style."""
    for v in LAYOUT.iter():
        attrs = {}
        st = v.get("style")
        if st:
            attrs.update(style_items(st.replace("@style/", "")))
        attrs.update({k.replace(A, ""): val for k, val in v.attrib.items() if k.startswith(A)})
        yield v, attrs


def by_id(name: str):
    for v, attrs in views():
        if attrs.get("id") == f"@+id/{name}":
            return v, attrs
    raise AssertionError(name)


def test_every_dimen_text_size_is_at_or_above_the_27px_floor():
    sps = {n: value(v)[0] for n, v in DIMENS.items() if v.endswith("sp")}
    assert sps, "no sp dimens"
    assert {n: v for n, v in sps.items() if v < FLOOR_SP} == {}


def test_every_player_style_and_layout_text_size_is_at_or_above_the_floor():
    for name in STYLES:
        if name.startswith("JoeyPlayer"):
            size = style_items(name).get("textSize")
            if size:
                assert value(size) >= (FLOOR_SP, "sp"), name
    sized = 0
    for v, attrs in views():
        if v.tag == "TextView":
            assert "textSize" in attrs, attrs.get("id") or v.get("style")
            assert value(attrs["textSize"]) >= (FLOOR_SP, "sp"), attrs.get("id")
            sized += 1
    assert sized >= 15


def test_the_step_sizes():
    assert value(DIMENS["player_eyebrow"]) == (13.5, "sp")      # 27 px
    assert value(DIMENS["player_title"]) == (24.0, "sp")        # 48 px
    assert value(DIMENS["player_method"]) == (13.5, "sp")       # line / time / chapter 27 px
    assert value(DIMENS["player_label"]) == (15.0, "sp")        # labels and pop-up rows 30 px
    assert value(DIMENS["player_title_max"]) == (550.0, "dp")   # 1100 px
    assert value(DIMENS["player_ring"]) == (3.0, "dp")          # 6 px ring
    assert value(DIMENS["player_icon"]) == (20.0, "dp")         # 40 px icons
    assert value(DIMENS["player_bar_row"]) == (24.0, "dp")      # bar row 48 px
    assert value(DIMENS["player_bar_track"]) == (4.0, "dp")     # track 8 px
    assert value(DIMENS["player_bar_thumb"]) == (8.0, "dp")     # thumb 16 px
    assert value(DIMENS["player_bar_thumb_on"]) == (12.0, "dp")  # focused thumb 24 px
    assert value(DIMENS["player_bar_tick"]) == (1.0, "dp")      # ticks 2 px
    assert value(DIMENS["player_popup_col"]) == (270.0, "dp")   # 540 px columns
    assert value(DIMENS["player_row"]) == (42.0, "dp")          # 84 px rows
    assert value(DIMENS["player_upnext_tile"]) == (200.0, "dp")  # 400 x 225 px tile
    assert value(DIMENS["player_upnext_tile_h"]) == (112.5, "dp")
    assert value(DIMENS["player_chip_height"]) == (36.0, "dp")  # 72 px chips


def test_five_icon_buttons_at_42dp_in_the_old_order():
    assert value(DIMENS["player_button_height"]) == (42.0, "dp")
    ids = []
    for v, attrs in views():
        if (attrs.get("id") or "").startswith("@+id/player_btn_"):
            ids.append(attrs["id"].split("/")[1])
            assert v.get("style") == "@style/JoeyPlayerButton"
            assert value(attrs["layout_height"]) == (42.0, "dp")
            assert value(attrs["minWidth"]) == (42.0, "dp")
            assert attrs["drawableStart"].startswith("@drawable/ic_player_")
            assert "text" not in attrs   # icon only; the label shows on focus (PlayerActivity.renderButton)
            assert (RES / "drawable" / (attrs["drawableStart"].split("/")[1] + ".xml")).exists()
    assert ids == ["player_btn_play", "player_btn_back", "player_btn_forward", "player_btn_tracks", "player_btn_next"]


def test_margins_are_36_by_20dp_and_the_block_sits_at_the_bottom():
    assert value(DIMENS["player_mx"]) == (36.0, "dp")
    assert value(DIMENS["player_my"]) == (20.0, "dp")
    _, bottom = by_id("player_bottom")
    assert bottom["layout_gravity"] == "bottom"
    assert (bottom["paddingStart"], bottom["paddingEnd"], bottom["paddingBottom"]) == ("@dimen/player_mx",) * 2 + ("@dimen/player_my",)
    assert bottom["background"] == "@drawable/player_scrim_bottom"
    assert value(bottom["minHeight"]) == (243.0, "dp")   # ~45 % of 540 dp
    _, card = by_id("player_upnext")
    assert (card["layout_marginEnd"], card["layout_marginBottom"]) == ("@dimen/player_mx", "@dimen/player_my")
    _, popup = by_id("player_popup")
    assert popup["layout_marginStart"] == "@dimen/player_mx"


def test_no_top_scrim_and_no_top_title_block():
    text = (RES / "layout" / "activity_player.xml").read_text(encoding="utf-8")
    assert "player_scrim_top" not in text and "player_top" not in text and "player_resumed" not in text
    assert not (RES / "drawable" / "player_scrim_top.xml").exists()
    order = [a.get("id", "").split("/")[-1] for _, a in views()]
    want = ["player_eyebrow", "player_title", "player_line", "player_chapter", "player_time", "player_bar", "player_btn_play"]
    assert [i for i in order if i in want] == want   # bottom up: buttons, bar, time line, then the title block


def test_the_up_next_tile_is_an_image_over_the_plain_tile():
    v, attrs = by_id("player_upnext_still")
    assert v.tag == "ImageView" and attrs["background"] == "@drawable/player_tile"
    assert (attrs["layout_width"], attrs["layout_height"]) == ("@dimen/player_upnext_tile", "@dimen/player_upnext_tile_h")


# ---- the device audit's rules, on a synthetic dump (the live run is on the TCL) ----

def _audit_module():
    spec = importlib.util.spec_from_file_location("player_audit", ROOT / "tv" / "tools" / "player_audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _dump(*nodes):
    inner = "".join(f'<node class="{c}" resource-id="{("net.example:id/" + r) if r else ""}" text="{t}" '
                    f'selected="{str(s).lower()}" bounds="{b}" />' for c, r, t, s, b in nodes)
    return ('<hierarchy><node class="android.widget.FrameLayout" resource-id="net.example:id/player_root" text="" '
            f'selected="false" bounds="[0,0][1920,1080]">{inner}</node>'
            '<node class="android.widget.TextView" resource-id="" text="12:00" selected="true" bounds="[0,0][50,10]" />'
            '</hierarchy>')


@pytest.mark.parametrize("expect", [1])
def test_the_audit_flags_tiny_text_outside_margins_and_focus_count(expect):
    audit = _audit_module().audit
    good = _dump(("android.widget.TextView", "player_title", "Harbour Lights", False, "[72,700][700,764]"),
                 ("android.widget.TextView", "player_btn_play", "Pause", True, "[72,956][250,1040]"),
                 ("android.widget.FrameLayout", "player_bottom", "", False, "[0,594][1920,1080]"))
    r = audit(good, expect_focus=expect)
    assert r["pass"] and r["tiny"] == [] and r["outside"] == [] and r["focus"] == ["player_btn_play"]
    bad = _dump(("android.widget.TextView", "player_meta", "Direct play", False, "[100,700][300,720]"),
                ("android.widget.TextView", "player_btn_back", "", False, "[40,956][124,1040]"),
                ("android.widget.TextView", "", "English", True, "[100,500][400,584]"),
                ("android.widget.TextView", "", "Off", True, "[100,600][400,684]"))
    r = audit(bad, expect_focus=expect)
    assert not r["pass"]
    assert [t[0] for t in r["tiny"]] == ["player_meta"]
    assert [o[0] for o in r["outside"]] == ["player_btn_back"]
    assert r["focus"] == ["English", "Off"]   # two rings: fails "exactly one"; the status bar clock is not the player's
    assert audit(_dump(), expect_focus=0)["pass"]
