"""WP16 — areas.yaml registry + validated loader."""
from pathlib import Path

import pytest
import yaml

from hub.registry import load_registry
from tests.hub.helpers import AREAS_YAML, make_area, make_tile, write_registry  # noqa: F401  (re-export: defined in tests/hub/helpers.py)

REPO_ROOT = Path(__file__).resolve().parents[2]

LOCKED_ORDER = ["money", "calendar", "media", "server"]  # Food, Desk, House, Car retired 2026-10-27 (JY-221)


def test_real_registry_loads_in_locked_order():
    reg = load_registry(AREAS_YAML)
    assert [a.id for a in reg.areas] == LOCKED_ORDER


def test_real_registry_tiles_are_well_formed():
    reg = load_registry(AREAS_YAML)
    for area in reg.areas:
        for tile in area.tiles:
            assert tile.tier.value in {"link", "embed", "ingest"}
            assert tile.owner.value in {"you", "her", "shared"}
            if tile.tier.value == "link":
                assert tile.href
            else:
                assert tile.snapshot and tile.stale_after_minutes > 0


def test_valid_synthetic_registry_loads(tmp_path):
    reg = load_registry(write_registry(tmp_path, make_area("a1"), make_area("a2")))
    assert [a.id for a in reg.areas] == ["a1", "a2"]


def test_tenth_area_rejected(tmp_path):
    areas = [make_area(f"a{i}") for i in range(10)]
    with pytest.raises(ValueError, match="between 1 and 9"):
        load_registry(write_registry(tmp_path, *areas))


def test_duplicate_area_id_rejected(tmp_path):
    with pytest.raises(ValueError, match="duplicate area id 'dup'"):
        load_registry(write_registry(
            tmp_path, make_area("dup", "t1"), make_area("dup", "t2")))


def test_duplicate_tile_id_across_areas_rejected(tmp_path):
    with pytest.raises(ValueError, match="duplicate tile id 'same'"):
        load_registry(write_registry(
            tmp_path, make_area("a1", "same"), make_area("a2", "same")))


def test_blank_icon_rejected(tmp_path):
    bad = make_area("a1")
    bad["icon"] = "  "
    with pytest.raises(ValueError, match="icon must be a non-empty icon id"):
        load_registry(write_registry(tmp_path, bad))


def test_link_missing_href_rejected(tmp_path):
    with pytest.raises(ValueError, match="tier link requires href"):
        load_registry(write_registry(
            tmp_path, make_area("a1", tier="link", snapshot=None, stale_after_minutes=None)))


def test_embed_missing_stale_after_rejected(tmp_path):
    with pytest.raises(ValueError, match="requires stale_after_minutes"):
        load_registry(write_registry(
            tmp_path, make_area("a1", stale_after_minutes=None)))


def test_embed_missing_snapshot_rejected(tmp_path):
    with pytest.raises(ValueError, match="requires a snapshot id"):
        load_registry(write_registry(tmp_path, make_area("a1", snapshot=None)))


def test_snapshot_outside_frozen_namespace_rejected(tmp_path):
    with pytest.raises(ValueError, match="not in the frozen D13 namespace"):
        load_registry(write_registry(tmp_path, make_area("a1", snapshot="spotify")))


def test_dangling_summary_tile_rejected(tmp_path):
    bad = make_area("a1")
    bad["summary_tile"] = "ghost"
    with pytest.raises(ValueError, match="summary_tile 'ghost'"):
        load_registry(write_registry(tmp_path, bad))


def test_all_violations_reported_together(tmp_path):
    """Triple-violation fixture: blank icon + missing snapshot + dangling summary."""
    bad = make_area("a1", snapshot=None)
    bad["icon"] = " "
    bad["summary_tile"] = "ghost"
    with pytest.raises(ValueError) as exc:
        load_registry(write_registry(tmp_path, bad))
    msg = str(exc.value)
    assert "3 violation(s)" in msg
    assert "icon must be a non-empty icon id" in msg
    assert "requires a snapshot id" in msg
    assert "summary_tile 'ghost'" in msg


def test_wp21_signoff_link_hrefs_are_real_urls():
    """WP21 sign-off (2026-09-11): no LINK tile ships a placeholder href —
    every href is a real http(s) URL (Q12 Notion answered, Jellyfin WP6 fix)."""
    config = yaml.safe_load(AREAS_YAML.read_text(encoding="utf-8"))
    link_tiles = [t for a in config["areas"] for t in a["tiles"] if t["tier"] == "link"]
    assert link_tiles, "the Notion/NAS/Jellyfin LINK tiles vanished"
    for tile in link_tiles:
        href = tile["href"]
        assert href.startswith(("http://", "https://")), f"{tile['id']}: href {href!r} is not a URL"
        assert "PLACEHOLDER" not in href, f"{tile['id']}: placeholder href survived sign-off"


def test_retired_areas_are_gone_from_the_real_registry():
    """JY-221 (2026-10-27): Food, Desk, House and Car left areas.yaml; their tiles and the MacroMates link went with them."""
    reg = load_registry(AREAS_YAML)
    ids = {a.id for a in reg.areas}
    assert not ids & {"kitchen", "desk", "house", "car"}
    assert "macromates-app" not in {t.id for a in reg.areas for t in a.tiles}


# rail_section (B., 2026-10-06)
def test_rail_section_accepts_home_and_areas_and_defaults_to_areas(tmp_path):
    reg = load_registry(write_registry(
        tmp_path, make_area("a1"), make_area("a2", ), {**make_area("a3"), "rail_section": "home"},
        {**make_area("a4"), "rail_section": "areas"}))
    assert [a.rail_section for a in reg.areas] == ["areas", "areas", "home", "areas"]


def test_rail_section_rejects_other_values(tmp_path):
    with pytest.raises(ValueError, match="rail_section"):
        load_registry(write_registry(tmp_path, {**make_area("a1"), "rail_section": "footer"}))


def test_real_registry_puts_media_in_home_rail_section():
    reg = load_registry(AREAS_YAML)
    assert [a.id for a in reg.areas if a.rail_section == "home"] == ["media"]


def test_gated_hrefs_live_in_areas_yaml_and_must_be_https(tmp_path):
    """H-42: public hostnames are config (areas.yaml `gated_hrefs`), never hub code."""
    import yaml
    from pathlib import Path
    reg = load_registry(AREAS_YAML)
    assert reg.gated_hrefs == {}                     # homepage was the only one (retired 2026-10-09, decision 9)
    hub_dir = Path(__file__).resolve().parents[2] / "hub"
    core = ["main.py", "shell.py", "ids.py", "server.py", "server_alerts.py", "server_history.py", "server_updates.py"]
    assert all("joeyhome.net" not in (hub_dir / name).read_text(encoding="utf-8") for name in core)
    p = tmp_path / "areas.yaml"
    p.write_text(yaml.safe_dump({"gated_hrefs": {"x": "http://lan:1"}, "areas": [make_area("a1")]}), encoding="utf-8")
    with pytest.raises(ValueError, match="gated_hrefs 'x'"):
        load_registry(p)
