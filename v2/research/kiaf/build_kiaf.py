"""Build kiaf_<year>.json (2016-2026) from raw sources cached under research/kiaf/.

usage:
  python build_kiaf.py --out <dir>          # cache only, NO network (fails loudly on a cache miss)
  python build_kiaf.py --fetch [--out <dir>] # fill cache misses politely from the network, then build

Every edition JSON carries:
  source_urls  - data/metadata URLs actually read for that edition (Wayback URLs include the snapshot timestamp)
  files        - {url: relative path (under research/kiaf/) of the cached raw body}, incl. robots.txt evidence
  booths[*].sources - the fetched URLs each booth row was derived from
"""
import argparse
import collections
import difflib
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kiaf_fetch as K          # noqa: E402
import parsers_kiaf as P        # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", default=HERE, help="output directory for kiaf_<year>.json (default: research/kiaf)")
ap.add_argument("--fetch", action="store_true", help="allow network for cache misses (default: cache only)")
args = ap.parse_args()
K.set_offline(not args.fetch)
OUT = os.path.abspath(args.out)
os.makedirs(OUT, exist_ok=True)

ROBOTS_URLS = {"kiaf": "https://kiaf.org/robots.txt", "static": "https://static-edge.kiaf.org/robots.txt",
               "wayback": "http://web.archive.org/robots.txt", "drive": "https://drive.google.com/robots.txt",
               "drive_uc": "https://drive.usercontent.google.com/robots.txt"}
KAPI = P.KAPI_PAST
HL_URL, EX_URL, SPEC_INDEX = P.HIGHLIGHT_REST, P.EXHIBITION_REST, P.SPECIAL_INDEX
CATS_URL = "https://kiaf.org/wp-json/wp/v2/categories?per_page=100&page=1&_fields=id,name,slug,count"
HISTORY_URL = "https://kiaf.org/about-history"


class Edition:
    """collects every URL read for one edition -> files map + source_urls"""

    def __init__(self, year):
        self.year = year
        self.files = {}
        self.sources = []

    def _reg(self, url, path, data_source=True):
        self.files[url] = K.rel(path)
        if data_source and url not in self.sources:
            self.sources.append(url)

    def text(self, url, data_source=True):
        p, st = K.fetch(url)
        if st != 200:
            raise RuntimeError(f"{url} -> HTTP {st}")
        self._reg(url, p, data_source)
        return open(p, encoding="utf-8", errors="replace").read()

    def wb(self, ts, url):
        p, st, u = K.wb(ts, url)
        if st != 200:
            raise RuntimeError(f"{u} -> HTTP {st}")
        self._reg(u, p)
        return open(p, encoding="utf-8", errors="replace").read(), u

    def pdf(self, url, name):
        p = K.fetch_pdf(url, name)
        self._reg(url, p)
        return p

    def robots(self, *keys):
        for k in keys:
            u = ROBOTS_URLS[k]
            p, st = K.fetch(u)
            self.files[u] = K.rel(p)


def exact(s):
    return P.exact_key(s)


def matcher(cands, key_en=lambda b: b.get("gallery_en") or b["gallery"]):
    ex, lo = collections.defaultdict(list), collections.defaultdict(list)
    for b in cands:
        ex[exact(key_en(b))].append(b)
        lo[P.name_key(key_en(b))].append(b)

    def f(name):
        e = ex.get(exact(name))
        if e and len(e) == 1:
            return e[0]
        l = lo.get(P.name_key(name))
        if l and len(l) == 1:
            return l[0]
        return None
    return f


def fuzzy_pair(left, right, key=lambda x: x, min_ratio=0.6):
    """greedy 1:1 pairing: containment (>=6 chars, or >=5 after removing generic words) or difflib ratio"""
    cand = []
    for i, a in enumerate(left):
        ka, na = exact(key(a)), P.name_key(key(a))
        for j, b in enumerate(right):
            kb, nb = exact(key(b)), P.name_key(key(b))
            if not ka or not kb:
                continue
            if min(len(ka), len(kb)) >= 6 and (ka in kb or kb in ka):
                cand.append((1.01, i, j, "contains"))
            elif na and nb and min(len(na), len(nb)) >= 5 and (na in nb or nb in na):
                cand.append((1.0, i, j, "contains (generic words removed)"))
            else:
                r = difflib.SequenceMatcher(None, ka, kb).ratio()
                if r >= min_ratio:
                    cand.append((r, i, j, f"fuzzy {r:.2f}"))
    cand.sort(key=lambda t: -t[0])
    ui, uj, out = set(), set(), []
    for r, i, j, how in cand:
        if i in ui or j in uj:
            continue
        ui.add(i); uj.add(j); out.append((left[i], right[j], how))
    return out


def add_src(b, *urls):
    b.setdefault("sources", [])
    for u in urls:
        if u and u not in b["sources"]:
            b["sources"].append(u)


ROBOTS_NOTE = ("kiaf.org/robots.txt = 'User-agent: * / Allow : /' (everything allowed); web.archive.org/robots.txt "
               "-> 404 (no restrictions); static-edge.kiaf.org/robots.txt -> 403 S3 AccessDenied (no robots file; the "
               "PDFs are linked from kiaf.org). Google Drive download endpoints are disallowed "
               "(drive.usercontent.google.com 'Disallow: /'), so the Drive-hosted 2026 catalogue was not fetched. "
               "Checked 2026-10-12 with python requests; robots bodies are in `files`.")

# ---- shared REST data (read once, registered per edition) ---------------------------------------------------
_shared = Edition(0)
cats = {c["id"]: c["slug"] for c in json.loads(_shared.text(CATS_URL))}
cat_year = {cid: int(slug[:4]) for cid, slug in cats.items() if re.match(r"^20\d\d", slug)}
hl_raw = _shared.text(HL_URL)
ex_raw = _shared.text(EX_URL)
spec_index = P.parse_special_exhibition_index(_shared.text(SPEC_INDEX))
ex_cat_map = {111: (2026, "Special Exhibition: Kiaf Special Exhibition 1 《HUMAL》"),
              112: (2026, "Special Exhibition: Kiaf Special Exhibition 2 《VIRTUAL VITAL》 (AR)"),
              107: (2025, "Special Exhibition: 특별전: 리버스 캐비닛 (Reverse Cabinet)")}
EX_DEFAULT = {2024: "Special Exhibition: Kiaf onSITE : 보이지 않는 전환점 (Invisible Transitions)"}
SPEC_DETAIL_FOR = {  # supporting detail pages for the REST-derived special exhibitions (same artist names)
    "Special Exhibition: Kiaf Special Exhibition 1 《HUMAL》": "humal",
    "Special Exhibition: Kiaf Special Exhibition 2 《VIRTUAL VITAL》 (AR)": "ar-exhibition",
    "Special Exhibition: 특별전: 리버스 캐비닛 (Reverse Cabinet)": "kiaf-special-exhibition-reverse-cabinet",
    "Special Exhibition: Kiaf onSITE : 보이지 않는 전환점 (Invisible Transitions)": "kiaf-onsite-invisible-transitions",
}


def share(ed, *urls):
    for u in urls:
        ed.files[u] = _shared.files[u]
        if u not in ed.sources:
            ed.sources.append(u)


def special_from_archive(ed):
    share(ed, SPEC_INDEX)
    out = []
    for it in spec_index:
        if it["year"] != ed.year:
            continue
        html = ed.text(it["url"])
        r = P.parse_special_exhibition_detail(html)
        if r:
            for b in r:
                b["artist_source"] = "kiaf.org/archive-special-exhibitions detail page ('Artists' field)"
                add_src(b, it["url"])
            out += r
        elif "박래현과 박생광" in it["title"]:
            b = P._booth("Special Exhibition: 박래현과 박생광 | 그대로의 색깔 고향",
                         section="Special Exhibition: 박래현과 박생광 | 그대로의 색깔 고향",
                         artists=[P.split_person("박래현"), P.split_person("박생광")],
                         artist_source="exhibition title on the kiaf.org archive page (no 'Artists' field)")
            add_src(b, it["url"]); out.append(b)
    return out


def highlights(ed, booths):
    share(ed, HL_URL, CATS_URL)
    res = P.parse_wp_highlight(hl_raw, cat_year=cat_year, year=ed.year)
    ko_map = {}
    for b in booths:
        if b.get("gallery_ko"):
            ko_map[re.sub(r"\s|갤러리|화랑|gallery", "", b["gallery_ko"].lower())] = b
    f_en = matcher([x for x in booths if x.get("gallery_en")])
    for h in res:
        k = re.sub(r"\s|갤러리|화랑|gallery", "", (h.get("gallery_ko") or h["gallery"]).lower())
        m = ko_map.get(k) or (f_en(h["gallery"]) if not h.get("gallery_ko") else None)
        if m:
            h["booth"] = m.get("booth"); h["gallery_en"] = m.get("gallery_en"); h["gallery_city"] = m.get("gallery_city")
        h["artist_source"] = "kiaf.org/wp-json/wp/v2/highlight (acf.gallery = nominating gallery)"
        h.pop("year", None); h.pop("source_post", None)
        add_src(h, HL_URL)
    return res


def specials_rest(ed):
    share(ed, EX_URL)
    res = P.parse_wp_exhibition_list(ex_raw, cat_map=ex_cat_map, year=ed.year)
    for r in res:
        if r["section"] == "Special Exhibition" and ed.year in EX_DEFAULT:
            r["section"] = r["gallery"] = EX_DEFAULT[ed.year]
        r["artist_source"] = "kiaf.org/wp-json/wp/v2/exhibition_list"
        r.pop("year", None)
        add_src(r, EX_URL)
        slug = SPEC_DETAIL_FOR.get(r["section"])
        det = next((it["url"] for it in spec_index if slug and slug in it["url"].lower()), None)
        if det:
            ed.text(det); add_src(r, det)
    return res


def kapi(ed, year=None):
    url = KAPI.format(y=year or ed.year)
    raw = ed.text(url)
    rows = P.parse_kapi_past_exhibitors(raw, year or ed.year)
    for r in rows:
        add_src(r, url)
    return rows, url, raw


def finish(ed, meta, booths):
    main = [b for b in booths if b["section"] == "main"]
    artists = {a["name"] for b in booths for a in b["artists"]}
    artists_main = {a["name"] for b in main for a in b["artists"]}
    doc = {"edition_id": f"kiaf-{ed.year}", "fair": "Kiaf SEOUL", "year": ed.year}
    doc.update(meta)
    doc["source_urls"] = ed.sources
    doc["robots_ok"] = {"ok": True, "note": ROBOTS_NOTE}
    doc["extracted_gallery_count"] = len({exact(b["gallery"]) + "|" + str(b.get("booth")) for b in main})
    doc["extracted_artist_count"] = len(artists)
    doc["extracted_artist_count_main_booths"] = len(artists_main)
    doc["booths_with_artists"] = sum(1 for b in main if b["artists"])
    doc["sections"] = dict(collections.Counter(b["section"] for b in booths))
    doc["files"] = dict(sorted(ed.files.items()))
    doc["booths"] = booths
    keys = ["edition_id", "fair", "year", "start_date", "end_date", "city", "venue", "source_tier", "source_urls",
            "robots_ok", "fetch_method", "announced_gallery_count", "extracted_gallery_count",
            "extracted_artist_count", "notes"]
    ordered = {k: doc.get(k) for k in keys}
    ordered.update({k: v for k, v in doc.items() if k not in ordered})
    missing = [u for b in booths for u in b.get("sources", []) if u not in ed.files]
    assert not missing, ("booth source not in files map", missing[:3])
    with open(os.path.join(OUT, f"kiaf_{ed.year}.json"), "w", encoding="utf-8") as fh:
        json.dump(ordered, fh, ensure_ascii=False, indent=1)
    print(ed.year, "galleries", ordered["extracted_gallery_count"], "| unique artists", len(artists),
          "| main-booth artists", len(artists_main), "| booths w/ artists", doc["booths_with_artists"],
          "/", len(main), "| files", len(ed.files))


# ======================================================================================================
# 2016-2019: Wayback snapshots of the official per-year sites + kiaf.org archive DB (kapi)
# ======================================================================================================
WB_PAGES = {2016: ("20161016174852", "http://kiaf.org:80/2016/en/exhibitors_en/"),
            2017: ("20170927125359", "http://kiaf.org:80/2017/en/exhibitors_en/"),
            2018: ("20181005144207", "http://kiaf.org:80/2018/exhibitors/"),
            2019: ("20200127014918", "http://kiaf.org:80/2019/exhibitors/")}
META_PAGES = {  # pages read for dates / counts (Wayback timestamps are the request timestamps)
    2016: [("wb", "20160906", "http://kiaf.org/2016/en/about-kiaf-art-seoul")],
    2018: [("wb", "20181005", "http://kiaf.org/2018/about-us/")],
    2019: [("wb", "20190901", "http://kiaf.org/2019/visitor-info-k/")],
}
META_OLD = {
    2016: dict(start_date="2016-10-13", end_date="2016-10-16", venue="COEX Hall A & B", announced_gallery_count=None,
               announced_note="No official count found for 2016: kiaf.org/2016 'About' (Wayback 20160906) says only "
                              "'about 20 countries' 180 galleries are participating in KIAF annually'; Aesthetica "
                              "(secondary) reported ~170 galleries / 16 countries. Dates from a coex.co.kr listing "
                              "(secondary, via web search); VIP preview 10-12 not verified."),
    2017: dict(start_date="2017-09-20", end_date="2017-09-24", venue="COEX Hall A & B", announced_gallery_count=None,
               announced_note="No official count captured; secondary press reports conflict (e.g. 161). 09-20 = VIP "
                              "preview, public 09-21..24 (secondary press via web search)."),
    2018: dict(start_date="2018-10-04", end_date="2018-10-07", venue="COEX Hall A & B", announced_gallery_count=174,
               announced_note="174 galleries / 14 countries (Korea JoongAng Daily, secondary). Dates from archived "
                              "kiaf.org/2018/about-us ('Oct. 4th (Thu.) to 7th (Sun)'); VIP preview 10-03 not verified."),
    2019: dict(start_date="2019-09-26", end_date="2019-09-29", venue="COEX Hall A & B", announced_gallery_count=175,
               announced_note="175 galleries / 17 countries (Newsis 2019-09-21, secondary). Public days 09-26..29 per "
                              "archived kiaf.org/2019/visitor-info-k; VIP opening 09-25."),
}
for year, (ts, url) in WB_PAGES.items():
    ed = Edition(year); ed.robots("kiaf", "wayback")
    html, wb_url = ed.wb(ts, url)
    wb_rows = P.parse_wb_exhibitors_table(html)
    k_rows, k_url, k_raw = kapi(ed)
    withdrawn = {it["gallery_name"].upper() for it in json.loads(k_raw)["data"] if it.get(f"year_{year}") == "철회"}
    f = matcher(k_rows)
    used, booths = set(), []
    for b in wb_rows:
        add_src(b, wb_url)
        if b["gallery"].upper() in withdrawn:
            b["withdrawn_per_kiaf_archive"] = True; add_src(b, k_url)
        m = f(b["gallery"])
        if m is not None and id(m) not in used:
            used.add(id(m)); b["kiaf_code"] = m.get("kiaf_code"); b["country"] = m.get("country"); add_src(b, k_url)
            if m["gallery"] != b["gallery"]:
                b["name_in_kapi"] = m["gallery"]
        booths.append(b)
    left_wb = [b for b in booths if k_url not in b["sources"]]
    left_k = [k for k in k_rows if id(k) not in used]
    for b, k, how in fuzzy_pair(left_wb, left_k, key=lambda x: x["gallery"]):
        used.add(id(k)); b["kiaf_code"] = k.get("kiaf_code"); b["country"] = k.get("country")
        add_src(b, k_url); b["name_in_kapi"] = k["gallery"]; b["kapi_match"] = how
    extra = [k for k in k_rows if id(k) not in used]
    booths += extra
    for b in booths:
        if b.get("sector") == "Highlight":
            b["sector"] = "Highlight (gallery sector)"
    spec = special_from_archive(ed)
    for kind, mts, murl in META_PAGES.get(year, []):
        ed.wb(mts, murl)
    m = dict(META_OLD[year])
    notes = [m.pop("announced_note"),
             f"Gallery list = official {year} exhibitor page (Wayback {ts}, {len(wb_rows)} galleries) matched to the "
             f"kiaf.org past-exhibitors archive DB ({len(k_rows)} galleries for {year}); {len(extra)} archive-DB-only "
             f"rows kept (unmatched name variants, see each booth's `sources`).",
             "kiaf_code = " + P.KAPI_CODE_NOTE,
             "NO per-booth artists: the official site never listed artists per booth; the catalogue was only published "
             "as an issuu embed (image-based; 2017 pre-catalog issuu 30628428/51835497, 2018 catalog 30628428/64970384) "
             "and was not parsed.",
             "Artist-level special exhibition(s) are separate sections from kiaf.org/archive-special-exhibitions."]
    if year == 2017:
        notes.append("The 2017 archive also lists '실험과 도전의 전사들 (한국 행위예술 50주년 기념 자료전)' but its page has no "
                     "artist list. 'WON ART SPACE' (official page) and 'GALLERY WAS' (archive DB) are probably the same "
                     "gallery but were not merged.")
    meta = dict(city="Seoul", source_tier="Tier 3 (Wayback snapshot of official per-year site) + Tier 1 (kiaf.org archive API)",
                fetch_method="html (Wayback id_ raw, server-rendered WP table) + json (kiaf.org/kapi)",
                notes=" | ".join(notes), **m)
    finish(ed, meta, booths + spec)

# ======================================================================================================
# 2020 (online), 2021, 2023: archive DB only
# ======================================================================================================
OTHER = {
    2020: dict(start_date="2020-09-16", end_date="2020-10-18", venue="Online only (Kiaf ONLINE 2020 / online viewing room)",
               announced_gallery_count=139,
               note="Physical fair cancelled (COVID-19); held online 2020-09-16..10-18 with 139 galleries / 4,000+ works per "
                    "kiaf.org/about-history. The whole edition was the online fair, so booths are section 'main' (no "
                    "physical booths). kiaf_code 'OVR' marks 7 galleries coded online-only even in the DB; the other "
                    "codes are hall zones allocated before cancellation. A mobile catalogue app-book existed but was not "
                    "found online. No per-gallery artist lists recovered (2020 OVR pages were JS-rendered; their data "
                    "endpoints were not archived).",
               press=[]),
    2021: dict(start_date="2021-10-13", end_date="2021-10-17", venue="COEX Hall A & B", announced_gallery_count=170,
               note="170 galleries / 10 countries (kiaf.org press clip 7387 title; kiaf.org/about-history '170'). Dates "
                    "from press clips listed on kiaf.org (7387, 7424). No per-booth artists: 2021 OVR data is not exposed "
                    "by the current CMS and was not archived; the 2021 Incheon Airport special exhibition is "
                    "gallery-level only.",
               press=[7387, 7424]),
    2023: dict(start_date="2023-09-06", end_date="2023-09-10", venue="COEX Hall A, B + Grand Ballroom",
               announced_gallery_count=210,
               note="210 galleries / 20 countries (kiaf.org/about-history and press clip 30373; clip 34238 says 211). "
                    "kiaf_code 'G' (30) most likely = Grand Ballroom, where Kiaf PLUS 2023 was held per the history page "
                    "(not verified per gallery). No per-booth artists: no 2023 catalogue PDF found, OVR 2023 not archived "
                    "(1 capture), floor-plan PDF is outlined (no text). The 2023 Kiaf HIGHLIGHTS list (20 artists) was "
                    "loaded via XHR and never archived -> not included.",
               press=[30373, 34238]),
}
for year, mx in OTHER.items():
    ed = Edition(year); ed.robots("kiaf")
    k_rows, k_url, _ = kapi(ed)
    spec = special_from_archive(ed)
    ed.text(HISTORY_URL)
    for pid in mx.pop("press"):
        ed.text(f"https://kiaf.org/wp-json/wp/v2/press/{pid}?_fields=id,date,title,content,acf")
    note = mx.pop("note")
    meta = dict(city="Seoul", source_tier="Tier 1 (kiaf.org archive API, galleries only)",
                fetch_method="json (kiaf.org/kapi/page?f=past-exhibitors)", notes=note + " | kiaf_code: " + P.KAPI_CODE_NOTE,
                **mx)
    finish(ed, meta, k_rows + spec)

# ======================================================================================================
# 2022: archive DB + floor plans (booths) + OVR artwork-items (artists); Kiaf PLUS 2022 = satellite section
# ======================================================================================================
ed = Edition(2022); ed.robots("kiaf", "static")
k_rows, k_url, _ = kapi(ed)
FS_URL = "https://static-edge.kiaf.org/web/2022/08/19000901/Kiaf-SEOUL-Floor-Plan.pdf"
FP_URL = "https://static-edge.kiaf.org/web/2022/08/19000905/Kiaf-PLUS-Floor-Plan.pdf"
fs = [b for b in P.parse_floorplan_pdf(ed.pdf(FS_URL, "kiaf2022_floorplan_seoul.pdf")) if not b["booth"].startswith("M")]
fp = P.parse_floorplan_pdf(ed.pdf(FP_URL, "kiaf2022_floorplan_plus.pdf"))
f_fs = matcher(fs)
for b in k_rows:
    m = f_fs(b["gallery"])
    if m:
        b["booth"] = m["booth"]; add_src(b, FS_URL)
used_fs = {b["booth"] for b in k_rows if b.get("booth")}
for kb, fb, how in fuzzy_pair([b for b in k_rows if not b.get("booth")], [f for f in fs if f["booth"] not in used_fs],
                              key=lambda x: x["gallery"], min_ratio=0.85):
    kb["booth"] = fb["booth"]; kb["floorplan_name"] = fb["gallery"]; kb["floorplan_match"] = how; add_src(kb, FS_URL)
PLUS_SEC = "Kiaf PLUS 2022 (satellite fair, SETEC)"
plus = []
for b in fp:
    nb = P._booth(b["gallery"], en=b["gallery"], booth=b["booth"], section=PLUS_SEC); add_src(nb, FP_URL); plus.append(nb)
art_items = []
for pg in range(1, 36):
    u = P.ARTWORK_ITEMS.format(n=pg)
    for it in json.loads(ed.text(u)):
        it["_src"] = u; art_items.append(it)
TEST_SLUGS = {"gallery-test-vision", "gallery-kiaf"}
by_flag = {True: [], False: []}
for it in art_items:
    by_flag[bool((it.get("acf") or {}).get("exhibits_kiaf_plus"))].append(it)


def attach(t, g, extra_note=None):
    seen = {a["name"].lower() for a in t["artists"]}
    for a in g["artists"]:
        if a["name"].lower() not in seen:
            t["artists"].append(a); seen.add(a["name"].lower())
    t["artist_source"] = "kiaf.org OVR 2022 artwork-items (wp-json/wp/v2/artwork-item)"
    add_src(t, *g.get("source_urls", []))
    if extra_note:
        t["ovr_slug_match"] = extra_note


ovr_unmatched = []
for flag, items in by_flag.items():
    groups = P.parse_wp_artwork_items(json.dumps(items))
    targets, other = (plus, k_rows) if flag else (k_rows, plus)
    f_t, f_o = matcher(targets), matcher(other)
    slug_t = {P.slugify_wp(b["gallery"]): b for b in targets}
    slug_o = {P.slugify_wp(b["gallery"]): b for b in other}
    for g in groups:
        s = g["gallery_slug"]
        if s in TEST_SLUGS:
            continue
        t = slug_t.get(s) or f_t(s.replace("-", " ")) or f_t(s.replace("-", ""))
        if t is None:      # gallery flagged for the other fair in the OVR -> attach there
            t = slug_o.get(s) or f_o(s.replace("-", " ")) or f_o(s.replace("-", ""))
        if t is None:
            ovr_unmatched.append((s, flag, g)); continue
        attach(t, g)
still = []
for flag in (True, False):
    left = [u for u in ovr_unmatched if u[1] == flag]
    pool = plus if flag else k_rows
    done = set()
    for (s, fl, g), t, how in fuzzy_pair(left, [b for b in pool if not b["artists"]],
                                         key=lambda u: (u[0] if isinstance(u, tuple) else u["gallery"]).replace("-", " "),
                                         min_ratio=0.9):
        done.add(s); attach(t, g, f"{s} ({how})")
    still += [(s, fl, len(g["artists"])) for s, fl, g in left if s not in done]
spec = special_from_archive(ed)
ed.text(HISTORY_URL)
for pid in (15155, 15159):
    ed.text(f"https://kiaf.org/wp-json/wp/v2/press/{pid}?_fields=id,date,title,content,acf")
meta = dict(start_date="2022-09-02", end_date="2022-09-05", city="Seoul", venue="COEX Hall A & B",
            announced_gallery_count=163,
            source_tier="Tier 1 (kiaf.org archive API + official floor-plan PDFs + kiaf.org WP REST OVR artworks)",
            fetch_method="json (kapi + WP REST, 35 pages) + pdf (floor plans, text layer)",
            notes=("Kiaf SEOUL 2022: 163 galleries / 17 countries per kiaf.org/about-history (164 in the July 2022 "
                   "announcement, press clips 15155/15159); Kiaf PLUS 2022 (separate satellite fair at SETEC): 73 "
                   f"galleries / 10 countries -> separate section '{PLUS_SEC}', NOT merged. Artists come from the 2022 "
                   f"online viewing room (OVR) artworks still exposed by the CMS ({len(art_items)} artwork records): the "
                   "works a gallery uploaded to its OVR, which overlaps with but is not guaranteed identical to the "
                   "physical booth. Galleries identified by artwork slug prefix (the OVR gallery posts were deleted) and "
                   "matched to the gallery lists; test accounts ('gallery-test-vision', 'gallery-kiaf') dropped; "
                   f"unmatched OVR slugs (not in either 2022 list, left out): {still}. Booth codes from the official "
                   "floor-plan PDFs (name match). kiaf_code: " + P.KAPI_CODE_NOTE))
finish(ed, meta, k_rows + plus + spec)

# ======================================================================================================
# 2024, 2025: official online catalogue PDFs
# ======================================================================================================
CAT = {2024: "https://static-edge.kiaf.org/web/2024/08/30174214/Kiaf-SEOUL-2024_Online-Catalog.pdf",
       2025: "https://static-edge.kiaf.org/web/2025/08/29140728/Kiaf-SEOUL-2025_Online-Catalog.pdf"}
META_CAT = {
    2024: dict(start_date="2024-09-04", end_date="2024-09-08", venue="COEX Hall A, B, Grand Ballroom + The Platz",
               announced_gallery_count=206,
               note="206 galleries / 21 countries (catalogue greetings; dates on the catalogue cover). Booth prefixes "
                    "A/B (halls), G (Grand Ballroom), P (16 booths; per kiaf.org/about-history Kiaf PLUS 2024 had 27 "
                    "exhibitors at The Platz, so P booths are probably Kiaf PLUS, not verified per booth) - kept in "
                    "section 'main' because PLUS was inside the main fair in 2024."),
    2025: dict(start_date="2025-09-03", end_date="2025-09-07", venue="COEX Hall A, B, Grand Ballroom",
               announced_gallery_count=175,
               note="175 galleries (kiaf.org/about-history; 176 in the pre-fair list announcement). Kiaf PLUS 2025 "
                    "(19 emerging galleries) was inside the main fair; booth prefix G (19 booths) matches that count but "
                    "is not labelled PLUS in the catalogue - kept in 'main'. Catalogue error handled: the Wooson Gallery "
                    "page prints booth 'A57' (index: B04); gallery pages are matched by header name, not printed booth."),
}
for year, url in CAT.items():
    ed = Edition(year); ed.robots("kiaf", "static")
    pdf = ed.pdf(url, f"kiaf{year}_catalog.pdf")
    booths = P.parse_catalog_pdf(pdf)
    k_rows, k_url, _ = kapi(ed)
    f_k = matcher(k_rows)
    n_in_kapi = 0
    for b in booths:
        add_src(b, url)
        if f_k(b["gallery"]):
            n_in_kapi += 1; add_src(b, k_url)
    hl = highlights(ed, booths)
    sp = specials_rest(ed)
    cs = P.parse_catalog_contents_sections(pdf)
    cat_hl = next((c for c in cs if c["section"] == "Kiaf HIGHLIGHTS"), None)
    cat_sp = next((c for c in cs if c["section"] == "Special Exhibition"), None)
    if cat_hl:   # catalogue gives EN+KO names; REST gives the nominating gallery
        byko = {re.sub(r"\s", "", a["name_ko"]): a for a in cat_hl["artists"]}
        have = set()
        for h in hl:
            a = h["artists"][0]; k = re.sub(r"\s", "", a["name_ko"] or a["name"])
            if k in byko:
                h["artists"] = [byko[k]]; have.add(k); add_src(h, url)
                h["artist_source"] += " + catalogue contents page (EN name)"
        for k, a in byko.items():
            if k not in have:
                nb = P._booth("(gallery not given)", section="Kiaf HIGHLIGHTS", artists=[a],
                              artist_source="catalogue contents page only (missing from wp-json highlight list)")
                add_src(nb, url); hl.append(nb)
    if cat_sp and len(sp) == 1:
        n_rest = len(sp[0]["artists"])
        sp[0]["artists"] = cat_sp["artists"]; add_src(sp[0], url)
        sp[0]["artist_source"] = (f"catalogue contents page (EN+KO, {len(cat_sp['artists'])} entries); wp-json "
                                  f"exhibition_list has the same artists in Korean ({n_rest} entries after splitting duos)")
    ed.text(HISTORY_URL)
    m = dict(META_CAT[year]); note = m.pop("note")
    diffs = sum(1 for b in booths if b.get("n_artists_gallery_page") != b.get("n_artists_index"))
    meta = dict(city="Seoul", source_tier="Tier 1 (official online catalogue PDF on static-edge.kiaf.org)",
                fetch_method="pdf (text layer, PyMuPDF positional parse) + json",
                notes=(note + f" | Artists per booth = union of the gallery page 'Artists' field and the catalogue's "
                       f"Artist Index (joined by booth); {diffs} booths where the two lists differ in length (spelling "
                       f"variants or one side empty). {n_in_kapi}/{len(booths)} catalogue galleries auto-matched to the "
                       f"kiaf.org archive DB list ({len(k_rows)}). Kiaf HIGHLIGHTS ({len(hl)} artists, with nominating "
                       f"gallery) and the special exhibition are separate artist-level sections."), **m)
    finish(ed, meta, booths + hl + sp)

# ======================================================================================================
# 2026: current exhibitor index API (KO+EN) + floor plan (booths) + HIGHLIGHTS + special exhibitions
# ======================================================================================================
ed = Edition(2026); ed.robots("kiaf", "static", "drive", "drive_uc")
E_URL = "https://kiaf.org/kapi/eindex?mode=exhibitor3&y=coex&cached=true&keyword="
booths = P.parse_kapi_eindex(ed.text(E_URL))
k_rows, k_url, _ = kapi(ed)
f_k = matcher(k_rows)
FP26 = "https://static-edge.kiaf.org/web/2023/07/26175229/KiafSEOUL2026_floorplan.pdf"
fl = P.parse_floorplan_pdf(ed.pdf(FP26, "kiaf2026_floorplan.pdf"))
f_fl = matcher(fl)
nb = nk = 0
for b in booths:
    add_src(b, E_URL)
    if f_k(b["gallery_en"] or b["gallery"]):
        nk += 1; add_src(b, k_url)
    m = f_fl(b["gallery_en"] or b["gallery"])
    if m:
        b["booth"] = m["booth"]; nb += 1; add_src(b, FP26)
hl = highlights(ed, booths)
sp = specials_rest(ed)
ed.text("https://kiaf.org/info")
DRIVE_VIEW = "https://drive.google.com/file/d/1e0lycq8AiB9AKpFBfNoicbDY0OEbn1Po/view?usp=sharing"
p, st = K.fetch(DRIVE_VIEW); ed.files[DRIVE_VIEW] = K.rel(p)   # view page only (robots-allowed); file NOT downloaded
meta = dict(start_date="2026-09-02", end_date="2026-09-06", city="Seoul", venue="COEX Hall A, B, Grand Ballroom",
            announced_gallery_count=175,
            source_tier="Tier 1 (kiaf.org exhibitor-index API + official floor-plan PDF + WP REST)",
            fetch_method="json (kiaf.org/kapi/eindex) + pdf (floor plan text) + json (WP REST)",
            notes=("175 galleries / 18 countries (Newsis 2026-06-09, secondary; dates/venue from kiaf.org/info). "
                   f"Booth codes matched from the floor plan for {nb}/{len(booths)} galleries; {nk}/{len(booths)} matched "
                   "to the archive DB list. NO per-booth artists: the 2026 catalogue is only linked as a Google Drive "
                   "file (kiaf.org/catalogue -> drive.google.com/file/d/1e0lycq8AiB9AKpFBfNoicbDY0OEbn1Po, view page "
                   "kept in `files` as evidence); its download endpoints are disallowed by robots.txt, so it was not "
                   "fetched. The 2026 OVR is closed (/ovr redirects to home) and not archived. Artist-level sections: "
                   "Kiaf HIGHLIGHTS 2026 (10) and the two special exhibitions (HUMAL 7, VIRTUAL VITAL 4)."))
finish(ed, meta, booths + hl + sp)
print("wrote JSONs to", OUT, "| network", "ON" if args.fetch else "OFF (cache only)")
