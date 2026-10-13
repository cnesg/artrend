"""
parsers_kiaf.py -- self-contained parsers for Kiaf SEOUL (Korea International Art Fair) 2016-2026.

Every parser takes the raw fetched body and returns list[dict]. HTML/JSON parsers take `page_text: str`;
PDF parsers take the raw PDF bytes (or a str path to a local file) because PDFs are binary.
Booth dicts follow the shape:
    {"gallery", "gallery_ko", "gallery_en", "gallery_city", "booth", "section", "artists": [{"name","name_ko","name_en"}]}
plus optional provenance keys ("sector", "kiaf_code", "artist_source", ...).

Dependencies: bs4 + lxml for HTML; pymupdf (fitz) for PDFs. No network access here (the crawler fetches).

URL discovery notes (see EDITION_SOURCES at the bottom for the concrete URLs used per edition):
  * kiaf.org/kapi/page?f=past-exhibitors&y=<YYYY>&k=      -> JSON gallery list for any year 2002-2026 (no artists)
  * kiaf.org/kapi/eindex?mode=exhibitor3&y=coex&cached=true&keyword=  -> JSON current-edition list (KO+EN names)
  * kiaf.org/wp-json/wp/v2/artwork-item?per_page=100&page=N&_fields=...  -> 2022 OVR artworks (artist per gallery);
        paginate 1..X-WP-TotalPages (35 pages / 3,407 items as of 2026-10-12)
  * kiaf.org/wp-json/wp/v2/highlight?per_page=100      -> Kiaf HIGHLIGHTS artists 2024-2026 (acf.gallery = KO name)
  * kiaf.org/wp-json/wp/v2/exhibition_list?per_page=100 -> special-exhibition artists 2024-2026 (category = year / AR)
  * kiaf.org/archive-special-exhibitions (listing, years) -> detail pages with "Director"/"Artists" fields
  * static-edge.kiaf.org/.../Kiaf-SEOUL-2024_Online-Catalog.pdf, ...2025_Online-Catalog.pdf -> per-booth artists
  * floor-plan PDFs on static-edge.kiaf.org -> booth codes (2022 SEOUL, 2022 PLUS, 2026)
  * Wayback (id_ raw snapshots) of kiaf.org/<year>/.../exhibitors pages for 2016-2019 -> gallery, city (+booth 2018-19)
Endpoints deliberately NOT used: wp-json gallery_info (gallery accounts / e-mails), the media library listing
(it links gallery business-registration PDFs), the Google Drive 2026 catalogue (robots-disallowed download).
"""
from __future__ import annotations

import html as _html
import json
import re
import unicodedata
from urllib.parse import unquote

from bs4 import BeautifulSoup

# ----------------------------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------------------------
HANGUL_RE = re.compile(r"[가-힣ㄱ-ㆎᄀ-ᇿ]")
LATIN_RE = re.compile(r"[A-Za-zÀ-ɏ]")
BOOTH_RE = re.compile(r"^\(?([A-Z]{1,3}\d{1,3}[A-Z]?)\)?$")
WS_RE = re.compile(r"[\s   　]+")
NAME_NOISE = {"", "etc", "etc.", "외", "등", "and more", "others", "외 다수", "외다수", "-", "–"}


def norm_ws(s: str | None) -> str:
    # NFC first: some CMS strings are stored as decomposed Hangul jamo (NFD), which breaks matching
    return WS_RE.sub(" ", unicodedata.normalize("NFC", s or "")).strip()


def split_person(raw: str) -> dict:
    """'Gina Sohn 지나손' -> {'name': 'Gina Sohn 지나손', 'name_ko': '지나손', 'name_en': 'Gina Sohn'}"""
    name = norm_ws(raw).strip(" ,;/")
    # drop birth-place/year parentheticals '(°Daegu, 1957)'; unwrap bilingual ones 'Youngjoo Kim (김영주)'
    name = re.sub(r"\s*\([^)]*\d{4}[^)]*\)", "", name)
    name = norm_ws(re.sub(r"\(([^)]*)\)", lambda m: " " + m.group(1) + " " if HANGUL_RE.search(m.group(1)) or
                          (HANGUL_RE.search(name.split("(")[0]) and LATIN_RE.search(m.group(1))) else m.group(0), name))
    toks = name.split(" ")
    ko = [t for t in toks if HANGUL_RE.search(t)]
    en = [t for t in toks if not HANGUL_RE.search(t) and LATIN_RE.search(t)]
    if en:  # keep connective tokens like '&' inside the latin part
        first = toks.index(en[0]); last = max(i for i, t in enumerate(toks) if t in en)
        en_str = " ".join(t for t in toks[first:last + 1] if not HANGUL_RE.search(t))
    else:
        en_str = None
    return {"name": name, "name_ko": " ".join(ko) if ko else None, "name_en": en_str}


def split_names_list(text: str, seps=r"\s*/\s*") -> list[dict]:
    out, seen = [], set()
    for part in re.split(seps, norm_ws(text)):
        p = part.strip(" ,;")
        if p.lower() in NAME_NOISE or len(p) < 2:
            continue
        d = split_person(p)
        k = d["name"].lower()
        if k not in seen:
            seen.add(k); out.append(d)
    return out


def name_key(s: str | None) -> str:
    """aggressive normalisation for matching gallery names across sources (generic words removed)"""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("&", "and")
    s = re.sub(r"\b(the|gallery|galerie|galeria|galleria|art|arts|space|artspace|fine|contemporary|seoul)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def exact_key(s: str | None) -> str:
    """case/punctuation/diacritics-insensitive key"""
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


def slugify_wp(s: str) -> str:
    """approximation of WordPress sanitize_title for latin names"""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    return re.sub(r"[\s-]+", "-", s).strip("-")


def _booth(gallery, *, ko=None, en=None, city=None, booth=None, section="main", artists=None, **extra) -> dict:
    d = {"gallery": norm_ws(gallery), "gallery_ko": norm_ws(ko) or None, "gallery_en": norm_ws(en) or None,
         "gallery_city": norm_ws(city) or None, "booth": booth or None, "section": section,
         "artists": artists or []}
    d.update({k: v for k, v in extra.items() if v is not None})
    return d


def _open_pdf(pdf):
    import pymupdf as fitz  # PyMuPDF
    if isinstance(pdf, (bytes, bytearray)):
        return fitz.open(stream=bytes(pdf), filetype="pdf")
    return fitz.open(pdf)


def _pdf_lines(page):
    """[(x0, y0, x1, y1, size, font, text)] for every non-empty text line of a PyMuPDF page"""
    out = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for l in b["lines"]:
            txt = "".join(s["text"] for s in l["spans"])
            if not txt.strip():
                continue
            s0 = l["spans"][0]
            x0, y0, x1, y1 = l["bbox"]
            out.append((x0, y0, x1, y1, round(s0["size"], 1), s0["font"], txt))
    return out


# ----------------------------------------------------------------------------------------------------------
# 1. kiaf.org/kapi/page?f=past-exhibitors&y=YYYY  (JSON, all years 2002-2026; galleries only)
# ----------------------------------------------------------------------------------------------------------
KAPI_CODE_NOTE = ("raw per-year code from kiaf.org past-exhibitors DB: letters A-G/S appear to be hall/booth "
                  "zones, 'HLT' = Highlight sector, 'SOLO' = Solo Project, 'OVR' = online-only (2020), "
                  "'O' = participated (2024+), '철회' = withdrawn")


def parse_kapi_past_exhibitors(page_text: str, year: int | str | None = None, keep_withdrawn: bool = False) -> list[dict]:
    data = json.loads(page_text)
    items = data.get("data", data) if isinstance(data, dict) else data
    out = []
    for it in items:
        code = it.get(f"year_{year}") if year else None
        if year and not code:
            continue
        if code == "철회" and not keep_withdrawn:  # withdrawn before the fair
            continue
        out.append(_booth(it["gallery_name"], en=it["gallery_name"], city=it.get("city"),
                          kiaf_code=code, country=it.get("country")))
    return out


# ----------------------------------------------------------------------------------------------------------
# 2. kiaf.org/kapi/eindex?mode=exhibitor3&y=coex&cached=true&keyword=   (JSON, current edition only)
# ----------------------------------------------------------------------------------------------------------
def parse_kapi_eindex(page_text: str) -> list[dict]:
    data = json.loads(page_text)
    if isinstance(data, str):
        data = json.loads(data)
    out = []
    for it in data:
        if (it.get("gallery_name") or "").strip().upper() == "GALLERY KIAF":  # placeholder hidden by the site
            continue
        en = _html.unescape(it.get("gallery_name") or "")
        ko = _html.unescape(BeautifulSoup(it.get("gallery_name_han") or "", "lxml").get_text(" "))
        out.append(_booth(en or ko, ko=ko, en=en, city=it.get("city"), city_ko=it.get("city_han") or None))
    return out


# ----------------------------------------------------------------------------------------------------------
# 3. Wayback snapshots of kiaf.org/<2016..2019>/.../exhibitors  (server-rendered WP tables)
#    rows: <td class="gtitle"><a>NAME</a></td> [<td class="gsub01">BOOTH</td>] <td class="gsub02">CITY</td>
#    The page repeats rows inside tabs (All / Domestic / Overseas or All / General / Highlight / Solo Project);
#    the 2016 'Domestic' tab writes "EN NAME 한글명 / City" into one cell (source of Korean names).
# ----------------------------------------------------------------------------------------------------------
def parse_wb_exhibitors_table(page_text: str) -> list[dict]:
    soup = BeautifulSoup(page_text, "lxml")
    tab_title = {}
    for a in soup.select("a[href^='#']"):
        t = a.get_text(" ", strip=True)
        if t:
            tab_title[a["href"][1:]] = t
    rows, order = {}, []
    for td in soup.select("td.gtitle"):
        a = td.find("a")
        name = norm_ws(td.get_text(" ", strip=True))
        if not name or (not a and len(name) <= 3):        # alphabet headers '1-9', 'A', ...
            continue
        if name.lower() in ("booth", "city"):
            continue
        tr = td.find_parent("tr")
        booth = tr.select_one("td.gsub01")
        city = tr.select_one("td.gsub02")
        booth = norm_ws(booth.get_text(" ", strip=True)) if booth else None
        city = norm_ws(city.get_text(" ", strip=True)) if city else None
        if booth and not BOOTH_RE.match(booth):          # some tabs put the city in the 'gsub01' cell
            city, booth = city or booth, None
        ko = None
        if not city and " / " in name:                    # 2016 'Domestic' tab: "EN NAME 한글명 / City"
            name, city = [x.strip() for x in name.rsplit(" / ", 1)]
        if HANGUL_RE.search(name):
            toks = name.split(" ")
            first_ko = next(i for i, t in enumerate(toks) if HANGUL_RE.search(t))
            if first_ko > 0:
                name, ko = " ".join(toks[:first_ko]), " ".join(toks[first_ko:])
        pane = td.find_parent(id=True)
        tab = None
        while pane is not None and tab is None:
            tab = tab_title.get(pane.get("id"))
            pane = pane.find_parent(id=True)
        key = name.upper()
        if key not in rows:
            rows[key] = {"name": name, "booth": booth, "city": city, "ko": ko, "tabs": set()}
            order.append(key)
        else:
            rows[key]["booth"] = rows[key]["booth"] or booth
            rows[key]["city"] = rows[key]["city"] or city
            rows[key]["ko"] = rows[key]["ko"] or ko
        if tab:
            rows[key]["tabs"].add(tab)
    out = []
    for k in order:
        r = rows[k]
        sector = None
        for t in ("Highlight", "Solo Project"):
            if t in r["tabs"]:
                sector = t
        if not sector and r["booth"]:
            sector = "Highlight" if r["booth"].startswith("HLT") else ("Solo Project" if re.match(r"^S\d", r["booth"]) else None)
        out.append(_booth(r["name"], ko=r["ko"], en=r["name"], city=r["city"], booth=r["booth"], sector=sector))
    return out


# ----------------------------------------------------------------------------------------------------------
# 4. Official online catalogue PDF (2024, 2025 layouts) -> galleries (EN/KO/city/booth) + per-booth artists
#    Sources inside the PDF:
#      a) "Galleries Index" table  (Gallery | Booth | Page)
#      b) gallery pages: field "Artists" (2024: value to the right of the label; 2025: value below the label)
#      c) "Artist(s) Index" table  (Artist | Gallery | Booth | Page)
#    a) gives the gallery list; b) and c) are merged per booth (union, dedup by normalised EN/KO name).
# ----------------------------------------------------------------------------------------------------------
def _table_rows(lines, header_word, booth_word="Booth"):
    """Generic multi-up table reader keyed on the Booth column.
    returns list of dicts {booth, cells:[line...], y}"""
    heads = [l for l in lines if norm_ws(l[6]) == header_word]
    booths_h = [l for l in lines if norm_ws(l[6]).split(" ")[0] == booth_word]  # "Booth" or merged "Booth Page"
    rows = []
    for h in heads:
        cand = [b for b in booths_h if abs(b[1] - h[1]) < 2 and b[0] > h[0]]
        if not cand:
            continue
        bh = min(cand, key=lambda b: b[0] - h[0])
        # right edge of the first column = next column header on the same baseline (e.g. 'Gallery' after 'Artist')
        nxt = [l for l in lines if abs(l[1] - h[1]) < 2 and h[0] + 5 < l[0] <= bh[0] and l[4] < 10]
        col_l, col_r = h[0] - 2, (min(l[0] for l in nxt) - 2 if nxt else bh[0] - 2)
        hy = h[1]
        bcells = sorted([l for l in lines if abs(l[0] - bh[0]) < 3 and l[1] > hy + 3
                         and BOOTH_RE.match(norm_ws(l[6]))], key=lambda l: l[1])
        if not bcells:
            continue
        # Fast path: one first-column line per booth cell -> rows correspond 1:1 in reading order. Cells are
        # vertically centred, so a wrapped neighbour cell can shift a line by ~3-4pt; ordering is robust to that.
        col_lines = sorted([l for l in lines if col_l <= l[0] < col_r and l[1] > hy + 3 and l[4] < 10],
                           key=lambda l: (l[1], l[0]))
        if len(col_lines) == len(bcells):
            for b, c in zip(bcells, col_lines):
                rows.append({"booth": BOOTH_RE.match(norm_ws(b[6])).group(1), "cells": [c], "y": b[1]})
            continue
        ys = [b[1] for b in bcells]
        for i, b in enumerate(bcells):
            lo = (ys[i - 1] + ys[i]) / 2 if i else ys[i] - 6
            hi = (ys[i] + ys[i + 1]) / 2 if i + 1 < len(ys) else ys[i] + 9
            cell = [l for l in lines if col_l <= l[0] < col_r and lo <= l[1] < hi and l[4] < 10]
            cell.sort(key=lambda l: (round(l[1]), l[0]))
            rows.append({"booth": BOOTH_RE.match(norm_ws(b[6])).group(1), "cells": cell, "y": b[1]})
    return rows


def _split_gallery_cell(cell_lines):
    names = [l for l in cell_lines if l[4] >= 5.5]
    cities = [l for l in cell_lines if l[4] < 5.5]
    txt = "  ".join(l[6] for l in names)
    parts = [p.strip() for p in re.split(r"[  ]+", txt) if p.strip()]
    en = next((p for p in parts if not HANGUL_RE.search(p)), None)
    ko = " ".join(p for p in parts if HANGUL_RE.search(p)) or None
    rest = [p for p in parts if p is not en and not HANGUL_RE.search(p)]
    city = norm_ws(" ".join(l[6] for l in cities)) or (rest[-1] if rest else None)
    return norm_ws(en), norm_ws(ko) or None, city


def _gallery_page_artists(page):
    """Artists field(s) on one catalogue spread -> [(printed_booth, header_en, header_ko, [names...])]
    The gallery header (big EN name, KO name) on the same half of the spread is returned too, because the
    printed booth code on a gallery page can be wrong (2025: Wooson Gallery page prints A57, index says B04)."""
    lines = _pdf_lines(page)
    W = page.rect.width
    labels = [l for l in lines if norm_ws(l[6]) == "Artists" and l[4] <= 9]
    booths = [l for l in lines if l[4] >= 18 and l[1] < 150 and BOOTH_RE.match(norm_ws(l[6]))]
    stop = {"Director", "Established", "Address", "Contact", "Artists", "Website", "Booth"}
    found = []
    for lab in labels:
        side = lab[0] >= W / 2
        same_size = lambda l, lab=lab: abs(l[4] - lab[4]) <= 0.25        # value text uses the label's font size
        vals = []
        right = [l for l in lines if abs(l[1] - lab[1]) < 2.5 and lab[2] + 2 < l[0] < lab[0] + 300 and same_size(l)]
        if right:  # 2024 layout: value starts on the label baseline, to the right
            cur = min(right, key=lambda r: r[0]); x = cur[0]
        else:      # 2025 layout: value lines below the label, same x
            below = [l for l in lines if abs(l[0] - lab[0]) < 2.5 and 3 < l[1] - lab[1] < 15 and same_size(l)]
            if not below:
                found.append((side, lab, [])); continue
            cur = min(below, key=lambda l: l[1]); x = cur[0]
        vals.append(cur)
        while True:
            nxt = [l for l in lines if abs(l[0] - x) < 2.5 and 3 < l[1] - cur[1] < 14 and same_size(l)]
            if not nxt:
                break
            cur = min(nxt, key=lambda l: l[1])
            if norm_ws(cur[6]) in stop:
                break
            vals.append(cur)
        found.append((side, lab, vals))
    res = []
    for side, lab, vals in found:
        same = [b for b in booths if (b[0] >= W / 2) == side]
        booth = None
        if len(same) == 1:
            booth = BOOTH_RE.match(norm_ws(same[0][6])).group(1)
        elif len(booths) == 1 and len(found) == 1:
            booth = BOOTH_RE.match(norm_ws(booths[0][6])).group(1)
        head = [l for l in lines if l[4] >= 22 and l[1] < 100 and (l[0] >= W / 2) == side
                and not BOOTH_RE.match(norm_ws(l[6]))]
        head.sort(key=lambda l: (round(l[1]), l[0]))
        en_parts = []
        for l in head:
            t = norm_ws(l[6])
            if t and (not en_parts or en_parts[-1] != t):
                en_parts.append(t)
        ko = [norm_ws(l[6]) for l in lines if 12 <= l[4] < 18 and l[1] < 100 and (l[0] >= W / 2) == side
              and HANGUL_RE.search(l[6])]
        txt = " ".join(norm_ws(v[6]) for v in vals)
        res.append((booth, " ".join(en_parts) or None, ko[0] if ko else None, split_names_list(txt)))
    return res


def parse_catalog_pdf(pdf) -> list[dict]:
    doc = _open_pdf(pdf)
    galleries, art_index, page_art, page_hits = {}, {}, {}, []
    for page in doc:
        lines = _pdf_lines(page)
        text = " ".join(l[6] for l in lines[:12])
        if "Galleries Index" in text and ("Alphabet" in text or "Alphabet" in page.get_text()):
            for r in _table_rows(lines, "Gallery"):
                en, ko, city = _split_gallery_cell(r["cells"])
                if en or ko:
                    galleries.setdefault(r["booth"], (en, ko, city))
        elif re.search(r"Artists? Index", text) and any(norm_ws(l[6]) == "Artist" for l in lines):
            for r in _table_rows(lines, "Artist"):
                nm = " ".join(norm_ws(l[6].split("\t")[0]) for l in r["cells"]).strip()
                if len(nm) >= 2:
                    art_index.setdefault(r["booth"], []).append(split_person(nm))
        else:
            for booth, h_en, h_ko, names in _gallery_page_artists(page):
                page_hits.append((booth, h_en, h_ko, names))
    # attach gallery-page artist lists to booths: header name match first, printed booth code as fallback
    by_exact, by_ko, loose = {}, {}, {}
    for b, v in galleries.items():
        if v[0]:
            by_exact.setdefault(exact_key(v[0]), []).append(b)
            loose.setdefault(name_key(v[0]), []).append(b)
        if v[1]:
            by_ko.setdefault(re.sub(r"\s", "", v[1]), []).append(b)

    def _pick(cands, printed):
        if not cands:
            return None
        return printed if printed in cands else cands[0]

    for booth, h_en, h_ko, names in page_hits:
        b = _pick(by_exact.get(exact_key(h_en)), booth) if h_en else None
        b = b or (_pick(by_ko.get(re.sub(r"\s", "", h_ko)), booth) if h_ko else None)
        if not b and h_en and len(loose.get(name_key(h_en), [])) == 1:
            b = loose[name_key(h_en)][0]
        if not b and booth and booth not in galleries and h_en:   # gallery missing from the index table
            galleries[booth] = (h_en, h_ko, None)
        b = b or booth
        if b:
            page_art.setdefault(b, []).extend(names)
    # strip gallery names glued onto artist-index lines (cells share one PDF line in a few rows)
    for b, lst in art_index.items():
        en, ko, _ = galleries.get(b, (None, None, None))
        for a in lst:
            nm = a["name"]
            for g in (en, ko):
                if g and nm.endswith(g) and len(nm) > len(g) + 2:
                    nm = nm[: -len(g)].strip()
            if en and ko and en in nm:
                nm = nm.split(en)[0].strip()
            if nm != a["name"]:
                a.update(split_person(nm))
    out = []
    for booth, (en, ko, city) in galleries.items():
        merged, seen, src = [], set(), set()
        for origin, lst in (("gallery_page", page_art.get(booth, [])), ("artist_index", art_index.get(booth, []))):
            for a in lst:
                if len(re.sub(r"\W", "", a["name"])) < 2:
                    continue
                keys = {re.sub(r"\W", "", (a["name_en"] or a["name"]).lower()) or a["name"]}
                if a["name_ko"]:
                    keys.add("ko:" + re.sub(r"\s", "", a["name_ko"]))
                if keys & seen:
                    continue
                seen |= keys; merged.append(a); src.add(origin)
        out.append(_booth(en or ko, ko=ko, en=en, city=city, booth=booth, artists=merged,
                          artist_source="+".join(sorted(src)) or None,
                          n_artists_gallery_page=len(page_art.get(booth, [])),
                          n_artists_index=len(art_index.get(booth, []))))
    for booth in sorted((set(page_art) | set(art_index)) - set(galleries)):   # should be none
        out.append(_booth(f"[unmatched booth {booth}]", booth=booth,
                          artists=page_art.get(booth, []) or art_index.get(booth, []), unmatched=True))
    return out


def parse_catalog_contents_sections(pdf) -> list[dict]:
    """Catalogue 'Contents' page lists HIGHLIGHTS and Special Exhibition artists as an EN block followed by a
    KO block in the same order ('HIGHLIGHTS' ... '하이라이트' ... ; 'Special Exhibition' ... '특별전' ...)."""
    doc = _open_pdf(pdf)
    out = []
    for page in list(doc)[:8]:
        lines = [norm_ws(x) for x in page.get_text().splitlines()]
        if "HIGHLIGHTS" not in lines or "하이라이트" not in lines:
            continue
        for en_head, ko_head, label in (("HIGHLIGHTS", "하이라이트", "Kiaf HIGHLIGHTS"),
                                        ("Special Exhibition", "특별전", "Special Exhibition")):
            if en_head not in lines:
                continue
            i = lines.index(en_head)
            try:
                j = lines.index(ko_head, i + 1)
            except ValueError:
                continue
            en = [x for x in lines[i + 1:j] if x]
            ko = [x for x in lines[j + 1:j + 1 + len(en)] if x]
            if len(en) != len(ko) or not en:
                continue
            arts = [{"name": f"{e} {k}", "name_ko": k, "name_en": e} for e, k in zip(en, ko)]
            out.append(_booth(label, section=label, artists=arts, artist_source="catalogue contents page"))
        if out:
            break
    return out


# ----------------------------------------------------------------------------------------------------------
# 5. Floor-plan PDF -> [(booth, gallery-name-as-printed)]  (text stream is "BOOTH \n NAME LINES ...")
# ----------------------------------------------------------------------------------------------------------
FLOOR_STOP = {"INFO", "VIP", "EXHIBITOR", "TICKET", "PRESS", "SERVICE", "LOUNGE", "F&B", "SPECIAL", "EXHIBITION",
              "DOCENT", "KB INFO", "MEDIA", "PARTNERS", "PLUS", "SOLO", "HIGHLIGHTS", "GALLERIES", "AR",
              "INFORMATION", "CATALOGUE", "SERVICE POINT", "RESTROOM", "PARTNER", "COAT", "ROOM", "CAR", "PACKAGING"}


def parse_floorplan_pdf(pdf) -> list[dict]:
    doc = _open_pdf(pdf)
    out = []
    for page in doc:
        cur, buf = None, []
        for raw in page.get_text().split("\n"):
            t = norm_ws(raw)
            if not t:
                continue
            m = BOOTH_RE.match(t)
            if m:
                if cur and buf:
                    out.append(_booth(" ".join(buf), en=" ".join(buf), booth=cur))
                cur, buf = m.group(1), []
            elif cur is not None:
                if t.upper() in FLOOR_STOP or t.startswith("█"):
                    if buf:
                        out.append(_booth(" ".join(buf), en=" ".join(buf), booth=cur))
                    cur, buf = None, []
                else:
                    buf.append(t)
        if cur and buf:
            out.append(_booth(" ".join(buf), en=" ".join(buf), booth=cur))
    return out


# ----------------------------------------------------------------------------------------------------------
# 6. kiaf.org/wp-json/wp/v2/artwork-item  (2022 OVR; one item per artwork)
#    gallery identity = slug prefix ("gallery-yeh-draft-18" -> "gallery-yeh"); the gallery OVR post itself
#    (acf.gallery_ovr_id) was deleted from the CMS, so the crawler must map slug -> gallery name (see build script).
#    Items may carry an injected "_src" key (the page URL they came from); it is collected into source_urls.
# ----------------------------------------------------------------------------------------------------------
def parse_wp_artwork_items(page_text: str) -> list[dict]:
    items = json.loads(page_text)
    groups = {}
    for it in items:
        acf = it.get("acf") or {}
        if not isinstance(acf, dict):
            continue
        if acf.get("artwork_item_is_public") is False:
            continue
        slug = unquote(it.get("slug") or "")
        gslug = re.sub(r"-draft(?:-\d+)*$", "", slug)   # '<gallery>-draft', '-draft-18', '-draft-15-2'
        key = (acf.get("gallery_ovr_id"), gslug)
        g = groups.setdefault(key, {"artists": [], "seen": set(), "plus": 0, "n": 0, "src": []})
        g["n"] += 1
        g["plus"] += 1 if acf.get("exhibits_kiaf_plus") else 0
        if it.get("_src") and it["_src"] not in g["src"]:
            g["src"].append(it["_src"])
        nm = norm_ws(_html.unescape(acf.get("artwork_item_artist_name") or ""))
        nm = norm_ws(re.sub(r"^New Artist", "", nm))                 # CMS placeholder prefix
        nm = re.sub(r"(?<=[a-z])Artist$", "", nm)                      # 'SaputroArtist'
        if re.search(r"\d+-\d+", nm):                                 # artwork codes typed into the artist field
            nm = ""
        if nm and nm.lower() not in g["seen"]:
            g["seen"].add(nm.lower()); g["artists"].append(split_person(nm))
    out = []
    for (ovr_id, gslug), g in groups.items():
        out.append(_booth(gslug, section="main", artists=g["artists"], gallery_slug=gslug,
                          ovr_gallery_id=ovr_id, n_artworks=g["n"], n_kiaf_plus_artworks=g["plus"],
                          source_urls=g["src"] or None, artist_source="ovr_artwork_items"))
    return out


# ----------------------------------------------------------------------------------------------------------
# 7. kiaf.org/wp-json/wp/v2/highlight  (Kiaf HIGHLIGHTS; artist-level, gallery given in Korean)
# ----------------------------------------------------------------------------------------------------------
def parse_wp_highlight(page_text: str, cat_year: dict | None = None, year: int | None = None) -> list[dict]:
    """cat_year: {category_id: year}. Posts without a year category are assigned by post date year."""
    out = []
    for it in json.loads(page_text):
        acf = it.get("acf") or {}
        y = None
        for c in it.get("categories") or []:
            if cat_year and c in cat_year:
                y = cat_year[c]
        y = y or int(it["date"][:4])
        if year and y != year:
            continue
        title = norm_ws(_html.unescape(it["title"]["rendered"]).split(" | ")[0])
        gal = norm_ws(acf.get("gallery") if isinstance(acf, dict) else "")
        out.append(_booth(gal or "(gallery not given)", ko=gal if HANGUL_RE.search(gal or "") else None,
                          en=gal if gal and not HANGUL_RE.search(gal) else None,
                          section="Kiaf HIGHLIGHTS", artists=[split_person(title)], year=y,
                          source_post=it.get("id")))
    return out


# ----------------------------------------------------------------------------------------------------------
# 8. kiaf.org/wp-json/wp/v2/exhibition_list  (special-exhibition artists 2024-2026)
# ----------------------------------------------------------------------------------------------------------
def parse_wp_exhibition_list(page_text: str, cat_map: dict | None = None, year: int | None = None,
                             exclude=("이승아",)) -> list[dict]:
    """cat_map: {category_id: (year, section_label)}; posts w/o category use post-date year + default label.
    `exclude` drops non-artist entries (2024: curator 이승아 is listed in the CMS but is the curator)."""
    by_sec = {}
    for it in json.loads(page_text):
        y, lab = None, None
        for c in it.get("categories") or []:
            if cat_map and c in cat_map:
                y, lab = cat_map[c]
        y = y or int(it["date"][:4])
        if year and y != year:
            continue
        nm = norm_ws(_html.unescape(it["title"]["rendered"]))
        if nm in exclude:
            continue
        lab = lab or "Special Exhibition"
        names = [p for p in re.split(r"\s*,\s*", nm) if p]
        by_sec.setdefault((y, lab), []).extend(split_person(n) for n in names)
    return [_booth(lab, section=lab, artists=arts, year=y) for (y, lab), arts in by_sec.items()]


# ----------------------------------------------------------------------------------------------------------
# 9. kiaf.org/archive-special-exhibitions  (listing -> (year, title, url)) and detail pages
# ----------------------------------------------------------------------------------------------------------
def parse_special_exhibition_index(page_text: str) -> list[dict]:
    soup = BeautifulSoup(page_text, "lxml")
    out, year = [], None
    root = soup.find(id="page") or soup
    for el in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "a"]):
        t = norm_ws(el.get_text(" ", strip=True))
        if el.name != "a" and re.fullmatch(r"20\d\d", t) and not el.find(["a"]):
            year = int(t)
        elif el.name == "a" and "/archive-special-exhibitions/" in (el.get("href") or "") and t:
            out.append({"year": year, "title": t, "url": el["href"]})
    seen, res = set(), []
    for o in out:
        if o["url"] not in seen:
            seen.add(o["url"]); res.append(o)
    return res


def parse_special_exhibition_detail(page_text: str) -> list[dict]:
    """returns [ {section: 'Special Exhibition: <title>', artists: [...], director} ] or [] if no artist list"""
    soup = BeautifulSoup(page_text, "lxml")
    for t in soup(["script", "style", "header", "footer", "nav"]):
        t.decompose()
    root = soup.find(id="page") or soup.body
    lines = [norm_ws(x) for x in root.get_text("\n", strip=True).split("\n")]
    lines = [x for x in lines if x]
    title = None
    h = root.find(["h1", "h2", "h3"], string=True)
    if h:
        title = norm_ws(h.get_text(" "))
    director = artists = None
    for i, l in enumerate(lines):
        if l == "Director" and i + 1 < len(lines):
            director = lines[i + 1]
        if l in ("Artists", "Artist", "참여작가", "참여 작가") and i + 1 < len(lines):
            artists = lines[i + 1]
            if not title and i >= 3:
                title = lines[i - 3] if director else lines[i - 1]
            break
    if not artists:
        return []
    names = [p for p in re.split(r"\s*,\s*(?![^()]*\))", artists) if p]   # keep '김준(영상, 설치)' intact
    arts, seen = [], set()
    for n in names:
        d = split_person(n)
        if d["name"] not in seen:
            seen.add(d["name"]); arts.append(d)
    return [_booth(f"Special Exhibition: {title}" if title else "Special Exhibition",
                   section=f"Special Exhibition: {title}" if title else "Special Exhibition",
                   artists=arts, director=director)]


# ----------------------------------------------------------------------------------------------------------
# Sources actually used per edition (fetch = how to get the body; parser = function above)
# ----------------------------------------------------------------------------------------------------------
WB = "https://web.archive.org/web/{ts}id_/{url}"
KAPI_PAST = "https://kiaf.org/kapi/page?f=past-exhibitors&y={y}&k="
ARTWORK_ITEMS = ("https://kiaf.org/wp-json/wp/v2/artwork-item?per_page=100&page={n}&_fields=id,date,slug,title,"
                 "acf.artwork_item_artist_name,acf.gallery_id,acf.gallery_ovr_id,acf.exhibits_kiaf_plus,"
                 "acf.artwork_item_is_public")
HIGHLIGHT_REST = "https://kiaf.org/wp-json/wp/v2/highlight?per_page=100&_fields=id,date,title,slug,acf,categories"
EXHIBITION_REST = "https://kiaf.org/wp-json/wp/v2/exhibition_list?per_page=100&_fields=id,date,title,slug,acf,categories"
SPECIAL_INDEX = "https://kiaf.org/archive-special-exhibitions"

EDITION_SOURCES = {
    "kiaf-2016": {"urls": [WB.format(ts="20161016174852", url="http://kiaf.org:80/2016/en/exhibitors_en/"),
                           KAPI_PAST.format(y=2016), SPECIAL_INDEX],
                  "parser": "parse_wb_exhibitors_table", "fetch": "html",
                  "aux_parsers": ["parse_kapi_past_exhibitors", "parse_special_exhibition_index",
                                  "parse_special_exhibition_detail"]},
    "kiaf-2017": {"urls": [WB.format(ts="20170927125359", url="http://kiaf.org:80/2017/en/exhibitors_en/"),
                           KAPI_PAST.format(y=2017), SPECIAL_INDEX],
                  "parser": "parse_wb_exhibitors_table", "fetch": "html",
                  "aux_parsers": ["parse_kapi_past_exhibitors", "parse_special_exhibition_index",
                                  "parse_special_exhibition_detail"]},
    "kiaf-2018": {"urls": [WB.format(ts="20181005144207", url="http://kiaf.org:80/2018/exhibitors/"),
                           KAPI_PAST.format(y=2018), SPECIAL_INDEX],
                  "parser": "parse_wb_exhibitors_table", "fetch": "html",
                  "aux_parsers": ["parse_kapi_past_exhibitors", "parse_special_exhibition_index",
                                  "parse_special_exhibition_detail"]},
    "kiaf-2019": {"urls": [WB.format(ts="20200127014918", url="http://kiaf.org:80/2019/exhibitors/"),
                           KAPI_PAST.format(y=2019), SPECIAL_INDEX],
                  "parser": "parse_wb_exhibitors_table", "fetch": "html",
                  "aux_parsers": ["parse_kapi_past_exhibitors", "parse_special_exhibition_index",
                                  "parse_special_exhibition_detail"]},
    "kiaf-2020": {"urls": [KAPI_PAST.format(y=2020), SPECIAL_INDEX], "parser": "parse_kapi_past_exhibitors",
                  "fetch": "json", "aux_parsers": ["parse_special_exhibition_index", "parse_special_exhibition_detail"]},
    "kiaf-2021": {"urls": [KAPI_PAST.format(y=2021)], "parser": "parse_kapi_past_exhibitors", "fetch": "json"},
    "kiaf-2022": {"urls": [KAPI_PAST.format(y=2022), ARTWORK_ITEMS + "  (n = 1..35)",
                           "https://static-edge.kiaf.org/web/2022/08/19000901/Kiaf-SEOUL-Floor-Plan.pdf",
                           "https://static-edge.kiaf.org/web/2022/08/19000905/Kiaf-PLUS-Floor-Plan.pdf"],
                  "parser": "parse_kapi_past_exhibitors", "fetch": "json",
                  "aux_parsers": ["parse_wp_artwork_items", "parse_floorplan_pdf"]},
    "kiaf-2023": {"urls": [KAPI_PAST.format(y=2023), SPECIAL_INDEX], "parser": "parse_kapi_past_exhibitors",
                  "fetch": "json", "aux_parsers": ["parse_special_exhibition_index", "parse_special_exhibition_detail"]},
    "kiaf-2024": {"urls": ["https://static-edge.kiaf.org/web/2024/08/30174214/Kiaf-SEOUL-2024_Online-Catalog.pdf",
                           KAPI_PAST.format(y=2024), HIGHLIGHT_REST, EXHIBITION_REST],
                  "parser": "parse_catalog_pdf", "fetch": "pdf",
                  "aux_parsers": ["parse_catalog_contents_sections", "parse_kapi_past_exhibitors",
                                  "parse_wp_highlight", "parse_wp_exhibition_list"]},
    "kiaf-2025": {"urls": ["https://static-edge.kiaf.org/web/2025/08/29140728/Kiaf-SEOUL-2025_Online-Catalog.pdf",
                           KAPI_PAST.format(y=2025), HIGHLIGHT_REST, EXHIBITION_REST],
                  "parser": "parse_catalog_pdf", "fetch": "pdf",
                  "aux_parsers": ["parse_catalog_contents_sections", "parse_kapi_past_exhibitors",
                                  "parse_wp_highlight", "parse_wp_exhibition_list"]},
    "kiaf-2026": {"urls": ["https://kiaf.org/kapi/eindex?mode=exhibitor3&y=coex&cached=true&keyword=",
                           KAPI_PAST.format(y=2026),
                           "https://static-edge.kiaf.org/web/2023/07/26175229/KiafSEOUL2026_floorplan.pdf",
                           HIGHLIGHT_REST, EXHIBITION_REST],
                  "parser": "parse_kapi_eindex", "fetch": "json",
                  "aux_parsers": ["parse_kapi_past_exhibitors", "parse_floorplan_pdf", "parse_wp_highlight",
                                  "parse_wp_exhibition_list"]},
}
