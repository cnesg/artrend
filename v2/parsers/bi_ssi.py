"""Participant-list parsers: Bienal de Sao Paulo (32nd-36th), Biennale of Sydney (20th-25th),
Istanbul Biennial (15th-18th).

Contract
--------
Every ``parse_<edition_id>(page_text: str) -> list[dict]`` takes the raw text of ONE fetched
document and returns records shaped like::

    {"name": str, "name_en": str|None, "country": str|None, "birth_year": int|None, ...extras}

Extras (only when the page provides them): ``url`` (detail page), ``members`` (list of
{"name","country"} for collaborations credited as one unit), ``note``.

``country`` is the page's own wording, not normalised: 3-letter Bienal codes for SP 2018
("EUA", "GER", "EUA/NGR"), or the full parenthetical affiliation for Sydney PDFs
("Kamilaroi / Kooma, Australia").

Fetch kinds in EDITION_SOURCES:
  "html" - plain requests GET; "wayback" - Internet Archive raw snapshot (``.../web/<ts>id_/<url>``);
  "pdf"  - download PDF, extract text with PyMuPDF (``"\\n".join(p.get_text() for p in doc)``), pass text.
Multi-URL editions: run the parser per URL, concatenate, then ``dedupe()``. Edition-level
reconciliation (exclusions, merges) lives in ``postprocess(edition_id, records)``.

The crawler is expected to fetch/store the raw page itself; nothing here does network I/O.
"""
from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

# --------------------------------------------------------------------------- helpers

_CONNECTOR_RE = re.compile(r"^\s*(?:(?:,|;|&|\+|and\b|with\b|e\b)\s*)+", re.I)
_TRAILING_CONNECTOR_RE = re.compile(r"(?:,|;|&|\+|\band|\bwith|:)\s*$", re.I)
_ACRONYM_RE = re.compile(r"[A-Z0-9][A-Z0-9.&\- ]{2,}")
_YEAR_RE = re.compile(r"\b(1[5-9]\d\d|20[0-2]\d)\b")


def _soup(text: str) -> BeautifulSoup:
    return BeautifulSoup(text, "lxml")


_INVISIBLE_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")


def _ws(s: str | None) -> str:
    s = _INVISIBLE_RE.sub("", (s or "").replace("\u00a0", " "))
    return re.sub(r"\s+", " ", s).strip()


def _rec(name, name_en=None, country=None, birth_year=None, **extra) -> dict:
    r = {"name": _ws(name), "name_en": _ws(name_en) or None,
         "country": _ws(country) or None, "birth_year": birth_year}
    r.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
    return r


def norm_key(name: str) -> str:
    """Accent/case/punctuation-insensitive key used for dedupe and cross-checks."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("&", "and").casefold()
    return re.sub(r"[^0-9a-z]+", "", s)


def dedupe(records: list[dict]) -> list[dict]:
    """Keep first occurrence per norm_key(name); fill missing fields from later duplicates."""
    out: dict[str, dict] = {}
    for r in records:
        k = norm_key(r["name"])
        if not k:
            continue
        if k not in out:
            out[k] = dict(r)
        else:
            for f, v in r.items():
                if out[k].get(f) in (None, "", []) and v not in (None, "", []):
                    out[k][f] = v
    return list(out.values())


def _top_level_groups(s: str) -> list[tuple[int, int]]:
    """(start, end_exclusive) spans of top-level (...) groups; an unclosed group runs to EOS."""
    spans, depth, start = [], 0, None
    for i, ch in enumerate(s):
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
            if depth == 0:
                spans.append((start, i + 1))
    if depth > 0 and start is not None:
        spans.append((start, len(s)))
    return spans


def split_entry(entry: str) -> dict:
    """'Name (Affil)' / 'A (X) & B (Y)' / 'Org (ACR) (Country)' -> record (members for collabs)."""
    entry = _ws(entry).rstrip("*").strip()
    spans = _top_level_groups(entry)
    if not spans:
        return _rec(entry)
    members: list[list[str | None]] = []  # [name, affil]
    prev = 0
    for (a, b) in spans:
        seg = entry[prev:a]
        inner = entry[a + 1:b - 1] if entry[b - 1:b] == ")" else entry[a + 1:b]
        if members and members[-1][1] is not None and _ACRONYM_RE.fullmatch(_ws(members[-1][0])) \
                and _CONNECTOR_RE.match(seg):
            # "STARTTS (NSW Service for ...) and X (Australia)": first group expands the acronym
            members[-1][0] = f"{_ws(members[-1][0])} ({members[-1][1]})"
            members[-1][1] = None
        if not members:
            members.append([seg, inner])
        elif _CONNECTOR_RE.match(seg):
            members.append([_CONNECTOR_RE.sub("", seg), inner])
        else:  # adjacent group or name continuation -> previous group belongs to the name
            m = members[-1]
            m[0] = f"{m[0]} ({m[1]}){seg}" if m[1] is not None else f"{m[0]}{seg}"
            m[1] = inner
        prev = b
    tail = entry[prev:]
    if _ws(tail):
        if _CONNECTOR_RE.match(tail):
            members.append([_CONNECTOR_RE.sub("", tail), None])
        else:
            m = members[-1]
            m[0] = f"{m[0]} ({m[1]}){tail}" if m[1] is not None else f"{m[0]}{tail}"
            m[1] = None
    members = [[_ws(n).strip(" ,;"), _ws(c) or None] for n, c in members]
    if len(members) == 1:
        return _rec(members[0][0], country=members[0][1])
    # collaboration credited as one unit: keep the credit line (without affiliations) as name
    name = _ws(re.sub(r"\s*\((?:[^()]|\([^()]*\))*\)?", "", entry))
    return _rec(name, members=[{"name": n, "country": c} for n, c in members])


def _join_wrapped(lines: list[str], *, new_entry_on_every_line: bool) -> list[str]:
    """Re-join PDF lines wrapped inside one entry.

    new_entry_on_every_line=False: an entry is closed only when parentheses balance and the text
    ends with ')' (narrow-column layouts where names themselves wrap).
    new_entry_on_every_line=True: each line opens a new entry unless the previous one has
    unbalanced parentheses or ends with a connector (wide layouts, entries may lack parens).
    """
    out, buf = [], ""
    for ln in lines:
        ln = _ws(ln)
        if not ln:
            continue
        if not buf:
            buf = ln
        elif new_entry_on_every_line:
            if buf.count("(") > buf.count(")") or _TRAILING_CONNECTOR_RE.search(buf):
                buf = f"{buf} {ln}"
            else:
                out.append(buf)
                buf = ln
        else:
            buf = f"{buf} {ln}"
        if not new_entry_on_every_line and buf.count("(") <= buf.count(")") \
                and buf.rstrip().endswith(")") and not _TRAILING_CONNECTOR_RE.search(buf):
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


# --------------------------------------------------------------------------- Bienal de Sao Paulo

def parse_saopaulo_2016(page_text: str) -> list[dict]:
    """32bienal.org.br /en/participants/l (archived): div.participante > a[href*=/participants/o/] > h1."""
    s = _soup(page_text)
    out = []
    for a in s.select("div.participante a[href*='/participants/o/']"):
        h1 = a.find("h1")
        if h1 and _ws(h1.get_text()):
            out.append(_rec(h1.get_text(" "), url=a.get("href")))
    return dedupe(out)


def _sp2018_line(line: str) -> list[dict]:
    line = _ws(line)
    if not line or line.startswith("*"):
        return []
    no_bio = line.endswith("*") or "*" in line.split("(")[0]
    line = line.replace("*", "").strip()
    # "Escola de Vallecas: A (ESP, 1895 – RUS, 1962), B (ESP, 1894 – 1980)" -> members
    m = re.match(r"^([^():]+):\s*(.+\(.*)$", line)
    if m:
        group = _ws(m.group(1))
        parts = re.split(r"\)\s*(?:,|\band\b)\s*", m.group(2))
        recs = []
        for p in parts:
            p = p.strip()
            if p.startswith("and "):
                p = p[4:]
            if p and "(" in p and not p.endswith(")"):
                p += ")"
            recs += [dict(r, note=f"member of '{group}'") for r in _sp2018_line(p)]
        return recs
    m = re.match(r"^(.*?)\s*\(([^()]*)\)?\s*$", line)
    if m and "(" in line:
        name, inside = m.group(1), m.group(2)
        country = _ws(inside.split(",")[0]) if "," in inside else _ws(inside)
        y = _YEAR_RE.search(inside)
        return [_rec(name, country=country or None, birth_year=int(y.group(1)) if y else None)]
    return [_rec(line, note="no biographical data on page" if no_bio else "no parenthetical data")]


def parse_saopaulo_2018(page_text: str) -> list[dict]:
    """33.bienal.org.br (archived). Two templates:
    - group show page (exposicao-coletiva-detalhe): block after 'Participating artists',
      one '<Name> (<CTY>, <birth>[ – <death>])' per <br>, '*' = no bio data, 'Group: A (..), B (..)'.
    - solo project page (exposicao-individual-detalhe): h1 'Individual Projects' + h2 artist name.
    """
    s = _soup(page_text)
    marker = s.find(string=re.compile(r"Participating artists|Artistas participantes"))
    if marker:
        container = marker.find_parent("p").parent
        for br in container.find_all("br"):
            br.replace_with("\n")
        text = container.get_text("\n")
        text = re.split(r"Participating artists|Artistas participantes", text, maxsplit=1)[1]
        lines = [_ws(x) for x in text.split("\n") if _ws(x)]
        joined: list[str] = []
        for ln in lines:  # re-join "Name (" + "SWE, 1930 – 2017)" split by inline markup
            if joined and joined[-1].count("(") > joined[-1].count(")") \
                    and re.match(r"^[A-Z]{2,3}(?:/[A-Z]{2,3})*\s*,\s*\d", ln):
                joined[-1] = f"{joined[-1]} {ln}"
            else:
                joined.append(ln)
        out = []
        for line in joined:
            if re.search(r"no biographical data|sem dados biogr", line, re.I):
                continue
            out += _sp2018_line(line)
        return dedupe(out)
    h1 = s.find("h1", string=re.compile(r"Individual Projects|Projetos individuais", re.I))
    if h1:
        h2 = h1.find_next("h2")
        if h2 and _ws(h2.get_text()):
            return [_rec(h2.get_text(" "), note="individual project")]
    return []


def parse_saopaulo_2021(page_text: str) -> list[dict]:
    """34.bienal.org.br /en/artistas (archived): ul.artists__list-items li > a; li class = section."""
    s = _soup(page_text)
    out = []
    for li in s.select("ul.artists__list-items li"):
        a = li.find("a", href=re.compile(r"/artistas/\d+"))
        if a and _ws(a.get_text()):
            secs = [c for c in li.get("class", []) if c in ("coletiva", "individual")]
            out.append(_rec(a.get_text(" "), url=a.get("href"),
                            note="sections: " + ",".join(secs) if secs else None))
    return dedupe(out)


def parse_saopaulo_2023(page_text: str) -> list[dict]:
    """35.bienal.org.br /participantes/: div.participant-item div.participant-title a."""
    s = _soup(page_text)
    out = [_rec(a.get_text(" "), url=a.get("href"))
           for a in s.select("div.participant-item div.participant-title a[href*='/participante/']")
           if _ws(a.get_text())]
    return dedupe(out)


def parse_saopaulo_2025(page_text: str) -> list[dict]:
    """36.bienal.org.br /artistas/ (pt) or /en/artists/ (en): h2.artista-item > a."""
    s = _soup(page_text)
    out = [_rec(a.get_text(" "), url=a.get("href"))
           for a in s.select("h2.artista-item a[href*='/artista/']") if _ws(a.get_text())]
    return dedupe(out)


def slug_stem(url: str | None) -> str:
    """'/en/artista/aislan-pankararu-2/' -> 'aislan-pankararu' (pairs pt/en pages of 36th Bienal)."""
    from urllib.parse import unquote
    slug = _INVISIBLE_RE.sub("", unquote((url or "").rstrip("/").rsplit("/", 1)[-1]))
    return re.sub(r"(?:-e[nm])?(?:-\d+)?$", "", slug)  # '-em' is a typo used on 2 en pages


def merge_pt_en(pt: list[dict], en: list[dict]) -> list[dict]:
    en_by = {slug_stem(r.get("url")): r for r in en}
    en_by_name = {norm_key(r["name"]): r for r in en}
    out = []
    for r in pt:
        e = en_by.get(slug_stem(r.get("url"))) or en_by_name.get(norm_key(r["name"]))
        r = dict(r)
        if e and e["name"] != r["name"]:
            r["name_en"] = e["name"]
        out.append(r)
    return out


# Casa do Povo performance programme ("Ensaio geral") of the 36th Bienal: listed on the artists
# page but held off-site as a separate programme; announced as "120 at the Pavilion + 5 at Casa do Povo".
SAOPAULO_2025_CASA_DO_POVO = ["MEXA", "Marcelo Evelin", "Alexandre Paulikevitch",
                              "Boxe Autônomo", "Dorothée Munyaneza"]


# --------------------------------------------------------------------------- Biennale of Sydney

def parse_sydney_2016(page_text: str) -> list[dict]:
    """biennaleofsydney.com.au/20bos/artists/?letter=<x> (archived 2016-03-10):
    article.posttype-artist > header h1 a; trailing article text = venue."""
    s = _soup(page_text)
    out = []
    for art in s.select("article.posttype-artist"):
        a = art.select_one("header h1 a")
        if not a or not _ws(a.get_text()):
            continue
        venue = _ws(art.get_text(" ").replace(a.get_text(" "), "", 1))
        out.append(_rec(a.get_text(" "), url=a.get("href"), note=f"venue: {venue}" if venue else None))
    return dedupe(out)


def parse_sydney_archive(page_text: str) -> list[dict]:
    """biennaleofsydney.art/biennale/<edition>/ archive page: div.participant-grid .participant-item h3.
    Same list as REST /wp-json/wp/v2/participant?biennale=<term_id>. Mixes in public-programme
    participants for 2022+ editions, so 2022-2026 use the official PDFs instead."""
    s = _soup(page_text)
    out = []
    for it in s.select("div.participant-grid div.participant-item"):
        h = it.select_one("h3")
        a = it.select_one("a[href*='/participants/']")
        if h and _ws(h.get_text()):
            out.append(_rec(h.get_text(" "), url=a.get("href") if a else None))
    return dedupe(out)


parse_sydney_2018 = parse_sydney_archive
parse_sydney_2020 = parse_sydney_archive

_PAGE_NOISE = re.compile(r"^(?:\d+(?:\s+\d+)?|\d*\s*Participants|Participants:?|\d*Report|Report|"
                         r"23rd Biennale|of Sydney: r.vus|24th Biennale of Sydney|ABOUT THE|"
                         r"BIENNALE OF SYDNEY|EXHIBITING|ARTISTS)\s*$", re.I)


def parse_sydney_2022(page_text: str) -> list[dict]:
    """23rd BoS 2022 Report PDF (text): 'Participants:' list up to the venue section
    ('Art Gallery of New South Wales'). Narrow columns: entries close on balanced ')'.
    Returns ALL 89 participants incl. rivers / fossil (see postprocess)."""
    i = page_text.find("Participants:")
    j = page_text.find("Art Gallery of", i)
    if i < 0 or j < 0:
        return []
    lines = [ln for ln in page_text[i + len("Participants:"):j].splitlines()
             if not _PAGE_NOISE.match(_ws(ln))]
    return dedupe([split_entry(e) for e in _join_wrapped(lines, new_entry_on_every_line=False)])


def parse_sydney_2024(page_text: str) -> list[dict]:
    """24th BoS 2024 Report PDF (text): 'EXHIBITING ARTISTS' list (one entry per line, wraps
    allowed) up to 'PROGRAMMING ARTISTS' (public-programme performers, excluded)."""
    i = page_text.find("EXHIBITING")
    j = page_text.find("PROGRAMMING", i)
    if i < 0 or j < 0:
        return []
    lines = [ln for ln in page_text[i:j].splitlines() if not _PAGE_NOISE.match(_ws(ln))]
    return dedupe([split_entry(e) for e in _join_wrapped(lines, new_entry_on_every_line=False)])


def parse_sydney_2026(page_text: str) -> list[dict]:
    """25th BoS launch media release PDF (text): 'Artists as part of the 25th Biennale of Sydney
    (2026) are:' grouped by venue until 'Key Dates'. Venue header = paren-less line right after a
    blank line. Artists repeat across venues -> dedupe; venues kept in note."""
    i = page_text.find("Artists as part of the 25th Biennale")
    j = page_text.find("Key Dates", i)
    if i < 0 or j < 0:
        return []
    raw_lines = page_text[i:j].splitlines()[1:]
    venue, prev_blank, chunks = None, True, []  # chunks: (venue, [lines])
    for ln in raw_lines:
        t = _ws(ln)
        if not t:
            prev_blank = True
            continue
        if prev_blank and "(" not in t and not (chunks and chunks[-1][1] and
                                                 chunks[-1][1][-1].count("(") > chunks[-1][1][-1].count(")")):
            venue = t
            chunks.append((venue, []))
        else:
            if not chunks:
                chunks.append((venue, []))
            chunks[-1][1].append(t.rstrip("*").strip())
        prev_blank = False
    out = []
    for v, lines in chunks:
        for e in _join_wrapped(lines, new_entry_on_every_line=True):
            r = split_entry(e)
            r["note"] = f"venue: {v}"
            out.append(r)
    merged: dict[str, dict] = {}
    for r in out:
        k = norm_key(r["name"])
        if k in merged:
            merged[k]["note"] += "; " + r["note"].replace("venue: ", "")
        else:
            merged[k] = r
    return list(merged.values())


_RIVER_RE = re.compile(r"\bRiver$", re.I)
SYDNEY_2022_NON_HUMAN = {"Canowindra Fossil Slab #84": "fossil (object) listed as participant",
                         "Zenadh Kes": "Torres Strait islands credited as an entity, like the rivers - verify"}


# --------------------------------------------------------------------------- Istanbul Biennial

def parse_istanbul_2017(page_text: str) -> list[dict]:
    """bienal.iksv.org/en/biennial-archive/15th-istanbul-biennial (archived): <p><strong>Artists:</strong> a, b, ...</p>."""
    s = _soup(page_text)
    st = s.find("strong", string=re.compile(r"^\s*(Artists|Sanatçılar)\s*:\s*$"))
    if not st:
        return []
    text = _ws(st.parent.get_text(" ")).split(":", 1)[1]
    return dedupe([_rec(n) for n in (x.strip() for x in text.split(",")) if n])


def _iksv_artist_links(page_text: str, path_part: str, extra_key: str) -> list[dict]:
    s = _soup(page_text)
    out = []
    for a in s.find_all("a", href=re.compile(path_part)):
        span = a.find("span")
        extra = _ws(span.get_text(" ")) if span else ""
        if span:
            span.extract()
        name = _ws(a.get_text(" "))
        if name:
            out.append(_rec(name, url=a.get("href"), **{extra_key: extra or None}))
    return dedupe(out)


def parse_istanbul_2019(page_text: str) -> list[dict]:
    """bienal.iksv.org/en/16th-istanbul-biennial/artists (archived): a[href*=/bienal-artists/] Name <span><i>Born in X, lives in Y.</i></span>."""
    return _iksv_artist_links(page_text, r"/bienal-artists/", "note")


def parse_istanbul_2022(page_text: str) -> list[dict]:
    """bienal.iksv.org/en/17th-istanbul-biennial/contributors (archived): ul.artist-list a[href*=/17b-artists/] + <i>venues</i>."""
    return _iksv_artist_links(page_text, r"/17b-artists/", "note")


def parse_istanbul_2025(page_text: str) -> list[dict]:
    """bienal.iksv.org/en/18th-istanbul-biennial/artists (archived): a[href*=/18b-artists/]."""
    return _iksv_artist_links(page_text, r"/18b-artists/", "note")


# --------------------------------------------------------------------------- edition reconciliation

def postprocess(edition_id: str, records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (main_exhibition_artists, excluded_candidates[with 'reason'])."""
    keep, excluded = [], []
    for r in records:
        reason = None
        if edition_id == "saopaulo_2025" and r["name"] in SAOPAULO_2025_CASA_DO_POVO:
            reason = "Casa do Povo 'Ensaio geral' performance programme (off-site, announced separately from the 120 Pavilion participants)"
        elif edition_id == "saopaulo_2018" and r.get("note") == "no parenthetical data":
            reason = "listed under 'Participating artists' but not an artist name (e.g. anonymous object group)"
        elif edition_id == "sydney_2022":
            if _RIVER_RE.search(r["name"]):
                reason = "river credited as participant (rivus concept), not an artist"
            elif r["name"] in SYDNEY_2022_NON_HUMAN:
                reason = SYDNEY_2022_NON_HUMAN[r["name"]]
        elif edition_id == "sydney_2018" and norm_key(r["name"]) in (
                norm_key("Cercle d’Art des Travailleurs de Plantation Congolaise (CATPC)"), norm_key("Renzo Martens")):
            reason = ("separate web page, but credited inside the unit 'CATPC with Baloji and Renzo Martens' "
                      "(one entry in the official 2018 Exhibition Report list of 69)")
        if reason:
            excluded.append(dict(r, reason=reason))
        else:
            keep.append(r)
    return keep, excluded


# --------------------------------------------------------------------------- sources

_SP33 = "http://33.bienal.org.br:80/en/"
_WB = "https://web.archive.org/web/{ts}id_/{url}"

EDITION_SOURCES = {
    "saopaulo_2016": {"fetch": "wayback", "parser": "parse_saopaulo_2016", "urls": [
        _WB.format(ts="20160902084615", url="http://www.32bienal.org.br:80/en/participants/l")]},
    "saopaulo_2018": {"fetch": "wayback", "parser": "parse_saopaulo_2018", "urls": [
        _WB.format(ts=ts, url=_SP33 + p) for ts, p in [
            ("20180909045344", "exposicao-coletiva-detalhe/5328"), ("20180909045349", "exposicao-coletiva-detalhe/5329"),
            ("20180909045354", "exposicao-coletiva-detalhe/5330"), ("20180909045400", "exposicao-coletiva-detalhe/5331"),
            ("20180909045405", "exposicao-coletiva-detalhe/5332"), ("20180909045411", "exposicao-coletiva-detalhe/5333"),
            ("20180909045415", "exposicao-coletiva-detalhe/5334"),
            ("20180909224136", "exposicao-individual-detalhe/5316"), ("20180909224141", "exposicao-individual-detalhe/5317"),
            ("20180907224537", "exposicao-individual-detalhe/5318"), ("20180909224719", "exposicao-individual-detalhe/5319"),
            ("20180909224724", "exposicao-individual-detalhe/5320"), ("20180909224739", "exposicao-individual-detalhe/5321"),
            ("20180909224744", "exposicao-individual-detalhe/5322"), ("20180909224147", "exposicao-individual-detalhe/5323"),
            ("20190119094335", "exposicao-individual-detalhe/5324"), ("20180909224809", "exposicao-individual-detalhe/5325"),
            ("20180909224153", "exposicao-individual-detalhe/5326"), ("20180909224205", "exposicao-individual-detalhe/5327")]]},
    "saopaulo_2021": {"fetch": "wayback", "parser": "parse_saopaulo_2021", "urls": [
        _WB.format(ts="20250913103654", url="http://www.34.bienal.org.br/en/artistas")]},
    "saopaulo_2023": {"fetch": "html", "parser": "parse_saopaulo_2023", "urls": [
        "https://35.bienal.org.br/participantes/"]},
    "saopaulo_2025": {"fetch": "html", "parser": "parse_saopaulo_2025", "urls": [
        "https://36.bienal.org.br/artistas/", "https://36.bienal.org.br/en/artists/"],
        "merge": "merge_pt_en(pt=urls[0], en=urls[1])"},
    "sydney_2016": {"fetch": "wayback", "parser": "parse_sydney_2016", "urls": [
        _WB.format(ts=ts, url=f"http://www.biennaleofsydney.com.au/20bos/artists/?letter={L}") for L, ts in [
            ("0-9", "20160310161937"), ("a", "20160310161944"), ("b", "20160310161952"), ("c", "20160310162009"),
            ("d", "20160310162016"), ("e", "20160310162023"), ("f", "20160310162032"), ("g", "20160310162040"),
            ("h", "20160310162048"), ("i", "20160310162103"), ("j", "20160310162109"), ("k", "20160310162115"),
            ("l", "20160310162126"), ("m", "20160310162132"), ("n", "20160310162145"), ("o", "20160310162203"),
            ("p", "20160310162229"), ("q", "20160310162239"), ("r", "20160310162250"), ("s", "20160310162303"),
            ("t", "20160310162317"), ("u", "20160310162327"), ("v", "20160310162335"), ("w", "20160310162341"),
            ("x", "20160310162401"), ("y", "20160310162407"), ("z", "20160310162425")]],
        "crosscheck": ["https://www.biennaleofsydney.art/biennale/20th-biennale-of-sydney-2016/"]},
    "sydney_2018": {"fetch": "html", "parser": "parse_sydney_2018", "urls": [
        "https://www.biennaleofsydney.art/biennale/21st-biennale-of-sydney-2018/"],
        "crosscheck": ["https://www.biennaleofsydney.art/wp-content/uploads/2021/11/21nd-Biennale-of-Sydney-2018-Exhibition-Report.pdf.pdf"],
        "json_alt": "https://www.biennaleofsydney.art/wp-json/wp/v2/participant?biennale=50&per_page=100"},
    "sydney_2020": {"fetch": "html", "parser": "parse_sydney_2020", "urls": [
        "https://www.biennaleofsydney.art/biennale/22nd-biennale-of-sydney-2020/"],
        "json_alt": "https://www.biennaleofsydney.art/wp-json/wp/v2/participant?biennale=29&per_page=100&page={1,2}"},
    "sydney_2022": {"fetch": "pdf", "parser": "parse_sydney_2022", "urls": [
        "https://www.biennaleofsydney.art/wp-content/uploads/2023/04/23rd-Biennale-of-Sydney-2022-Report.pdf"],
        "crosscheck": ["https://www.biennaleofsydney.art/biennale/23rd-biennale-of-sydney-2022/"]},
    "sydney_2024": {"fetch": "pdf", "parser": "parse_sydney_2024", "urls": [
        "https://www.biennaleofsydney.art/wp-content/uploads/2024/10/2024-BOS-Report_FINAL-DIGITAL-compressed.pdf"],
        "crosscheck": ["https://www.biennaleofsydney.art/biennale/24th-biennale-archive/"]},
    "sydney_2026": {"fetch": "pdf", "parser": "parse_sydney_2026", "urls": [
        "https://www.biennaleofsydney.art/wp-content/uploads/2026/04/Media-Release_25thBoS_Launch_FINAL.pdf"],
        "crosscheck": ["https://www.biennaleofsydney.art/biennale/25th-biennale-of-sydney-2026/"]},
    "istanbul_2017": {"fetch": "wayback", "parser": "parse_istanbul_2017", "urls": [
        _WB.format(ts="20220520202155", url="https://bienal.iksv.org/en/biennial-archive/15th-istanbul-biennial")]},
    "istanbul_2019": {"fetch": "wayback", "parser": "parse_istanbul_2019", "urls": [
        _WB.format(ts="20200717062626", url="https://bienal.iksv.org/en/16th-istanbul-biennial/artists")]},
    "istanbul_2022": {"fetch": "wayback", "parser": "parse_istanbul_2022", "urls": [
        _WB.format(ts="20251009101311", url="https://bienal.iksv.org/en/17th-istanbul-biennial/contributors")]},
    "istanbul_2025": {"fetch": "wayback", "parser": "parse_istanbul_2025", "urls": [
        _WB.format(ts="20260829092535", url="https://bienal.iksv.org/en/18th-istanbul-biennial/artists")]},
}


# --------------------------------------------------------------------------- v2 adapter
def parse_pages(pages: list[str], edition_id: str) -> list[dict]:
    """load.py edition_parser 계약: 원본 텍스트들(소스 순서) -> 본전시 작가 목록 (제외 후보는 버림)."""
    fn = globals()[EDITION_SOURCES[edition_id]["parser"]]
    if edition_id == "saopaulo_2025":
        recs = merge_pt_en(fn(pages[0]), fn(pages[1]))
    else:
        recs = [r for t in pages for r in fn(t)]
    keep, _excluded = postprocess(edition_id, dedupe(recs))
    return keep
