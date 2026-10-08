"""Awards parsers (AWARDS_PLAN A2, 2026-10-08) — pure: no I/O, no DB, no network.

* `parse_award_blocks(wikitext)` reads a Wikipedia ceremony page in the shape every page since the mid-2000s uses:
  a `{{Award category|<colour>|[[<category page>|<label>]]}}` header, then `* '''winner'''` and `** nominee` lines
  ("''[[Film]]'' – [[People]]" for work categories, "[[Person]] – ''[[Film]]'' as Role" for people; Emmys mark the
  winner with `{{double dagger}}`; "(Network)" / "(Country)" parentheticals are dropped). A redirect page or a page
  without a single `{{Award category}}` is reported, never guessed at.
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


# ---- the page parser ----

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


def _entry(content: str) -> dict | None:
    won = "double dagger" in content.lower() or "'''" in content
    text = _COMMENT_RE.sub("", content)
    text = _REF_RE.sub("", text)
    text = _strip_templates(text)
    text = _TAG_RE.sub("", text)
    text = text.replace("'''''", "''").replace("'''", "")
    text = _drop_parens(text).strip()
    if not text:
        return None
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


def parse_award_blocks(wikitext: str | None) -> dict:
    """-> {shape: ok | none | redirect, redirect: title | None, blocks: [{label, page, kind, entries: [...]}]}.
    `kind` is the section heading's film / tv (None when the heading says neither); entries carry `won`, `lead`
    (work | person), `work` ({title, label} | None), `people` ([{title, label}]) and `pos`."""
    text = str(wikitext or "")
    m = _REDIRECT_RE.match(text)
    if m:
        return {"shape": SHAPE_REDIRECT, "redirect": _clip(m.group(1)), "blocks": []}
    if "award category" not in text.lower():
        return {"shape": SHAPE_NONE, "redirect": None, "blocks": []}
    text = _COMMENT_RE.sub("", text)
    blocks: list[dict] = []
    heading_kind, cur = None, None
    for raw in text.splitlines():
        line = raw.strip()
        h = _HEADING_RE.match(line)
        if h:
            heading_kind = _kind_of_heading(h.group(2))
            cur = None
            continue
        header = _award_header(line) if "ward category" in line else None
        if header:
            cur = {"label": header[0], "page": header[1], "kind": heading_kind, "entries": [], "_levels": []}
            blocks.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith(("{|", "|}", "|", "!")):
            cur = None
            continue
        if not line.startswith("*"):
            continue
        level = len(line) - len(line.lstrip("*"))
        got = _entry(line[level:])
        if got:
            got["pos"] = len(cur["entries"])
            cur["entries"].append(got)
            cur["_levels"].append(level)
    for b in blocks:
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
