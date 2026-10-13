"""Build research/frieze/frieze_<fair>_<year>.json (internal research use only).

    python build.py --fetch [--max-seconds 540]   fetch missing sources into raw/ (network, Wayback >= 5.5 s
                                                  spacing), re-check the 2026 London/Seoul Wayback index,
                                                  then build into research/frieze/
    python build.py --out <dir>                   build from the raw/ cache only - never touches the network

Provenance fields per edition JSON:
    source_urls  [{url (resolved Wayback capture), requested_url, wayback_timestamp, use, rel_path, sha256}]
    files        {url: rel_path of the cached raw file under research/frieze/}
    booths[].sources [{url, wayback_timestamp, use}]  - every fetched capture that contributed to the row
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import parsers_frieze as P          # noqa: E402
import frieze_fetch as F            # noqa: E402

FAIRS = {"london": ("Frieze London", "London"), "masters": ("Frieze Masters", "London"),
         "ny": ("Frieze New York", "New York"), "la": ("Frieze Los Angeles", "Los Angeles"),
         "seoul": ("Frieze Seoul", "Seoul")}
MONTHS = "January February March April May June July August September October November December".split()
USAGE = "internal research only (user decision 2026-10-13): gallery lists + 2016-2020 curated-section/programme artists"

DATES = {}


def _d(fair, rows):
    for y, s, e in rows:
        DATES[f"frieze_{fair}_{y}"] = (s, e)


_LON = [(2016, "2016-10-06", "2016-10-09"), (2017, "2017-10-05", "2017-10-08"), (2018, "2018-10-05", "2018-10-07"),
        (2019, "2019-10-03", "2019-10-06"), (2020, "2020-10-09", "2020-10-16"), (2021, "2021-10-13", "2021-10-17"),
        (2022, "2022-10-12", "2022-10-16"), (2023, "2023-10-11", "2023-10-15"), (2024, "2024-10-09", "2024-10-13"),
        (2025, "2025-10-15", "2025-10-19"), (2026, "2026-10-14", "2026-10-18")]
_d("london", _LON)
_d("masters", _LON)
_d("ny", [(2016, "2016-05-05", "2016-05-08"), (2017, "2017-05-05", "2017-05-07"), (2018, "2018-05-04", "2018-05-06"),
          (2019, "2019-05-02", "2019-05-05"), (2020, "2020-05-08", "2020-05-15"), (2021, "2021-05-05", "2021-05-09"),
          (2022, "2022-05-18", "2022-05-22"), (2023, "2023-05-17", "2023-05-21"), (2024, "2024-05-01", "2024-05-05"),
          (2025, "2025-05-07", "2025-05-11"), (2026, "2026-05-13", "2026-05-17")])
_d("la", [(2019, "2019-02-15", "2019-02-17"), (2020, "2020-02-14", "2020-02-16"), (2022, "2022-02-17", "2022-02-20"),
          (2023, "2023-02-16", "2023-02-19"), (2024, "2024-02-29", "2024-03-03"), (2025, "2025-02-20", "2025-02-23"),
          (2026, "2026-02-26", "2026-03-01")])
_d("seoul", [(2022, "2022-09-02", "2022-09-05"), (2023, "2023-09-06", "2023-09-09"), (2024, "2024-09-04", "2024-09-07"),
             (2025, "2025-09-03", "2025-09-06"), (2026, "2026-09-02", "2026-09-05")])

ONLINE_ONLY = {
    "frieze_london_2020": "online-only edition (Frieze Viewing Room, 9-16 Oct 2020); list = online exhibitors",
    "frieze_masters_2020": "online-only edition (Frieze Viewing Room, 9-16 Oct 2020); list = online exhibitors",
    "frieze_ny_2020": "physical fair cancelled (COVID); held online in Frieze Viewing Room 8-15 May 2020; source is the "
                      "Jan 2020 'galleries announced' release (pre-cancellation list)",
}

POLICY_URLS = {
    "frieze_robots": "https://www.frieze.com/robots.txt",
    "wayback_robots": "https://web.archive.org/robots.txt",
    "eflux_robots": "https://www.e-flux.com/robots.txt",
    "frieze_legals": P.WB("20260707032225", "https://www.frieze.com/legals"),
}
RECHECK_2026 = {
    "frieze_london_2026": "https://web.archive.org/cdx/search/cdx?url=frieze.com/fairs/frieze-london/galleries"
                          "&matchType=prefix&output=json&from=202601&filter=statuscode:200&fl=timestamp,original",
    "frieze_seoul_2026": "https://web.archive.org/cdx/search/cdx?url=frieze.com/fairs/frieze-seoul/galleries"
                         "&matchType=prefix&output=json&from=202601&filter=statuscode:200&fl=timestamp,original",
}
TOS_NOTE = ("ToS RED FLAG: frieze.com/legals (Wayback capture 2026-07-07) says you may not develop 'any scripts designed "
            "to scrape or extract data from the Website' without Frieze's prior written consent, nor 'mirror' Contents "
            "or exploit them commercially. Live frieze.com serves a Cloudflare bot challenge (HTTP 403) to this bot; it "
            "was not circumvented. Data here comes only from Wayback captures and archived official PDFs.")


class Ctx:
    def __init__(self, network: bool, deadline: float | None):
        self.network = network
        self.deadline = deadline
        self.missing = []

    def get(self, url, binary=False, required=True):
        allow = self.network and (self.deadline is None or time.time() < self.deadline)
        try:
            return F.get(url, allow_network=allow, binary=binary)
        except F.NotCached:
            if required:
                self.missing.append(url)
            return None, None


def text_of(ctx, url, kind):
    data, meta = ctx.get(url, binary=(kind == "pdf"))
    if data is None:
        return None, None
    return (P.pdf_to_text(data) if kind == "pdf" else data), meta


def plain(html):
    from bs4 import BeautifulSoup
    s = BeautifulSoup(html, "lxml")
    for x in s(["script", "style", "noscript"]):
        x.decompose()
    return s.get_text(" ", strip=True)


def ref(meta, use):
    url = meta["final_url"] if "web.archive.org/web/" in (meta.get("final_url") or "") else meta["requested_url"]
    return {"url": url, "requested_url": meta["requested_url"], "wayback_timestamp": F.wayback_ts(url),
            "use": use, "rel_path": meta["rel_path"], "sha256": meta.get("sha256")}


def bref(r):
    return {"url": r["url"], "wayback_timestamp": r["wayback_timestamp"], "use": r["use"]}


def announced_count(txt):
    t = re.sub(r"\s+", " ", txt)
    m = re.search(r"\b(more than|over|nearly|almost|around|some)\s+(\d{2,3})\s+"
                  r"(?:of the world[’']s |international |leading |invited |exhibiting |participating |)*galleries", t, re.I)
    if m and int(m.group(2)) >= 50:
        return f"{m.group(1).lower()} {m.group(2)}", m.group(0)[:120]
    return None, None


def dates_verified(txt, start, end):
    t = re.sub(r"\s+", " ", txt)
    sd, ed = int(start[8:]), int(end[8:])
    sm, em = MONTHS[int(start[5:7]) - 1], MONTHS[int(end[5:7]) - 1]
    pats = [rf"\b{sd}\s*[–-]\s*{ed}\s+{em}", rf"{sm}\s+{sd}\s*[–-]\s*{ed}\b", rf"{sm}\s+{sd}\s*(?:through|to)\s*{ed}\b",
            rf"\b{sd}\s+{sm}\s*[–-]\s*{ed}\s+{em}", rf"{sm}\s+{sd}\s*[–-]\s*{em}\s+{ed}\b"]
    return any(re.search(p, t) for p in pats)


def robots_summary(ctx):
    out = {}
    for k, u in POLICY_URLS.items():
        data, meta = ctx.get(u, required=False)
        if data is None:
            out[k] = {"url": u, "cached": False}
            continue
        dis = [l.strip() for l in data.splitlines() if l.lower().startswith(("disallow", "user-agent", "content-signal"))]
        out[k] = {"url": u, "cached": True, "rel_path": meta["rel_path"], "fetched_at_utc": meta["fetched_at_utc"],
                  "rules": dis[:20] if "robots" in k else None}
    return out


def recheck_2026(ctx):
    found = {}
    for ed, cdx in RECHECK_2026.items():
        data, meta = ctx.get(cdx, required=False)
        if data is None:
            found[ed] = {"checked": False}
            continue
        rows = json.loads(data)[1:] if data.strip() else []
        rows = [r for r in rows if re.search(r"/galleries/?(\?|$)", r[1]) and "section=" not in r[1]]
        found[ed] = {"checked": True, "checked_at_utc": meta["fetched_at_utc"], "captures": rows, "cdx_url": cdx,
                     "rel_path": meta["rel_path"]}
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="allow network (fill raw/ cache)")
    ap.add_argument("--out", default=None, help="output dir; implies cache-only build unless --fetch")
    ap.add_argument("--max-seconds", type=float, default=None, help="network time budget for --fetch")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    out_dir = os.path.abspath(a.out or BASE)
    ctx = Ctx(network=a.fetch, deadline=(time.time() + a.max_seconds) if a.max_seconds else None)
    os.makedirs(out_dir, exist_ok=True)

    policy = robots_summary(ctx)
    cdx_data, cdx_meta = ctx.get(P.GALLERY_DIRECTORY_CDX)
    slugs = sorted({m.group(1).strip("-") for r in (json.loads(cdx_data)[1:] if cdx_data else [])
                    for m in [re.search(r"/gallery/([a-z0-9\-]+)", r[0].lower())] if m})
    if a.fetch and slugs:
        json.dump({"source": ref(cdx_meta, "gallery directory (CDX)"), "slugs": slugs},
                  open(os.path.join(BASE, "gallery_slugs_from_cdx.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)

    sources = json.loads(json.dumps(P.EDITION_SOURCES))
    rechecks = recheck_2026(ctx)
    for ed, rc in rechecks.items():
        if rc.get("captures"):
            ts, orig = sorted(rc["captures"])[-1]
            sources[ed]["urls"] = [P.WB(ts, orig)]

    # ---- pass 1: gallery names seen anywhere -> known galleries for splitting comma-less rows
    known = set(slugs)
    cache_txt = {}
    for ed, src in sources.items():
        for u in src.get("urls", []):
            txt, meta = text_of(ctx, u, src["fetch"])
            if txt is None:
                continue
            cache_txt[u] = (txt, meta)
            rows = (P.parse_press_release_pdf(txt, known_galleries=slugs) if src["parser"] == "parse_press_release_pdf"
                    else getattr(P, src["parser"])(txt))
            for r in rows:
                if r.get("gallery") and not r.get("_parse_flag") and (r["section"] not in P.ARTIST_SECTIONS or r["artists"]):
                    known.update(r["gallery"].split(" / "))
        for aux in src.get("aux", []):
            for u in aux["urls"]:
                text_of(ctx, u, aux["fetch"])      # make sure aux pages are cached in --fetch mode
    known = sorted(known)

    if ctx.missing:
        print(f"MISSING from cache ({len(ctx.missing)}):")
        for u in sorted(set(ctx.missing)):
            print("  ", u)
        if not a.fetch:
            sys.exit(2)
        print("re-run with --fetch to continue filling the cache")
        sys.exit(3)

    summary = []
    for ed, src in sources.items():
        fair_key, year = re.match(r"frieze_(\w+)_(\d{4})", ed).groups()
        fair, city = FAIRS[fair_key]
        start, end = DATES.get(ed, (None, None))
        out = {"edition_id": ed, "fair": fair, "year": int(year), "start_date": start, "end_date": end, "city": city,
               "source_tier": None, "source_urls": [], "files": {}, "robots_ok": None, "fetch_method": None,
               "announced_gallery_count": None, "extracted_gallery_count": 0, "extracted_artist_count": 0,
               "complete": False, "artists_coverage": None, "usage_scope": USAGE, "notes": [], "booths": []}
        robots_note = ("web.archive.org/robots.txt: " + ("cached" if policy["wayback_robots"]["cached"] else "no robots.txt (404)")
                       + "; frieze.com robots.txt rules: " + "; ".join(policy["frieze_robots"].get("rules") or [])
                       + " -> /fairs/*/galleries, /gallery/*, /sites/default/files/*, /article/* allowed; "
                       "static.frieze.com has no robots.txt")
        out["robots_ok"] = {"ok": True, "note": robots_note}
        if ed in ONLINE_ONLY:
            out["notes"].append(ONLINE_ONLY[ed])
        if ed in rechecks:
            rc = rechecks[ed]
            out["notes"].append(f"Wayback index re-checked {rc.get('checked_at_utc')}: "
                                f"{len(rc.get('captures') or [])} gallery-list captures since 2026-01")
        if not src.get("urls"):
            out.update(source_tier="none", fetch_method="n/a", complete=False, artists_coverage="none")
            out["notes"].append(src.get("discovery", "no source"))
            if ed == "frieze_la_2021":
                out["start_date"] = out["end_date"] = None
                out["notes"].append("Frieze Los Angeles did not take place in 2021.")
            else:
                out["notes"].append("dates are Frieze-announced dates entered manually (not verified against a fetched page)")
            json.dump(out, open(os.path.join(out_dir, f"{ed}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            summary.append(out)
            continue

        def add_src(r):
            out["source_urls"].append(r)
            out["files"][r["url"]] = r["rel_path"]

        booths, texts = [], []
        for u in src["urls"]:
            txt, meta = cache_txt[u]
            r = ref(meta, "gallery_list")
            add_src(r)
            texts.append(txt if src["fetch"] == "pdf" else plain(txt))
            rows = (P.parse_press_release_pdf(txt, known_galleries=known) if src["parser"] == "parse_press_release_pdf"
                    else getattr(P, src["parser"])(txt))
            for row in rows:
                row.pop("_has_next_page", None)
                row["sources"] = [bref(r)]
            booths.extend(rows)
        seen, uniq = {}, []
        for b in booths:                                   # dedupe (D7 multi-page) and merge sources
            k = (b["section"], P.gallery_key(b["gallery"]), tuple(x["name"] for x in b["artists"]))
            if k in seen:
                seen[k]["sources"].extend(s for s in b["sources"] if s not in seen[k]["sources"])
                continue
            seen[k] = b
            uniq.append(b)
        booths = uniq

        if src["parser"] == "parse_press_release_pdf":
            out["source_tier"] = "T3 official Frieze press-release PDF (galleries list appendix), archived on Wayback"
            out["fetch_method"] = "pdf (text layer via PyMuPDF)"
        elif src["parser"] == "parse_d8_gallery_list":
            out["source_tier"] = "T2 frieze.com fair gallery-list page, Wayback capture (live site Cloudflare-challenged)"
            out["fetch_method"] = "html (server-rendered Drupal 8+; whole list in one page; sections only via ?section=)"
        else:
            out["source_tier"] = "T2 frieze.com Drupal-7 gallery-list page(s), Wayback capture - PARTIAL (paginated)"
            out["fetch_method"] = "html (server-rendered Drupal 7, 20 rows/page via ?page=N)"

        sec_pages = []
        for aux in src.get("aux", []):
            for u in aux["urls"]:
                txt, meta = text_of(ctx, u, aux["fetch"])
                use = aux["use"]
                if use == "booth_numbers":
                    r = ref(meta, "booth numbers (printed fair guide index)")
                    add_src(r)
                    idx = {P.gallery_key(x["gallery"]): x["booth"] for x in P.parse_fair_guide_index(txt)}
                    hit = 0
                    for b in booths:
                        if b["section"] in ("main", "Focus", "Collections", "Spotlight") and not b["booth"]:
                            for g in b["gallery"].split(" / "):
                                bk = idx.get(P.gallery_key(g))
                                if bk:
                                    b["booth"] = bk
                                    b["sources"].append(bref(r))
                                    hit += 1
                                    break
                    out["notes"].append(f"booth numbers from the printed fair guide index for {hit} rows")
                elif use == "section_filter":
                    rows = P.parse_d8_gallery_list(txt)
                    if rows and rows[0]["section"]:
                        r = ref(meta, f"section membership: {rows[0]['section']}")
                        add_src(r)
                        sec_pages.append((rows[0]["section"], r, rows))
                elif use == "programme":
                    r = ref(meta, f"{aux['section']} artists")
                    add_src(r)
                    rows = P.parse_programme_artists_pdf(txt, aux["section"], known_galleries=known)
                    for row in rows:
                        row["sources"] = [bref(r)]
                    booths.extend(rows)
                elif use == "award":
                    r = ref(meta, "Frieze Artist Award winner")
                    add_src(r)
                    rows = P.parse_artist_award(txt)
                    for row in rows:
                        row["sources"] = [bref(r)]
                    booths.extend(rows)

        if src["parser"] == "parse_d8_gallery_list":
            for b in booths:
                if b["section"] not in P.PROGRAMME_SECTIONS:
                    b["section"] = None
            opts = P.d8_section_options(cache_txt[src["urls"][0]][0])
            mains = {"main", "galleries"}
            if sec_pages:
                have = {s for s, _, _ in sec_pages}
                member = collections.defaultdict(list)
                for s, r, rows in sec_pages:
                    for x in rows:
                        member[P.gallery_key(x["gallery"])].append((s, r))
                extra = []
                for b in [b for b in booths if b["section"] is None]:
                    secs = member.get(P.gallery_key(b["gallery"]), [])
                    if secs:
                        s0, r0 = secs[0]
                        b["section"] = "main" if s0 in mains else s0
                        b["sources"].append(bref(r0))
                        for s2, r2 in secs[1:]:
                            nb = dict(b, artists=[], section="main" if s2 in mains else s2,
                                      sources=[b["sources"][0], bref(r2)])
                            extra.append(nb)
                    elif all(o in have for o in opts if o not in mains):
                        b["section"] = "main"
                booths.extend(extra)
                out["notes"].append(f"section filter pages archived for {sorted(have)} (options on page: {opts}); "
                                    f"{sum(1 for b in booths if b['section'] is None)} rows left section=null")
            else:
                out["notes"].append(f"section per gallery unknown (no archived ?section= pages); section=null. "
                                    f"Section options on page: {opts}")

        gal_rows = [b for b in booths if b.get("gallery") and b["section"] not in P.PROGRAMME_SECTIONS]
        out["extracted_gallery_count"] = len({P.gallery_key(g) for b in gal_rows for g in b["gallery"].split(" / ")})
        out["extracted_artist_count"] = len({P.slugify(x["name"]) for b in booths for x in b["artists"]})
        ac, phrase = announced_count(" ".join(texts))
        out["announced_gallery_count"] = ac
        if phrase:
            out["notes"].append(f"announced count phrase: '{phrase}'")
        if start:
            ok = dates_verified(" ".join(texts), start, end)
            out["notes"].append("dates " + ("confirmed in fetched source text" if ok else
                                            "entered from Frieze announcements (not found verbatim in the fetched source)"))
        out["notes"].append(f"rows by section: {dict(collections.Counter(b['section'] for b in booths))}")
        flagged = [b for b in booths if b.get("_parse_flag")]
        if flagged:
            out["notes"].append(f"{len(flagged)} curated rows have a heuristic gallery/city/artist split (_parse_flag)")
        with_art = sum(1 for b in gal_rows if b["artists"])
        out["notes"].append(f"gallery rows with artists: {with_art}/{len(gal_rows)} (artists exist only for curated "
                            "solo/duo sections in press releases; frieze.com never lists main-section booth artists)")
        out["artists_coverage"] = ("curated_sections_and_programmes" if with_art else
                                   ("programmes_only" if out["extracted_artist_count"] else "none"))
        out["complete"] = src["parser"] != "parse_d7_gallery_list"
        if not out["complete"]:
            out["notes"].append("INCOMPLETE gallery list: only the archived pages of the paginated Drupal-7 list exist")
        if any("e-flux.com" in s["url"] for s in out["source_urls"]):
            out["robots_ok"]["note"] += ("; e-flux.com robots.txt allows /announcements but blocks GPTBot/CCBot/"
                                         "Bytespider/Diffbot/Meta-ExternalAgent (AI-training opt-out signal)")
        out["notes"].append(TOS_NOTE)
        lg = policy["frieze_legals"]
        if lg.get("cached"):
            out["policy_files"] = {POLICY_URLS["frieze_legals"]: lg["rel_path"]}
        out["booths"] = booths
        json.dump(out, open(os.path.join(out_dir, f"{ed}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        summary.append(out)

    for o in summary:
        print(f"{o['edition_id']:20} gal={o['extracted_gallery_count']:4} art={o['extracted_artist_count']:3} "
              f"ann={str(o['announced_gallery_count']):14} complete={o['complete']!s:5} cov={o['artists_coverage']}")
    print("wrote", len(summary), "files to", out_dir)


if __name__ == "__main__":
    main()
