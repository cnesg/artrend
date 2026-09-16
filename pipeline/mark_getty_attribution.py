"""Getty sales 로트의 귀속 한정어(attrib_mod_auth_1)를 artworks.attribution_qualifier에 기록 (M6-b).

배경: M6 authority 병합에서 Getty 귀속 스텁 이름("école de X", "X ou sa manière" 등 1,018개)이 본체 작가에
흡수됐다. 이름 정규식으로 되돌리는 대신, Getty 원본의 구조화 필드 attrib_mod_auth_1(낙찰 로트 29,216건, 6.7%)을
작품 행에 그대로 옮긴다 — 소스 기반이라 오탐이 없고, 애초에 병합 전에도 "Teniers"류 스텁에는 이 정보가 없었다.

매칭 키: sales_contents_N.csv → sources.raw_path 로 source_id, 그 안에서 (lot_number, title, dimensions) 일치.
같은 키가 2건 이상이면 전부 같은 한정어를 적용(동일 로트의 재판매 기록). 기본 리포트, --apply 시 UPDATE. idempotent.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

from artist_merge_util import get_conn

sys.stdout.reconfigure(encoding="utf-8")
csv.field_size_limit(10**9)
RAW = Path(__file__).resolve().parent.parent / "crawlers" / "raw" / "getty_provenance_sales"
SOLD_PREFIXES = ("Sold", "Vendu", "Verkauft")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("select id::text, raw_path from sources where site_name = 'getty_provenance_sales' and raw_path like '%sales_contents_%'")
    src_by_file = {Path(rp).stem: sid for sid, rp in cur.fetchall()}
    print(f"sources: {len(src_by_file)}개 파일")

    stats = Counter()
    plan: dict[str, str] = {}  # artwork_id -> qualifier
    for stem, sid in sorted(src_by_file.items()):
        fp = RAW / f"{stem}.csv"
        if not fp.exists():
            continue
        # 이 파일의 로트를 (lot_number, title, dimensions) → artwork_id 목록으로
        cur.execute(
            """select coalesce(l.lot_number,''), coalesce(w.title,''), coalesce(w.dimensions,''), w.id::text, w.attribution_qualifier
               from auction_lots l join artworks w on w.id = l.artwork_id where l.source_id = %s""",
            (sid,),
        )
        idx: dict[tuple, list] = defaultdict(list)
        for ln, title, dims, wid, cur_q in cur.fetchall():
            idx[(ln, title, dims)].append((wid, cur_q))
        with open(fp, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if not (row.get("transaction") or "").strip().startswith(SOLD_PREFIXES):
                    continue
                mod = (row.get("attrib_mod_auth_1") or "").strip()
                if not mod:
                    continue
                stats["sold_with_mod"] += 1
                key = ((row.get("lot_number") or "").strip(), (row.get("title") or "").strip() or "(제목 미상)", (row.get("dimensions") or "").strip())
                hits = idx.get(key)
                if not hits:
                    stats["no-match"] += 1
                    continue
                for wid, cur_q in hits:
                    if cur_q:
                        stats["already"] += 1
                    else:
                        plan[wid] = mod.lower()
                        stats["plan"] += 1
        print(f"  {stem}: 누적 {dict(stats)}")
    print(f"결과: {dict(stats)} · 갱신 대상 artworks {len(plan)}")
    print("한정어 분포:", Counter(plan.values()).most_common(12))
    if not args.apply:
        print("--apply 없음: 리포트만")
        return
    items = list(plan.items())
    for i in range(0, len(items), 5000):
        cur.executemany("update artworks set attribution_qualifier = %s, updated_at = now() where id = %s and attribution_qualifier is null",
                        [(q, w) for w, q in items[i:i + 5000]])
        conn.commit()
    cur.execute("select count(*) from artworks where attribution_qualifier is not null")
    print("완료: attribution_qualifier 보유 artworks =", cur.fetchone()[0])


if __name__ == "__main__":
    main()
