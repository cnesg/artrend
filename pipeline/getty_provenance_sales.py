"""Getty Provenance Index Sales Catalogs(raw/getty_provenance_sales/) -> auction_houses/auctions/auction_lots 적재.

crawlers/getty_provenance_sales.py가 받아온 sales_contents_1~13.csv(로트 1,826,237건)를
정규화한다. 1650~1945년 유럽 경매 기록이라 낙찰 여부가 불확실한 행이 섞여 있어
(sample: Sold 41% / Unknown 51% / Bought In 8% 등, docs/크롤러현황.md 참고),
`transaction` 필드가 "Sold"/"Sold [?]"인 확정 낙찰 행만 auction_lots로 적재한다
(Bought In/Withdrawn/Passed/Unknown은 낙찰가가 있어도 최고 입찰가일 뿐 실제 거래가
아니거나 불명확해서 제외).

경매사(auction_house_1)는 프랑스 세일만 예외적으로 비어있고 대신 expert_auth_1
(경매인)에 채워진다는 README 규칙을 그대로 따른다 — catalog_number 접두사(F-)로 구분.
"""
from __future__ import annotations

import csv

from raw_iter import RAW_ROOT, to_int

SITE_NAME = "getty_provenance_sales"
DATA_DIR = RAW_ROOT / SITE_NAME
# transaction 필드는 세일이 열린 나라에 따라 영어/프랑스어/독일어로 기록된다
# (README: "Sold, Vendu, Verkauft"). 2026-09-03 첫 실행에서 영어만 걸러 프랑스/독일
# 세일 파일(6, 8~13)이 사실상 통째로 스킵되는 버그를 겪은 뒤 다국어로 확장함 — "[?]"
# 불확실 접미사가 붙은 변형까지 잡기 위해 접두어(startswith)로 비교한다.
SOLD_PREFIXES = ("Sold", "Vendu", "Verkauft")

SALES_CONTENTS_FILES = [f"sales_contents_{i}" for i in range(1, 14)]


def _read_meta(record_id: str) -> dict:
    import json

    return json.loads((DATA_DIR / f"{record_id}.meta.json").read_text(encoding="utf-8"))


def _auction_date(row: dict) -> str | None:
    year = to_int(row.get("lot_sale_year"))
    if year is None or not (1 <= year <= 9999):
        return None
    month = to_int(row.get("lot_sale_month")) or 1
    day = to_int(row.get("lot_sale_day")) or 1
    month = month if 1 <= month <= 12 else 1
    day = day if 1 <= day <= 28 else 1  # 월별 최대일수 검증 없이 안전한 상한만 적용
    return f"{year:04d}-{month:02d}-{day:02d}"


def load(store) -> int:
    loaded = 0
    skipped_not_sold = 0
    skipped_no_house = 0

    for record_id in SALES_CONTENTS_FILES:
        csv_path = DATA_DIR / f"{record_id}.csv"
        if not csv_path.exists():
            continue
        meta = _read_meta(record_id)
        if store.source_already_loaded(meta["raw_path"]):
            continue

        source_id = store.insert_source(meta)
        auction_cache: dict[str, str] = {}

        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                transaction = (row.get("transaction") or "").strip()
                if not transaction.startswith(SOLD_PREFIXES):
                    skipped_not_sold += 1
                    continue

                catalog_number = (row.get("catalog_number") or "").strip()
                is_french = catalog_number.startswith("F-")
                house_name = (
                    (row.get("expert_auth_1") if is_french else row.get("auction_house_1")) or ""
                ).strip()
                if not house_name:
                    skipped_no_house += 1
                    continue

                auction_id = auction_cache.get(catalog_number)
                if auction_id is None:
                    auction_house_id = store.get_or_create_auction_house(house_name)
                    auction_id = store.get_or_create_auction(
                        auction_house_id, _auction_date(row), source_id=source_id
                    )
                    auction_cache[catalog_number] = auction_id

                artist_name = (row.get("artist_name_1") or "").strip() or None
                if artist_name and artist_name.startswith("[") and artist_name.endswith("]"):
                    artist_name = None  # [Anonymous]/[Anonyme]/[Anonym]
                artist_id = store.get_or_create_artist_safe(artist_name, source_id=source_id) if artist_name else None

                title = (row.get("title") or "").strip() or "(제목 미상)"
                artwork_id = store.insert_artwork(
                    artist_id=artist_id,
                    title=title,
                    medium=(row.get("materials") or "").strip() or None,
                    dimensions=(row.get("dimensions") or "").strip() or None,
                    source_id=source_id,
                )

                price_amount = (row.get("price_amount_1") or "").strip()
                try:
                    hammer_price = float(price_amount) if price_amount else None
                except ValueError:
                    hammer_price = None

                store.insert_auction_lot_batch(
                    auction_id=auction_id,
                    artwork_id=artwork_id,
                    lot_number=(row.get("lot_number") or "").strip() or None,
                    hammer_price=hammer_price,
                    currency=(row.get("price_currency_1") or "").strip() or None,
                    sold=True,
                    source_id=source_id,
                )
                loaded += 1

        print(f"[pipeline:getty_provenance_sales] {record_id}.csv 처리 완료, 누적 적재 {loaded}건")

    store.commit()
    print(
        f"[pipeline:getty_provenance_sales] 총 {loaded}건 적재, "
        f"미확정낙찰 스킵 {skipped_not_sold}건, 경매사 없어 스킵 {skipped_no_house}건"
    )
    return loaded
