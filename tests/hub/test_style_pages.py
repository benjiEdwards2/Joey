"""MediaHub restyle, Phase 4 of 4 (2026-10-06): Hub, area/Calendar, Server and Weather on the Media recipes.
(a) the superseded classes are gone from the templates and the stylesheet, (b) no per-area --accent anywhere,
(c) the four pages render stats strips / panels / rows with no literal colours, (d) the guide's "2h 47m" runtime,
(e) the Server Update now / Ignore forms still render as .btn-primary / .btn-ghost, (f) no sideways-scroll traps."""
import re
from pathlib import Path

from hub.media_library import runtime_text
from tests.hub.test_apex_areas import site  # noqa: F401  (fixture: get(route) -> (hub.main, <main> html))
from tests.hub.test_server_updates import env  # noqa: F401  (fixture: Server with a WUD env)

HUB = Path(__file__).resolve().parents[2] / "hub"
TEMPLATES = HUB / "templates"
CSS = (HUB / "static" / "control-surface.css").read_text(encoding="utf-8")
PAGES = ("hub.html", "_kpi.html", "_shelf.html", "_upcoming_table.html", "_weather_glimpse.html", "area.html",
         "server.html", "server_update.html", "weather.html", "404.html", "_rate.html")
REMOVED = {"card", "kpi", "kpis", "kpirow", "kpiarea", "kpiicon", "kpibody", "jumpback", "sparkbar", "areakpis",
           "cardlink", "uplist", "uprow", "uptitle", "uptime", "upday", "upact", "uptable", "medialist", "mediacols",
           "appdot", "approw", "appstate", "appnote", "playrow", "hasposter", "nextleft", "pbar", "hubshelf",
           "hubposter", "seeall", "stale", "off", "glassbtn", "linkbtn", "launch", "reqbtns", "notfound", "quiet",
           "areaquiet", "value", "sub", "head", "foot", "ago", "open", "owner", "wxcard", "wxfacts", "hd", "bd",
           "subhd", "backupwarn", "rowchip", "gold-glow-chip"}
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def class_tokens(src):
    toks = set()
    for m in re.finditer(r'class="([^"]*)"', src):
        toks.update(t for t in re.split(r"\s+", re.sub(r"\{[{%].*?[}%]\}", " ", m.group(1))) if t)
    return toks


# (a) ---------------------------------------------------------------------------------------------

def test_page_templates_use_none_of_the_removed_classes():
    for name in PAGES:
        used = class_tokens((TEMPLATES / name).read_text(encoding="utf-8"))
        assert not (used & REMOVED), (name, sorted(used & REMOVED))
    assert not (TEMPLATES / "_tile.html").exists()          # the unused tile partial is gone


def test_stylesheet_has_no_rules_for_the_removed_classes():
    selectors = " ".join(re.findall(r"([^{}]+)\{", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)))
    for cls in ("card", "kpi", "kpis", "uplist", "uprow", "medialist", "mediacols", "appdot", "pbar", "hubshelf",
                "hubposter", "seeall", "cardlink", "uptable", "linkbtn", "notfound", "owner"):
        assert not re.search(rf"\.{re.escape(cls)}(?![\w-])", selectors), cls
    assert not re.search(r"\.badge\.(stale|off)|\.chip\.score|\.poster\.sm\b", selectors)


# (b) ---------------------------------------------------------------------------------------------

def test_no_accent_in_templates_python_or_css():
    for p in TEMPLATES.glob("*.html"):
        assert "accent" not in p.read_text(encoding="utf-8").lower(), p.name
    for p in HUB.glob("*.py"):
        if p.name != "registry.py":                         # areas.yaml still validates the (now inert) field
            assert "accent" not in p.read_text(encoding="utf-8").lower(), p.name
    assert "--accent" not in re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)


# (c) ---------------------------------------------------------------------------------------------

def test_the_four_pages_render_on_recipes_without_accent_or_literal_colours(site):  # noqa: F811
    for route in ("/", "/a/calendar", "/server", "/weather"):
        _, body = site(route)
        assert 'class="stats"' in body or 'class="panel' in body or "panel tile" in body, route
        assert 'class="row' in body, route
        assert "--accent" not in body and "style=\"--accent" not in body, route
        assert not HEX.search(re.sub(r'href="[^"]*"', "", body)), route
        assert not (class_tokens(body) & {"card", "kpi", "uplist", "uprow", "medialist", "cardlink", "seeall"}), route


def test_server_bands_use_the_stats_strip_and_status_words(site):  # noqa: F811
    _, body = site("/server")
    assert body.count('class="stats"') == 1 and 'class="bar"' in body
    assert '<span class="st-down">Down</span>' in body and '<span class="st-up">Up</span>' in body
    assert 'class="row is-down"' in body and 'class="panel panel-warn"' in body   # something to do = amber panel
    assert 'id="history"' in body and "spark-band" in body


# (d) ---------------------------------------------------------------------------------------------

def test_runtime_text_is_hours_and_minutes_the_guide_way():
    assert runtime_text(112) == "1h 52m"
    assert runtime_text(47) == "47m"
    assert runtime_text(120) == "2h"
    assert runtime_text(167) == "2h 47m"
    assert runtime_text(0) == "—" and runtime_text(None) == "—" and runtime_text("x") == "—"


# (e) ---------------------------------------------------------------------------------------------

def test_server_update_and_ignore_forms_render_as_primary_and_ghost_buttons(env):  # noqa: F811
    with env() as client:
        page = client.get("/server").text.split("<main", 1)[1]
        confirm = client.get("/server/updates/vaultwarden/run?step=confirm").text.split("<main", 1)[1]
    assert re.search(r'<a class="btn btn-primary btn-sm" href="/server/updates/vaultwarden/run\?step=confirm">Update now</a>', page)
    assert re.search(r'<form method="post" action="/server/updates/[\w-]+/ignore"><button class="btn btn-ghost btn-sm" type="submit">Ignore</button>', page)
    assert '<span class="badge badge-wait">' in page      # pending = amber outline badge
    assert 'class="btn btn-primary" type="submit">Update vaultwarden now' in confirm and 'class="btn btn-ghost"' in confirm


# (f) ---------------------------------------------------------------------------------------------

def test_no_fixed_widths_over_360px_and_no_min_width_over_the_viewport_outside_media_queries():
    flat = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    top, i = [], 0
    while True:                                             # keep only top-level rules (drop @media / @keyframes bodies)
        j = flat.find("{", i)
        if j < 0:
            break
        depth, k = 1, j + 1
        while depth:
            depth += {"{": 1, "}": -1}.get(flat[k], 0)
            k += 1
        if not flat[i:j].strip().startswith("@"):
            top.append(flat[i:k])
        i = k
    plain = "\n".join(top)
    for m in re.finditer(r"(?<![-\w])(?:min-)?width:\s*(\d+(?:\.\d+)?)px", plain):
        assert float(m.group(1)) <= 360, m.group(0)
    for m in re.finditer(r"min-width:\s*(\d+(?:\.\d+)?)(vw|rem)", plain):
        assert (float(m.group(1)) <= 100 if m.group(2) == "vw" else float(m.group(1)) * 16 <= 360), m.group(0)
    for sel in (".tile ", ".row ", ".row-body ", ".cols > *", ".stat "):
        assert re.search(re.escape(sel) + r"[^{]*\{[^}]*min-width:\s*0", flat), sel
