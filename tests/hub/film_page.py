"""The film page as a browser sees it once its deferred parts have landed (F2 fast item pages, 2026-10-12).

The page renders at once from Jellyfin + the caches; a section still waiting on Jellyseerr / OMDb is a placeholder
(`<div class="fpart" id="fp-<name>">`) and ONE htmx request (`.../part/all?p=...`, the `.fpart-load` element) returns
every part wrapped in its placeholder's id, swapped out of band. `whole()` does what htmx does: it requests that URL and
puts each part where its placeholder was. The part's content is spliced in WITHOUT its wrapper div (a display:contents
box), so a test reads the same markup a cached page draws inline.
"""
import html as htmllib
import re

LOADER = re.compile(r'<div class="fpart-load" hidden hx-get="([^"]+)" hx-trigger="load" hx-swap="none"></div>')


def parts_href(page: str) -> str | None:
    m = LOADER.search(page)
    return htmllib.unescape(m.group(1)) if m else None


def element(text: str, name: str) -> tuple[int, int, int, int] | None:
    """(start, inner start, inner end, end) of the div with id fp-<name>, matching nested divs."""
    m = re.search(rf'<div class="fpart" id="fp-{name}"[^>]*>', text)
    if not m:
        return None
    depth, i = 1, m.end()
    for tag in re.finditer(r"<(/?)div\b[^>]*>", text[m.end():]):
        depth += -1 if tag.group(1) else 1
        if depth == 0:
            return m.start(), m.end(), m.end() + tag.start(), m.end() + tag.end()
    raise AssertionError(f"unclosed placeholder fp-{name}")


def parts(fragment: str) -> dict[str, str]:
    """{name: inner html} of a part response."""
    out = {}
    for name in re.findall(r'<div class="fpart" id="fp-([a-z]+)" hx-swap-oob="true">', fragment):
        _, a, b, _ = element(fragment, name)
        out[name] = fragment[a:b]
    return out


def splice(page: str, fragment: str) -> str:
    for name, inner in parts(fragment).items():
        at = element(page, name)
        assert at, f"part {name} has no placeholder on the page"
        page = page[:at[0]] + inner + page[at[3]:]
    return page


def whole(client, url: str) -> str:
    """GET the page, then its parts request (when it has one), and return the page with every part in place."""
    page = client.get(url).text
    href = parts_href(page)
    if not href:
        return page
    resp = client.get(href)
    assert resp.status_code == 200, (href, resp.status_code)
    return splice(page, resp.text)
