"""media-ux2 item 5 (2026-10-08): actions add no history entries. A boosted POST form 303s back to a page; base.html's
htmx:beforeHistoryUpdate hook turns htmx's "push" into "replace" for every non-GET request, so one Back goes to the
page before. Checked three ways: the hook is on every page, the vendored htmx acts on the very object the event
hands out, and the hook's own JS (run under node when available) flips POST and leaves GET alone."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.hub.test_history_nav import client, REPO_ROOT


def _hook(html):
    m = re.search(r"document\.addEventListener\('htmx:beforeHistoryUpdate', function \(e\) \{.*?\n\}\);", html, re.S)
    assert m, "the beforeHistoryUpdate hook is missing"
    return m.group(0)


def test_hook_is_on_every_page_before_htmx_runs(monkeypatch):
    c, _ = client(monkeypatch)
    with c:
        for path in ("/", "/weather"):
            html = c.get(path).text
            hook = _hook(html)
            assert "h.type = 'replace'" in hook and "requestConfig" in hook
            assert html.index("htmx:beforeHistoryUpdate") < html.index("<body hx-boost")


def test_vendored_htmx_reads_the_type_after_the_event():
    js = (REPO_ROOT / "hub/static/htmx.min.js").read_text(encoding="utf-8")
    assert 'version:"2.0.4"' in js
    # the event carries {history: u} merged with the response info, and htmx decides push/replace from u AFTER it
    assert 'he(ne().body,"htmx:beforeHistoryUpdate",ce({history:u},i));if(u.type==="push")' in js
    assert "requestConfig:C" in js and ",verb:" in js


NODE_HARNESS = """
var listeners = {};
var document = {addEventListener: function (n, f) { (listeners[n] = listeners[n] || []).push(f); }};
%s
function run(verb, type) {
  var h = {type: type, path: '/media/tv?flash=x'};
  listeners['htmx:beforeHistoryUpdate'].forEach(function (f) { f({detail: {history: h, requestConfig: verb === null ? undefined : {verb: verb}}}); });
  return h.type;
}
console.log(JSON.stringify([run('post', 'push'), run('get', 'push'), run('delete', 'push'), run('post', 'replace'),
                            run(null, 'push')]));
"""


def test_hook_logic_under_node(monkeypatch, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    c, _ = client(monkeypatch)
    with c:
        hook = _hook(c.get("/").text)
    script = tmp_path / "hook.js"
    script.write_text(NODE_HARNESS % hook, encoding="utf-8")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == ["replace", "push", "replace", "replace", "push"]


def test_flash_strip_still_listens_to_both_history_events(monkeypatch):
    c, _ = client(monkeypatch)
    with c:
        html = c.get("/").text
    assert "htmx:pushedIntoHistory', strip" in html and "htmx:replacedInHistory', strip" in html
