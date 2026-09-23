"""이미 적재된 Bonhams 세일에서 '새로 미술로 판정한 부서'의 낙찰 로트만 뒤늦게 채운다.

배경: `pipeline/bonhams.py`는 로트의 `department.code`가 `PIC*`/`PHO`인 것만 미술로 보고
적재해 왔다. 2026-09-22에 raw 전수(11,396 세일)의 부서 코드 126종을 훑어보니 `PIC` 접두사를
쓰지 않으면서도 순수미술인 부서가 남아 있어(`bonhams.EXTRA_ART_DEPARTMENTS`) 필터를 넓혔다.

그런데 `bonhams.py`의 로더는 `source_already_loaded(raw_path)`로 **세일 단위 스킵**을 하기
때문에, 필터만 넓혀서 재실행해도 이미 적재된 11,396개 세일은 통째로 건너뛴다 — 넓힌 부서가
반영되지 않는다. 그래서 이 일회성 백필 스크립트를 따로 둔다.

관례대로 **기본은 리포트, `--apply`로만 반영**하고, 재실행해도 결과가 같다(idempotent):
세일(source_id)별로 이미 auction_lots에 들어 있는 lot_number 집합을 먼저 읽고 없는 것만
넣는다. auctions 행은 그 세일에 이미 있으면 재사용하고, 없으면(= 그 세일에 PIC/PHO 로트가
하나도 없어서 auctions 행 자체가 없던 경우) 새로 만든다.

사용법:
    python pipeline/bonhams_backfill_departments.py            # 리포트만
    python pipeline/bonhams_backfill_departments.py --apply    # 실제 적재
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

from bonhams import EXTRA_ART_DEPARTMENTS, HOUSE_NAME  # noqa: E402
from db import get_connection  # noqa: E402
from raw_iter import iter_records  # noqa: E402
from store import PgStore  # noqa: E402

SITE_NAME = "bonhams"


def main() -> None:
    parser = argparse.ArgumentParser(description="Bonhams 확장 미술 부서 뒤늦은 백필")
    parser.add_argument("--apply", action="store_true", help="실제 DB에 반영(기본은 리포트만)")
    parser.add_argument("--limit", type=int, default=None, help="처리할 최대 세일 수(검증용)")
    args = parser.parse_args()

    conn = get_connection()
    store = PgStore(conn)
    cur = conn.cursor()

    cur.execute("select id, raw_path from sources where site_name = %s", (SITE_NAME,))
    source_by_path = {raw_path: str(sid) for sid, raw_path in cur.fetchall()}
    print(f"[bonhams-backfill] 적재된 Bonhams source {len(source_by_path)}건")

    house_id = store.get_or_create_auction_house(HOUSE_NAME) if args.apply else None

    dept_counter: Counter[str] = Counter()
    would_load = 0
    sales_touched = 0
    sales_not_loaded = 0
    seen_sales = 0

    for _record_id, data, meta in iter_records(SITE_NAME):
        if args.limit is not None and seen_sales >= args.limit:
            break
        seen_sales += 1

        if data.get("empty"):
            continue
        source_id = source_by_path.get(meta["raw_path"])
        if source_id is None:
            # 아직 pipeline/run.py --site bonhams로 적재된 적 없는 세일 — 그쪽이 처리한다.
            sales_not_loaded += 1
            continue

        lots = (data.get("lotData") or {}).get("auctionLots") or []
        target = [
            lot
            for lot in lots
            if (lot.get("department") or {}).get("code") in EXTRA_ART_DEPARTMENTS
            and lot.get("status") == "SOLD"
        ]
        if not target:
            continue

        cur.execute(
            "select lot_number, auction_id from auction_lots where source_id = %s", (source_id,)
        )
        rows = cur.fetchall()
        existing_lot_numbers = {r[0] for r in rows}
        existing_auction_id = str(rows[0][1]) if rows else None

        new_lots = [
            lot
            for lot in target
            if (lot.get("lotNo") or {}).get("full") not in existing_lot_numbers
        ]
        if not new_lots:
            continue

        sales_touched += 1
        for lot in new_lots:
            dept_counter[(lot.get("department") or {}).get("code")] += 1
        would_load += len(new_lots)

        if not args.apply:
            continue

        auction_id = existing_auction_id
        if auction_id is None:
            hammer_time = new_lots[0].get("hammerTime") or {}
            auction_date = (hammer_time.get("datetime") or "")[:10] or None
            auction_id = store.get_or_create_auction(house_id, auction_date, source_id=source_id)

        for lot in new_lots:
            title = (lot.get("title") or "").strip() or "(제목 미상)"
            artwork_id = store.insert_artwork(artist_id=None, title=title, source_id=source_id)
            price = lot.get("price") or {}
            store.insert_auction_lot_batch(
                auction_id=auction_id,
                artwork_id=artwork_id,
                lot_number=(lot.get("lotNo") or {}).get("full"),
                estimate_low=price.get("estimateLow") or None,
                estimate_high=price.get("estimateHigh") or None,
                currency=(lot.get("currency") or {}).get("iso_code"),
                hammer_price=price.get("hammerPrice"),
                sold=True,
                source_id=source_id,
            )

        if sales_touched % 200 == 0:
            print(f"[bonhams-backfill] 진행: 세일 {sales_touched}건 처리, 로트 {would_load}건")

    if args.apply:
        store.commit()

    print(f"[bonhams-backfill] 부서별 신규 로트: {dict(dept_counter.most_common())}")
    print(
        f"[bonhams-backfill] {'적재' if args.apply else '적재 예정'} {would_load}건 "
        f"(세일 {sales_touched}개), 아직 미적재 세일 {sales_not_loaded}개"
    )
    if not args.apply:
        print("[bonhams-backfill] 리포트 모드 — 실제 반영하려면 --apply")


if __name__ == "__main__":
    main()
