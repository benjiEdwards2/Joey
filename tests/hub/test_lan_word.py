"""JY-238 (2026-10-24): the word a home-network-only link carries ("LAN") has one source, `hub.server.LAN_WORD`,
exposed to every template as the Jinja global `lan_word` (hub/shell.py). The Server card, the Health row and the
"Open <app> ↗" link all read it; no template spells the word. Swapping the global moves all three places, which
proves they share it; the scan fails if a template hardcodes it again."""
import re
from pathlib import Path

import pytest

from hub import server, shell
from tests.hub.conftest import app_with, main_raw as main_of
from tests.hub.helpers import make_area, make_tile, write_envelope
from tests.hub.test_first_screens_e3 import server_page

TEMPLATES = Path(shell.TEMPLATES_DIR)
SWAPPED = "HOMENET"


def test_the_word_is_one_global_from_the_server_module():
    assert server.LAN_WORD == "LAN"
    assert shell.templates.env.globals["lan_word"] is server.LAN_WORD


def test_app_link_says_the_global(monkeypatch):
    ctx = {"app_link": {"href": "http://192.168.1.10:8080", "name": "qBittorrent", "logo": None,
                        "initial": "Q", "lan": True}}
    tpl = shell.templates.env.get_template("_app_link.html")
    assert '<span class="metaline">LAN</span>' in tpl.render(**ctx)
    monkeypatch.setitem(shell.templates.env.globals, "lan_word", SWAPPED)
    out = tpl.render(**ctx)
    assert f'<span class="metaline">{SWAPPED}</span>' in out and "LAN" not in out


def test_health_row_says_the_global(tmp_path, monkeypatch):
    area = make_area("alpha", "apps-t", snapshot="media_status", stale_after_minutes=10, detail="/media/apps")
    factory = app_with(tmp_path, monkeypatch, area)
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "media_status", age_minutes=1, data={"summary": "x", "apps": [
        {"id": "jellyfin", "name": "Jellyfin", "href": "http://192.168.1.10:8096",
         "up": True, "status_text": "Up", "note": None}]})
    with factory(snaps) as client:
        before = main_of(client.get("/media/apps").text)
        monkeypatch.setitem(shell.templates.env.globals, "lan_word", SWAPPED)
        after = main_of(client.get("/media/apps").text)
    sep = '<span class="sep"> · </span>'
    assert f'<span class="st-up">Up</span>{sep}LAN</div>' in before
    assert f'<span class="st-up">Up</span>{sep}{SWAPPED}</div>' in after and "LAN" not in after


def test_server_card_says_the_global(tmp_path, monkeypatch):
    assert "svc-sub\">Media server · LAN<" in server_page(tmp_path, monkeypatch, lan=True)
    monkeypatch.setitem(shell.templates.env.globals, "lan_word", SWAPPED)
    page = server_page(tmp_path, monkeypatch, lan=True)
    assert f"svc-sub\">Media server · {SWAPPED}<" in page and "· LAN<" not in page


@pytest.mark.parametrize("path", sorted(TEMPLATES.glob("*.html")), ids=lambda p: p.name)
def test_no_template_hardcodes_the_word(path):
    """Outside {# comments #}, the word LAN stands alone only if a template spells it: as a string, or as text."""
    code = re.sub(r"\{#.*?#\}", "", path.read_text(encoding="utf-8"), flags=re.S)
    assert not re.search(r"""["'>]\s*LAN\s*["'<]""", code), f"{path.name} hardcodes the LAN word: use {{{{ lan_word }}}}"
