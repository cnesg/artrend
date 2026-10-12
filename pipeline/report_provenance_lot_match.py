"""출처(provenance) 경매 판매 → auction_lots 매칭 수확 리포트 (읽기 전용, DB 변경 없음).

NGA 등 출처 텍스트의 "Sotheby's London, 21 March 1972, lot 142"를 구조화해
(경매사 계열, 정확한 날짜, 로트 번호)가 auctions/auction_lots와 맞는 건수를 센다.
경매사·날짜·로트 세 가지가 모두 맞아야 후보로 인정하고(로트 번호는 해마다 재사용되므로),
작가까지 일치하면 strong으로 따로 센다. 연결(apply)은 하지 않는다.

    python pipeline/report_provenance_lot_match.py [--json docs/logs/xxx.json]
"""
import argparse
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import get_connection  # noqa: E402

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
MON = "(" + "|".join(list(MONTHS) + [m[:3] for m in MONTHS]) + r")\.?"
RE_MDY = re.compile(MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", re.I)
RE_DMY = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+" + MON + r",?\s+(\d{4})", re.I)
RE_LOT = re.compile(r"\b(?:lots?|nos?\.?)\s*(\d{1,5}[a-z]?)", re.I)


def house_key(name):
    n = re.sub(r"['’]s\b", "", (name or "").lower())
    n = re.sub(r"[^a-z0-9 ]", " ", n).split()
    return n[0] if n else ""


def mon_num(s):
    s = s.lower().rstrip(".")
    for k, v in MONTHS.items():
        if k == s or k[:3] == s[:3]:
            return v
    return None


def parse_date(note):
    m = RE_MDY.search(note)
    if m:
        mo, d, y = mon_num(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = RE_DMY.search(note)
        if not m:
            return None
        d, mo, y = int(m.group(1)), mon_num(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d)
    except (TypeError, ValueError):
        return None


def parse_lot(note):
    m = RE_LOT.search(note)
    return m.group(1).lower() if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("set statement_timeout='300s'")

    cur.execute("""select p.id, p.artwork_id, w.artist_id, h.name, p.note
                   from provenance_records p
                   join auction_houses h on h.id = p.owner_auction_house_id
                   join artworks w on w.id = p.artwork_id
                   where p.note is not null""")
    rows = cur.fetchall()

    cur.execute("""select a.id, h.name, a.auction_date
                   from auctions a join auction_houses h on h.id = a.auction_house_id
                   where a.auction_date is not null""")
    by_key = {}
    for aid, hname, d in cur.fetchall():
        by_key.setdefault((house_key(hname), d), []).append(aid)

    cur.execute("""select l.auction_id, lower(l.lot_number::text), w.artist_id, l.id
                   from auction_lots l left join artworks w on w.id = l.artwork_id""")
    lots = {}
    for aid, ln, art, lid in cur.fetchall():
        lots.setdefault((aid, ln), []).append((art, lid))

    stat = Counter()
    by_year = {}
    cands = []
    for pid, awid, art, hname, note in rows:
        stat["provenance_rows"] += 1
        d, lot = parse_date(note), parse_lot(note)
        if d is None:
            stat["no_full_date"] += 1
            continue
        if lot is None:
            stat["date_no_lot"] += 1
            continue
        stat["parsed_house_date_lot"] += 1
        y = by_year.setdefault(d.year, Counter())
        y["parsed"] += 1
        auctions = by_key.get((house_key(hname), d))
        if not auctions:
            stat["auction_not_in_db"] += 1
            continue
        stat["auction_found"] += 1
        y["auction_found"] += 1
        hit = [(a, h) for aid in auctions for (a, h) in lots.get((aid, lot), [])]
        if not hit:
            stat["auction_found_lot_missing"] += 1
            continue
        stat["lot_matched"] += 1
        y["lot_matched"] += 1
        strong = art is not None and any(a == art for a, _ in hit)
        stat["lot_matched_same_artist"] += int(strong)
        cands.append({"provenance_id": pid, "artwork_id": awid, "lot_ids": [h for _, h in hit],
                      "strong": strong})

    print("== 출처→경매 로트 매칭 수확 (읽기 전용) ==")
    for k in ["provenance_rows", "no_full_date", "date_no_lot", "parsed_house_date_lot",
              "auction_not_in_db", "auction_found", "auction_found_lot_missing",
              "lot_matched", "lot_matched_same_artist"]:
        print(f"{k:28s} {stat[k]:>7,}")
    print("-- 연도별(파싱 성공 기준, 상위) --")
    for y in sorted(by_year):
        v = by_year[y]
        if v["parsed"] >= 20 or v["lot_matched"]:
            print(f"{y} parsed={v['parsed']:>4} auction_found={v['auction_found']:>4} lot_matched={v['lot_matched']:>4}")
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"stat": dict(stat), "by_year": {str(k): dict(v) for k, v in by_year.items()},
             "candidates_sample": cands[:200]}, ensure_ascii=False, indent=1), encoding="utf-8")
    conn.close()


if __name__ == "__main__":
    main()
