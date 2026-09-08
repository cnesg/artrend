"""Bonhams(raw/bonhams/) -> auction_houses/auctions/auction_lots 적재.

crawlers/bonhams.py가 세일 페이지 SSR JSON(pageProps.auction + pageProps.lotData)을
그대로 저장한 11,369개 세일 원본을 정규화한다. Bonhams는 미술뿐 아니라 자동차/시계/
와인/보석/카펫 등 전 카테고리를 취급하므로, 로트별 `department.code`가 `PIC-*`
(Pictures/회화)이거나 `PHO`(Photographs)인 것만 미술품으로 간주해 걸러낸다.
표본 확인(2026-09-04): 전체 세일의 약 20%가 미술 관련 부서 로트를 포함, 그 안에서도
`status`가 `SOLD`인 로트만 실제 낙찰가(`price.hammerPrice`)가 신뢰할 수 있음
(BI=bought-in/유찰은 최고 입찰가일 뿐).

Bonhams는 단일 경매사(하나의 auction_houses 행)이므로 `get_or_create_auction`이
(auction_house_id, auction_date) 조합으로 캐싱하는 기존 구조상, **같은 날짜에 여러
세일이 열린 경우 하나의 auctions 행으로 합쳐질 수 있다** — Wikidata/Getty Provenance
로더에도 이미 있는 동일한 한계를 그대로 이어받음(store.py 공용 메서드라 수정하지 않음).
"""
from __future__ import annotations

from raw_iter import iter_records

SITE_NAME = "bonhams"
HOUSE_NAME = "Bonhams"


def _is_art_department(code: str | None) -> bool:
    if not code:
        return False
    return code.startswith("PIC") or code == "PHO"


def load(store) -> int:
    loaded = 0
    skipped_not_art = 0
    skipped_not_sold = 0
    skipped_empty = 0

    for _record_id, data, meta in iter_records(SITE_NAME):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        if data.get("empty"):
            skipped_empty += 1
            continue

        lots = (data.get("lotData") or {}).get("auctionLots") or []
        art_sold_lots = []
        for lot in lots:
            department = (lot.get("department") or {}).get("code")
            if not _is_art_department(department):
                skipped_not_art += 1
                continue
            if lot.get("status") != "SOLD":
                skipped_not_sold += 1
                continue
            art_sold_lots.append(lot)

        if not art_sold_lots:
            continue

        source_id = store.insert_source(meta)
        auction_house_id = store.get_or_create_auction_house(HOUSE_NAME)

        hammer_time = art_sold_lots[0].get("hammerTime") or {}
        auction_date = (hammer_time.get("datetime") or "")[:10] or None
        auction_id = store.get_or_create_auction(auction_house_id, auction_date, source_id=source_id)

        for lot in art_sold_lots:
            title = (lot.get("title") or "").strip() or "(제목 미상)"
            artwork_id = store.insert_artwork(
                artist_id=None,
                title=title,
                source_id=source_id,
            )

            price = lot.get("price") or {}
            hammer_price = price.get("hammerPrice")
            estimate_low = price.get("estimateLow") or None
            estimate_high = price.get("estimateHigh") or None
            currency = (lot.get("currency") or {}).get("iso_code")
            lot_number = (lot.get("lotNo") or {}).get("full")

            store.insert_auction_lot_batch(
                auction_id=auction_id,
                artwork_id=artwork_id,
                lot_number=lot_number,
                estimate_low=estimate_low,
                estimate_high=estimate_high,
                currency=currency,
                hammer_price=hammer_price,
                sold=True,
                source_id=source_id,
            )
            loaded += 1

    store.commit()
    print(
        f"[pipeline:bonhams] {loaded}건 적재, "
        f"미술 부서 아니라 스킵 {skipped_not_art}건, SOLD 아니라 스킵 {skipped_not_sold}건, "
        f"빈 결과 {skipped_empty}건"
    )
    return loaded
