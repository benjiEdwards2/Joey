"""Awards seeds (AWARDS_PLAN A1, 2026-10-08): the ceremonies, their hero category, curated category ranks and the
usual month each one is held. Pure data + two tiny pure helpers; no I/O.

source: `wd` = Oscars (one SPARQL per edition, nominees + winners), `wp` = the Wikipedia ceremony page (nominees +
winners), `wdw` = winners only from Wikidata P166 (+ P1346 on the category item) for a curated category list — Cannes and
the guilds in v1 (Q3: their nominee tables are a v2 item). Year = the ceremony year (Q1).
`year_offset`: ceremony year ~= offset + ordinal, used to list editions (and to place one on the year stepper) when
Wikidata has no edition item / date for it; a real Wikidata date always wins.
"""

from __future__ import annotations

import re

SEED_VERSION = 1

BODIES: list[dict] = [
    {"id": "oscars", "name": "Oscars", "kinds": "film", "source": "wd", "wd_series": "Q16913666", "wd_series_prop": "P31",
     "wp_title_fmt": "{ord} Academy Awards", "usual_month": 3, "sort": 1, "prestige": 1, "year_offset": 1928,
     "hero": {"film": ("best-picture", "outstanding-picture", "outstanding-production")},
     "prefixes": ("Academy Award for ", "Academy Honorary Award", "Academy Award - ")},
    {"id": "globes", "name": "Golden Globes", "kinds": "film,tv", "source": "wp", "wd_series": "Q19311591",
     "wp_title_fmt": "{ord} Golden Globe Awards", "usual_month": 1, "sort": 2, "prestige": 4, "year_offset": 1943,
     "hero": {"film": ("best-motion-picture-drama", "best-motion-picture"),
              "tv": ("best-television-series-drama", "best-tv-series-drama")}},
    {"id": "bafta", "name": "BAFTA", "kinds": "film", "source": "wp", "wd_series": "Q732997",
     "wp_title_fmt": "{ord} British Academy Film Awards", "usual_month": 2, "sort": 3, "prestige": 3, "year_offset": 1947,
     "hero": {"film": ("best-film", "best-film-from-any-source")}},
    {"id": "critics", "name": "Critics' Choice", "kinds": "film,tv", "source": "wp", "wd_series": "Q7585305",
     "wp_title_fmt": "{ord} Critics' Choice Awards", "usual_month": 1, "sort": 4, "prestige": 6, "year_offset": 1995,
     "hero": {"film": ("best-picture",), "tv": ("best-drama-series",)}},
    {"id": "sag", "name": "SAG", "kinds": "film,tv", "source": "wp", "wd_series": "Q268200",
     "wp_title_fmt": "{ord} Screen Actors Guild Awards", "usual_month": 2, "sort": 5, "prestige": 7, "year_offset": 1994,
     "hero": {"film": ("outstanding-performance-by-a-cast-in-a-motion-picture",),
              "tv": ("outstanding-performance-by-an-ensemble-in-a-drama-series",)}},
    {"id": "dga", "name": "DGA", "kinds": "film", "source": "wdw", "usual_month": 2, "sort": 6, "prestige": 8,
     "edition_fmt": "{year} DGA Awards",
     "categories": {"Q5280675": "Outstanding Directing – Feature Film"},
     "hero": {"film": ("outstanding-directing-feature-film",)}},
    {"id": "pga", "name": "PGA", "kinds": "film", "source": "wdw", "usual_month": 2, "sort": 7, "prestige": 9,
     "edition_fmt": "{year} PGA Awards",
     "categories": {"Q5569374": "Best Theatrical Motion Picture"},
     "hero": {"film": ("best-theatrical-motion-picture",)}},
    {"id": "wga", "name": "WGA", "kinds": "film", "source": "wdw", "usual_month": 3, "sort": 8, "prestige": 10,
     "edition_fmt": "{year} WGA Awards",
     "categories": {"Q8038461": "Best Original Screenplay", "Q8038458": "Best Adapted Screenplay"},
     "hero": {"film": ("best-original-screenplay",)}},
    {"id": "cannes", "name": "Cannes", "kinds": "film", "source": "wdw", "usual_month": 5, "sort": 9, "prestige": 2,
     "edition_fmt": "{year} Cannes Film Festival",
     "categories": {"Q179808": "Palme d'Or", "Q844804": "Grand Prix", "Q510175": "Best Director",
                    "Q586140": "Best Actor", "Q840286": "Best Actress", "Q164200": "Jury Prize",
                    "Q978420": "Best Screenplay"},
     "hero": {"film": ("palme-d-or",)}},
    {"id": "emmys", "name": "Emmys", "kinds": "tv", "source": "wp", "wd_series": "Q1044427",
     "wp_title_fmt": "{ord} Primetime Emmy Awards", "usual_month": 9, "sort": 10, "prestige": 5, "year_offset": 1948,
     "hero": {"tv": ("outstanding-drama-series",)}},
]
BY_ID = {b["id"]: b for b in BODIES}

# Curated ranks (Q2: every category shows; these come first, the rest fold under "More categories").
# First matching rule wins; a name matching FOLD never ranks as core.
FOLD = re.compile(r"\b(short|documentary|guest|technical|special|honorary|humanitarian|lifetime|"
                  r"stunt|casting|rising star|newcomer|debut|young|juvenile|song|score|sound|makeup|make-up|hair|"
                  r"costume|visual effects|editing|cinematography|production design|art direction|"
                  r"choreography|main title|commercial|children|reality|talk|variety|game show|structured)\b", re.I)
CORE_RULES: list[tuple[int, re.Pattern]] = [   # checked in this order; the number is the rank band
    (80, re.compile(r"animated|animation", re.I)),
    (90, re.compile(r"international|foreign|non-english|not in the english", re.I)),
    (20, re.compile(r"direct", re.I)),
    (70, re.compile(r"screenplay|writing|written|writer", re.I)),
    (30, re.compile(r"^(?!.*support)(?!.*actress)(?!.*female).*\bactor\b", re.I)),
    (40, re.compile(r"^(?!.*support).*\b(actress|female actor)\b", re.I)),
    (50, re.compile(r"^(?!.*(actress|female)).*support.*\b(actor|male)\b|^(?!.*(actress|female)).*\bactor\b.*support",
                    re.I)),
    (60, re.compile(r"support|actress|female", re.I)),
    (10, re.compile(r"\b(picture|best film|motion picture|production|drama series|comedy series|musical series|"
                    r"television series|tv series|limited|anthology series|miniseries|palme|feature film|"
                    r"theatrical|cast in a motion picture|ensemble|grand prix|jury prize)\b", re.I)),
]
MORE_RANK = 1000


def hero_slugs(body_id: str, kind: str) -> tuple:
    return (BY_ID.get(body_id) or {}).get("hero", {}).get(kind, ())


def rank_of(body_id: str, kind: str, name: str, slug: str, page_order: int = 0) -> tuple[int, str]:
    """(rank, group) for one category: hero 0, curated core 10–99 (+ page order), everything else 1000+ in 'more'."""
    order = max(0, min(int(page_order or 0), 99))
    if slug in hero_slugs(body_id, kind):
        return 0, "core"
    if not FOLD.search(name or ""):
        for base, rule in CORE_RULES:
            if rule.search(name or ""):
                return base * 10 + order, "core"
    return MORE_RANK + order, "more"
