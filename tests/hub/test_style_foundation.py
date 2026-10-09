"""MediaHub restyle, Phase 1 (2026-10-06): the dark token set, self-hosted Geist and the recipe classes
from docs/style-guide.md are all present in hub/static/control-surface.css."""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC = REPO_ROOT / "hub" / "static"
CSS = (STATIC / "control-surface.css").read_text(encoding="utf-8")

ROOT = re.search(r"(?m)^:root\s*\{(.*?)\}", CSS, re.S).group(1)

TOKENS = {
    # older names, remapped to the guide's palette
    "--bg": "#09090b", "--fg": "#fafafa", "--border": "rgba(255, 255, 255, .07)",
    "--soft": "rgba(255, 255, 255, .04)",
    "--brand": "#6366f1", "--brand-fg": "#ffffff",
    "--good": "#34d399", "--good-soft": "rgba(16, 185, 129, .1)",
    "--warn-soft": "rgba(245, 158, 11, .1)",
    "--bad": "#fca5a5", "--bad-soft": "rgba(239, 68, 68, .1)",
    "--gold": "#f2c14e", "--gold-glow": "rgba(251, 191, 36, .45)",
    "--bar": "rgba(9, 9, 11, .95)", "--topbar": "rgba(9, 9, 11, .8)",  # shell bars (Phase 2 retired --rail*)
    "--scrim": "rgba(9, 9, 11, .9)",
    # new guide tokens
    "--primary": "#6366f1", "--primary-hover": "#818cf8",
    "--text-1": "#fafafa", "--text-2": "#e4e4e7", "--text-3": "#d4d4d8",
    "--text-4": "#a1a1aa", "--text-5": "#71717a", "--text-6": "#52525b",
    "--sky": "#7dd3fc", "--orange": "#fb923c", "--fuchsia": "#f0abfc", "--teal": "#5eead4",
    "--indigo-glow": "rgba(99, 102, 241, .1)",
}
KEPT = ["--stage", "--stage-fg", "--stage-btn", "--stage-line",
        "--badge-ink", "--badge-fg", "--surface", "--line"]   # badge-*: pinned by test_media_discover
# 2026-10-09 (T3, H-12/H-13): --muted, --faint, --card, --brand-soft, --warn, --scrim-soft, --shadow, --rose and the
# parked radar ramp --rad-1..15 were never read and are gone.
REMOVED = ["--muted", "--faint", "--card", "--brand-soft", "--warn", "--scrim-soft",
           "--shadow", "--rose"] + [f"--rad-{i}" for i in range(1, 16)]

RECIPES = [
    "btn", "btn-primary", "btn-secondary", "btn-ghost", "btn-danger", "btn-glass", "btn-sm",
    "chip", "input", "label", "select", "seclabel", "microlabel",
    "listbox", "row", "row-poster", "row-title", "row-score", "row-meta", "sep",
    "stats", "stat-number", "stat-word", "stat",
    "badge", "badge-watching", "badge-new", "badge-complete",
    "waitcount", "glass", "poster-grid", "card-poster", "empty", "panel",
] + [f"score-{i}" for i in range(1, 10)] + ["score-none"]   # toast / textarea / live-dot not carried (2026-10-09, decision 6)

SCORE_HEX = {9: "#34d399", 8: "#4ade80", 7: "#a3e635", 6: "#facc15", 5: "#fbbf24",
             4: "#fb923c", 3: "#f87171", 2: "#ef4444", 1: "#dc2626"}


def _decl(name):
    m = re.search(rf"(?<![\w-]){re.escape(name)}\s*:\s*([^;]+);", ROOT)
    return m and m.group(1).strip()


# (1) every token on :root with the guide's value; one dark theme, no theme blocks
@pytest.mark.parametrize("name, value", sorted(TOKENS.items()))
def test_token_on_root_with_guide_value(name, value):
    assert _decl(name) == value


@pytest.mark.parametrize("name", KEPT)
def test_kept_token_on_root(name):
    assert _decl(name)


def test_unread_tokens_stay_removed():
    assert [n for n in REMOVED if _decl(n)] == []


def test_single_dark_theme_no_theme_blocks():
    assert "color-scheme: dark" in ROOT
    assert "prefers-color-scheme" not in CSS
    assert "[data-theme=" not in CSS
    assert len(re.findall(r"(?m)^:root", CSS)) == 1


@pytest.mark.parametrize("grade, hexval", sorted(SCORE_HEX.items()))
def test_score_grades_use_tailwind_hexes(grade, hexval):
    assert _decl(f"--score-{grade}") == hexval
    assert re.search(rf"\.score-{grade}\s*\{{\s*color:\s*var\(--score-{grade}\)", CSS)


# (2) each recipe class appears as a selector
@pytest.mark.parametrize("cls", RECIPES)
def test_recipe_class_is_a_selector(cls):
    assert re.search(rf"(?m)\.{re.escape(cls)}(?![\w-])[^{{}};]*\{{", CSS), cls


@pytest.mark.parametrize("compound", [".chip.on", ".row.is-watching", ".row.is-new", ".row.is-complete", ".row.is-down"])
def test_recipe_state_selectors(compound):
    assert compound in CSS


def test_global_css_from_the_guide():
    flat = " ".join(CSS.split())
    assert "html { scrollbar-gutter: stable; }" in flat
    assert "overflow-x: clip;" in flat and "-webkit-font-smoothing: antialiased;" in flat
    assert "body::before {" in flat and "var(--indigo-glow)" in flat
    for kf in ("gold-glow-pulse", "gold-glow-sm-pulse", "hero-drift"):
        assert f"@keyframes {kf} " in CSS, kf
    assert ".gold-text-glow {" in CSS
    reduced = CSS.split("@media (prefers-reduced-motion: reduce) { .hero-drift { animation: none; } }")
    assert len(reduced) == 2


# (3) self-hosted Geist + Geist Mono
def test_geist_fonts_are_self_hosted():
    fonts = STATIC / "fonts"
    for name in ("GeistVF.woff2", "GeistMonoVF.woff2"):
        data = (fonts / name).read_bytes()
        assert data[:4] == b"wOF2", name
    assert (fonts / "OFL.txt").is_file() and (fonts / "README.md").is_file()
    faces = re.findall(r"@font-face\s*\{(.*?)\}", CSS, re.S)
    families = {re.search(r'font-family:\s*"([^"]+)"', f).group(1) for f in faces}
    assert {"Geist", "Geist Mono"} <= families
    assert all("font-display: swap" in f for f in faces)
    assert 'url("fonts/GeistVF.woff2")' in CSS and 'url("fonts/GeistMonoVF.woff2")' in CSS


def test_phone_bar_respects_iphone_safe_area_and_is_lifted():
    """B., 2026-10-08: the phone bars sat too low. viewport-fit=cover makes env(safe-area-inset-bottom)
    real on iPhones (it read 0 without it) and --tab-lift raises the bar ~20 % of its 56 px height."""
    base = (Path(__file__).resolve().parents[2] / "hub" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "viewport-fit=cover" in base
    assert re.search(r"--tab-lift:\s*\d+px", ROOT)
    assert "padding-bottom: calc(env(safe-area-inset-bottom) + var(--tab-lift))" in CSS
