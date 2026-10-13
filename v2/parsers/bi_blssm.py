"""Main-exhibition artist-list parsers: Berlin Biennale, Biennale de Lyon,
Shanghai Biennale, Sharjah Biennial, Manifesta (editions 2016-2026).

Self-contained (requests is NOT needed here; only bs4 + lxml + stdlib).
The crawler fetches and stores the raw page itself, then calls

    parse_<edition_id>(page_text: str) -> list[dict]

once per URL listed in EDITION_SOURCES[edition_id]["urls"] (or "requests"),
concatenates the results and finally calls dedupe(). parse_edition() below
does exactly that for a list of already-fetched page texts.

Record shape (extra keys are optional, never required downstream):
    {"name": str,              # name as printed in the primary list
     "name_en": str | None,    # English/Latin form when the source gives a
                               # distinct one (Shanghai zh/en API, M11 flip)
     "country": str | None,    # only when the source states it (ISO-2 codes or
                               # free text, exactly as published)
     "birth_year": int | None, # only when the source states it
     "section": str | None,    # sub-exhibition / act, when the source groups them
     "source_ref": str | None} # detail-page URL or slug on the source site

Scope rule: only the main/central exhibition. National pavilions, collateral /
parallel events, city projects, performance/public programmes are excluded.
Multi-person credits ("A/B", "A & B", "X, Y, Z") are kept as ONE record, exactly
as the organiser credits them; announced counts often count them differently.

Fetch etiquette used during research: UA
"artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)", >= 1 s between
requests; m11.manifesta.org declares Crawl-delay: 10; manifesta.org answers
HTTP 429 above ~1 req / 5 s (use >= 8 s and honour Retry-After).
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Callable, Iterable

from bs4 import BeautifulSoup

USER_AGENT = "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _soup(page_text: str) -> BeautifulSoup:
    return BeautifulSoup(page_text, "lxml")


def _clean(s: str | None) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFC", s).replace("\u00a0", " ").replace("\u2028", " ")
    return re.sub(r"\s+", " ", s).strip()


def _rec(name, name_en=None, country=None, birth_year=None, section=None,
         source_ref=None, **extra) -> dict:
    d = {
        "name": _clean(name),
        "name_en": _clean(name_en) or None,
        "country": _clean(country) or None,
        "birth_year": int(birth_year) if birth_year not in (None, "", 0) else None,
        "section": section,
        "source_ref": source_ref,
    }
    for k, v in extra.items():
        if v not in (None, "", [], {}):
            d[k] = v
    return d


def _key(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-z\u0080-\uffff]+", "", s.lower())


def dedupe(records: Iterable[dict]) -> list[dict]:
    """Drop exact repeats (accent/case/punctuation-insensitive on name).
    Keeps the first occurrence, but fills its empty fields from later ones and
    merges distinct 'section' values ("A; B")."""
    out: dict[str, dict] = {}
    for r in records:
        k = _key(r.get("name", ""))
        if not k:
            continue
        if k not in out:
            out[k] = dict(r)
            continue
        cur = out[k]
        for f, v in r.items():
            if cur.get(f) in (None, "", []) and v not in (None, "", []):
                cur[f] = v
        s_old, s_new = cur.get("section"), r.get("section")
        if s_new and s_old and s_new not in s_old.split("; "):
            cur["section"] = f"{s_old}; {s_new}"
    return list(out.values())


def flip_surname_first(name: str) -> str:
    """'Surname, Given' -> 'Given Surname'; handles 'A, B & C, D' pairs.
    Leaves names without exactly one comma per part untouched."""
    parts = [p.strip() for p in re.split(r"\s+&\s+", name)]
    out = []
    for p in parts:
        bits = [b.strip() for b in p.split(",")]
        if len(bits) == 2 and bits[0] and bits[1] and not bits[1].startswith("("):
            out.append(f"{bits[1]} {bits[0]}")
        elif len(bits) == 2 and bits[1].startswith("("):
            out.append(f"{bits[0]} {bits[1]}")  # 'Daniel Kelly, (DKUK)'
        else:
            out.append(p)
    return _clean(" & ".join(out))


# --------------------------------------------------------------------------- #
# Berlin Biennale  (www.berlinbiennale.de archive pages, server-rendered HTML)
# --------------------------------------------------------------------------- #
BB_BASE = "https://www.berlinbiennale.de"


def _parse_berlin_archive(page_text: str) -> list[dict]:
    """<div class="artists__columns"> <li class="artists__name"> under the
    'Participants' heading of /en/biennalen/<id>/<slug>. BB13 entries are plain
    text (no links) and two of them are chapter labels of the form
    'flowers — A, B, C'; those are expanded into members (section=label)."""
    s = _soup(page_text)
    out = []
    for col in s.select("div.artists__columns"):
        for li in col.select("li.artists__name"):
            ch = li.find(class_="artists__char")
            if ch:
                ch.extract()
            a = li.find("a", href=True)
            text = _clean(li.get_text(" "))
            if not text:
                continue
            ref = (BB_BASE + a["href"]) if a and a["href"].startswith("/") else (a["href"] if a else None)
            m = re.match(r"^(\S[^\u2014]*?)\s+\u2014\s+(.+)$", text)  # em dash = chapter label
            if m and not a:
                label, members = m.group(1), m.group(2)
                for mem in re.split(r",\s*", members):
                    mem = mem.strip(" \u2602\ufe0f")
                    if mem:
                        out.append(_rec(mem, section=f"chapter: {label}"))
                continue
            name_en = None
            # 'சிந்துஜன் வரதராஜா (Sinthujan Varatharajah)'-style transliteration
            # only when NO Latin letter precedes the parenthesis
            t = re.match(r"^([^A-Za-z\u00c0-\u024f(]+?)\s+\(([\x20-\u024f]+)\)$", text)
            if t:
                name_en = t.group(2)
            out.append(_rec(text, name_en=name_en, source_ref=ref))
    return dedupe(out)


def parse_berlin_2016(page_text: str) -> list[dict]:
    return _parse_berlin_archive(page_text)


def parse_berlin_2018(page_text: str) -> list[dict]:
    return _parse_berlin_archive(page_text)


def parse_berlin_2020(page_text: str) -> list[dict]:
    return _parse_berlin_archive(page_text)


def parse_berlin_2022(page_text: str) -> list[dict]:
    return _parse_berlin_archive(page_text)


def parse_berlin_2025(page_text: str) -> list[dict]:
    return _parse_berlin_archive(page_text)


def parse_berlin_person(page_text: str) -> dict:
    """OPTIONAL enrichment for one /en/personen/<id>/<slug> page (one request per
    artist, so not run in bulk during research). Returns
    {"birth_year", "birth_place", "country"} from '* 1966 in Munich, DE'."""
    s = _soup(page_text)
    h1 = s.find("h1")
    nxt = h1.find_next(["p", "div", "span"]) if h1 else None
    line = _clean(nxt.get_text(" ")) if nxt else ""
    m = re.match(r"^\*\s?(\d{4})(?:\s+in\s+([^,;†]+?))?(?:,\s*([A-Z]{2}))?(?:[;†]|$)", line)
    if not m:
        return {"birth_year": None, "birth_place": None, "country": None}
    return {"birth_year": int(m.group(1)), "birth_place": (m.group(2) or "").strip() or None,
            "country": m.group(3)}


# --------------------------------------------------------------------------- #
# Biennale de Lyon  (www.labiennaledelyon.com archives, server-rendered HTML)
# --------------------------------------------------------------------------- #
LYON_BASE = "https://www.labiennaledelyon.com"


def _parse_lyon_cards(page_text: str) -> list[dict]:
    """One paginated page (15 cards) of /archives-generale/<ed>/<artists-page>
    filtered with categories[0]=<main-exhibition category>. Card = h2.person__name a."""
    s = _soup(page_text)
    out = []
    for h in s.select("h2.person__name"):
        a = h.find("a", href=True)
        name = _clean(h.get_text(" "))
        if name:
            out.append(_rec(name, source_ref=(LYON_BASE + a["href"]) if a else None))
    return out


def lyon_page_count(first_page_text: str) -> int:
    """Number of result pages = highest 'page=N' link on page 1 of a filtered
    Lyon artist list (the pager elides middle pages, e.g. 1 2 3 … 5 6)."""
    nums = [int(m) for m in re.findall(r"[?&;]page=(\d+)", first_page_text)]  # hrefs are '&amp;page=N'
    return max(nums) if nums else 1


def parse_lyon_2017(page_text: str) -> list[dict]:
    return _parse_lyon_cards(page_text)


def parse_lyon_2019(page_text: str) -> list[dict]:
    return _parse_lyon_cards(page_text)


def parse_lyon_2024(page_text: str) -> list[dict]:
    return _parse_lyon_cards(page_text)


_LYON_QUAL = re.compile(
    r"\s*\((d['’]après[^)]*|attribué à|graveur|imprimeur|faïencier|imprimerie [^)]*)\)\s*$", re.I)


def parse_lyon_2022(page_text: str) -> list[dict]:
    """/archives-generale/art-contemporain-2022/liste-artistes-2022 : one flat
    <br>-separated list inside div.content__column__col <p>. Attribution
    qualifiers ('(d'après)', '(graveur)'...) are moved to 'note'; the closing
    line 'et de nombreux artistes anonymes...' is dropped."""
    s = _soup(page_text)
    main = s.find("main") or s
    out = []
    for col in main.select("div.content__column__col"):
        for p in col.find_all("p"):
            for br in p.find_all("br"):
                br.replace_with("\n")
            for line in p.get_text().split("\n"):
                line = _clean(line)
                if not line or line.lower().startswith("et de nombreux"):
                    continue
                note = None
                m = _LYON_QUAL.search(line)
                if m:
                    note, line = m.group(1), _clean(line[: m.start()])
                m2 = re.match(r"^(.+?)\s+-\s+(Avec .+)$", line)  # 'Eszter Salamon - Avec le Jeune Ballet…'
                if m2:
                    line, note = m2.group(1), m2.group(2)
                m3 = re.match(r"^(.+?)\s+\((d['’]après .+)\)$", line)
                if m3:
                    line, note = m3.group(1), m3.group(2)
                out.append(_rec(line, note=note))
    return dedupe(out)


# --------------------------------------------------------------------------- #
# Shanghai Biennale  (Power Station of Art; React SPA backed by a JSON feed)
#   GET https://www.powerstationofart.com/campus/api/feed/public/psa
#       /whats-on/programs/<program-slug>/<artists-page-slug>
#   header  X-Language: en | zh-Hans   (anything else -> 400 INCORRECT_LANGUAGE)
# --------------------------------------------------------------------------- #
PSA_API = "https://www.powerstationofart.com/campus/api/feed/public/psa"


_MULTI = re.compile(r"\s(&|and|und|with|x)\s|/|,|×|、|和", re.I)


def _psa_birth_year(bio_html: str | None, name: str = "") -> int | None:
    """Birth year only when the bio is about ONE person and states it in its
    first sentence ('Born in 1983 in Tokyo', 'B. 1968, Johannesburg',
    '1954年生于…'). Collectives / duos / 'Estd. 2011' bios return None, so a
    member's year is never attached to a group credit."""
    if not bio_html or _MULTI.search(name or ""):
        return None
    if re.search(r"collective|group|studio|architect|arquitect|associates|\blab\b|组合|小组|团体", name or "", re.I):
        return None
    t = _clean(BeautifulSoup(bio_html, "lxml").get_text(" "))[:160]
    years = set(re.findall(r"(?:born|b\.)\s*(?:in\s+)?(1[89]\d\d|20[0-2]\d)", t, re.I))
    if len(years) > 1:  # bio describes several people
        return None
    if re.search(r"\b(estd|est\.|founded|established|formed)\b|成立", t[:60], re.I):
        return None
    m = (re.match(r"^[^.]{0,80}?\b(?:born(?: in)?|b\.)\s*(?:in\s+)?(1[89]\d\d|20[0-2]\d)\b", t, re.I)
         or re.match(r"^\W{0,3}(1[89]\d\d|20[0-2]\d)\s*年(?:生|出生)", t)
         or re.match(r"^.{0,20}?(?:生于|出生于)\s*(1[89]\d\d|20[0-2]\d)", t))
    return int(m.group(1)) if m else None


def _parse_psa(page_text: str, zh_page_text: str | None = None, flip_commas=False) -> list[dict]:
    """page_text = JSON from the X-Language: en request (required).
    zh_page_text = same URL with X-Language: zh-Hans (optional). With both,
    name = Chinese display name, name_en = English; joined on 'slug'."""
    en = json.loads(page_text)
    zh_by_slug = {}
    if zh_page_text:
        for a in json.loads(zh_page_text).get("artists") or []:
            zh_by_slug[a.get("slug")] = a
    out = []
    for a in en.get("artists") or []:
        en_name = _clean(a.get("name"))
        if flip_commas and en_name.count(",") == 1:
            en_name = flip_surname_first(en_name)
        bio = (a.get("bio") or {}).get("body")
        z = zh_by_slug.get(a.get("slug"))
        zh_name = _clean(z.get("name")) if z else None
        by = _psa_birth_year(bio, en_name) or (_psa_birth_year((z.get("bio") or {}).get("body"), en_name) if z else None)
        out.append(_rec(zh_name or en_name, name_en=en_name, country=a.get("country") or None,
                        birth_year=by, source_ref=a.get("slug")))
    return dedupe(out)


def parse_shanghai_2016(page_text: str, zh_page_text: str | None = None) -> list[dict]:
    return _parse_psa(page_text, zh_page_text)


def parse_shanghai_2018(page_text: str, zh_page_text: str | None = None) -> list[dict]:
    return _parse_psa(page_text, zh_page_text)


def parse_shanghai_2020(page_text: str, zh_page_text: str | None = None) -> list[dict]:
    return _parse_psa(page_text, zh_page_text)


def parse_shanghai_2023(page_text: str, zh_page_text: str | None = None) -> list[dict]:
    return _parse_psa(page_text, zh_page_text)


def parse_shanghai_2025(page_text: str, zh_page_text: str | None = None) -> list[dict]:
    # 15th edition lists many English names as 'Surname, Given' ('Yang, Haegue')
    return _parse_psa(page_text, zh_page_text, flip_commas=True)


# --------------------------------------------------------------------------- #
# Sharjah Biennial  (www.sharjahart.org/en/sharjah-biennial/sb-NN/people/)
# robots.txt disallows /AJAX/, /search/ … ; /people/ pages are allowed.
# --------------------------------------------------------------------------- #
SHARJAH_MAIN_SECTIONS = {
    # edition_id: predicate(h2 text) -> True if the section is main exhibition
    "sharjah_2017": lambda h: "participating artists" in h.lower(),          # Act I + Act II
    "sharjah_2019": lambda h: "will include works by" in h.lower(),           # 3 curated exhibitions
    "sharjah_2023": lambda h: h.strip().lower() == "artists",
    "sharjah_2025": lambda h: h.strip().lower() == "sb16 artists",            # excludes 'April Acts Participants'
}


def _fix_sharjah_name(n: str) -> str:
    # 'Havini,Taloi Havini' -> 'Taloi Havini' (CMS glitch: 'Surname,Given Surname')
    m = re.match(r"^([^,\s][^,]*),(\S.*\b\1)$", n)
    return m.group(2) if m else n


def _parse_sharjah(page_text: str, keep: Callable[[str], bool]) -> list[dict]:
    s = _soup(page_text)
    out, cur = [], None
    for el in s.find_all(["h2", "a"]):
        if el.name == "h2":
            cur = _clean(el.get_text(" "))
            continue
        href = el.get("href") or ""
        if cur and "text-link" in (el.get("class") or []) and "/people/details/" in href and keep(cur):
            name = _fix_sharjah_name(_clean(el.get_text(" ")))
            # SB14: 'Journey Beyond the Arrow, curated by Zoe Butt, will include works by:'
            sec = cur.split(", curated by")[0] if ", curated by" in cur else cur
            out.append(_rec(name, section=sec, source_ref=href))
    return dedupe(out)


def parse_sharjah_2017(page_text: str) -> list[dict]:
    return _parse_sharjah(page_text, SHARJAH_MAIN_SECTIONS["sharjah_2017"])


def parse_sharjah_2019(page_text: str) -> list[dict]:
    return _parse_sharjah(page_text, SHARJAH_MAIN_SECTIONS["sharjah_2019"])


def parse_sharjah_2023(page_text: str) -> list[dict]:
    return _parse_sharjah(page_text, SHARJAH_MAIN_SECTIONS["sharjah_2023"])


def parse_sharjah_2025(page_text: str) -> list[dict]:
    return _parse_sharjah(page_text, SHARJAH_MAIN_SECTIONS["sharjah_2025"])


# --------------------------------------------------------------------------- #
# Manifesta
# --------------------------------------------------------------------------- #
def parse_manifesta_org_archive(page_text: str) -> list[dict]:
    """manifesta.org/editions/<slug>/participants (Nuxt SSR). Items are
    'Name, CC' or 'Name, CC/CC'. Used as enrichment (country) and cross-check;
    NOTE: this archive lists only a subset for some editions (M11: the 29
    Joint-Venture commissions only) and codes are as published (e.g. Lee Bul
    is tagged 'KP' for M14, which is wrong)."""
    s = _soup(page_text)
    out = []
    for a in s.select('a[href*="/participants/"]'):
        t = _clean(a.get_text(" "))
        if not t:
            continue
        m = re.match(r"^(.*),\s*((?:[A-Z]{2,3})(?:\s*/\s*[A-Z]{2,3})*)$", t)
        name, cc = (m.group(1), m.group(2).replace(" ", "")) if m else (t, None)
        out.append(_rec(name, country=cc, source_ref="https://manifesta.org" + a["href"]))
    return dedupe(out)


def _enrich_country(records: list[dict], archive_records: list[dict]) -> list[dict]:
    idx = {}
    for r in archive_records:
        idx[_key(r["name"])] = r
    for r in records:
        hit = idx.get(_key(r.get("name_en") or r["name"])) or idx.get(_key(r["name"]))
        if hit and not r.get("country"):
            r["country"] = hit.get("country")
    return records


def parse_manifesta_2016(page_text: str, archive_page_text: str | None = None) -> list[dict]:
    """M11 Zurich: m11.manifesta.org/en/art-artists/new-works.html, pane
    'All Manifesta 11 Artists' (div.pane-all-artists-list .views-field-title a).
    Covers Joint Ventures (new commissions) + The Historical Exhibition. Names
    are 'Surname, Given' -> name keeps the source string, name_en is flipped.
    Optional archive_page_text = manifesta.org M11 participants (adds country
    codes for the 29 Joint-Venture artists)."""
    s = _soup(page_text)
    pane = s.select_one("div.pane-all-artists-list") or s
    out = []
    for a in pane.select(".views-field-title a"):
        raw = _clean(a.get_text(" "))
        if not raw:
            continue
        href = a.get("href") or ""
        ref = "https://m11.manifesta.org/en/" + href.replace("../", "") if href.startswith("../") else href
        out.append(_rec(raw, name_en=flip_surname_first(raw), source_ref=ref))
    out = dedupe(out)
    if archive_page_text:
        _enrich_country(out, parse_manifesta_org_archive(archive_page_text))
    return out


def parse_manifesta_2018(page_text: str, archive_page_text: str | None = None) -> list[dict]:
    """M12 Palermo: m12.manifesta.org/participants/index.html (static WP mirror),
    article.category-participants h2.entry-title a. (Paginated mirror
    /category/participants/page/N/ holds the same 44.)"""
    s = _soup(page_text)
    arts = s.select("article.category-participants h2.entry-title a") or s.select("article h2.entry-title a")
    out = []
    for a in arts:
        href = a.get("href") or ""
        ref = "https://m12.manifesta.org/" + href.replace("../", "") if href.startswith("../") else href
        out.append(_rec(a.get_text(" "), source_ref=ref))
    out = dedupe(out)
    if archive_page_text:
        _enrich_country(out, parse_manifesta_org_archive(archive_page_text))
    return out


def parse_manifesta_2020(page_text: str, archive_page_text: str | None = None) -> list[dict]:
    """M13 Marseille, central programme 'Traits d'union.s':
    manifesta13.org/participants/index.html — div.filterbox a.filterlink.
    Trailing '*' = newly conceived work for M13 -> new_commission=True.
    The list deliberately includes historical figures shown via archival works
    (e.g. Antonin Artaud, Walter Benjamin)."""
    s = _soup(page_text)
    out = []
    for a in s.select("a.filterlink"):
        t = _clean(a.get_text(" "))
        if not t:
            continue
        star = t.endswith("*")
        name = t.rstrip("*").strip()
        href = a.get("href") or ""
        ref = "https://manifesta13.org/participants/" + href if not href.startswith("http") else href
        out.append(_rec(name, source_ref=ref, new_commission=True if star else None))
    out = dedupe(out)
    if archive_page_text:
        _enrich_country(out, parse_manifesta_org_archive(archive_page_text))
    return out


def parse_manifesta_2022(page_text: str, archive_page_text: str | None = None) -> list[dict]:
    """M14 Prishtina: manifesta14.org/participants/ (WordPress) — every
    participant appears twice (image grid + list); figcaption / link text."""
    s = _soup(page_text)
    out = []
    for a in s.select("div.participants__layout a[href*='/participant/']"):
        cap = a.find("figcaption")
        t = _clean(cap.get_text(" ") if cap else a.get_text(" "))
        if t:
            out.append(_rec(t, source_ref=a["href"]))
    out = dedupe(out)
    if archive_page_text:
        _enrich_country(out, parse_manifesta_org_archive(archive_page_text))
    return out


def parse_manifesta_2024(page_text: str) -> list[dict]:
    """M15 Barcelona Metropolitana: the participants page is Nuxt; its full
    data set is the prerendered static JSON https://manifesta15.org/data/participants-en.json
    (Strapi export: data[].attributes{name, collective_name, year_born,
    place_born.i18n_string_en, slug}). The HTML page only shows 24/92."""
    d = json.loads(page_text)
    out = []
    for it in d.get("data") or []:
        at = it.get("attributes") or {}
        name = at.get("name") or at.get("title")
        pb = (at.get("place_born") or {}).get("i18n_string_en") if isinstance(at.get("place_born"), dict) else None
        coll = at.get("collective_name")
        out.append(_rec(name, country=(pb or "").replace(" ", "") or None, birth_year=at.get("year_born"),
                        source_ref=f"https://manifesta15.org/participants/{at.get('slug')}" if at.get("slug") else None,
                        death_year=at.get("year_of_death"), collective=True if coll else None))
    return dedupe(out)


# --------------------------------------------------------------------------- #
# Sources registry
# --------------------------------------------------------------------------- #
def _lyon_pages(base: str, cat: str, n: int) -> list[str]:
    return [f"{base}?categories%5B0%5D={cat}&_locale=fr&page={p}" for p in range(1, n + 1)]


EDITION_SOURCES: dict[str, dict] = {
    # ---- Berlin -------------------------------------------------------------
    "berlin_2016": {"urls": [f"{BB_BASE}/en/biennalen/1335/the-present-in-drag"],
                    "parser": "parse_berlin_2016", "fetch": "html"},
    "berlin_2018": {"urls": [f"{BB_BASE}/en/biennalen/1339/we-don-t-need-another-hero"],
                    "parser": "parse_berlin_2018", "fetch": "html"},
    "berlin_2020": {"urls": [f"{BB_BASE}/en/biennalen/2509/the-crack-begins-within"],
                    "parser": "parse_berlin_2020", "fetch": "html"},
    "berlin_2022": {"urls": [f"{BB_BASE}/en/biennalen/2931/still-present"],
                    "parser": "parse_berlin_2022", "fetch": "html"},
    "berlin_2025": {"urls": [f"{BB_BASE}/en/biennalen/3389/13th-berlin-biennale-for-contemporary-art"],
                    "parser": "parse_berlin_2025", "fetch": "html",
                    "alt_urls": ["https://13.berlinbiennale.de/en/artists/list"]},
    # ---- Lyon (paginated, 15 per page; page count = max 'page=' link on page 1)
    "lyon_2017": {"urls": _lyon_pages(f"{LYON_BASE}/archives-generale/art-contemporain-2017/artistes-5f198d0bd4b3b",
                                      "expo-internationale", 6),
                  "parser": "parse_lyon_2017", "fetch": "html", "paginated": True},
    "lyon_2019": {"urls": _lyon_pages(f"{LYON_BASE}/archives-generale/art-2019/artistes-2019",
                                      "expo-internationale", 4),
                  "parser": "parse_lyon_2019", "fetch": "html", "paginated": True},
    "lyon_2022": {"urls": [f"{LYON_BASE}/archives-generale/art-contemporain-2022/liste-artistes-2022"],
                  "parser": "parse_lyon_2022", "fetch": "html"},
    "lyon_2024": {"urls": _lyon_pages(f"{LYON_BASE}/archives-generale/art-contemporain-2024/les-artistes-2024",
                                      "les-voix-des-fleuves-crossing-the-water", 6),
                  "parser": "parse_lyon_2024", "fetch": "html", "paginated": True},
    # ---- Shanghai (same URL twice with different X-Language header) -----------
    **{
        eid: {"urls": [f"{PSA_API}/whats-on/programs/{prog}/{page}"],
              "requests": [{"url": f"{PSA_API}/whats-on/programs/{prog}/{page}", "headers": {"X-Language": "en"}},
                           {"url": f"{PSA_API}/whats-on/programs/{prog}/{page}", "headers": {"X-Language": "zh-Hans"},
                            "role": "zh_page_text"}],
              "parser": f"parse_{eid}", "fetch": "json",
              "human_url": f"https://www.powerstationofart.com/whats-on/programs/{prog}/{page}"}
        for eid, prog, page in [
            ("shanghai_2016", "shanghai-biennale-2016", "artist-and-artwork"),
            ("shanghai_2018", "shanghai-biennale-2018", "artists-and-artworks"),
            ("shanghai_2020", "shanghai-biennale-2020", "artist-and-artwork"),
            ("shanghai_2023", "shanghai-biennale-2023", "artists-and-artwork"),
            # 15th is still the 'current' program; when PSA archives it the slug
            # will likely become 'shanghai-biennale-2025' (check /previous-shb).
            ("shanghai_2025", "shanghai-biennale", "artists-and-works"),
        ]
    },
    # ---- Sharjah --------------------------------------------------------------
    **{
        eid: {"urls": [f"https://www.sharjahart.org/en/sharjah-biennial/{sb}/people/"],
              "parser": f"parse_{eid}", "fetch": "html"}
        for eid, sb in [("sharjah_2017", "sb-13"), ("sharjah_2019", "sb-14"),
                        ("sharjah_2023", "sb-15"), ("sharjah_2025", "sb-16")]
    },
    # ---- Manifesta ------------------------------------------------------------
    "manifesta_2016": {"urls": ["https://m11.manifesta.org/en/art-artists/new-works.html"],
                       "parser": "parse_manifesta_2016", "fetch": "html", "crawl_delay": 10,
                       "enrich_url": "https://manifesta.org/editions/manifesta-11-zurich/participants"},
    "manifesta_2018": {"urls": ["https://m12.manifesta.org/participants/index.html"],
                       "parser": "parse_manifesta_2018", "fetch": "html",
                       "alt_urls": [f"https://m12.manifesta.org/category/participants/page/{p}/index.html" for p in range(2, 6)],
                       "enrich_url": "https://manifesta.org/editions/manifesta-12-palermo/participants"},
    "manifesta_2020": {"urls": ["https://manifesta13.org/participants/index.html"],
                       "parser": "parse_manifesta_2020", "fetch": "html",
                       "enrich_url": "https://manifesta.org/editions/manifesta-13-marseille/participants"},
    "manifesta_2022": {"urls": ["https://manifesta14.org/participants/"],
                       "parser": "parse_manifesta_2022", "fetch": "html",
                       "enrich_url": "https://manifesta.org/editions/manifesta-prishtina/participants"},
    "manifesta_2024": {"urls": ["https://manifesta15.org/data/participants-en.json"],
                       "parser": "parse_manifesta_2024", "fetch": "json",
                       "human_url": "https://manifesta15.org/participants"},
}


def parse_edition(edition_id: str, pages: list[str], extra: dict | None = None) -> list[dict]:
    """pages = raw texts in EDITION_SOURCES[edition_id]['urls'] order (for
    Shanghai: [en_json, zh_json]). extra may carry {'archive_page_text': …} for
    Manifesta country enrichment."""
    fn = globals()[EDITION_SOURCES[edition_id]["parser"]]
    extra = extra or {}
    if edition_id.startswith("shanghai_"):
        return fn(pages[0], pages[1] if len(pages) > 1 else None)
    if edition_id.startswith("manifesta_") and edition_id != "manifesta_2024":
        return fn(pages[0], extra.get("archive_page_text"))
    recs: list[dict] = []
    for p in pages:
        recs.extend(fn(p))
    return dedupe(recs)


# --------------------------------------------------------------------------- #
# v2 어댑터 — load.py의 edition_parser 계약: (회차 원본 텍스트들, 소스 순서) -> list[dict]
# Shanghai: [en_json, zh_json] / Manifesta(2016-2022): [본 명단, manifesta.org 아카이브(국가 보강)]
# --------------------------------------------------------------------------- #
def parse_pages(pages: list[str], edition_id: str) -> list[dict]:
    extra = {}
    if edition_id.startswith("manifesta_") and edition_id != "manifesta_2024" and len(pages) > 1:
        extra["archive_page_text"] = pages[1]
        pages = pages[:1]
    return parse_edition(edition_id, pages, extra)
