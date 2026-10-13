"""Frieze fair participant parsers (artrend / ArtGraph, internal research use only).

Self-contained (no network). A crawler fetches and stores raw pages itself, then calls one
parser per page template:

    parse_d8_gallery_list(html)        frieze.com Aug-2020+ "Galleries"/"Exhibiting Galleries" page
                                        (also /fairs/archive/<fair>/<year>/galleries and ?section=<x>)
    parse_d7_gallery_list(html)        frieze.com 2016 - mid-2020 Drupal-7 page (20 rows/page, ?page=N)
    parse_press_release_pdf(text)      Frieze "galleries announced"/"highlights" press-release PDFs 2016-2020
    parse_fair_guide_index(text)       2016 printed fair guide / map PDF (gallery -> stand index)
    parse_programme_artists_pdf(text)  Frieze Projects / Frieze Sculpture press-release PDFs
    parse_artist_award(text_or_html)   Frieze Artist Award announcement (PDF text or HTML)

PDF parsers take text produced by pdf_to_text(pdf_bytes).

Booth dict returned by all parsers:
    {"gallery": str|None, "gallery_city": str|None, "booth": str|None,
     "section": "main"|<section name>|None (None = the page did not say),
     "artists": [{"name": str}], optional: gallery_url, gallery_location_raw, gallery_cities, _parse_flag}

DATA SEMANTICS
* frieze.com list pages never name the artists shown on a booth. /gallery/<slug> pages list the
  gallery's represented roster (not edition-specific) - never use them as "artists at booth".
* Artists here come only from curated-section rows of press releases ("Gallery, City  Artist" in
  Spotlight / Frame / Live / Social Work / Sex Work / Woven / Dialogos / JAM) and from the
  artist-level programmes (Frieze Projects, Frieze Sculpture, Frieze Artist Award).
"""
from __future__ import annotations

import re
import unicodedata

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_WS = re.compile(r"[    ]+")


def _clean(s: str | None) -> str | None:
    if s is None:
        return None
    s = s.replace("’", "'").replace("‘", "'")
    s = _WS.sub(" ", s).strip()
    return s or None


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace("&", " ").replace("+", " ").replace("|", " ").replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def gallery_key(name: str) -> str:
    """Loose key for matching the same gallery across sources."""
    s = slugify(name)
    s = re.sub(r"(^|-)(the|gallery|galerie|galeria|galleria|galerija|galeri|galleries|fine-art|fine-arts|"
               r"inc|ltd|co|contemporary|projects|art)(?=-|$)", "-", s)
    return re.sub(r"-+", "-", s).strip("-") or slugify(name)


def split_artist_names(text: str | None) -> list[dict]:
    """'Sari Dienes & Michelle Stuart' -> two names; 'Elmgreen & Dragset' stays one."""
    text = _clean(text)
    if not text:
        return []
    text = text.strip(" ,;:-–")
    text = re.sub(r"^\([^)]*\)\s*", "", text)  # stray '(GA)' after a city
    if not text:
        return []
    parts = [text]
    for sep in (" & ", " + ", " and "):
        nxt = []
        for p in parts:
            bits = [b.strip() for b in p.split(sep)]
            if len(bits) > 1 and all(len(b.split()) >= 2 for b in bits):
                nxt.extend(bits)
            else:
                nxt.append(p)
        parts = nxt
    return [{"name": p} for p in parts if p]


# ---------------------------------------------------------------------------
# frieze.com HTML templates
# ---------------------------------------------------------------------------

def _soup(html: str):
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 + lxml required")
    return BeautifulSoup(html, "lxml")


def _split_location(loc: str | None):
    loc = _clean(loc)
    if not loc or loc.lower().startswith("multiple location"):
        return None, loc
    city = loc.split(",")[0].strip()
    return city or None, loc


def parse_d8_gallery_list(page_text: str) -> list[dict]:
    """frieze.com (Aug 2020 ->) fair gallery list; one request returns the whole list.

    Section: only present when the page was requested with ?section=<x> (the selected <option>);
    otherwise None.
    """
    soup = _soup(page_text)
    selected = None
    for opt in soup.select("select[name=section] option[selected]"):
        if opt.get("value"):
            selected = opt.get("value")
            break
    out, seen = [], set()
    for it in soup.select(".fair-galleries-results-item"):
        a = it.select_one(".fair-galleries-results-title a")
        if not a:
            continue
        name = _clean(a.get_text(" "))
        href = a.get("href")
        if not name or (name, href) in seen:
            continue
        seen.add((name, href))
        loc_el = it.select_one(".fair-galleries-results-description-location")
        city, loc_raw = _split_location(loc_el.get_text(" ") if loc_el else None)
        out.append({"gallery": name, "gallery_city": city, "booth": None, "section": selected,
                    "artists": [], "gallery_location_raw": loc_raw, "gallery_url": href})
    return out


def d8_section_options(page_text: str) -> list[str]:
    vals = []
    for o in _soup(page_text).select("select[name=section] option"):
        v = o.get("value")
        if v and v not in vals:
            vals.append(v)
    return vals


def parse_d7_gallery_list(page_text: str) -> list[dict]:
    """frieze.com Drupal-7 list (2016 - mid 2020): name, city, stand; 20 rows per page.

    "_has_next_page" is set on every row when a "Show more" pager link exists (fetch ?page=1,2,...).
    """
    soup = _soup(page_text)
    has_next = bool(soup.select_one(".pager-show-more-next a, .pager-next a"))
    sel = None
    for s in soup.select("select"):
        if "fair_section" in (s.get("name") or ""):
            o = s.select_one("option[selected]")
            if o and o.get("value") not in (None, "", "All"):
                sel = o.get("value")
    out, seen = [], set()
    for node in soup.select(".node-gallery.node-teaser"):
        a = node.select_one(".field-name-title-field a")
        if not a:
            continue
        name = _clean(a.get_text(" "))
        if not name or name in seen:
            continue
        seen.add(name)
        loc = node.select_one(".field-name-gallery-location h4, .field-name-gallery-location .field-item")
        stand = node.select_one(".field-name-ds-gallery-fair-stand .field-item")
        city, loc_raw = _split_location(loc.get_text(" ") if loc else None)
        out.append({"gallery": name, "gallery_city": city,
                    "booth": _clean(stand.get_text(" ")) if stand else None, "section": sel,
                    "artists": [], "gallery_location_raw": loc_raw, "gallery_url": a.get("href"),
                    "_has_next_page": has_next})
    return out


# ---------------------------------------------------------------------------
# PDF text
# ---------------------------------------------------------------------------

def pdf_to_text(data: bytes) -> str:
    try:
        import pymupdf  # PyMuPDF >= 1.24
    except ImportError:
        try:
            import fitz as pymupdf  # older PyMuPDF
        except ImportError:
            pymupdf = None
    if pymupdf is not None:
        doc = pymupdf.open(stream=data, filetype="pdf")
        return "\n".join(p.get_text() for p in doc)
    import io
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)


# ---------------------------------------------------------------------------
# press-release PDF list parser
# ---------------------------------------------------------------------------

BASE_CITIES = (
    "Aarau|Abu Dhabi|Accra|Amsterdam|Antwerp|Athens|Athens (GA)|Aspen|Auckland|Baltimore|Bangkok|Barcelona|"
    "Basel|Beijing|Beirut|Belgrade|Berlin|Bern|Beverly Hills|Bogota|Bogotá|Bologna|Brescia|Brooklyn|Brussels|"
    "Bucharest|Budapest|Buenos Aires|Busan|Cairo|Cape Town|Caracas|Chicago|Cluj|Cologne|Copenhagen|Dallas|Delhi|"
    "Dubai|Dublin|Düsseldorf|Edinburgh|Florence|Frankfurt|Geneva|Glasgow|Guatemala City|Hamburg|Hanover|Havana|"
    "Helsinki|Hong Kong|Houston|Istanbul|Jakarta|Johannesburg|Karlsruhe|Kolkata|Kyiv|Lagos|Leipzig|Lima|Lisbon|"
    "Ljubljana|London|Los Angeles|Lucerne|Lugano|Luxembourg|Madrid|Manila|Margate|Marseille|Melbourne|"
    "Mexico City|Miami|Milan|Modica|Monaco|Montevideo|Montreal|Moscow|Mumbai|Munich|Nairobi|Nancy|Naples|"
    "New Delhi|New York|Osaka|Oslo|Palm Beach|Paris|Philadelphia|Porto|Prague|Rio de Janeiro|Rome|Rotterdam|"
    "Salzburg|San Francisco|San Gimignano|San Juan|Santa Monica|Santiago|São Paulo|Sao Paulo|Seattle|Seoul|"
    "Shanghai|Singapore|St Moritz|St. Moritz|Stockholm|Stuttgart|Sydney|Taipei|Tbilisi|Tehran|Tel Aviv|"
    "The Hague|Tokyo|Toronto|Turin|Valencia|Vancouver|Venice|Vienna|Vigo|Vilnius|Warsaw|Washington|"
    "Washington DC|Wijnegem|Zurich|Zürich|Ankara|Kobe|Toledo|Bilbao|Lyon|Bordeaux|Nice|Ghent|Knokke|Mechelen|"
    "Oxford|Cambridge|Manchester|Bristol|Liverpool|Berkeley|Santa Fe|New Orleans|Atlanta|Detroit|Minneapolis|"
    "Hudson|Kinderhook|East Hampton|Southampton|Guadalajara|Monterrey|Oaxaca|Quito|Medellín|Medellin|"
    "Panama City|Kingston|Lahore|Karachi|Dhaka|Colombo|Kathmandu|Ho Chi Minh City|Hanoi|Kuala Lumpur|Bangalore|"
    "Chennai|Hyderabad|Daegu|Gwangju|Kyoto|Nagoya|Fukuoka|Hiroshima|Taichung|Kaohsiung|Shenzhen|Guangzhou|"
    "Hangzhou|Chengdu|Wuhan|Doha|Riyadh|Jeddah|Kuwait|Amman|Ramallah|Jerusalem|Tunis|Casablanca|Marrakech|"
    "Dakar|Addis Ababa|Harare|Kampala|Luanda|Lusaka|Durban|Abidjan|Cincinnati|Pittsburgh|Cleveland|"
    "Saint Louis|St. Louis|Denver|Austin|San Diego|Portland|Boston|Chapel Hill|Marfa|Toluca|Tulum|Puebla|"
    "León|Valparaíso|Rio|Belo Horizonte|Porto Alegre|Recife|Curitiba|Brasília|Asunción|La Paz|Cusco|"
    "Santo Domingo|Port-au-Prince|San José|Managua|Tegucigalpa|San Salvador"
).split("|")

SECTION_HEADERS = {
    "main section": "main", "main": "main", "galleries": "main",
    "focus": "Focus", "frame": "Frame", "spotlight": "Spotlight", "live": "Live",
    "collections": "Collections", "social work": "Social Work", "sex work": "Sex Work",
    "woven": "Woven", "the 90s": "The Nineties", "the nineties": "The Nineties",
    "diálogos": "Diálogos", "dialogos": "Diálogos", "diálogos (in formation)": "Diálogos",
    "jam (in formation)": "Just Above Midtown", "jam": "Just Above Midtown",
    "just above midtown": "Just Above Midtown", "chicago tribute": "Chicago Tribute",
    "non-profits": "Non-Profits", "non-profit": "Non-Profits", "editions": "Editions",
    "possessions": "Possessions", "stand out": "Stand Out", "studio": "Studio",
    "theme": "Theme", "unworlding": "Unworlding",
}
ARTIST_SECTIONS = {"Spotlight", "Frame", "Live", "Social Work", "Sex Work", "Woven",
                   "Diálogos", "Just Above Midtown"}
PROGRAMME_SECTIONS = {"Frieze Projects", "Frieze Sculpture", "Frieze Artist Award"}

_NOISE = [
    re.compile(r"Press Release", re.I),
    re.compile(r"Page \d+ of\s*\d+", re.I),
    re.compile(r"^Participating Galleries", re.I),
    re.compile(r"List in formation", re.I),
    re.compile(r"^Galleries from the City", re.I),
    re.compile(r"^(Further Information|For (further|more) information|To keep up to date|"
               r"and Instagram|Further information is available)", re.I),
]
_STOP = re.compile(r"^(Territories|Notes to Editors|Press [Cc]ontacts?|"
                   r"Frieze .*public opening dates|The final list)", re.I)
_PROTECT = re.compile(r",\s*(Inc|Ltd|LLC|Co)\b\.?", re.I)
# a row that ends like this continues on the next line
_GALLERY_TAIL = re.compile(r"(\s(and|&|\+|\||-|of|de|du|der)|\b(and|&)\s+(Galerie|Gallery|Galeria|Galleria|Galería)|:)$", re.I)
# generic words that can end a gallery name ("Kavi Gupta" + "Gallery")
_GALLERY_WORD = re.compile(r"^(Gallery|Galleries|Galerie|Projects|Fine Arts?|Contemporary|Modern|Studio)\b")
# ...and the same word immediately closing a wrapped gallery name: "Rena Bransten" / "Gallery, Dawoud Bey"
_GALLERY_WORD_COMMA = re.compile(r"^(Gallery|Galleries|Projects|Fine Arts?|Contemporary)\s*,")


def _protect(s: str) -> str:
    return _PROTECT.sub(lambda m: "¸ " + m.group(1) + ("." if m.group(0).endswith(".") else ""), s)


def _unprotect(s: str) -> str:
    return s.replace("¸", ",")


def _is_prose(line: str) -> bool:
    if len(line) > 64:
        return True
    if line.endswith(".") and len(line) > 30 and not re.search(r"\b(Inc|Ltd|Co|St|Jr)\.$", line):
        return True
    if re.search(r"[a-z]-$", line):
        return True
    if line[:1].islower() and len(line.split()) >= 6:
        return True
    words = re.findall(r"\b(the|and|of|with|will|is|are|for|in|to|from|by|a)\b", line)
    return len(words) >= 3 and len(line) > 38


def _section_of(line: str):
    return SECTION_HEADERS.get(_clean(line).lower().rstrip(":"))


class _Ctx:
    def __init__(self, known_galleries, cities):
        self.gal_slugs = set()
        for g in known_galleries or []:
            s = slugify(g)
            if s:
                self.gal_slugs.add(s)
                self.gal_slugs.add(re.sub(r"^the-", "", s))
        self.cities = sorted({c for c in cities if c}, key=len, reverse=True)

    def is_gallery(self, s: str) -> bool:
        sl = slugify(s)
        return sl in self.gal_slugs or re.sub(r"^the-", "", sl) in self.gal_slugs

    def gallery_prefix_split(self, s: str):
        toks = s.split()
        for k in range(len(toks) - 1, 0, -1):
            cand = " ".join(toks[:k])
            if self.is_gallery(cand):
                rest = toks[k:]
                while len(rest) > 1 and _GALLERY_WORD.match(rest[0]):
                    cand += " " + rest.pop(0)
                return cand, " ".join(rest)
        return None

    def peel_city(self, rest: str):
        rest = rest.lstrip(" ,")
        for c in self.cities:
            if rest.startswith(c):
                tail = rest[len(c):]
                if tail == "" or tail[0] in " ,/:;(" or tail.startswith("¸"):
                    m = re.match(r"^\s*(\([^)]{1,12}\))", tail)
                    if m:
                        c, tail = c + " " + m.group(1), tail[m.end():]
                    return c, tail
        return None, rest


def _harvest_cities(lines):
    out = set()
    for ln in lines:
        p = _protect(ln)
        if p.count(",") == 1:
            city = p.split(",", 1)[1].strip().rstrip(" /")
            if 0 < len(city.split()) <= 3 and city[:1].isupper() and not re.search(r"\d", city):
                out.add(_unprotect(city))
    return out


def parse_press_release_pdf(page_text: str, known_galleries=None, extra_cities=None) -> list[dict]:
    """Parse the 'Participating Galleries' appendix of a Frieze press-release PDF (2016-2020).

    known_galleries: iterable of gallery names/slugs (e.g. the frieze.com /gallery/<slug> directory)
    used to split rows without a comma ("Frameless Gallery Stanislav Kolibal").
    Rows whose city/artist split was guessed carry "_parse_flag".
    """
    raw_lines = [_clean(l.replace("\t", "  ")) for l in page_text.splitlines()]
    raw_lines = [l for l in raw_lines if l]
    counts = {}
    for l in raw_lines:
        counts[l] = counts.get(l, 0) + 1
    first_pg = next((i for i, l in enumerate(raw_lines) if re.match(r"^Participating Galleries", l, re.I)), None)
    if first_pg is None:
        return []
    start = first_pg
    for j in range(first_pg, -1, -1):          # page header preceding the first list footer/header
        if re.search(r"Page \d+ of\s*\d+", raw_lines[j]):
            start = j
            break
    zone = []
    for l in raw_lines[start:]:
        if _STOP.search(l):
            break
        sec = _section_of(l)
        if sec:
            zone.append(("SEC", sec))
            continue
        if any(p.search(l) for p in _NOISE):
            continue
        if counts.get(l, 0) >= 5 or (counts.get(l, 0) >= 3 and len(l) > 12):   # running headers
            continue
        zone.append(("L", l))
    zone = [z for z in zone if not (z[0] == "L" and _is_prose(z[1]))]

    plain, _sec = [], "main"
    for z in zone:
        if z[0] == "SEC":
            _sec = z[1]
        elif _sec not in ARTIST_SECTIONS:
            plain.append(z[1])
    cities = set(BASE_CITIES) | _harvest_cities(plain) | set(extra_cities or [])
    ctx = _Ctx(known_galleries, cities)

    main_rows = []
    for z in zone:
        if z[0] == "SEC":
            break
        main_rows.append(z[1])
    city_mode = bool(main_rows) and sum(1 for r in main_rows if "," in _protect(r)) >= 0.5 * len(main_rows)

    records, buf, section = [], None, "main"

    def flush():
        nonlocal buf
        if buf:
            records.append((section, buf))
        buf = None

    for kind, val in zone:
        if kind == "SEC":
            flush()
            section = val
            continue
        line = val
        artist_sec = section in ARTIST_SECTIONS
        if buf is None:
            buf = line
            continue
        pb, pl = _protect(buf), _protect(line)
        if (pb.rstrip().endswith((",", "/")) or _GALLERY_TAIL.search(pb.rstrip())
                or re.match(r"^(/|&|and\s)", line)
                or (city_mode and "," not in pb and _GALLERY_WORD_COMMA.match(line) and not ctx.is_gallery(buf))):
            buf = buf + " " + line
            continue
        if not city_mode:
            flush(); buf = line
            continue
        if "," in pl:
            if "," not in pb and not ctx.is_gallery(buf) and not (artist_sec and ctx.gallery_prefix_split(buf)):
                buf = buf + " " + line          # wrapped gallery name
            else:
                flush(); buf = line
        else:
            if "," in pb:
                if artist_sec:
                    sp = ctx.gallery_prefix_split(line)
                    _b = _parse_record(buf, section, city_mode, ctx)
                    if sp and sp[1] and _b and _b["artists"]:
                        flush(); buf = line     # new comma-less row "Gallery Artist"
                    else:
                        buf = buf + " " + line  # wrapped artist / city
                elif ctx.peel_city(line)[0] or len(line.split()) <= 1:
                    buf = buf + " " + line      # wrapped city ("Angeles", "Kong")
                else:
                    flush(); buf = line
            else:
                flush(); buf = line
    flush()

    parsed = [b for b in (_parse_record(rec, sec, city_mode, ctx) for sec, rec in records) if b]
    # second chance for comma-less curated rows: an artist already seen in this document, or a
    # generic gallery word ('... Fine Art', '... Projects') ending the gallery name
    doc_artists = {a["name"] for b in parsed for a in b["artists"]}
    for b in parsed:
        if b.get("_parse_flag") != "no_separator_artist_unsplit":
            continue
        raw = b["gallery"]
        hit = next((a for a in sorted(doc_artists, key=len, reverse=True)
                    if raw.endswith(" " + a) and len(raw) > len(a) + 2), None)
        if hit:
            b["gallery"], b["artists"] = raw[: -len(hit)].strip(), [{"name": hit}]
            b["_parse_flag"] = "split_on_artist_seen_elsewhere_in_doc"
            continue
        m = re.match(r"^(.+?\b(?:Fine Art|Art|Arts|Projects|Gallery|Galerie|Contemporary))\s+(\S.+)$", raw)
        if m and len(m.group(2).split()) >= 2:
            b["gallery"], b["artists"] = m.group(1), split_artist_names(m.group(2))
            b["_parse_flag"] = "split_on_gallery_word"
    booths, seen = [], set()
    for b in parsed:
        k = (b["section"], gallery_key(b["gallery"]), tuple(a["name"] for a in b["artists"]))
        if k in seen:
            continue
        seen.add(k)
        booths.append(b)
    return booths


def _parse_record(rec: str, section: str, city_mode: bool, ctx: _Ctx):
    artist_sec = section in ARTIST_SECTIONS
    p = _protect(_clean(rec))
    flag = None
    galleries, cities_found, rest = [], [], p
    if not city_mode and not artist_sec:
        return _mk(p, None, section, None, None)
    if "," not in p:
        if artist_sec:
            sp = ctx.gallery_prefix_split(p)
            if sp:
                return _mk(sp[0], None, section, sp[1], None)
            return _mk(p, None, section, None, "no_separator_artist_unsplit")
        return _mk(p, None, section, None, None)
    while True:
        g, sep, rest = rest.partition(",")
        if not sep:
            break
        galleries.append(g.strip())
        if not city_mode:
            break
        city, rest2 = ctx.peel_city(rest)
        if city is None and "," in rest:          # gallery name containing a comma: "VI, VII, Oslo"
            seg, _, after = rest.partition(",")
            c3, r3 = ctx.peel_city(after)
            if c3 and len(seg.split()) <= 3:
                galleries[-1] = galleries[-1] + "," + seg
                city, rest2 = c3, r3
        if city is None:
            r = rest.strip()
            if not artist_sec:
                city, rest2 = r, ""                  # unknown city in a plain section
            elif re.match(r"^\s*[A-Z][^:,]{1,28}:\s*\S", rest):
                city, rest2 = rest.split(":", 1)     # "Cincinnati: USCO and Gerd Stern"
                flag = "city_split_on_colon"
            else:
                flag = "city_not_recognised"         # e.g. Dialogos rows without a city
                rest2 = rest
        cities_found.append(city.strip() if city else None)
        rest = rest2
        while True:                                  # further cities: ", Hong Kong"
            m = re.match(r"^\s*,\s*", rest)
            if not m:
                break
            c2, r2 = ctx.peel_city(rest[m.end():])
            if not c2:
                break
            rest = r2
        nxt = re.match(r"^\s*(?:/|and\s|&\s)\s*(.+)$", rest)   # second gallery: "/ Spruth Magers, Berlin"
        if nxt and "," in nxt.group(1):
            rest = nxt.group(1)
            continue
        break
    artist_text = rest.strip(" ,:;/")
    if not artist_sec and artist_text:
        cities_found[-1:] = [((cities_found[-1] or "") + " " + artist_text).strip()] if cities_found else [artist_text]
        artist_text = ""
    gname = " / ".join(_unprotect(g) for g in galleries if g)
    city = cities_found[0] if cities_found else None
    b = _mk(gname, _unprotect(city) if city else None, section, _unprotect(artist_text) if artist_text else None, flag)
    if b and len(cities_found) > 1:
        b["gallery_cities"] = [_unprotect(c) for c in cities_found if c]
    return b


def _mk(gallery, city, section, artist_text, flag):
    gallery = _clean(_unprotect(gallery or "")).strip(" ,") if gallery else None
    if not gallery or len(gallery) < 2:
        return None
    b = {"gallery": gallery, "gallery_city": _clean(city), "booth": None, "section": section,
         "artists": split_artist_names(artist_text)}
    if flag:
        b["_parse_flag"] = flag
    return b


# ---------------------------------------------------------------------------
# 2016 fair-guide / map PDF: "Gallery Name  B18" index lines
# ---------------------------------------------------------------------------

_GUIDE_ROW = re.compile(r"^(?:[A-Z]\s{1,3}(?=\S))?(?P<g>[^\d\s].*?)\s{2,}(?P<b>[A-Z]{1,2}\d{1,2}[a-z]?)$")


def parse_fair_guide_index(page_text: str) -> list[dict]:
    out, seen = [], set()
    for raw in page_text.splitlines():
        l = raw.replace("\t", "  ").rstrip()
        l = re.sub(r"^\s*[A-Z]\s{2,}", "", l).strip()   # alphabet index letter
        m = _GUIDE_ROW.match(l)
        if not m:
            continue
        g = _clean(m.group("g"))
        if not g or re.match(r"^(L|P)\d", g) or ":" in g or re.search(r"\d(am|pm)", g):
            continue
        k = (gallery_key(g), m.group("b"))
        if k in seen:
            continue
        seen.add(k)
        out.append({"gallery": g, "gallery_city": None, "booth": m.group("b"), "section": None, "artists": []})
    return out


# ---------------------------------------------------------------------------
# artist-level programmes (Frieze Projects / Frieze Sculpture) press-release PDFs
# ---------------------------------------------------------------------------

_NAME_TOK = r"(?:[A-Z][\w'’\-.]*|de|da|del|della|di|van|von|der|du|la|le|y|e|bin|al|el)"
_BIO_NAME = re.compile(r"(?<![\w’'])([A-Z][\w'’\-.]+(?:\s+" + _NAME_TOK + r"){1,4}?)(?:’s|'s)?\s*\(b\.\s?\d{4}")
_LIST_SENT = re.compile(
    r"(?:artists(?: for [^:.]{0,60}?)? (?:are|include)|[Pp]articipating [Aa]rtists(?: Announced)?|"
    r"artists for [^:]{0,80}\(list in formation\))\s*:?\s+"
    r"((?:[A-Z][^.:;]{2,60}?,\s+){2,}[^.]*?)(?=\.\s|\s+Frieze today|\s+Frieze [A-Z]\w+ (?:said|will|announces)|$)")
_NAME_GAL = re.compile(r"(?<![\w’'])([A-Z][\w’'\-.]+(?:\s+" + _NAME_TOK + r"){1,4}?)\s*\(([^()]{2,70})\)")
_STOPWORDS = {"Frieze", "The", "This", "Curated", "Selected", "Works", "London", "Projects", "Sculpture",
              "Gallery", "Galleries", "Park", "Regent", "Today", "Director", "Programme", "Press", "Winner"}
_YEAR_LINE = re.compile(r"(?:\(|,\s*|\s|^)(1[5-9]\d\d|20[0-2]\d)(?:[–-]\d{2,4})?\)?\s*$")


def _plausible_name(n: str) -> bool:
    toks = n.split()
    if not (1 <= len(toks) <= 6) or len(n) > 60:
        return False
    if toks[0] in _STOPWORDS or any(t in ("said", "will", "the", "and", "with", "for") for t in toks):
        return False
    caps = sum(1 for t in toks if t[:1].isupper() or t[:1].isdigit())
    return caps >= max(1, len(toks) - 2)


def _tidy_name(n: str) -> str:
    n = _clean(n) or ""
    n = re.split(r"(?<!\b[A-Z])\.\s", n)[-1]            # drop tail of previous sentence (keep 'P. Butler')
    n = re.sub(r"^(?:Artists Announced|Participating Artists|By|by|With|Artist|artist|Veteran|Works by|Sir|Dame)\s+", "", n)
    n = re.sub(r"(’|')s$", "", n)
    return n.strip(" ,.;:")


def _works_list(page_text: str):
    """'Full list of works' appendix: Artist / Title (YYYY) / Gallery -> [(artist, gallery)]."""
    lines = [_clean(l) for l in page_text.splitlines()]
    lines = [l for l in lines if l and not any(p.search(l) for p in _NOISE)
             and not re.match(r"^\d{1,2} \w+ 20\d\d:|^(January|February|March|April|May|June|July|August|"
                              r"September|October|November|December) 20\d\d:", l)]
    start = next((i for i, l in enumerate(lines) if re.search(r"^Full list of works", l, re.I)), None)
    if start is None:
        return []
    body = lines[start + 1:]
    stop = next((i for i, l in enumerate(body)
                 if re.match(r"^(–End|-End|End\.|Notes to Editors|Further Inform|Press Contacts)", l)), len(body))
    body = body[:stop]
    entries, prev_year = [], -1
    for yi in [i for i, l in enumerate(body) if _YEAR_LINE.search(l)]:
        cand = yi - 1
        if cand > prev_year:
            a = body[cand].rstrip(" ,*").strip()
            if (not re.search(r"\d", a) and not (a.isupper() and len(a) > 6) and _plausible_name(a)
                    and len(a.split()) <= 5):
                entries.append((cand, yi, a))
        prev_year = yi
    out = []
    for n, (ai, yi, a) in enumerate(entries):
        nxt = entries[n + 1][0] if n + 1 < len(entries) else len(body)
        gal_lines = []
        for g in body[yi + 1:nxt]:
            g = g.strip(" ,")
            if (re.search(r"[\d(]", g) or (g.isupper() and len(g) > 6) or g.endswith(".")
                    or len(g.split()) > 6 or g.startswith("*") or g.endswith("*")):
                break                                    # first non-gallery-looking line ends the block
            gal_lines.append(g)
        out.append((a, " / ".join(gal_lines) or None))
    return out


def parse_programme_artists_pdf(page_text: str, section: str = "Frieze Projects", known_galleries=None) -> list[dict]:
    """Artists named in a Frieze Projects / Frieze Sculpture press release; one row per artist.

    High-precision signals only: (1) roll-call sentence ('the 2018 artists are: A, B ... and Z'),
    (2) bio notation 'Name (b. 1975, ...)', (3) 'Full list of works' appendix (keeps presenting
    gallery), (4) 'Name (Gallery)' when Gallery is a known gallery.
    """
    ctx = _Ctx(known_galleries, [])
    flat = re.sub(r"-\n(?=[a-z])", "", page_text)
    flat = re.sub(r"­\s*", "", flat)
    flat = _WS.sub(" ", flat.replace("\n", " "))
    flat_i = re.sub(r"\b([A-Z])\.\s", lambda m: m.group(1) + "§ ", flat)   # protect initials
    names = []
    m = _LIST_SENT.search(flat_i)
    if m:
        body = re.sub(r"\([^)]*\)", "", m.group(1)).replace("§", ".")
        body = re.sub(r"\s+and\s+(?=[A-Z])", ", ", body)
        body = re.sub(r"Frieze Artist Award-winner\s+", "", body)
        for part in body.split(","):
            n = _tidy_name(part)
            if n and _plausible_name(n):
                names.append((n, None))
    for bm in _BIO_NAME.finditer(flat):
        n = _tidy_name(bm.group(1))
        if n and _plausible_name(n):
            names.append((n, None))
    for a, g in _works_list(page_text):
        n = _tidy_name(a)
        if n and _plausible_name(n):
            names.append((n, g))
    if known_galleries:
        for gm in _NAME_GAL.finditer(flat):
            gals = [g.strip() for g in re.split(r"\s+and\s+|\s*/\s*|,\s*", _clean(gm.group(2))) if g.strip()]
            if gals and all(ctx.is_gallery(g) for g in gals):
                n = _tidy_name(gm.group(1))
                if n and _plausible_name(n):
                    names.append((n, " / ".join(gals)))
    full = [n for n, _ in names if len(n.split()) > 1]
    names = [(n, g) for n, g in names
             if len(n.split()) > 1 or n.isupper() or not any(f.split()[-1] == n for f in full)]
    out, idx = [], {}
    for n, g in names:
        k = slugify(n)
        if k in idx:
            if g and not out[idx[k]]["gallery"]:
                out[idx[k]]["gallery"] = g
            continue
        idx[k] = len(out)
        out.append({"gallery": g, "gallery_city": None, "booth": None, "section": section,
                    "artists": [{"name": n}]})
    return out


# ---------------------------------------------------------------------------
# Frieze Artist Award announcement (press-release PDF text or article/announcement HTML)
# ---------------------------------------------------------------------------

_AWARD_PATTERNS = [
    re.compile(r"Frieze Artist Award(?: 20\d\d)?:\s+([A-Z][\w'’\-]+(?: [A-Z][\w'’\-]+){0,3})"),
    re.compile(r"([A-Z][\w'’\-]+(?: [A-Z][\w'’\-]+){0,3})(?::\s+(?:Inaugural\s+)?Winner| [Ww]ins\b|"
               r" [Aa]nnounced as (?:the )?[Ww]inner| [Rr]eceives)"),
    re.compile(r"Frieze Artist Award-winner\s+([A-Z][\w'’\-]+(?: [A-Z][\w'’\-]+){0,3})"),
]


def parse_artist_award(page_text: str) -> list[dict]:
    """Winner of the Frieze Artist Award from an announcement (HTML <title>/<h1> or PDF text)."""
    head = page_text
    if "<html" in page_text[:3000].lower() and BeautifulSoup is not None:
        soup = _soup(page_text)
        bits = [soup.title.get_text(" ") if soup.title else ""]
        h1 = soup.find("h1")
        if h1:
            bits.append(h1.get_text(" "))
        head = " | ".join(bits)
    head = _WS.sub(" ", head.replace("\n", " "))[:3000]
    for pat in _AWARD_PATTERNS:
        for m in pat.finditer(head):
            toks = _tidy_name(m.group(1)).split()
            cut = next((i for i, t in enumerate(toks) if t in _STOPWORDS), len(toks))
            n = " ".join(toks[:cut])
            if len(toks[:cut]) >= 2 and _plausible_name(n):
                return [{"gallery": None, "gallery_city": None, "booth": None,
                         "section": "Frieze Artist Award", "artists": [{"name": n}]}]
    return []


# ---------------------------------------------------------------------------
# Sources per edition. WB(ts, url) = raw Wayback capture https://web.archive.org/web/<ts>id_/<url>
# "aux" entries: use = booth_numbers | section_filter | programme | award
# ---------------------------------------------------------------------------

def WB(ts: str, url: str) -> str:
    return f"https://web.archive.org/web/{ts}id_/{url}"


_FC = "https://www.frieze.com/fairs"
_D7 = "https://frieze.com/fairs"
_SF = "https://frieze.com/sites/default/files/fairs_and_events"
_IF = "https://static.frieze.com/files/inline-files"

GALLERY_DIRECTORY_CDX = ("https://web.archive.org/cdx/search/cdx?url=frieze.com/gallery/*&output=json"
                         "&filter=statuscode:200&fl=original&collapse=urlkey&limit=100000")


def _aux(use, ts, url, parser, fetch, **kw):
    return {"use": use, "urls": [WB(ts, url)], "parser": parser, "fetch": fetch, **kw}


def _sec(ts, url):
    return _aux("section_filter", ts, url, "parse_d8_gallery_list", "html")


def _prog(ts, url, section):
    return _aux("programme", ts, url, "parse_programme_artists_pdf", "pdf", section=section)


def _award(ts, url, fetch):
    return _aux("award", ts, url, "parse_artist_award", fetch)


def _d8(fair, ts, sections=(), aux=(), alt=()):
    return {"urls": [WB(ts, f"{_FC}/{fair}/galleries")], "parser": "parse_d8_gallery_list", "fetch": "html",
            "live_urls": [f"{_FC}/{fair}/galleries"] + [f"{_FC}/{fair}/galleries?section={s}" for s in sections],
            "alt_urls": list(alt), "aux": list(aux)}


def _pdf(ts, url, aux=()):
    return {"urls": [WB(ts, url)], "parser": "parse_press_release_pdf", "fetch": "pdf", "aux": list(aux)}


_AWARD_FL17_PROJECTS = (f"{_SF}/frieze_projects_2017_v14.pdf", "20200716195759")

EDITION_SOURCES = {
    # ---- Frieze London ----
    "frieze_london_2016": _pdf("20161223042323", f"{_SF}/frieze_london_2016_galleries_28_july.pdf", [
        _aux("booth_numbers", "20161223082957", f"{_SF}/frieze_london_2016_fair_guide.pdf", "parse_fair_guide_index", "pdf"),
        _prog("20161222221603", "https://frieze.com/sites/default/files/projects/frieze_projects_2016_27_september.pdf", "Frieze Projects"),
        _prog("20161222214013", f"{_SF}/sculpture_park_2016_3_october.pdf", "Frieze Sculpture"),
        _award("20161223022232", f"{_SF}/frieze_artist_award_yuri_pattison_25_may_final.pdf", "pdf")]),
    "frieze_london_2017": _pdf("20200716192019", f"{_SF}/frieze_london_highlights_v25.pdf", [
        _prog("20200716195759", f"{_SF}/frieze_projects_2017_v14.pdf", "Frieze Projects"),
        _prog("20200716195220", f"{_SF}/frieze_sculpture_2017_v28.pdf", "Frieze Sculpture"),
        _award("20200716195759", f"{_SF}/frieze_projects_2017_v14.pdf", "pdf")]),
    "frieze_london_2018": _pdf("20200716232121", f"{_SF}/frieze_london_highlights_v18.pdf", [
        _prog("20200716211258", f"{_SF}/frieze_sculpture_2018_final_1.pdf", "Frieze Sculpture")]),
    "frieze_london_2019": _pdf("20190919141149", f"{_SF}/fl_2019_galleries_final_0.pdf", [
        _prog("20191015030727", f"{_SF}/frieze_sculpture_london_artists_announced_2019_v12.pdf", "Frieze Sculpture")]),
    "frieze_london_2020": _d8("frieze-london", "20201003", ("main", "focus", "possessions"), [
        _sec("20210420015029", f"{_FC}/frieze-london/galleries?section=focus"),
        _award("20200825", "https://www.e-flux.com/announcements/314841/alberta-whittle-wins-frieze-artist-award-2020/", "html")]),
    "frieze_london_2021": _d8("frieze-london", "20211008", ("main", "focus", "unworlding", "editions")),
    "frieze_london_2022": _d8("frieze-london", "20221007", ("main", "focus", "indra's net", "editions", "non-profit"), [
        _sec("20220923002457", f"{_FC}/frieze-london/galleries?section=indra%27s%20net"),
        _sec("20230202082210", f"{_FC}/frieze-london/galleries?section=editions"),
        _award("20220706", "https://www.frieze.com/article/abbas-zahedi-winner-frieze-artist-award-2022", "html")],
        alt=[f"{_FC}/archive/frieze-london/2022/galleries"]),
    "frieze_london_2023": _d8("frieze-london", "20230929", ("main", "focus", "artist to artist", "editions"), [
        _award("20230629", "https://www.frieze.com/article/adham-faramawy-announced-winner-2023-frieze-london-artist-award", "html")],
        alt=[WB("20231018002339", f"{_FC}/archive/frieze-london/2023/galleries")]),
    "frieze_london_2024": _d8("frieze-london", "20241007", ("galleries", "focus", "artist-to-artist", "smoke", "editions"),
                              alt=[f"{_FC}/archive/frieze-london/2024/galleries"]),
    "frieze_london_2025": _d8("frieze-london", "20251003", ("galleries", "focus", "artist-to-artist", "echoes in the present", "editions")),
    "frieze_london_2026": {"urls": [], "parser": "parse_d8_gallery_list", "fetch": "html", "aux": [],
                           "discovery": "Wayback CDX url=frieze.com/fairs/frieze-london/galleries (prefix, from=2026); "
                                        "live frieze.com is Cloudflare-challenged"},
    # ---- Frieze Masters ----
    "frieze_masters_2016": _pdf("20161222020616", f"{_SF}/masters_2016_galleries_28_july.pdf", [
        _aux("booth_numbers", "20161223100529", f"{_SF}/frieze_masters_2016_fair_guide.pdf", "parse_fair_guide_index", "pdf")]),
    "frieze_masters_2017": _pdf("20200716210801", f"{_SF}/masters_highlights_v27.pdf"),
    "frieze_masters_2018": {"urls": [WB("20181016053923", f"{_D7}/frieze-masters/galleries")],
                            "parser": "parse_d7_gallery_list", "fetch": "html", "aux": [],
                            "discovery": "only page 0 (20 rows) of the paginated Drupal-7 list is archived; "
                                         "no 2018 Masters list PDF archived"},
    "frieze_masters_2019": _pdf("20191015031015", f"{_SF}/fm_galleries_announced_final_0.pdf"),
    "frieze_masters_2020": _d8("frieze-masters", "20201003", ("main", "spotlight")),
    "frieze_masters_2021": _d8("frieze-masters", "20211008", ("main", "spotlight", "stand out")),
    "frieze_masters_2022": _d8("frieze-masters", "20221004", ("main", "spotlight", "stand out"), [
        _sec("20220922072924", f"{_FC}/frieze-masters/galleries?section=main"),
        _sec("20220922073257", f"{_FC}/frieze-masters/galleries?section=spotlight"),
        _sec("20220922073439", f"{_FC}/frieze-masters/galleries?section=stand%20out")]),
    "frieze_masters_2023": _d8("frieze-masters", "20230922", ("main", "spotlight", "stand out", "studio", "modern women")),
    "frieze_masters_2024": _d8("frieze-masters", "20241007", ("galleries", "spotlight", "studio")),
    "frieze_masters_2025": _d8("frieze-masters", "20250831", ("galleries", "spotlight", "studio", "reflections")),
    "frieze_masters_2026": _d8("frieze-masters", "20260801", ("galleries", "spotlight", "reflections", "queering modernism")),
    # ---- Frieze New York ----
    "frieze_ny_2016": _pdf("20160528020558", "http://www.frieze.com:80/sites/default/files/Fairs%20and%20Events/FriezeNY2016_v10.pdf"),
    "frieze_ny_2017": _pdf("20200922145856", f"{_IF}/fairs-and-events-fny17-galleries-v3.pdf"),
    "frieze_ny_2018": _pdf("20200922153857", f"{_IF}/fairs-and-events-fny-2018-galleries-v30.pdf", [
        _award("20200922142713", f"{_IF}/fairs-and-events-kiwanga-faa-2018-april-16.pdf", "pdf")]),
    "frieze_ny_2019": _pdf("20200922142942", f"{_IF}/fairs-and-events-fny-galleries-2019-v40.pdf", [
        _award("20200922154954", f"{_IF}/fairs-and-events-frieze-artist-award-2019-fny-v4.pdf", "pdf")]),
    "frieze_ny_2020": _pdf("20200426145202", "https://frieze.com/sites/default/files/fny_2020_galleries_release.pdf"),
    "frieze_ny_2021": _d8("frieze-new-york", "20210505", ("main", "frame"), [
        _award("20210303", "https://www.e-flux.com/announcements/371329/precious-okoyomon-wins-2021-frieze-artist-award-at-frieze-new-york/", "html")]),
    "frieze_ny_2022": _d8("frieze-new-york", "20220329", ("main", "frame")),
    "frieze_ny_2023": _d8("frieze-new-york", "20230512", ("main", "focus"), alt=[f"{_FC}/archive/frieze-new-york/2023/galleries"]),
    "frieze_ny_2024": _d8("frieze-new-york", "20240407", ("galleries", "focus")),
    "frieze_ny_2025": _d8("frieze-new-york", "20250328", ("galleries", "focus")),
    "frieze_ny_2026": _d8("frieze-new-york", "20260425", ("galleries", "focus")),
    # ---- Frieze Los Angeles ----
    "frieze_la_2019": _pdf("20200922143412", f"{_IF}/fairs-and-events-fla-highlights-2019-v37.pdf", [
        _prog("20200922131036", f"{_IF}/fairs-and-events-fla-projects-2019-v22.pdf", "Frieze Projects")]),
    "frieze_la_2020": {"urls": [WB("20200402091218", f"{_D7}/frieze-los-angeles/galleries"),
                                WB("20191213100247", f"{_D7}/frieze-los-angeles/galleries?page=1")],
                       "parser": "parse_d7_gallery_list", "fetch": "html",
                       "aux": [_prog("20200220065902", f"{_SF}/frieze_projects_los_angeles_2020.pdf", "Frieze Projects")],
                       "discovery": "pages >= 2 of the Drupal-7 list are not archived"},
    "frieze_la_2021": {"urls": [], "parser": None, "fetch": None, "aux": [],
                       "discovery": "no 2021 edition (list page in Apr 2021 already pointed to Feb 2022, 0 galleries)"},
    "frieze_la_2022": _d8("frieze-los-angeles", "20220210", ("main", "focus la"), [
        _sec("20220128103633", f"{_FC}/frieze-los-angeles/galleries?section=focus%20la")]),
    "frieze_la_2023": _d8("frieze-los-angeles", "20230210", ("main", "focus"), alt=[f"{_FC}/archive/frieze-los-angeles/2023/galleries"]),
    "frieze_la_2024": _d8("frieze-los-angeles", "20240226", ("galleries", "focus"), alt=[f"{_FC}/archive/frieze-los-angeles/2024/galleries"]),
    "frieze_la_2025": _d8("frieze-los-angeles", "20250207", ("galleries", "focus")),
    "frieze_la_2026": _d8("frieze-los-angeles", "20251210", ("galleries", "focus")),
    # ---- Frieze Seoul ----
    "frieze_seoul_2022": _d8("frieze-seoul", "20220901", ("main", "focus asia", "frieze masters"), [
        _sec("20221004144625", f"{_FC}/frieze-seoul/galleries?section=focus%20asia"),
        _sec("20221004131112", f"{_FC}/frieze-seoul/galleries?section=frieze%20masters")],
        alt=[f"{_FC}/archive/frieze-seoul/2022/galleries"]),
    "frieze_seoul_2023": _d8("frieze-seoul", "20230906", ("galleries", "focus asia", "frieze masters"), [
        _sec("20230628210658", f"{_FC}/frieze-seoul/galleries?year&section=focus%20asia")],
        alt=[f"{_FC}/archive/frieze-seoul/2023/galleries"]),
    "frieze_seoul_2024": _d8("frieze-seoul", "20240827", ("galleries", "focus asia", "frieze masters"), [
        _award("20240624", "https://www.frieze.com/article/choi-goen-announced-winner-artist-award-frieze-seoul-2024", "html")],
        alt=[f"{_FC}/archive/frieze-seoul/2024/galleries"]),
    "frieze_seoul_2025": _d8("frieze-seoul", "20250831", ("galleries", "focus asia", "frieze masters")),
    "frieze_seoul_2026": {"urls": [], "parser": "parse_d8_gallery_list", "fetch": "html", "aux": [],
                          "discovery": "Wayback CDX url=frieze.com/fairs/frieze-seoul/galleries (prefix, from=2026); "
                                       "live frieze.com is Cloudflare-challenged"},
}
