"""crawlers/raw/wikidata_artist_events/*.json → artist_events / exhibitions / exhibition_artists 적재 (R4).

- award  → artist_events(event_kind='award', event_date, detail='<상 이름> — <수여자>', url=Wikidata 항목)
- death  → artists.death_year가 비어 있으면 채움 + artist_events(event_kind='death')
- exhibition → exhibitions(venue_kind='other' 또는 museum/gallery 이름 매칭 시 해당, venue_name=placeLabel) +
               exhibition_artists(role=null). 작가는 wikidata_qid로만 매칭(이름 매칭·신규 생성 없음).
기본 리포트, --apply 시 적재. 유니크 인덱스(0009)로 idempotent.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path

from artist_merge_util import get_conn

sys.stdout.reconfigure(encoding="utf-8")
RAW = Path(__file__).resolve().parent.parent / "crawlers" / "raw" / "wikidata_artist_events"
LICENSE_NOTE = "Wikidata CC0 1.0 (https://www.wikidata.org/wiki/Wikidata:Licensing)"


def _date(v: str | None) -> str | None:
    if not v:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", v)
    if not m or m.group(1) == "0000":
        return None
    y, mo, d = m.groups()
    return f"{y}-{mo if mo != '00' else '01'}-{d if d != '00' else '01'}"


def _qid(uri: str | None) -> str | None:
    return uri.rsplit("/", 1)[-1] if uri else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("select wikidata_qid, id::text, death_year from artists where wikidata_qid is not null and entity_kind = 'person'")
    by_qid = {q: (i, d) for q, i, d in cur.fetchall()}
    cur.execute("select lower(name), id::text from museums")
    museums = dict(cur.fetchall())
    cur.execute("select lower(name), id::text from galleries")
    galleries = dict(cur.fetchall())

    stats = Counter()
    awards, deaths, exhs, award_map = [], [], {}, {}
    for fp in glob.glob(str(RAW / "*.json")):
        if fp.endswith(".meta.json"):
            continue
        d = json.load(open(fp, encoding="utf-8"))
        for e in d.get("events", []):
            q = _qid(e.get("artist"))
            if q not in by_qid:
                stats["unknown-artist"] += 1
                continue
            aid, dy = by_qid[q]
            if e.get("kind") == "award":
                # 같은 수상이 en/ko 라벨 조합으로 여러 행 → (작가, 날짜, 항목)당 1건, 한국어 라벨 우선
                key = (aid, _date(e.get("date")), e.get("url"))
                cur_rec = award_map.setdefault(key, {"label": set(), "extra": set()})
                if e.get("label"):
                    cur_rec["label"].add(e["label"])
                if e.get("extra"):
                    cur_rec["extra"].add(e["extra"])
            elif e.get("kind") == "death":
                dt = _date(e.get("date"))
                if dt:
                    deaths.append((aid, dt, dy))
        for x in d.get("exhibitions", []):
            q = _qid(x.get("artist"))
            if q not in by_qid:
                continue
            key = _qid(x.get("exh"))
            rec = exhs.setdefault(key, dict(title=x.get("exhLabel") or key, start=_date(x.get("start")), end=_date(x.get("end")),
                                             place=x.get("placeLabel"), country=x.get("countryLabel"), url=x.get("exh"), artists=set()))
            rec["artists"].add(by_qid[q][0])
    def _pick(vals: set) -> str:
        ko = [v for v in vals if re.search(r"[가-힣]", v)]
        return (sorted(ko) or sorted(vals) or [""])[0]
    for (a, d, u), rec in award_map.items():
        detail = _pick(rec["label"])
        if rec["extra"]:
            detail += f" — {_pick(rec['extra'])}"
        awards.append((a, d, detail[:500], u))
    awards = list({(a, d, t): (a, d, t, u) for a, d, t, u in awards}.values())
    print(f"수상 {len(awards)} · 사망일 {len(deaths)}(death_year 비어 있는 작가 {sum(1 for _, _, dy in deaths if dy is None)}) · 전시 {len(exhs)}(참여 {sum(len(r['artists']) for r in exhs.values())}) · 미매칭 {stats['unknown-artist']}")
    for a, d, t, u in awards[:5]:
        print("  award:", d, t[:60])
    for k, r in list(exhs.items())[:5]:
        print("  exh:", r["start"], r["title"][:50], "@", r["place"], len(r["artists"]))
    if not args.apply:
        print("--apply 없음: 리포트만")
        return

    cur.execute("insert into sources (url, site_name, fetched_at, raw_path, license_note) values (%s, %s, now(), %s, %s) returning id",
                ("https://query.wikidata.org/sparql", "wikidata_artist_events", "crawlers/raw/wikidata_artist_events/", LICENSE_NOTE))
    source_id = cur.fetchone()[0]
    n = Counter()
    for a, d, t, u in awards:
        cur.execute("""insert into artist_events (artist_id, event_kind, event_date, detail, url, source_id) values (%s,'award',%s,%s,%s,%s)
                       on conflict do nothing""", (a, d, t, u, source_id))
        n["award"] += cur.rowcount
    for a, dt, dy in deaths:
        cur.execute("""insert into artist_events (artist_id, event_kind, event_date, detail, url, source_id) values (%s,'death',%s,'',null,%s)
                       on conflict do nothing""", (a, dt, source_id))
        n["death"] += cur.rowcount
        if dy is None:
            cur.execute("update artists set death_year = %s, updated_at = now() where id = %s and death_year is null", (int(dt[:4]), a))
            n["death_year_filled"] += cur.rowcount
    for k, r in exhs.items():
        place = (r["place"] or "").lower()
        mid, gid, kind = museums.get(place), None, "other"
        if mid:
            kind = "museum"
        elif galleries.get(place):
            gid, kind = galleries[place], "gallery"
        cur.execute("""insert into exhibitions (title, venue_kind, museum_id, gallery_id, venue_name, country, start_date, end_date, url, source_id)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing returning id""",
                    (r["title"][:500], kind, mid, gid, r["place"], r["country"], r["start"], r["end"], r["url"], source_id))
        row = cur.fetchone()
        if row:
            eid = row[0]; n["exhibition"] += 1
        else:
            cur.execute("select id from exhibitions where url = %s limit 1", (r["url"],))
            eid = cur.fetchone()[0]
        for a in r["artists"]:
            cur.execute("insert into exhibition_artists (exhibition_id, artist_id) values (%s,%s) on conflict do nothing", (eid, a))
            n["exhibition_artist"] += cur.rowcount
    conn.commit()
    print("완료:", dict(n))


if __name__ == "__main__":
    main()
