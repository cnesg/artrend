"""AstaGuru(raw/astaguru/) -> auction_houses/auctions/auction_lots 적재.

`crawlers/astaguru.py`가 저장한 두 종류의 JSON을 읽는다.

  - `auctions_past.json` — 과거 세일 133건의 메타(`id`, `name`, `startDateTime`,
    `endDateTime`, `totalSaleINR`). **경매 날짜는 여기에만 있고 로트 응답에는 없다**
    (로트의 `auctionBasicDetails.auctionEndIST`는 MM-DD-YYYY 현지시 문자열이라
    파싱이 불안정해 쓰지 않는다). 그래서 로더가 이 파일을 먼저 읽어
    auction_id -> 종료일(YYYY-MM-DD) 맵을 만든 뒤 로트를 처리한다.
  - `lots_<auctionId>_pNNN.json` — 세일별 로트. 과거 세일의 filter-lots는
    **낙찰된 로트만** 돌려준다(크롤러 독스트링에 검증 근거: hammer 합계 x 프리미엄이
    사이트 공시 Total Sale과 133개 세일 중 132개에서 정확히 일치. 2008년 첫 세일 1건만
    프리미엄 10% 시절이라 비율이 다를 뿐 역시 합계 일치). 따라서 전부 `sold=True`,
    `hammer_price = auctionState.currentHammerINR`로 적재한다.

**미술품만 적재하는 기준 — 휴리스틱이 아니라 소스가 주는 `category` 필드를 쓴다.**
AstaGuru는 미술 외에 보석·시계·은제품·장식미술·텍스타일·클래식카도 파는 종합 경매사다.
본햄스는 부서 코드로, Bukowskis는 텍스트 휴리스틱으로 걸러야 했지만 이 소스는 로트마다
`category`가 정확히 채워져 있다(2026-09-23 전수 확인: 9,869건 중 Art 7,170 / Prints 13 /
Decorative Art 809 / Timepieces 577 / Jewellery 416 / Silver 402 / Collectibles 351 /
Textiles 111 / Automobiles 20). `category in {Art, Prints}`만 적재하고 나머지는 스킵한다.

주의 — **`creatorType` 필드는 믿으면 안 된다.** 값이 'Artist'/'Brand'/빈값인데, 미술
세일인데도 통째로 빈값인 세일이 많다(예: 217 Masters Legacy, 213 Iconic Masters,
209 ManiFest, 203 Masters Legacy — 전 로트 `creatorType: ""`). 이걸 작가 판정에 쓰면
2025년 이후 주요 미술 세일이 통째로 누락된다(처음에 그렇게 짰다가 연도별 집계에서
2025년이 615 -> 184건으로 줄어드는 걸 보고 발견했다). 작가명은 `creatorValue`에
일관되게 들어 있고, `category in {Art, Prints}`인 로트는 **전부** `creatorValue`가
비어 있지 않다(전수 확인). 그래서 `creatorType`은 'Brand'를 배제하는 용도로만 쓴다.

작가는 `get_or_create_artist_safe`의 정확 이름 매칭만 쓴다(이름 유사도 병합 금지).
`creatorID`(AstaGuru 내부 GUID)는 authority ID(ULAN/Wikidata QID)가 아니므로 병합
근거로 쓰지 않는다 — 적재하지 않고 버린다. 결손 메타(생몰년·국적)는 채우지 않는다.

금액은 전부 INR 원화 기준(`priceMinINR`/`priceMaxINR`/`currentHammerINR`). 응답에
USD/GBP/SGD 환산값도 있지만 **환산 시점 환율이 아니라 조회 시점 환율**이라
(`currencies[].conversionRate`가 응답마다 현재 환율로 들어온다) 적재하지 않는다 —
과거 낙찰가에 현재 환율을 곱한 값은 임의 환율 시장지표와 같은 종류의 오염이다.
"""
from __future__ import annotations

import html
import json
import re

from raw_iter import RAW_ROOT, iter_records

SITE_NAME = "astaguru"
HOUSE_NAME = "AstaGuru"
HOUSE_COUNTRY = "IN"
CURRENCY = "INR"

AUCTIONS_RECORD_ID = "auctions_past"
ART_CATEGORIES = {"Art", "Prints"}


def _auction_dates() -> dict[str, str]:
    """auctions_past.json -> {auction_id: 'YYYY-MM-DD'} (종료일). 없으면 빈 dict."""
    path = RAW_ROOT / SITE_NAME / f"{AUCTIONS_RECORD_ID}.json"
    if not path.exists():
        print(f"[pipeline:astaguru] {path} 없음 — 경매 날짜 없이 적재한다")
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    dates: dict[str, str] = {}
    for a in data.get("auctions") or []:
        aid = a.get("id")
        end = a.get("endDateTime") or a.get("startDateTime")
        if aid is None or not end:
            continue
        day = str(end)[:10]
        # 'YYYY-MM-DD' 형태만 인정 — 아니면 날짜 없이 둔다(지어내지 않는다).
        if len(day) == 10 and day[4] == "-" and day[7] == "-":
            dates[str(aid)] = day
    return dates


def _to_number(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _clean(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# description 필드에는 카탈로그 원문이 HTML 조각으로 들어온다
# ("Signed : Bottom Left<br>Published : ... &amp; ..."). 태그/엔티티를 평문으로 편다.
_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.I)


def _clean_html(value) -> str | None:
    if value is None:
        return None
    text = _BR_RE.sub("\n", str(value))
    text = html.unescape(_TAG_RE.sub(" ", text))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n", text)
    return text.strip() or None


def parse_lots(payload: dict) -> list[dict]:
    """filter-lots 응답 하나에서 적재 대상 로트만 뽑아 정규화한다."""
    items: list[dict] = []
    for lot in payload.get("lots") or []:
        if (lot.get("category") or "") not in ART_CATEGORIES:
            continue
        if (lot.get("creatorType") or "") == "Brand":
            continue
        # 작가명에도 HTML 엔티티(&amp; 등)가 섞여 들어오는 경우가 있어 같이 편다.
        artist = _clean_html(lot.get("creatorValue"))
        if not artist:
            continue
        state = lot.get("auctionState") or {}
        hammer = _to_number(state.get("currentHammerINR"))
        if not hammer:
            continue

        # productID가 로트의 고유 식별자(lotID는 세일 안에서만 유일).
        key = _clean(lot.get("productID")) or f"{lot.get('auctionID')}:{lot.get('lotID')}"
        items.append(
            {
                "key": key,
                "auction_key": str(lot.get("auctionID") or ""),
                "lot_number": _clean(lot.get("lotID")),
                "artist": artist,
                "title": _clean_html(lot.get("title")) or "(제목 미상)",
                "year_created": _clean(lot.get("creationYearValue")),
                "medium": _clean(lot.get("mediumValue")),
                "dimensions": _clean(lot.get("size")),
                "description": _clean_html(lot.get("description")),
                "estimate_low": _to_number(lot.get("priceMinINR")),
                "estimate_high": _to_number(lot.get("priceMaxINR")),
                "hammer_price": hammer,
            }
        )
    return items


def load(store) -> int:
    loaded = 0
    skipped_non_art = 0
    skipped_dupe = 0
    seen: set[str] = set()
    auction_ids: dict[str, str] = {}
    dates = _auction_dates()

    house_id = store.get_or_create_auction_house(HOUSE_NAME, country=HOUSE_COUNTRY)

    for record_id, payload, meta in iter_records(SITE_NAME):
        if not record_id.startswith("lots_"):
            continue  # auctions_past.json은 날짜 맵 용도로만 쓴다
        if store.source_already_loaded(meta["raw_path"]):
            continue
        if not isinstance(payload, dict):
            continue

        raw_count = len(payload.get("lots") or [])
        items = parse_lots(payload)
        skipped_non_art += raw_count - len(items)
        if not items:
            continue

        source_id = store.insert_source(meta)
        # record_id = lots_<auctionId>_pNNN
        sale_key = record_id.split("_")[1]

        for item in items:
            if item["key"] in seen:
                skipped_dupe += 1
                continue
            seen.add(item["key"])

            auction_id = auction_ids.get(sale_key)
            if auction_id is None:
                auction_id = store.get_or_create_auction(
                    house_id, dates.get(sale_key), source_id=source_id, sale_key=sale_key
                )
                auction_ids[sale_key] = auction_id

            artist_id = store.get_or_create_artist_safe(item["artist"], source_id=source_id)
            artwork_id = store.insert_artwork(
                artist_id=artist_id,
                title=item["title"],
                year_created=item["year_created"],
                medium=item["medium"],
                dimensions=item["dimensions"],
                description=item["description"],
                source_id=source_id,
            )
            store.insert_auction_lot_batch(
                auction_id=auction_id,
                artwork_id=artwork_id,
                lot_number=item["lot_number"],
                estimate_low=item["estimate_low"],
                estimate_high=item["estimate_high"],
                currency=CURRENCY,
                hammer_price=item["hammer_price"],
                sold=True,
                source_id=source_id,
            )
            loaded += 1

    store.commit()
    print(
        f"[pipeline:astaguru] {loaded}건 적재, 미술 외 카테고리 스킵 {skipped_non_art}건, "
        f"중복 로트 스킵 {skipped_dupe}건, 세일 {len(auction_ids)}개"
    )
    return loaded
