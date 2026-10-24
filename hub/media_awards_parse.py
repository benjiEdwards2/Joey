"""Awards parsers (AWARDS_PLAN A2, 2026-10-08) — pure: no I/O, no DB, no network.

* `parse_award_blocks(wikitext)` reads a Wikipedia ceremony page in the shape every page since the mid-2000s uses:
  a `{{Award category|<colour>|[[<category page>|<label>]]}}` header, then `* '''winner'''` and `** nominee` lines
  ("''[[Film]]'' – [[People]]" for work categories, "[[Person]] – ''[[Film]]'' as Role" for people; Emmys mark the
  winner with `{{double dagger}}`; "(Network)" / "(Country)" parentheticals are dropped). WP-D1 (2026-10-16) adds the
  three older shapes: wikitables whose `!` header cells name the categories (Globes ≤ 2023, SAG ≤ 2020, early BAFTA),
  `* '''Best Actor:'''` bold-label lists (Critics' Choice 1996–2001) and `===Category===` headings (BAFTA 1949–1964,
  Globes 1946). A redirect page or a page none of them reads is reported, never guessed at.
* `sparql_rows(answer)` flattens a SPARQL CSV (or JSON) answer; `wd_nominations(rows, ...)` turns the Oscars edition answer (or a
  winners-only category answer) into categories + nominations + entities.
* `qids_from_pageprops(json)` maps enwiki titles -> QIDs (redirects and normalisation followed); `entities_from(json)`
  reads the ids answer (TMDB movie / TV / person, IMDb, TheTVDB, human or not).
* `ordinal(n)` / `wp_title(fmt, n)` build "97th Academy Awards".
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata

LABEL_MAX = 200
BOM = chr(0xFEFF)
SHAPE_OK, SHAPE_NONE, SHAPE_REDIRECT = "ok", "none", "redirect"

_REDIRECT_RE = re.compile(r"^\s*#REDIRECT\s*\[\[([^\]|#]+)", re.I)
_HEADING_RE = re.compile(r"^(=+)\s*(.*?)\s*\1\s*$")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_REF_RE = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.S | re.I)
_TAG_RE = re.compile(r"</?(?:small|span|sup|br|abbr|nowiki)[^>]*>", re.I)
_LINK_RE = re.compile(r"\[\[([^\[\]|]*)(?:\|([^\[\]]*))?\]\]")
_DASHES = (" – ", " — ", " - ", " − ")
_TV_WORDS = ("television", "tv ", " tv", "series", "miniseries", "limited", "anthology", "talk show", "variety",
             "reality", "made for television", "made-for-television", "streaming")
_FILM_WORDS = ("film", "motion picture", "movie", "picture", "cinema")
PERSON_CAT = re.compile(r"\b(direct\w*|actor|actress|performance|screenplay|writing|writer|written)\b", re.I)
WRITING_CAT = re.compile(r"screenplay|writing|written", re.I)
_SKIP_TARGETS = ("file:", "image:", "category:", "wikt:", "wiktionary:")


# ---- small helpers ----

def ordinal(n: int) -> str:
    n = int(n)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def wp_title(fmt: str | None, n: int) -> str | None:
    return fmt.format(ord=ordinal(n), n=int(n)) if fmt else None


def slug(text: str) -> str:
    """'Best Motion Picture – Drama' -> 'best-motion-picture-drama' (diacritics folded)."""
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:80]


def _clip(text) -> str:
    return " ".join(str(text or "").split())[:LABEL_MAX]


def _strip_templates(text: str) -> str:
    """Drop every {{…}} (nested), keeping the visible text of a few inline ones (sortname, nowrap, …)."""
    out, i, n = [], 0, len(text)
    while i < n:
        if text.startswith("{{", i):
            depth, j = 0, i
            while j < n:
                if text.startswith("{{", j):
                    depth += 1
                    j += 2
                elif text.startswith("}}", j):
                    depth -= 1
                    j += 2
                    if depth == 0:
                        break
                else:
                    j += 1
            out.append(_inline_template(text[i + 2:j - 2] if depth == 0 else ""))
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _inline_template(inner: str) -> str:
    parts = [p.strip() for p in _split_top(inner, "|")]
    name = parts[0].lower() if parts else ""
    args = [p for p in parts[1:] if "=" not in p.split("[[")[0]]
    if name in ("sortname", "sort name") and len(args) >= 2:
        shown = f"{args[0]} {args[1]}"
        target = args[2] if len(args) >= 3 and args[2] else shown
        return f"[[{target}|{shown}]]"
    if name in ("nowrap", "nobr", "nowr", "small", "lang") and args:
        return _strip_templates(args[-1])
    return ""


def _split_top(text: str, sep: str) -> list[str]:
    """Split on `sep` outside [[…]] and {{…}}."""
    out, cur, depth, i = [], [], 0, 0
    while i < len(text):
        two = text[i:i + 2]
        if two in ("[[", "{{"):
            depth += 1
            cur.append(two)
            i += 2
            continue
        if two in ("]]", "}}"):
            depth = max(0, depth - 1)
            cur.append(two)
            i += 2
            continue
        if depth == 0 and text.startswith(sep, i):
            out.append("".join(cur))
            cur = []
            i += len(sep)
            continue
        cur.append(text[i])
        i += 1
    out.append("".join(cur))
    return out


def _drop_parens(text: str) -> str:
    """Remove (…) groups outside links: '(HBO Max)', '(France)'."""
    out, depth, link, i = [], 0, 0, 0
    while i < len(text):
        two = text[i:i + 2]
        if two == "[[":
            link += 1
            if depth == 0:
                out.append(two)
            i += 2
            continue
        if two == "]]":
            link = max(0, link - 1)
            if depth == 0:
                out.append(two)
            i += 2
            continue
        ch = text[i]
        if link == 0 and ch == "(":
            depth += 1
        elif link == 0 and ch == ")" and depth:
            depth -= 1
        elif depth == 0:
            out.append(ch)
        i += 1
    return "".join(out)


def _link(text: str) -> dict | None:
    """The first wikilink in `text` -> {title, label}; plain text -> {title: None, label}."""
    for m in _LINK_RE.finditer(text):
        target = (m.group(1) or "").split("#", 1)[0].strip()
        if target.lower().startswith(_SKIP_TARGETS):
            continue
        label = _plain(m.group(2) if m.group(2) is not None else target)
        if target:
            return {"title": _clip(target.replace("_", " ")), "label": _clip(label) or _clip(target)}
    label = _plain(text)
    return {"title": None, "label": label} if label else None


def _plain(text: str) -> str:
    text = _LINK_RE.sub(lambda m: m.group(2) if m.group(2) is not None else m.group(1), str(text or ""))
    text = text.replace("'''", "").replace("''", "")
    return _clip(text.strip(" \"“”,;:"))


def _italic(text: str) -> tuple[str | None, str]:
    """('inside of the first ''…'' run', 'the rest after it')."""
    m = re.search(r"''(.+?)''", text)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def _names(text: str) -> list[dict]:
    """'[[A]], [[B]], and C' -> people (linked or plain)."""
    people = []
    for chunk in _split_top(text, ","):
        for piece in _split_top(chunk, " and "):
            for bit in _split_top(piece, " & "):
                bit = re.sub(r"^\s*and\s+", "", bit.strip())
                if not bit.strip():
                    continue
                got = _link(bit) if "[[" in bit else ({"title": None, "label": _plain(bit)} if _plain(bit) else None)
                if got and got["label"]:
                    people.append(got)
    return people


def _kind_of_heading(text: str) -> str | None:
    low = _plain(text).lower()
    if "television" in low or re.search(r"\btv\b", low):
        return "tv"
    if any(w in low for w in ("film", "motion picture", "movie")):
        return "film"
    return None


def category_kind(label: str, heading_kind: str | None, default: str | None = None) -> str:
    """film | tv for one category: the section heading when it says, else the label's words, else `default`."""
    if heading_kind:
        return heading_kind
    low = f" {str(label or '').lower()} "
    if any(w in low for w in _TV_WORDS):
        return "tv"
    if any(w in low for w in _FILM_WORDS):
        return "film"
    return default or "film"


def _award_header(line: str) -> tuple[str, str | None] | None:
    i = line.find("{{Award category")
    if i < 0:
        i = line.lower().find("{{award category")
        if i < 0:
            return None
    depth, j = 0, i
    while j < len(line):
        if line.startswith("{{", j):
            depth += 1
            j += 2
        elif line.startswith("}}", j):
            depth -= 1
            j += 2
            if depth == 0:
                break
        else:
            j += 1
    params = _split_top(line[i + 2:j - 2], "|")
    raw = params[-1] if len(params) >= 2 else ""
    got = _link(raw)
    if not got:
        return None
    return got["label"], got["title"]


def _entry(content: str, in_split: bool = False) -> dict | None:
    """One nominee line -> {won, lead, work, people}. `in_split` (the heading shape's old BAFTA / Globes pages): with no
    dash on the line, "[[Person]] in ''[[Film]]''" splits on " in " like a dash (a wholly italic line is unwrapped)."""
    won = "double dagger" in content.lower() or "'''" in content
    text = _COMMENT_RE.sub("", content)
    text = _REF_RE.sub("", text)
    text = _strip_templates(text)
    text = _TAG_RE.sub("", text)
    text = text.replace("'''''", "''").replace("'''", "")
    song = _song(text)
    if song:
        return {"won": won, **song}
    text = _drop_parens(text).strip()
    if not text:
        return None
    if in_split:
        got = _in_split(text)
        if got:
            return {"won": won, **got}
    first, rest = text, ""
    for dash in _DASHES:
        parts = _split_top(text, dash)
        if len(parts) > 1:
            first, rest = parts[0], dash.join(parts[1:])
            break
    if first.lstrip().startswith("''"):
        inner, _ = _italic(first)
        work = _link(inner or first)
        people = _names(rest) if rest else []
        lead = "work"
    else:
        people = _names(first)
        inner, _ = _italic(rest)
        work = _link(inner) if inner else None
        lead = "person"
        if not people and work:
            lead = "work"
    if not work and not people:
        return None
    return {"won": won, "lead": lead, "work": work, "people": people}


_SONG_RE = re.compile(r"^\s*[\"“](.+?)[\"”](.*)$", re.S)
_CREDIT_RE = re.compile(r"^\s*(?:(?:music|lyrics|words|songs?)(?:\s+(?:and|&)\s+(?:music|lyrics|words))?|written|composed)"
                        r"\s+by\s+", re.I)
_PERFORMED_RE = re.compile(r"\b(?:performed|sung)\s+by\b", re.I)


def _first_paren(text: str) -> str:
    """The inside of the first (…) group outside links ('' when none)."""
    depth, link, start, i = 0, 0, -1, 0
    while i < len(text):
        two = text[i:i + 2]
        if two in ("[[", "]]"):
            link = link + 1 if two == "[[" else max(0, link - 1)
            i += 2
            continue
        if link == 0 and text[i] == "(":
            depth += 1
            if depth == 1:
                start = i + 1
        elif link == 0 and text[i] == ")" and depth:
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return ""


def _song(text: str) -> dict | None:
    """JY-152 (2026-10-24): '"[[Song]]" (writers; performed by …) – ''[[Film]]''' -> the film is the work and the
    writers in the first parenthesis are the people (credit words and the performers dropped); no writers -> work-led.
    The song title is never a person. None when the line does not open with a quoted title."""
    m = _SONG_RE.match(text)
    if not m:
        return None
    rest = m.group(2)
    people = []
    for part in _split_top(_first_paren(rest), ";"):
        cut = _PERFORMED_RE.search(part)           # the writers before "performed by" stay, the performers go
        people += _names(_CREDIT_RE.sub("", part[:cut.start()] if cut else part, count=1))
    rest = _drop_parens(rest)
    for dash in _DASHES:
        parts = _split_top(rest, dash)
        if len(parts) > 1:
            rest = dash.join(parts[1:])
            break
    inner, _ = _italic(rest)
    work = _link(inner) if inner else None
    if not work and not people:
        return None
    return {"lead": "person" if people else "work", "work": work, "people": people}


_PEOPLE_RE = re.compile(r"\[\[[^\[\]]+\]\](?:\s*(?:,|,?\s*and|&)\s*\[\[[^\[\]]+\]\])*")


def _in_split(text: str) -> dict | None:
    """"[[Person]] in ''[[Film]]''" (or the whole line in italics) -> person-led; None when the line is not that."""
    if any(len(_split_top(text, d)) > 1 for d in _DASHES):
        return None
    bare, unwrapped = text.strip(), False
    if bare.startswith("''") and bare.endswith("''") and bare.count("''") == 2:
        bare, unwrapped = bare[2:-2].strip(), True
    parts = _split_top(bare, " in ")
    if len(parts) < 2:
        return None
    who = parts[0].strip()
    linked = bool(_PEOPLE_RE.fullmatch(who))
    plain = not unwrapped and "[[" not in who and "''" not in who and 0 < len(who.split()) <= 6
    if not (linked or plain):
        return None
    rest = " in ".join(parts[1:])
    inner, _ = _italic(rest)
    people = _names(who)
    if not people:
        return None
    return {"lead": "person", "work": _link(inner or rest), "people": people}


# ---- the page parser: four page shapes ----

def _add(cur: dict, line: str, in_split: bool = False, won: bool | None = None) -> None:
    """One list (or bare bold) line -> an entry of `cur`."""
    level = len(line) - len(line.lstrip("*"))
    got = _entry(line[level:], in_split)
    if got:
        if won is not None:
            got["won"] = won
        got["pos"] = len(cur["entries"])
        cur["entries"].append(got)
        cur["_levels"].append(level)


def _award_category_blocks(lines: list[str]) -> list[dict]:
    """Today's shape: a `{{Award category|…|[[page|label]]}}` header, then `* '''winner'''` / `** nominee` lines.
    WP-D3 (2026-10-16): Critics' Choice 2002–2018 and BAFTA 1965–1972 put the winner on a bare bold line (not a list
    item) under the header, nominees as `*` lines — that line is the block's winner."""
    blocks: list[dict] = []
    heading_kind, cur = None, None
    for at, line in enumerate(lines):
        h = _HEADING_RE.match(line)
        if h:
            heading_kind = _kind_of_heading(h.group(2))
            cur = None
            continue
        header = _award_header(line) if "ward category" in line else None
        if header:
            cur = {"label": header[0], "page": header[1], "kind": heading_kind, "entries": [], "_levels": [], "_at": at}
            blocks.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith(("{|", "|}", "|", "!")):
            cur = None
            continue
        if line.startswith("*"):
            _add(cur, line)
        elif line.startswith("'''"):
            _add(cur, line, won=True)
    return blocks


_FULL_NAME_RE = re.compile(r"(?:best|outstanding|most)\b|.*\baward\b", re.I)    # a label that needs no caption
_COLSPAN_RE = re.compile(r"colspan\s*=\s*[\"']?\s*(\d+)", re.I)
_AWARD_FOR_RE = re.compile(r"^.*?\bAward for\s+", re.I)


def _cell(raw: str) -> tuple[int, str]:
    """One table cell ('attrs | content' or 'content') -> (colspan, content)."""
    parts = _split_top(raw, "|")
    if len(parts) > 1 and "[[" not in parts[0]:
        attrs, content = parts[0], "|".join(parts[1:])
    else:
        attrs, content = "", raw
    m = _COLSPAN_RE.search(attrs)
    return (max(1, min(int(m.group(1)), 20)) if m else 1), content.strip()


def _category_of(text: str) -> tuple[str, str | None] | None:
    """A table header cell / a heading -> (label, page). Linked: the page is the link target and the label is that target
    minus its leading "<…> Award for " (the visible text is a fragment like "Drama" / "Actor"), else the visible text."""
    clean = _TAG_RE.sub("", _strip_templates(_REF_RE.sub("", text)))
    for m in _LINK_RE.finditer(clean):
        target = (m.group(1) or "").split("#", 1)[0].strip().replace("_", " ")
        if not target or target.lower().startswith(_SKIP_TARGETS):
            continue
        visible = _plain(m.group(2) if m.group(2) is not None else target)
        label = _clip(_AWARD_FOR_RE.sub("", target, count=1)) if _AWARD_FOR_RE.match(target) else visible
        return (label or visible or _clip(target)), _clip(target)
    label = _plain(clean)
    return (label, None) if label else None


def _table_blocks(lines: list[str]) -> list[dict]:
    """Old Globes / SAG / BAFTA tables: a header row of `!` cells names the categories (a header row followed by another
    header row is a group caption, prefixed to the next row's unlinked labels: "Drama" -> "Best Television Series –
    Drama"), the next row's `|` cells carry the entries, cell i under header i (colspan kept). In a cell, `*` lines are
    entries and a bare bold line (or bold cell text) is a winner."""
    blocks: list[dict] = []
    stack: list[dict] = []
    heading_kind = None
    for at, line in enumerate(lines):
        h = _HEADING_RE.match(line)
        if h:
            heading_kind = _kind_of_heading(h.group(2))
            continue
        if line.startswith("{|"):
            stack.append({"heads": [], "row": None, "prev": None, "col": 0, "cell": None})
            continue
        if not stack:
            continue
        t = stack[-1]
        if line.startswith("|}"):
            stack.pop()
            continue
        if line.startswith("|-"):
            t["prev"], t["row"], t["col"], t["cell"] = t["row"], None, 0, None
            continue
        if line.startswith("|+"):
            continue
        if line.startswith("!"):
            t["cell"] = None
            if t["row"] == "data":          # a row-header cell inside a data row
                continue
            if t["row"] != "head":
                caption = t["heads"][0][2] if t["prev"] == "head" and len(t["heads"]) == 1 else None
                t["row"], t["heads"], t["col"], t["caption"] = "head", [], 0, caption and caption[0]
            for raw in _split_top(line[1:], "!!"):
                span, content = _cell(raw)
                cat = None if "award category" in content.lower() else _category_of(content)
                if cat and not cat[1] and t["caption"] and not _FULL_NAME_RE.match(cat[0]):
                    cat = (_clip(f"{t['caption']} – {cat[0]}"), None)
                t["heads"].append((t["col"], span, cat))
                t["col"] += span
            continue
        if line.startswith("|"):
            if t["row"] != "data":
                t["row"], t["col"] = "data", 0
            for raw in _split_top(line[1:], "||"):
                span, content = _cell(raw)
                head = next((c for s, n, c in t["heads"] if s <= t["col"] < s + n), None)
                t["col"] += span
                t["cell"] = None
                if head and "award category" not in content.lower():
                    t["cell"] = {"label": head[0], "page": head[1], "kind": heading_kind, "entries": [], "_levels": [],
                                 "_at": at}
                    if "'''" in content and "[[" in content:     # the winner written in the cell itself
                        _add(t["cell"], content, won=True)
                        if t["cell"]["entries"]:
                            blocks.append(t["cell"])
            continue
        cur = t["cell"]
        if cur is not None and line.startswith(("*", "'''")):
            _add(cur, line, won=True if line.startswith("'''") else None)
            if cur["entries"] and not any(b is cur for b in blocks):
                blocks.append(cur)
    return blocks


_BOLD_LABEL_RE = re.compile(r"'''\s*([^'\[\]{}|]+?)\s*:?\s*'''\s*:?")


def _bold_list_blocks(lines: list[str]) -> list[dict]:
    """Early Critics' Choice: `* '''Best Actor:'''` (bold, no link) names the category, its `**` lines are the winners."""
    blocks: list[dict] = []
    heading_kind, cur = None, None
    for at, line in enumerate(lines):
        h = _HEADING_RE.match(line)
        if h:
            heading_kind = _kind_of_heading(h.group(2))
            cur = None
            continue
        if line.startswith(("{|", "|", "!")):
            cur = None
            continue
        if not line.startswith("*"):
            continue
        level = len(line) - len(line.lstrip("*"))
        if level == 1:
            m = _BOLD_LABEL_RE.fullmatch(line[1:].strip())
            if m:
                cur = {"label": _clip(m.group(1)), "page": None, "kind": heading_kind, "entries": [], "_levels": [],
                       "_at": at}
                blocks.append(cur)
            elif cur is not None and "'''" in line and "[[" in line:
                _add(cur, line, won=True)          # a bold linked level-1 line is a winner of the current block
            else:
                cur = None
            continue
        if cur is not None:
            _add(cur, line, won=True)              # these pages list the winners only
    return [b for b in blocks if b["entries"]]


_STRUCTURAL_RE = re.compile(
    r"^(?:winners?|nominees?|winners and nominees|nominations?|awards?|films?|television|tv|motion pictures?|movies?|"
    r"(?:film|television|tv) awards?|ceremony(?: information)?|background|presenters?(?: and performers)?|performers?|"
    r"in memoriam|see also|references|notes|external links|further reading|sources|statistics|controvers(?:y|ies)|"
    r"reception|broadcast|ratings|hosts?|summary|top \d+ films)$|"
    r"^(?:multiple|most|films with|programs with|series with|networks with|shows with|presenters|ceremony)\b", re.I)


def _heading_blocks(lines: list[str]) -> list[dict]:
    """Old BAFTA / Globes pages with no table: a `===Category===` heading, then a bare bold line (the winner) and `*`
    nominees. Page-structure headings (Film, Winners and nominees, See also, Multiple nominations, …) are not categories;
    under a 'Winners' section (no nominees listed) every entry won, and a category's lone entry won."""
    blocks: list[dict] = []
    cur, section_kind, winners_only = None, None, False
    for at, line in enumerate(lines):
        h = _HEADING_RE.match(line)
        if h:
            cur = None
            level, title = len(h.group(1)), h.group(2)
            plain = _plain(_strip_templates(title))
            if level <= 2:
                low = plain.lower()
                winners_only = low.startswith("winner") and "nomin" not in low
                section_kind = _kind_of_heading(title)
                continue
            if _STRUCTURAL_RE.search(plain):
                section_kind = _kind_of_heading(title) or section_kind
                continue
            cat = _category_of(title)
            if cat:
                cur = {"label": cat[0], "page": cat[1], "kind": _kind_of_heading(title) or section_kind, "entries": [],
                       "_levels": [], "_at": at, "_winners_only": winners_only}
                blocks.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith(("{|", "|", "!")):
            cur = None
        elif line.startswith("*"):
            _add(cur, line, in_split=True)
        elif line.startswith("'''"):
            _add(cur, line, in_split=True, won=True)
    blocks = [b for b in blocks if b["entries"]]
    for b in blocks:
        only = b.pop("_winners_only")
        if not any(e["won"] for e in b["entries"]) and (only or len(b["entries"]) == 1):
            for e in b["entries"]:
                e["won"] = True
    return blocks


def parse_award_blocks(wikitext: str | None) -> dict:
    """-> {shape: ok | none | redirect, redirect: title | None, blocks: [{label, page, kind, entries: [...]}]}.
    `kind` is the section heading's film / tv (None when the heading says neither); entries carry `won`, `lead`
    (work | person), `work` ({title, label} | None), `people` ([{title, label}]) and `pos`.
    Shapes, in this order: `{{Award category}}` (unchanged) -> tables -> bold-label lists; a page may mix them, so every
    shape's blocks with entries are taken in page order, a later shape's block dropped when its page or label is already
    there. Headings are read only when none of those gave a block."""
    text = str(wikitext or "")
    m = _REDIRECT_RE.match(text)
    if m:
        return {"shape": SHAPE_REDIRECT, "redirect": _clip(m.group(1)), "blocks": []}
    text = _COMMENT_RE.sub("", text)
    lines = [raw.strip() for raw in text.splitlines()]
    blocks = _award_category_blocks(lines) if "award category" in text.lower() else []
    for extra in (_table_blocks(lines), _bold_list_blocks(lines)):
        pages = {b["page"].lower() for b in blocks if b["page"]}
        labels = {b["label"].lower() for b in blocks}
        blocks += [b for b in extra if b["entries"] and (b["page"] or "").lower() not in pages
                   and b["label"].lower() not in labels]
    if not blocks:
        blocks = _heading_blocks(lines)
    blocks.sort(key=lambda b: b["_at"])
    for b in blocks:
        del b["_at"]
        levels = b.pop("_levels")
        if b["entries"] and not any(e["won"] for e in b["entries"]) and 1 in levels and any(lv > 1 for lv in levels):
            for e, lv in zip(b["entries"], levels):
                e["won"] = lv == 1
    if not blocks:
        return {"shape": SHAPE_NONE, "redirect": None, "blocks": []}
    return {"shape": SHAPE_OK, "redirect": None, "blocks": blocks}


def titles_of(blocks: list[dict]) -> list[str]:
    """Every distinct linked title on the page (category pages, works, people), in page order."""
    seen, out = set(), []
    for b in blocks:
        cands = [b.get("page")]
        for e in b["entries"]:
            cands.append((e.get("work") or {}).get("title"))
            cands += [p.get("title") for p in e.get("people") or []]
        for t in cands:
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return out


# ---- Wikidata / Wikipedia JSON ----

def _val(binding: dict, key: str) -> str | None:
    v = binding.get(key)
    if not isinstance(v, dict):
        return None
    value = str(v.get("value") or "")
    if value.startswith("http://www.wikidata.org/entity/"):
        value = value.rsplit("/", 1)[1]
    return value or None


def _csv_val(value: str | None) -> str | None:
    value = str(value or "")
    if value.startswith("http://www.wikidata.org/entity/"):
        value = value.rsplit("/", 1)[1]
    return value or None


def sparql_rows(body) -> list[dict]:
    """A SPARQL answer -> [{var: value}] with entity URIs shortened to QIDs and blanks as None. The sync asks for CSV
    (`Accept: text/csv`, ~1/5 the bytes of SPARQL JSON: 320 rows of the 97th Oscars are 388 KB as JSON); a JSON
    answer (`results.bindings`) is read too."""
    if isinstance(body, (str, bytes)):
        text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
        reader = csv.DictReader(io.StringIO(text.lstrip(BOM)))
        return [{k: _csv_val(v) for k, v in r.items() if k} for r in reader]
    try:
        bindings = body["results"]["bindings"]
    except (KeyError, TypeError):
        return []
    return [{k: _val(b, k) for k in b} for b in bindings if isinstance(b, dict)]


def _int(value) -> int | None:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if 0 < n < 10 ** 10 else None


def _qid(value) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"Q[1-9][0-9]{0,11}", value) else None


def entity_kind(human, tm, tt, tp, tvdb) -> str:
    if str(human).lower() in ("true", "1") or (tp and not tm and not tt):
        return "person"
    if tm:
        return "film"
    if tt or tvdb:
        return "tv"
    return "other"


def _entity(qid, label, human, tm, tt, tp, imdb, tvdb) -> dict:
    tm, tt, tp, tvdb = _int(tm), _int(tt), _int(tp), _int(tvdb)
    imdb = imdb if isinstance(imdb, str) and re.fullmatch(r"(tt|nm)\d{5,10}", imdb) else None
    label = None if not label or _qid(str(label)) else _clip(label)    # the label service answers the QID when unlabelled
    return {"qid": qid, "kind": entity_kind(human, tm, tt, tp, tvdb), "label": label,
            "tmdb_movie": tm, "tmdb_tv": tt, "tmdb_person": tp, "imdb": imdb, "tvdb": tvdb}


def entities_from(body) -> dict[str, dict]:
    """The ids answer (?item ?human ?tm ?tt ?tp ?imdb ?tvdb [?itemLabel]) -> {qid: entity}; first value wins."""
    out: dict[str, dict] = {}
    for r in sparql_rows(body):
        qid = _qid(r.get("item"))
        if not qid:
            continue
        got = _entity(qid, r.get("itemLabel"), r.get("human"), r.get("tm"), r.get("tt"), r.get("tp"),
                      r.get("imdb"), r.get("tvdb"))
        old = out.get(qid)
        if old:
            for k, v in got.items():
                if old.get(k) is None and v is not None:
                    old[k] = v
        else:
            out[qid] = got
    return out


def qids_from_pageprops(body) -> dict[str, str]:
    """Wikipedia query+pageprops answer -> {asked title: QID} (normalised and redirected titles mapped back)."""
    q = (body or {}).get("query") if isinstance(body, dict) else None
    if not isinstance(q, dict):
        return {}
    back: dict[str, str] = {}
    for step in ("normalized", "redirects"):
        for r in q.get(step) or []:
            if isinstance(r, dict) and r.get("from") and r.get("to"):
                back[str(r["to"])] = back.get(str(r["from"]), str(r["from"]))
    out: dict[str, str] = {}
    for p in q.get("pages") or []:
        if not isinstance(p, dict):
            continue
        qid = _qid(((p.get("pageprops") or {}).get("wikibase_item")))
        title = str(p.get("title") or "")
        if not qid or not title:
            continue
        out[title] = qid
        t = title
        while t in back:          # chain: asked -> normalised -> redirect target
            t = back[t]
            out[t] = qid
    return out


def wd_label_name(label: str | None, prefixes: tuple = ()) -> str:
    text = _clip(label)
    for p in prefixes:
        if text.lower().startswith(p.lower()):
            return _clip(text[len(p):]) or text
    return text


def wd_nominations(rows: list[dict], *, names: dict | None = None, prefixes: tuple = (),
                   default_kind: str = "film") -> dict:
    """Oscars edition rows / winners-only rows -> {categories, nominations, entities}.
    A human item with a P1686 work is a person nominee for that work; a non-human item is the work itself.
    Category key = the award QID; its name = `names[qid]`, else the award label minus a body prefix."""
    cats: dict[str, dict] = {}
    noms: dict[tuple, dict] = {}
    ents: dict[str, dict] = {}
    for r in rows:
        award, item = _qid(r.get("award")), _qid(r.get("item"))
        if not award or not item:
            continue
        human = str(r.get("human")).lower() in ("true", "1")
        ent = _entity(item, r.get("itemLabel"), r.get("human"), r.get("tm"), r.get("tt"), r.get("tp"), r.get("imdb"),
                      r.get("tvdb"))
        ents.setdefault(item, ent)
        work_qid = _qid(r.get("work"))
        if work_qid:
            w = _entity(work_qid, r.get("workLabel"), None, r.get("wtm"), r.get("wtt"), None, None, r.get("wtvdb"))
            ents.setdefault(work_qid, w)
        if human:
            wq, wt, pq, pn = work_qid or "", (_clip(r.get("workLabel")) if work_qid else ""), item, ent["label"] or ""
        else:
            wq, wt, pq, pn = item, ent["label"] or "", "", ""
        name = (names or {}).get(award) or wd_label_name(r.get("awardLabel"), prefixes) or award
        kind = "tv" if (ent["kind"] == "tv" or (work_qid and ents[work_qid]["kind"] == "tv")) else default_kind
        c = cats.setdefault(award, {"cat_key": award, "name": name, "kind": kind, "lead": "person", "_works": 0})
        if not human:
            c["_works"] += 1
        key = (award, wq, pq)
        won = 1 if str(r.get("won", "1")) in ("1", "true") else 0
        n = noms.get(key)
        if n:
            n["won"] = max(n["won"], won)
        else:
            noms[key] = {"cat_key": award, "work_qid": wq, "work_title": wt, "person_qid": pq, "person_name": pn,
                         "won": won, "year": r.get("_year")}
    for c in cats.values():   # people categories lead with the person even when a film carries a statement too
        works = c.pop("_works")
        c["lead"] = "person" if (not works or PERSON_CAT.search(c["name"] or "")) else "work"
    # Work-led categories: a film named only through its producers' P1686 still is a nominee, and a producer row that
    # points at a duplicate item with the same title (seen live: two "Anora" items) folds into the category's own one.
    canon: dict[tuple, str] = {}
    for (award, wq, pq), n in noms.items():
        if not pq and wq and cats[award]["lead"] == "work":
            canon.setdefault((award, (n["work_title"] or "").lower()), wq)
    for key in list(noms):
        award, wq, pq = key
        n = noms[key]
        if not (pq and wq) or cats[award]["lead"] != "work":
            continue
        cq = canon.setdefault((award, (n["work_title"] or "").lower()), wq)
        if cq != wq:
            del noms[key]
            n["work_qid"] = cq
            old = noms.get((award, cq, pq))
            if old:
                old["won"] = max(old["won"], n["won"])
            else:
                noms[(award, cq, pq)] = n
        work = noms.get((award, cq, ""))
        if work is None:
            noms[(award, cq, "")] = {**n, "person_qid": "", "person_name": "", "work_qid": cq}
        else:
            work["won"] = max(work["won"], n["won"])
    # Person-led categories: the film's own statement ("Anora" holds Best Director too) folds into its people's rows.
    people_of: dict[tuple, list] = {}
    for (award, wq, pq), n in noms.items():
        if pq and wq:
            people_of.setdefault((award, wq), []).append(n)
    for key in list(noms):
        award, wq, pq = key
        if not pq and cats[award]["lead"] == "person" and (award, wq) in people_of:
            won = noms.pop(key)["won"]
            for n in people_of[(award, wq)]:
                n["won"] = max(n["won"], won)
    # pos: winners first, then by label, per category
    by_cat: dict[str, list] = {}
    for n in noms.values():
        by_cat.setdefault(n["cat_key"], []).append(n)
    for award, lst in by_cat.items():
        lst.sort(key=lambda n: (-n["won"], (n["work_title"] or n["person_name"]).lower(), n["person_name"].lower()))
        shared = cats[award]["lead"] == "person" and WRITING_CAT.search(cats[award]["name"] or "")
        slot: dict[tuple, int] = {}
        for i, n in enumerate(lst):
            # one nominee line = one pos; a screenplay's writers share their film's line, an actor never shares
            n["pos"] = slot.setdefault((n["work_qid"], n["won"]), i) if shared and n["work_qid"] else i
    return {"categories": list(cats.values()), "nominations": list(noms.values()), "entities": ents}
