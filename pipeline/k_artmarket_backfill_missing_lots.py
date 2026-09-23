"""K-ARTMARKET 1차 적재에서 통째로 빠졌던 'UCI 없는 로트'를 뒤늦게 채운다.

배경: `parse_items`가 처음엔 `data-ucicd`(국가표준식별자)를 **필수**로 보고, 없는 블록은
건너뛰었다. 그런데 출처에는 **UCI가 없는 로트가 2,912건(전체 55,729건의 5.2%)** 있고,
전부 경매사·낙찰가·경매일이 멀쩡한 실제 로트였다. 그래서 1차 적재분 52,651건에서
이 5%가 통째로 빠져 있었다(2026-09-23에 `<div class="list-box">` 블록 수와 파싱 건수를
대조해 발견 — 페이지 수만 세면 안 보이는 종류의 누락이다).

`parse_items`는 고쳤지만 로더가 페이지 단위 `source_already_loaded` 스킵을 하기 때문에
그냥 재실행하면 1,162페이지가 통째로 스킵된다. 그래서 이 백필을 따로 둔다
(`pipeline/bonhams_backfill_departments.py`와 같은 패턴).

**기본은 리포트, `--apply`로만 반영**하며 재실행해도 결과가 같다(idempotent):
페이지마다 (제목, 재질, 규격, 낙찰가) 키로 **이미 들어 있는 로트의 개수**를 세고,
파싱 결과와 비교해 **남는 만큼만** 넣는다. 그래서 두 번 돌려도 대상이 0건이 된다.

사용법:
    python pipeline/k_artmarket_backfill_missing_lots.py            # 리포트만
    python pipeline/k_artmarket_backfill_missing_lots.py --apply    # 실제 적재
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

from db import get_connection  # noqa: E402
from k_artmarket_works import (  # noqa: E402
    INT32_MAX,
    SITE_NAME,
    _known_houses,
    _normalise_house,
    build_en_artist_index,
    parse_items,
    resolve_artist,
)
from raw_iter import iter_records  # noqa: E402
from store import PgStore  # noqa: E402


def _key(item: dict) -> tuple:
    return (
        item["title"] or "(제목 미상)",
        item["medium"],
        item["dimensions"],
        item["hammer_price"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="K-ARTMARKET UCI 없는 누락 로트 백필")
    parser.add_argument("--apply", action="store_true", help="실제 DB에 반영(기본은 리포트만)")
    args = parser.parse_args()

    conn = get_connection()
    store = PgStore(conn)
    cur = conn.cursor()

    known_houses = _known_houses()
    en_index = build_en_artist_index(store)
    print(f"[kam-missing] 경매사 목록 {len(known_houses)}개 / 작가 인덱스 {len(en_index)}건")

    cur.execute("select raw_path, id::text from sources where site_name = %s", (SITE_NAME,))
    source_by_path = dict(cur.fetchall())
    print(f"[kam-missing] 적재된 페이지 {len(source_by_path)}건")

    # (경매사, 날짜) -> auction_id — 기존 행 재사용용(같은 세일에 auctions 행이 또 생기지 않게).
    cur.execute(
        "select ah.name, a.auction_date, a.id::text from auctions a "
        "join auction_houses ah on ah.id = a.auction_house_id"
    )
    auction_by_house_date: dict[tuple, str] = {}
    for house, date, aid in cur.fetchall():
        auction_by_house_date.setdefault((house, str(date) if date else None), aid)

    would_load = 0
    skipped_no_house = 0
    skipped_bad_price = 0
    pages_touched = 0

    for _record_id, page_html, meta in iter_records(SITE_NAME, ext="html"):
        source_id = source_by_path.get(meta["raw_path"])
        if source_id is None:
            continue

        items = parse_items(page_html)
        if not items:
            continue

        cur.execute(
            "select aw.title, aw.medium, aw.dimensions, al.hammer_price "
            "from auction_lots al join artworks aw on aw.id = al.artwork_id "
            "where al.source_id = %s::uuid",
            (source_id,),
        )
        existing = Counter(
            (t, m, d, float(p) if p is not None else None) for t, m, d, p in cur.fetchall()
        )

        missing = []
        for item in items:
            k = _key(item)
            if existing[k] > 0:
                existing[k] -= 1
                continue
            missing.append(item)

        if not missing:
            continue
        pages_touched += 1

        for item in missing:
            house_name = _normalise_house(item, known_houses)
            if not house_name:
                skipped_no_house += 1
                continue
            if item["hammer_price"] is None or item["hammer_price"] == INT32_MAX:
                skipped_bad_price += 1
                continue
            would_load += 1

            if not args.apply:
                continue

            date = item["auction_date"]
            auction_id = auction_by_house_date.get((house_name, date))
            if auction_id is None:
                house_id = store.get_or_create_auction_house(house_name, country="KR")
                auction_id = store.get_or_create_auction(
                    house_id, date, source_id=source_id, sale_key=f"{date}|{item['sale_name']}"
                )
                auction_by_house_date[(house_name, date)] = auction_id

            artist_id = resolve_artist(store, item, en_index, source_id)
            artwork_id = store.insert_artwork(
                artist_id=artist_id,
                title=item["title"] or "(제목 미상)",
                medium=item["medium"],
                dimensions=item["dimensions"],
                source_id=source_id,
            )
            store.insert_auction_lot_batch(
                auction_id=auction_id,
                artwork_id=artwork_id,
                lot_number=None,
                currency=item["currency"],
                hammer_price=item["hammer_price"],
                sold=True,
                source_id=source_id,
            )

    if args.apply:
        store.commit()

    print(
        f"[kam-missing] {'적재' if args.apply else '적재 예정'} {would_load}건 "
        f"(페이지 {pages_touched}개), 경매사 없어 스킵 {skipped_no_house}건, "
        f"가격 이상 스킵 {skipped_bad_price}건"
    )
    if not args.apply:
        print("[kam-missing] 리포트 모드 — 반영하려면 --apply")


if __name__ == "__main__":
    main()
