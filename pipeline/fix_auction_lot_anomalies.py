"""auction_lots/auctions 이상치 정리 — 2026-09-15 작업분담 §W5

세 가지 독립적인 정리를 리포트 후 --apply로 수행한다.

1. 중복 lot: 같은 (auction_id, lot_number, artworks.title) 그룹에서
   created_at이 가장 이른 1건만 남기고 나머지 auction_lots 행을 삭제한다.
   삭제되는 lot의 artwork_id가 (a) 다른 auction_lots에서도 안 쓰이고
   (b) museum_holdings에서도 안 쓰이면, 그 artwork도 함께 삭제한다(FK 위반을
   피하기 위해 해당 artwork를 참조하는 provenance_records도 동반 삭제 —
   delete_mia_duplicate_artworks.py와 동일 패턴).
2. auctions.auction_date가 1600-01-01 이전이거나 오늘 이후면 NULL 처리
   (명백한 파싱 오류로 판단).
3. auction_lots.hammer_price가 0 이하면 NULL 처리. sold 컬럼은 손대지 않는다
   (건드리는 대상은 hammer_price 하나뿐).

**기본은 dry-run(리포트만)이며, --apply 없이는 절대 DELETE/UPDATE하지 않는다.**
idempotent — 재실행 시 세 항목 모두 0건이어야 정상.

사용법:
    python pipeline/fix_auction_lot_anomalies.py              # dry-run, 리포트 JSON 저장
    python pipeline/fix_auction_lot_anomalies.py --apply       # 실제 반영
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path(__file__).parent / ".env")

from db import get_connection  # noqa: E402

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "logs"


def find_duplicate_lots(cur) -> list[dict]:
    cur.execute(
        """
        select al.id, al.auction_id, al.lot_number, a.title, a.id as artwork_id, al.created_at
        from auction_lots al
        join artworks a on a.id = al.artwork_id
        where al.lot_number is not null
        order by al.auction_id, al.lot_number, a.title, al.created_at
        """
    )
    groups: dict[tuple, list[tuple]] = defaultdict(list)
    for lot_id, auction_id, lot_number, title, artwork_id, created_at in cur.fetchall():
        groups[(auction_id, lot_number, title)].append((lot_id, artwork_id, created_at))

    dupes = []
    for key, rows in groups.items():
        if len(rows) <= 1:
            continue
        rows.sort(key=lambda r: r[2])  # created_at 오름차순 — 가장 이른 것 유지
        keep = rows[0]
        drop = rows[1:]
        dupes.append(
            {
                "auction_id": str(key[0]),
                "lot_number": key[1],
                "title": key[2],
                "keep_lot_id": str(keep[0]),
                "drop_lot_ids": [str(r[0]) for r in drop],
                "drop_artwork_ids": [str(r[1]) for r in drop],
            }
        )
    return dupes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 반영한다 (주의)")
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    # 1. 중복 lot
    dupes = find_duplicate_lots(cur)
    drop_lot_ids = [lid for d in dupes for lid in d["drop_lot_ids"]]
    drop_artwork_candidates = {aid for d in dupes for aid in d["drop_artwork_ids"]}
    print(f"[fix_lots] 중복 lot 그룹 {len(dupes)}개 / 삭제 대상 lot {len(drop_lot_ids)}건")

    # 삭제 대상 artwork 중, 다른 auction_lots/museum_holdings에서 안 쓰이는 것만 최종 artwork 삭제 대상
    final_drop_artworks: list[str] = []
    if drop_artwork_candidates:
        cur.execute(
            """
            select artwork_id::text, count(*)
            from auction_lots
            where artwork_id = any(%s::uuid[])
            group by artwork_id
            """,
            (list(drop_artwork_candidates),),
        )
        lot_ref_count = dict(cur.fetchall())
        cur.execute(
            """
            select artwork_id::text, count(*)
            from museum_holdings
            where artwork_id = any(%s::uuid[])
            group by artwork_id
            """,
            (list(drop_artwork_candidates),),
        )
        holding_ref_count = dict(cur.fetchall())
        for aid in drop_artwork_candidates:
            # lot_ref_count에는 삭제될 lot 자신도 포함돼 있으므로, 그 lot 1건을 빼고도
            # 남는 참조(다른 lot)가 있는지로 판단
            drop_lots_for_this_artwork = sum(
                1 for d in dupes for lid, a in zip(d["drop_lot_ids"], d["drop_artwork_ids"]) if a == aid
            )
            remaining_lot_refs = lot_ref_count.get(aid, 0) - drop_lots_for_this_artwork
            remaining_holding_refs = holding_ref_count.get(aid, 0)
            if remaining_lot_refs <= 0 and remaining_holding_refs <= 0:
                final_drop_artworks.append(aid)

    print(f"[fix_lots] 그중 다른 곳에서 안 쓰여 artwork까지 삭제될 것: {len(final_drop_artworks)}건")

    # 2. auctions.auction_date 이상치
    cur.execute(
        "select id from auctions where auction_date < '1600-01-01' or auction_date > current_date"
    )
    bad_date_ids = [str(r[0]) for r in cur.fetchall()]
    print(f"[fix_lots] auction_date 이상치(1600년 이전/미래): {len(bad_date_ids)}건")

    # 3. hammer_price <= 0
    cur.execute("select id from auction_lots where hammer_price <= 0")
    bad_price_ids = [str(r[0]) for r in cur.fetchall()]
    print(f"[fix_lots] hammer_price<=0: {len(bad_price_ids)}건")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duplicate_groups": len(dupes),
        "duplicate_lots_to_drop": len(drop_lot_ids),
        "artworks_to_drop": len(final_drop_artworks),
        "bad_auction_dates": len(bad_date_ids),
        "bad_hammer_prices": len(bad_price_ids),
        "duplicate_detail": dupes,
        "drop_lot_ids": drop_lot_ids,
        "final_drop_artwork_ids": final_drop_artworks,
        "bad_date_auction_ids": bad_date_ids,
        "bad_price_lot_ids": bad_price_ids,
    }
    out_path = DOCS_DIR / f"auction_lots_이상치_리포트_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[fix_lots] 상세 리포트 저장: {out_path}")

    if not args.apply:
        print("\n[fix_lots] dry-run — 변경 없음. --apply로 실행하면 실제 반영됩니다.")
        cur.close()
        conn.close()
        return

    # --- apply ---
    if drop_lot_ids:
        for i in range(0, len(drop_lot_ids), 2000):
            batch = drop_lot_ids[i : i + 2000]
            cur.execute("delete from auction_lots where id = any(%s::uuid[])", (batch,))
        conn.commit()
        print(f"[fix_lots] 중복 auction_lots {len(drop_lot_ids)}건 삭제 완료")

    if final_drop_artworks:
        for i in range(0, len(final_drop_artworks), 2000):
            batch = final_drop_artworks[i : i + 2000]
            cur.execute("delete from provenance_records where artwork_id = any(%s::uuid[])", (batch,))
            cur.execute("delete from artworks where id = any(%s::uuid[])", (batch,))
        conn.commit()
        print(f"[fix_lots] 참조 없는 artworks {len(final_drop_artworks)}건 (+ provenance_records) 삭제 완료")

    if bad_date_ids:
        cur.execute("update auctions set auction_date = null where id = any(%s::uuid[])", (bad_date_ids,))
        conn.commit()
        print(f"[fix_lots] auction_date 이상치 {len(bad_date_ids)}건 NULL 처리 완료")

    if bad_price_ids:
        cur.execute("update auction_lots set hammer_price = null where id = any(%s::uuid[])", (bad_price_ids,))
        conn.commit()
        print(f"[fix_lots] hammer_price<=0 {len(bad_price_ids)}건 NULL 처리 완료")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
