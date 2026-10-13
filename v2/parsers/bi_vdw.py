"""
Participant-list parsers for biennale MAIN exhibitions, 2017-2026:
  - Venice Biennale (Biennale Arte, International Art Exhibition only)
  - documenta 14 (2017) / documenta fifteen (2022)
  - Whitney Biennial 2017-2026

Design: the crawler fetches and stores the raw page itself; each parser takes
the raw text of ONE fetched page/response and returns a list of artist dicts.

    parse_<edition_id>(page_text: str) -> list[dict]

Every dict has at least:
    name        display name as the source prints it (whitespace-normalised)
    name_en     English/Latin form when the source gives a distinct one, else None
    country     birth country (or place token) as printed by the source, else None
    birth_year  int or None (for collectives this is the FOUNDING year when the
                source prints one - see `entity_hint`)
Optional extra keys (only when the source provides them): death_year,
birth_place, lives_in, section, venue, source_url, members, entity_hint,
given_name, family_name, name_raw, source_person_id, category.

Multi-page sources: call the parser on every page in EDITION_SOURCES[...]["urls"]
and pass the concatenated result through dedupe_artists(). parse_edition() does
exactly that.

Politeness (for the crawler, not enforced here):
  - labiennale.org / static.labiennale.org robots.txt: Crawl-delay: 60
  - asac.labiennale.org: no robots.txt (HTTP 404) - keep the same 60 s delay
  - whitney.org robots.txt disallows /artists? /guides? /collection/works? /search?
    (query-string variants only) - /exhibitions/... pages are allowed
  - documenta14.de, documenta-fifteen.de: Allow all
User-Agent used for research: "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Callable, Iterable

from bs4 import BeautifulSoup

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

_WS = re.compile(r"\s+")
_YEAR = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-3][0-9])(?!\d)")
_GROUP_WORDS = re.compile(
    r"\b(collective|collectif|colectivo|group|groupe|orchestra|archive[s]?|foundation|"
    r"company|institute|institut|library|project[s]?|club|art factory|studio|"
    r"film|publishing|practices|futurism|biennale|platform|plateforme|house|"
    r"cluster|gudskul|trust|centre|center|commons|workers|network|association)\b",
    re.I,
)


def _clean(s: str | None) -> str:
    if s is None:
        return ""
    s = s.replace("\xad", "").replace("\u200b", "").replace("\u2028", " ")
    s = unicodedata.normalize("NFC", s)
    s = _WS.sub(" ", s).strip()
    return re.sub(r"\s+([,.;:])(?=\s|$)", r"\1", s)


def _soup(page_text: str) -> BeautifulSoup:
    return BeautifulSoup(page_text, "lxml")


def _entity_hint(name: str, members: list | None = None) -> str | None:
    """HEURISTIC, not verified: 'group' if the display name looks like a duo/collective
    (members listed, '&'/'and'/',', or collective-type words). None = no group signal;
    _artist() then resolves it to 'person_likely' (has a birth/death year) or 'unknown'."""
    if members:
        return "group"
    if re.search(r"\s(&|and|und)\s|,|/|\+", name):
        return "group"
    if _GROUP_WORDS.search(name):
        return "group"
    return None


def _artist(name, name_en=None, country=None, birth_year=None, **extra) -> dict:
    d = {
        "name": _clean(name),
        "name_en": _clean(name_en) or None,
        "country": _clean(country) or None,
        "birth_year": birth_year,
    }
    for k, v in extra.items():
        if v not in (None, "", [], {}):
            d[k] = v
    if "entity_hint" in extra and d.get("entity_hint") in (None, "person"):
        if extra.get("entity_hint") == "person":  # source-asserted (e.g. ASAC collettivo=false)
            d["entity_hint"] = "person"
        else:
            d["entity_hint"] = "person_likely" if (birth_year or extra.get("death_year")) else "unknown"
    return d


def _norm_key(name: str) -> str:
    s = unicodedata.normalize("NFKD", _clean(name)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def dedupe_artists(artists: Iterable[dict]) -> list[dict]:
    """Drop exact repeats (same accent/case-folded name). First occurrence wins,
    but missing scalar fields are filled from later duplicates."""
    out: dict[str, dict] = {}
    for a in artists:
        k = _norm_key(a["name"])
        if not k:
            continue
        if k not in out:
            out[k] = dict(a)
        else:
            for f, v in a.items():
                if out[k].get(f) in (None, "", []) and v not in (None, "", []):
                    out[k][f] = v
    return list(out.values())


def _country_from_place(place: str) -> str | None:
    """'Chicago, IL, USA' -> 'USA'; 'Tel Aviv' -> None (no country token)."""
    parts = [p.strip(" .") for p in place.split(",") if p.strip(" .")]
    if len(parts) >= 2:
        last = parts[-1]
        m = re.search(r"\b(USA|UK)$", last)
        return m.group(1) if m else last
    return None


# --------------------------------------------------------------------------
# Venice - labiennale.org listing cards (2019, 2022, 2024 sections, 2026 /artists)
#   <article class="node node-partecipante node-teaser"> ... .lb-item-title,
#   .lb-date (venue), .lb-excerpt (birth info). 9 cards per page, pager link
#   a.js-pager-link -> ?page=N
# --------------------------------------------------------------------------

def _parse_lb_excerpt(text: str) -> dict:
    """Formats seen:
       '1985, Jordan' | 'United Kingdom' | '1924 – 2014, Italy'          (2019/2022)
       'Alexandria, Egypt\\n1930 – 2010'                                  (2024)
       'Cirebon, Indonesia, 1907 – 1990, Yogyakarta, Indonesia'           (2024)
       'Venice, Italy, 1985\\nLives in Paris, France'                      (2024)
       '1972, PRC\\n1974, PRC'  (duo: two lines)                           (2019)
    """
    out = {"country": None, "birth_year": None, "death_year": None,
           "birth_place": None, "lives_in": None}
    text = (text or "").replace("\xa0", " ").replace("\u2028", " ")
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    lives = [l for l in lines if re.match(r"lives\b", l, re.I)]
    if lives:
        out["lives_in"] = _clean(re.sub(r"^lives\s*in\s*", "", lives[0], flags=re.I))
    body_lines = [l for l in lines if not re.match(r"lives\b", l, re.I)]
    # duo with two birth lines -> keep only if all lines share the same country
    year_lines = [l for l in body_lines if _YEAR.search(l)]
    if len(year_lines) > 1 and all(not re.search(r"[–-]", l) for l in year_lines):
        countries = {l.split(",", 1)[1].strip() for l in year_lines if "," in l}
        out["country"] = countries.pop() if len(countries) == 1 else None
        return out
    body = ", ".join(body_lines)
    m = _YEAR.search(body)
    if not m:
        if body:
            out["country"] = _clean(body.split(",")[-1])
        return out
    out["birth_year"] = int(m.group(1))
    before = body[: m.start()].strip(" ,.")
    after = body[m.end():]
    md = re.match(r"\s*[–\-]\s*(\d{4})", after)
    if md:
        out["death_year"] = int(md.group(1))
        after = after[md.end():]
    if before:  # 2024 style: place precedes the year
        out["birth_place"] = _clean(before)
        parts = [p.strip() for p in before.split(",") if p.strip()]
        out["country"] = parts[-1] if parts else None
    else:  # 2019/2022 style: '1985, Jordan' / '1924 – 2014, Italy'
        tail = after.strip(" ,.")
        if tail:
            out["country"] = _clean(tail.split(",")[0]) if tail.count(",") == 0 else _clean(tail.split(",")[-1])
    return out


def parse_labiennale_listing(page_text: str) -> list[dict]:
    """One page of a labiennale.org participant listing (9 cards/page)."""
    s = _soup(page_text)
    out = []
    for art in s.select("article.node-partecipante"):
        title = art.select_one(".lb-item-title")
        if not title:
            continue
        name = _clean(title.get_text(" "))
        a = art.select_one("a.lb-entry-link")
        venue = art.select_one(".lb-date")
        exc = art.select_one(".lb-excerpt")
        info = _parse_lb_excerpt(exc.get_text("\n") if exc else "")
        out.append(_artist(
            name, None, info["country"], info["birth_year"],
            death_year=info["death_year"], birth_place=info["birth_place"],
            lives_in=info["lives_in"], venue=_clean(venue.get_text(" ")) if venue else None,
            source_url=("https://www.labiennale.org" + a["href"]) if a and a.get("href", "").startswith("/") else None,
            entity_hint=_entity_hint(name),
        ))
    return out


def labiennale_next_page_url(page_text: str) -> str | None:
    """Follow the 'Load more' pager; None on the last page."""
    a = _soup(page_text).select_one("a.js-pager-link")
    if a and a.get("href"):
        return "https://www.labiennale.org" + a["href"]
    return None


# --------------------------------------------------------------------------
# Venice 2017 - single page https://www.labiennale.org/en/art/2017/artists
#   '1. ADER, Bas Jan  >>>' / 'b. 1942 The Netherlands, missing since 1975'
# --------------------------------------------------------------------------

_PARTICLES = {"de", "da", "di", "del", "della", "van", "von", "der", "den", "y", "e", "la", "le"}


def _tc(chunk: str) -> str:
    """Title-case an ALL-CAPS surname chunk ('RAMÍREZ-FIGUEROA' -> 'Ramírez-Figueroa');
    particles after the first word stay lower-case. Casing like 'LeWitt' cannot be recovered."""
    def cap(w: str) -> str:
        return "-".join(p[:1].upper() + p[1:].lower() for p in w.split("-"))
    words = chunk.split()
    return " ".join(cap(w) if (i == 0 or w.lower() not in _PARTICLES) else w.lower()
                    for i, w in enumerate(words))


def _split_caps_given(chunk: str) -> tuple[str, str]:
    """'MIRALDA Antoni' -> ('Antoni', 'Miralda'); 'NUÑEZ Katherine' -> ..."""
    toks = chunk.split()
    caps = [t for t in toks if t.upper() == t and re.search(r"[A-ZÀ-Ý]", t)]
    given = [t for t in toks if t not in caps]
    return " ".join(given), _tc(" ".join(caps))


def _parse_2017_bio(bio: str) -> dict:
    out = {"birth_year": None, "death_year": None, "country": None, "lives_in": None}
    b = _clean(bio)
    m = re.match(r"b\.\s*(?:in\s+)?(\d{4})?\s*(.*)$", b)
    if not m:
        return out
    if m.group(1):
        out["birth_year"] = int(m.group(1))
    rest = m.group(2)
    md = re.search(r"[–-]\s*d\.\s*(\d{4})\s*(.*)$", rest)
    if md:
        out["death_year"] = int(md.group(1))
        pre = rest[: md.start()].strip(" ,")
        out["country"] = pre or md.group(2).strip(" ,") or None
        return out
    ml = re.search(r",\s*(?:lives and works|live and work)\s+in\s+(.*)$", rest)
    if ml:
        out["lives_in"] = ml.group(1).strip()
        rest = rest[: ml.start()]
    rest = re.sub(r",\s*missing since.*$", "", rest)
    out["country"] = rest.strip(" ,") or None
    return out


def parse_venice_2017(page_text: str) -> list[dict]:
    s = _soup(page_text)
    blocks = s.select("div.paragraphs-item-text div.col-md-12")
    lines: list[str] = []
    for blk in blocks:
        for d in blk.find_all("div", recursive=False):
            t = _clean(d.get_text(" ")).replace(">>>", "").strip()
            if t:
                lines.append(t)
    out, cur = [], None
    entry_re = re.compile(r"^(\d{1,3})\.\s*(.+)$")
    for ln in lines:
        m = entry_re.match(ln)
        if m and not ln.lower().startswith("b."):
            raw = _clean(m.group(2))
            bios = []
            # some entries carry the bio in the same <div>: 'NUÑEZ Katherine & RODRIGUEZ Issay b. 1992 ...'
            mb = re.search(r"\s(b\.\s.*|Founded\s.*)$", raw)
            if mb:
                bios.append(mb.group(1).strip())
                raw = raw[: mb.start()].strip()
            cur = {"no": int(m.group(1)), "raw": raw, "bios": bios}
            out.append(cur)
        elif cur is not None and (ln.startswith("b.") or ln.lower().startswith("founded")):
            cur["bios"].append(ln)
    artists = []
    for e in out:
        raw = e["raw"]
        members, given, family, founded = None, None, None, None
        paren = re.match(r"^(.*?)\s*\((.+)\)$", raw)
        if paren:  # 'MONDRIAN FAN CLUB (David Medalla & Adam Nankervis)'
            name = _tc(paren.group(1)) if paren.group(1).isupper() else paren.group(1)
            members = [m.strip() for m in re.split(r"\s*&\s*|,\s*", paren.group(2)) if m.strip()]
        elif "," in raw and re.match(r"^[^,]+,\s*[^,]+$", raw) and raw.split(",")[0].isupper():
            fam, giv = [p.strip() for p in raw.split(",", 1)]  # 'ADER, Bas Jan'
            family, given = _tc(fam), giv
            name = f"{given} {family}"
        elif re.search(r"&|,", raw):  # 'NUÑEZ Katherine & RODRIGUEZ Issay' / 4-person group
            parts = [p for p in re.split(r"\s*&\s*|,\s*", raw) if p]
            members = []
            for p in parts:
                g, f = _split_caps_given(p)
                members.append(f"{g} {f}".strip())
            name = (" & " if "&" in raw else ", ").join(members)
        else:  # mononym / collective, all caps: 'MARWAN', 'THE PLAY', 'OHO', 'ANDY HOPE 1930'
            name = raw if len(raw) <= 3 else _tc(raw)
        bio_txt = " ".join(e["bios"])
        info = _parse_2017_bio(e["bios"][0]) if e["bios"] and not members else {}
        if e["bios"] and e["bios"][0].lower().startswith("founded"):
            y = _YEAR.search(e["bios"][0])
            founded = int(y.group(1)) if y else None
        artists.append(_artist(
            name, None, info.get("country"), info.get("birth_year") or founded,
            death_year=info.get("death_year"), lives_in=info.get("lives_in"),
            given_name=given, family_name=family, name_raw=raw, members=members,
            bio_raw=bio_txt or None, list_no=e["no"],
            entity_hint="group" if (members or founded) else _entity_hint(name),
        ))
    return artists


# --------------------------------------------------------------------------
# Venice 2026 - single page https://www.labiennale.org/en/news/biennale-arte-2026-invited-artists
#   <ol><li value="N"><strong>Name</strong></li></ol><p>Born 1983, Manila, Philippines. Lives in ...</p>
#   collective members: <p style="margin-left:72pt"><strong>Member</strong></p>
#   'APPLIED ARTS PAVILION' heading -> special project (excluded from main list)
# --------------------------------------------------------------------------

def _parse_born(bio: str) -> dict:
    out = {"birth_year": None, "death_year": None, "birth_place": None,
           "country": None, "lives_in": None, "founded": None}
    b = _clean(bio)
    mf = re.match(r"founded\s*(\d{4}),?\s*(.*)$", b, re.I)
    if mf:
        out["founded"] = int(mf.group(1))
        out["birth_place"] = mf.group(2).strip(" .") or None
        out["country"] = _country_from_place(out["birth_place"] or "")
        return out
    mb = re.search(r"\bborn,?\s*(\d{4})[,.]?\s*(.*)$", b, re.I)
    if not mb:
        return out
    out["birth_year"] = int(mb.group(1))
    rest = mb.group(2)
    if re.match(r"lives in", rest, re.I):  # 'Born 1988. Lives in Berlin, Germany.'
        out["lives_in"] = re.sub(r"^lives in\s*", "", rest, flags=re.I).strip(" .")
        return out
    md = re.search(r"\bD\.\s*(\d{4})", rest)
    if md:
        out["death_year"] = int(md.group(1))
    ml = re.search(r"\bLives in\s+(.*?)\.?$", rest)
    if ml:
        out["lives_in"] = ml.group(1).strip()
    place = re.split(r"\.\s*(?:Lives|D\.)|,\s*D\.|\s+Lives in|\.\s+\d{4}", rest)[0].strip(" .,")
    place = re.sub(r",\s*\d{4}$", "", place)
    out["birth_place"] = place or None
    out["country"] = _country_from_place(place) if place else None
    return out


def parse_venice_2026(page_text: str) -> list[dict]:
    s = _soup(page_text)
    first = s.find(string=re.compile(r"Born \d{4}"))
    cont = first.find_parent("div", class_="lb-page-content") if first else None
    if cont is None:
        return []
    entries, cur, last_member, section = [], None, None, "main"
    for el in cont.find_all(["ol", "p"], recursive=False):
        txt = _clean(el.get_text(" "))
        if not txt:
            continue
        if "APPLIED ARTS PAVILION" in txt.upper():
            section = "applied_arts_pavilion"
            continue
        if el.name == "ol":
            li = el.find("li")
            if not li:
                continue
            strongs = "".join(st.get_text("") for st in li.find_all("strong"))
            name = _clean(strongs).rstrip(":*").strip()
            rest = _clean(li.get_text(" ").replace(strongs, "", 1)) if strongs else ""
            cur = {"no": int(li.get("value") or 1), "name": name, "bios": [],
                   "members": [], "section": section}
            if re.search(r"\bborn\b|\bfounded\b", rest, re.I):
                cur["bios"].append(rest)
            entries.append(cur)
            last_member = None
            continue
        if cur is None:
            continue
        style = el.get("style", "")
        if "72" in style and el.find("strong") and not re.match(r"(born|founded)\b", txt, re.I):
            last_member = {"name": _clean(el.get_text(" ")).rstrip(":*"), "bios": []}
            cur["members"].append(last_member)
            continue
        if re.search(r"\bborn\b|\bfounded\b", txt, re.I):
            (last_member["bios"] if last_member is not None else cur["bios"]).append(txt)
        elif "out of competition" in txt.lower():
            continue
    artists = []
    for e in entries:
        info = _parse_born(e["bios"][0]) if len(e["bios"]) == 1 else {}
        members = []
        for m in e["members"]:
            mi = _parse_born(m["bios"][0]) if m["bios"] else {}
            members.append({k: v for k, v in {
                "name": m["name"], "birth_year": mi.get("birth_year"),
                "founded": mi.get("founded"), "death_year": mi.get("death_year"),
                "birth_place": mi.get("birth_place")}.items() if v is not None})
        name = e["name"]
        if not members and len(e["bios"]) > 1 and " & " in name:  # duo with one bio line each
            for nm, bio in zip([x.strip() for x in name.split(" & ")], e["bios"]):
                mi = _parse_born(bio)
                members.append({k: v for k, v in {
                    "name": nm, "birth_year": mi.get("birth_year"), "death_year": mi.get("death_year"),
                    "birth_place": mi.get("birth_place")}.items() if v is not None})
        hint = "group" if (members or info.get("founded") or len(e["bios"]) > 1) else _entity_hint(name)
        artists.append(_artist(
            name, None, info.get("country"), info.get("birth_year") or info.get("founded"),
            death_year=info.get("death_year"), birth_place=info.get("birth_place"),
            lives_in=info.get("lives_in"), members=members or None,
            bio_raw=" | ".join(e["bios"]) or None, list_no=e["no"],
            section=e["section"], entity_hint=hint,
        ))
    return artists


# --------------------------------------------------------------------------
# Venice - ASAC (Archivio Storico delle Arti Contemporanee) Elasticsearch proxy
#   POST https://asac.labiennale.org/api/ricerca-semplice
#   body {"callBody": {"query": {"match": {"anno": "<YEAR>"}}}, "callIndex": "annali_arti_visive"}
#   -> one record per edition with `sezione` (sections) each holding `elenco_persone`.
#   Main exhibition = sections whose title starts with the exhibition title.
# --------------------------------------------------------------------------

def _asac_parse(page_text: str, section_pred: Callable[[str], bool],
                section_tag: Callable[[str], str]) -> list[dict]:
    d = json.loads(page_text)
    hits = d.get("data", {}).get("hits", {}).get("hits", [])
    if not hits:
        return []
    src = hits[0]["_source"]
    coll = {p["id"]: bool(p.get("collettivo")) for p in (src.get("partecipante") or [])}
    seen: dict[int, dict] = {}
    for sez in src.get("sezione") or []:
        title = _clean(sez.get("titolo"))
        if not section_pred(title):
            continue
        for p in sez.get("elenco_persone") or []:
            pid = p.get("id")
            if pid in seen:
                seen[pid]["asac_sections"].append(title)
                continue
            name = _clean(p.get("nome_cognome"))
            seen[pid] = _artist(
                name, None, None, None,
                given_name=_clean(p.get("nome")) or None,
                family_name=_clean(p.get("cognome")) or None,
                source_person_id=f"asac:persone/{pid}",
                section=section_tag(title),
                venue=_clean(sez.get("luogo")) or None,
                entity_hint="group" if coll.get(pid) else None,
            )
            seen[pid]["asac_sections"] = [title]
    # a person listed in several sections: prefer the core-exhibition tag over
    # special-project / college tags (section order in the JSON is arbitrary)
    for rec in seen.values():
        tags = [section_tag(t) for t in rec["asac_sections"]]
        core = [t for t in tags if not t.startswith(("special_project", "biennale_college"))]
        rec["section"] = core[0] if core else tags[0]
    return list(seen.values())


def _tag_2022(t: str) -> str:
    if "College" in t:
        return "biennale_college_arte (out of competition)"
    if "Forte Marghera" in t:
        return "special_project_forte_marghera"
    if "Capsula" in t:
        return "historical_capsule"
    return "main"


def parse_venice_2022(page_text: str) -> list[dict]:
    """ASAC JSON for anno=2022 (59th, 'Il latte dei sogni' / The Milk of Dreams)."""
    return _asac_parse(page_text, lambda t: t.startswith("Il latte dei sogni"), _tag_2022)


def _tag_2024(t: str) -> str:
    if "College" in t:
        return "biennale_college_arte (out of competition)"
    if "Forte Marghera" in t:
        return "special_project_forte_marghera"
    if "Nucleo storico" in t:
        return "nucleo_storico:" + t.split(":", 1)[-1].strip()
    return "nucleo_contemporaneo"


def parse_venice_2024(page_text: str) -> list[dict]:
    """ASAC JSON for anno=2024 (60th, 'Stranieri Ovunque' / Foreigners Everywhere)."""
    return _asac_parse(page_text, lambda t: t.startswith("Stranieri Ovunque"), _tag_2024)


def parse_venice_2019_asac(page_text: str) -> list[dict]:
    """Cross-check only (2019 primary source is the labiennale.org listing)."""
    return _asac_parse(page_text, lambda t: t.startswith("May You Live In Interesting Times - Proposta"),
                       lambda t: "main")


def parse_venice_2017_asac(page_text: str) -> list[dict]:
    """Cross-check only (2017 primary source is the labiennale.org single page)."""
    return _asac_parse(page_text, lambda t: t.startswith(("VIVA ARTE VIVA - Padiglione",
                                                          "VIVA ARTE VIVA - Progetti speciali")),
                       lambda t: t.replace("VIVA ARTE VIVA - ", ""))


def parse_venice_2019(page_text: str) -> list[dict]:
    """One page of https://www.labiennale.org/en/art/2019/artists?page=N"""
    return parse_labiennale_listing(page_text)


# --------------------------------------------------------------------------
# documenta 14 (2017) - https://www.documenta14.de/en/public-exhibition/
#   <section data-section="artists"> has two <ul class="content-list-items">:
#   [0] artists (149 entries), [1] historical positions with life dates (104)
# --------------------------------------------------------------------------

_LIFE = re.compile(r"\s*\(((?:ca\.\s*)?\d{3,4})\s*[–-]\s*(?:ca\.\s*)?(\d{3,4})?[^)]*\)\s*$")


def _d14_item(a, section: str) -> dict:
    raw = _clean(a.get_text(" "))
    name, by, dy, note = raw, None, None, None
    m = _LIFE.search(raw)
    if m:
        name = raw[: m.start()].strip()
        y1 = _YEAR.search(m.group(1))
        by = int(y1.group(1)) if y1 else None
        dy = int(m.group(2)) if m.group(2) else None
        if "," in raw[m.start():]:  # 'Jacob and Wilhelm Grimm (1785–1863, 1786–1859)'
            by = dy = None
            note = raw[m.start():].strip(" ()")
    else:
        mp = re.match(r"^(.*?)\s*\((.+)\)$", raw)
        if mp:
            name, note = mp.group(1).strip(), mp.group(2).strip()
    members, founded = None, None
    if note and "," in note and not _YEAR.search(note):
        # 'Sámi Artist Group (Keviselie/Hans Ragnar Mathisen, Britta Marakatt-Labba, Synnøve Persen)'
        members = [x.strip() for x in re.split(r",\s*", note) if x.strip()]
    mf = re.match(r"founded\s+(\d{4})", note or "", re.I)  # 'KSYME-CMRC (founded 1979)'
    if mf:
        founded = by = int(mf.group(1))
    href = a.get("href", "")
    return _artist(
        name, None, None, by, death_year=dy,
        paren_note=note if not members else None, members=members,
        section=section, source_url="https://www.documenta14.de" + href if href.startswith("/") else None,
        source_person_id=("documenta14:" + href.split("/")[3]) if re.match(r"^/en/artists/\d+", href) else None,
        entity_hint="group" if founded else _entity_hint(name, members),
    )


def parse_documenta_2017(page_text: str) -> list[dict]:
    """Contemporary participants only. Historical positions: parse_documenta_2017_historical."""
    s = _soup(page_text)
    sec = s.find("section", attrs={"data-section": "artists"})
    if not sec:
        return []
    uls = sec.find_all("ul", class_="content-list-items")
    return [_d14_item(a, "artist") for a in uls[0].find_all("a", href=True)] if uls else []


def parse_documenta_2017_historical(page_text: str) -> list[dict]:
    s = _soup(page_text)
    sec = s.find("section", attrs={"data-section": "artists"})
    uls = sec.find_all("ul", class_="content-list-items") if sec else []
    return [_d14_item(a, "historical_position") for a in uls[1].find_all("a", href=True)] if len(uls) > 1 else []


# --------------------------------------------------------------------------
# documenta fifteen (2022) - https://documenta-fifteen.de/en/lumbung-members-artists/
#   <a class="teaser" x-show="isFiltered('lumbung-artists ')"> <h3>Name</h3>
#   categories: lumbung-members (14), lumbung-artists (53), harvesters (5, excluded)
# --------------------------------------------------------------------------

def parse_documenta_2022(page_text: str, include_harvesters: bool = False) -> list[dict]:
    s = _soup(page_text)
    out = []
    for a in s.select("a.teaser"):
        m = re.search(r"isFiltered\('([^']*)'\)", a.get("x-show", ""))
        cat = m.group(1).strip() if m else None
        if cat == "harvesters" and not include_harvesters:
            continue
        h = a.find(["h3", "h2", "h4"])
        raw = _clean(h.get_text(" ") if h else a.get_text(" "))
        name, members = raw, None
        mb = re.match(r"^(.*?)\s*\[(.+)\]$", raw)  # 'ook_ [reinaart vanhoe, Neue Brüderkirche, ...]'
        if mb and not raw.startswith("Sada"):
            name = mb.group(1).strip()
            members = [x.strip() for x in mb.group(2).split(",") if x.strip() and x.strip() != "..."]
        out.append(_artist(
            name, None, None, None,
            category={"lumbung-members": "lumbung_member", "lumbung-artists": "lumbung_artist",
                      "harvesters": "harvester"}.get(cat, cat),
            members=members, name_raw=raw if raw != name else None,
            source_url=a.get("href"),
            entity_hint=_entity_hint(name, members),
        ))
    return out


# --------------------------------------------------------------------------
# Whitney Biennial - https://whitney.org/exhibitions/<year>-biennial/art
#   artist index: <a class="feature-section" href=".../art?section=N">Name</a>
#   detail (?section=N, optional enrichment): 'Born 1986 in Yellowknife, Canada' / 'Lives in ...'
# --------------------------------------------------------------------------

def parse_whitney(page_text: str) -> list[dict]:
    s = _soup(page_text)
    out = []
    for a in s.select("a.feature-section[href*='section=']"):
        name = _clean(a.get_text(" "))
        if not name:
            continue
        href = a["href"]
        out.append(_artist(name, None, None, None,
                           source_url="https://whitney.org" + href if href.startswith("/") else href,
                           entity_hint=_entity_hint(name)))
    return out


def parse_whitney_section_detail(page_text: str) -> dict | None:
    """Enrichment from a ?section=N page (active section only)."""
    s = _soup(page_text)
    frame = s.find("turbo-frame", id="turbo_exhibition_feature_section") or s
    txt = frame.get_text("\n", strip=True)
    mb = re.search(r"Born\s+(?:c\.\s*)?(\d{4})(?:\s+in\s+([^\n]+))?", txt)
    ml = re.search(r"Lives in\s+([^\n]+)", txt)
    if not mb and not ml:
        return None
    place = _clean(mb.group(2)) if mb and mb.group(2) else None
    return {"birth_year": int(mb.group(1)) if mb else None, "birth_place": place,
            "country": _country_from_place(place) if place else None,
            "lives_in": _clean(ml.group(1)) if ml else None}


parse_whitney_2017 = parse_whitney
parse_whitney_2019 = parse_whitney
parse_whitney_2022 = parse_whitney
parse_whitney_2024 = parse_whitney
parse_whitney_2026 = parse_whitney


# --------------------------------------------------------------------------
# Source registry
# --------------------------------------------------------------------------

def _lb_pages(path: str, last_page: int) -> list[str]:
    base = f"https://www.labiennale.org{path}"
    return [base] + [f"{base}?page={i}" for i in range(1, last_page + 1)]


ASAC_API = "https://asac.labiennale.org/api/ricerca-semplice"


def _asac_body(year: int) -> dict:
    return {"callBody": {"query": {"match": {"anno": str(year)}}}, "callIndex": "annali_arti_visive"}


EDITION_SOURCES: dict[str, dict] = {
    "venice_2017": {
        "urls": ["https://www.labiennale.org/en/art/2017/artists"],
        "parser": "parse_venice_2017", "fetch": "html", "crawl_delay_s": 60,
        "crosscheck": {"urls": [ASAC_API], "method": "POST", "json_body": _asac_body(2017),
                       "parser": "parse_venice_2017_asac", "fetch": "json"},
    },
    "venice_2019": {
        "urls": _lb_pages("/en/art/2019/artists", 8),  # verified: pages 0..8, 79 cards
        "parser": "parse_venice_2019", "fetch": "html", "crawl_delay_s": 60,
        "crosscheck": {"urls": [ASAC_API], "method": "POST", "json_body": _asac_body(2019),
                       "parser": "parse_venice_2019_asac", "fetch": "json"},
    },
    "venice_2022": {
        "urls": [ASAC_API], "method": "POST", "json_body": _asac_body(2022),
        "parser": "parse_venice_2022", "fetch": "json", "crawl_delay_s": 60,
        # cleaner (curated, with birth year/country) but 24 pages @ 60 s crawl-delay;
        # 24 pages = 213 participants / 9 per page (estimate; follow labiennale_next_page_url() to be exact)
        "alternative": {"urls": _lb_pages("/en/art/2022/milk-dreams", 23),
                        "parser": "parse_labiennale_listing", "fetch": "html", "paginate": "labiennale_next_page_url"},
    },
    "venice_2024": {
        "urls": [ASAC_API], "method": "POST", "json_body": _asac_body(2024),
        "parser": "parse_venice_2024", "fetch": "json", "crawl_delay_s": 60,
        # four section listings, page counts estimated from announced section sizes (110/111/37/40)
        "alternative": {"urls": (_lb_pages("/en/art/2024/nucleo-contemporaneo", 12)
                                 + _lb_pages("/en/art/2024/portraits", 12)
                                 + _lb_pages("/en/art/2024/abstractions", 4)
                                 + _lb_pages("/en/art/2024/italians-everywhere", 4)),
                        "parser": "parse_labiennale_listing", "fetch": "html", "paginate": "labiennale_next_page_url"},
    },
    "venice_2026": {
        "urls": ["https://www.labiennale.org/en/news/biennale-arte-2026-invited-artists"],
        "parser": "parse_venice_2026", "fetch": "html", "crawl_delay_s": 60,
        "alternative": {"urls": _lb_pages("/en/art/2026/artists", 12),
                        "parser": "parse_labiennale_listing", "fetch": "html", "paginate": "labiennale_next_page_url"},
    },
    "documenta_2017": {
        "urls": ["https://www.documenta14.de/en/public-exhibition/"],
        "parser": "parse_documenta_2017", "fetch": "html",
        "extra_parsers": {"historical_positions": "parse_documenta_2017_historical"},
    },
    "documenta_2022": {
        "urls": ["https://documenta-fifteen.de/en/lumbung-members-artists/"],
        "parser": "parse_documenta_2022", "fetch": "html",
        # JSON alternative (German titles, no category names - map artist_types ids):
        # https://documenta-fifteen.de/wp-json/wp/v2/artist?per_page=100
    },
    "whitney_2017": {"urls": ["https://whitney.org/exhibitions/2017-biennial/art"],
                     "parser": "parse_whitney_2017", "fetch": "html",
                     "detail_url_template": "https://whitney.org/exhibitions/2017-biennial/art?section={n}",
                     "detail_parser": "parse_whitney_section_detail"},
    "whitney_2019": {"urls": ["https://whitney.org/exhibitions/2019-biennial/art"],
                     "parser": "parse_whitney_2019", "fetch": "html",
                     "detail_url_template": "https://whitney.org/exhibitions/2019-biennial/art?section={n}",
                     "detail_parser": "parse_whitney_section_detail"},
    "whitney_2022": {"urls": ["https://whitney.org/exhibitions/2022-biennial/art"],
                     "parser": "parse_whitney_2022", "fetch": "html",
                     "detail_url_template": "https://whitney.org/exhibitions/2022-biennial/art?section={n}",
                     "detail_parser": "parse_whitney_section_detail"},
    "whitney_2024": {"urls": ["https://whitney.org/exhibitions/2024-biennial/art"],
                     "parser": "parse_whitney_2024", "fetch": "html",
                     "detail_url_template": "https://whitney.org/exhibitions/2024-biennial/art?section={n}",
                     "detail_parser": "parse_whitney_section_detail"},
    "whitney_2026": {"urls": ["https://whitney.org/exhibitions/2026-biennial/art"],
                     "parser": "parse_whitney_2026", "fetch": "html",
                     "detail_url_template": "https://whitney.org/exhibitions/2026-biennial/art?section={n}",
                     "detail_parser": "parse_whitney_section_detail"},
}


def parse_edition(edition_id: str, pages: list[str]) -> list[dict]:
    """Apply the registered parser to every fetched page (same order as urls) and dedupe."""
    fn = globals()[EDITION_SOURCES[edition_id]["parser"]]
    out: list[dict] = []
    for p in pages:
        out.extend(fn(p))
    return dedupe_artists(out)


# --------------------------------------------------------------------------- v2 adapter
def parse_pages(pages: list[str], edition_id: str) -> list[dict]:
    """load.py edition_parser 계약. 베니스 2017(공식)·2022/2024(ASAC 아카이브)는 "이름 성" 순으로 재구성돼
    동아시아 이름이 뒤집히므로('Bul Lee') "성 이름" 순 표기를 매칭용 별칭으로 추가한다(표시명은 그대로)."""
    # 응용미술관 특별 프로젝트(V&A 협업, 비경쟁)는 본전시 아님 — 조사 단계와 같은 기준으로 제외
    recs = [r for r in parse_edition(edition_id, pages) if r.get("section") != "applied_arts_pavilion"]
    for r in recs:
        if r.get("given_name") and r.get("family_name"):
            r.setdefault("aliases", []).append(f"{r['family_name']} {r['given_name']}")
        if r.get("entity_hint") == "group":
            r["collective"] = True
    return recs
