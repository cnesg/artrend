"""Phillips(raw/phillips/) -> auction_houses/auctions/auction_lots 적재.

`crawlers/phillips.py`가 저장한 두 종류의 HTML을 읽는다.

1. `index.html` — `/auctions/past` 1회 요청분. `React.createElement(PhillipsReact.
   PastAuctions, {...})` 하이드레이션 JSON에 과거 세일 전체의 saleNumber/제목/지역/날짜가
   있다. sources로는 적재하지 않고(로트 데이터가 없음) 세일 날짜 조회용으로만 쓴다.
2. `auction_<saleNumber>.html` — 세일별 상세 페이지(로트 그리드 SSR). 로트 하나는
   `data-testid="lot-<id>-object-tile"`로 시작하고 그 안에:
     · `seldon-object-tile__lot-number` → 로트번호
     · `seldon-object-tile__maker` → 작가명(복수면 "A; B"처럼 세미콜론으로 옴 — 첫 번째만
       artworks.artist_id에 연결한다. kanauction의 "화/제" 두 작가 케이스와 같은 이유로
       스키마가 작가 하나만 받는다)
     · `seldon-object-tile__title` → 작품명
     · "Estimate" 라벨 뒤 값 → 추정가 범위(예: "£4,000–6,000")
     · "Sold For" 라벨 뒤 값(유찰이면 이 블록 자체가 없음) → 낙찰가(예: "£18,060")
   통화는 지역별로 다르다(£/CHF/HK$/€/$...) — `_parse_price`가 기호·ISO코드를 그대로
   추출해 원문 통화를 보존한다(환산 안 함, Grisebach/Bonhams와 같은 소스별 정의 차이 원칙).

작가는 `get_or_create_artist_safe`의 정확 이름 매칭만 쓴다(이름 유사도 병합 금지).
"""
from __future__ import annotations

import html
import json
import re

from raw_iter import RAW_ROOT, iter_records

SITE_NAME = "phillips"
HOUSE_NAME = "Phillips"

CREATE_ELEMENT_MARKER = "React.createElement(PhillipsReact.PastAuctions, "

ITEM_MARKER_RE = re.compile(r'data-testid="lot-(\d+)-object-tile"')
LOT_NUMBER_RE = re.compile(r'seldon-object-tile__lot-number[^"]*">([^<]+)</span>')
MAKER_RE = re.compile(r'seldon-object-tile__maker[^"]*">.*?<span>(.*?)</span>', re.S)
TITLE_RE = re.compile(r'seldon-object-tile__title[^"]*">.*?<span>(.*?)</span>', re.S)
ESTIMATE_RE = re.compile(r'Estimate</span>.*?seldon-text--labelSmall">([^<]+)</span>', re.S)
SOLD_RE = re.compile(r'Sold For</span>.*?seldon-text--labelSmall">([^<]+)</span>', re.S)
TAG_RE = re.compile(r"<[^>]+>")

# 기호·ISO코드 순서 주의: HK$/US$/S$가 $보다 먼저 매치돼야 한다.
CURRENCY_RE = re.compile(
    r"^(CHF|HKD|USD|EUR|GBP|SGD|HK\$|US\$|S\$|£|\$|€|¥)\s*"
    r"([\d,]+(?:\.\d+)?)(?:\s*[–\-]\s*([\d,]+(?:\.\d+)?))?"
)
SYMBOL_CODE = {
    "£": "GBP", "$": "USD", "€": "EUR", "¥": "JPY",
    "HK$": "HKD", "US$": "USD", "S$": "SGD",
    "CHF": "CHF", "HKD": "HKD", "USD": "USD", "EUR": "EUR", "GBP": "GBP", "SGD": "SGD",
}

WINDOW = 9000


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", fragment))).strip()


def _first_artist(raw_name: str | None) -> str | None:
    """"Allen Jones; David Hockney"처럼 복수 작가면 첫 번째만(스키마가 하나만 받음)."""
    if not raw_name:
        return None
    return raw_name.split(";")[0].strip() or None


def _parse_price(raw: str | None) -> tuple[str | None, float | None, float | None]:
    """'£4,000–6,000' -> (통화코드, 최소값, 최대값). 단일값('£18,060')이면 최소=최대."""
    if not raw:
        return None, None, None
    m = CURRENCY_RE.match(raw.strip())
    if not m:
        return None, None, None
    symbol, low, high = m.group(1), m.group(2), m.group(3)
    code = SYMBOL_CODE.get(symbol, symbol)
    low_val = float(low.replace(",", ""))
    high_val = float(high.replace(",", "")) if high else low_val
    return code, low_val, high_val


def parse_items(page_html: str) -> list[dict]:
    items: list[dict] = []
    matches = list(ITEM_MARKER_RE.finditer(page_html))
    for i, m in enumerate(matches):
        lot_id = m.group(1)
        start = m.end()
        window_end = min(len(page_html), start + WINDOW)
        end = min(matches[i + 1].start(), window_end) if i + 1 < len(matches) else window_end
        chunk = page_html[start:end]

        lot_no_m = LOT_NUMBER_RE.search(chunk)
        maker_m = MAKER_RE.search(chunk)
        title_m = TITLE_RE.search(chunk)
        estimate_m = ESTIMATE_RE.search(chunk)
        sold_m = SOLD_RE.search(chunk)

        estimate_currency, estimate_low, estimate_high = _parse_price(
            _text(estimate_m.group(1)) if estimate_m else None
        )
        sold_currency, sold_low, _sold_high = _parse_price(
            _text(sold_m.group(1)) if sold_m else None
        )

        items.append(
            {
                "lot_id": lot_id,
                "lot_number": _text(lot_no_m.group(1)) if lot_no_m else None,
                "artist_name": _first_artist(_text(maker_m.group(1)) if maker_m else None),
                "title": (_text(title_m.group(1)) if title_m else None) or None,
                "estimate_low": estimate_low,
                "estimate_high": estimate_high,
                "currency": sold_currency or estimate_currency,
                "hammer_price": sold_low,
            }
        )
    return items


def _extract_json_object(text: str, marker: str) -> dict | None:
    start = text.find(marker)
    if start < 0:
        return None
    start += len(marker)
    depth = 0
    in_str = False
    esc = False
    end = None
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        return None
    return json.loads(text[start:end])


def _sale_meta() -> dict[str, dict]:
    """index.html 임베드 JSON에서 saleNumber -> {title, location, date} 표."""
    index_path = RAW_ROOT / SITE_NAME / "index.html"
    if not index_path.exists():
        return {}
    obj = _extract_json_object(index_path.read_text(encoding="utf-8"), CREATE_ELEMENT_MARKER)
    if not obj:
        return {}
    meta = {}
    for record in obj.get("data", []):
        sale_number = record.get("saleNumber")
        if not sale_number:
            continue
        date = record.get("startDateTimeOffset")
        meta[sale_number] = {
            "title": record.get("auctionTitle"),
            "location": record.get("locationName"),
            "date": date[:10] if date else None,
        }
    return meta


def load(store) -> int:
    sale_meta = _sale_meta()
    loaded = 0
    skipped_not_sold = 0
    seen_lots: set[str] = set()
    auction_ids: dict[str, str] = {}

    house_id = store.get_or_create_auction_house(HOUSE_NAME, country=None)

    for record_id, page_html, meta in iter_records(SITE_NAME, ext="html"):
        if not record_id.startswith("auction_"):
            continue  # index.html은 세일 날짜 조회용 — 로트 데이터가 없어 sources로 적재 안 함
        if store.source_already_loaded(meta["raw_path"]):
            continue

        sale_number = record_id[len("auction_"):]
        items = parse_items(page_html)
        if not items:
            continue
        source_id = store.insert_source(meta)

        info = sale_meta.get(sale_number, {})
        auction_id = auction_ids.get(sale_number)
        if auction_id is None:
            auction_id = store.get_or_create_auction(
                house_id,
                info.get("date"),
                source_id=source_id,
                sale_key=sale_number,
            )
            auction_ids[sale_number] = auction_id

        for item in items:
            key = f"{sale_number}:{item['lot_id']}"
            if key in seen_lots:
                continue
            seen_lots.add(key)

            if item["hammer_price"] is None:
                skipped_not_sold += 1
                continue

            artist_id = store.get_or_create_artist_safe(item["artist_name"], source_id=source_id)
            artwork_id = store.insert_artwork(
                artist_id=artist_id,
                title=item["title"] or "(제목 미상)",
                source_id=source_id,
            )
            store.insert_auction_lot_batch(
                auction_id=auction_id,
                artwork_id=artwork_id,
                lot_number=item["lot_number"],
                estimate_low=item["estimate_low"],
                estimate_high=item["estimate_high"],
                currency=item["currency"],
                hammer_price=item["hammer_price"],
                sold=True,
                source_id=source_id,
            )
            loaded += 1

    store.commit()
    print(
        f"[pipeline:phillips] {loaded}건 적재, 낙찰가 없어 스킵 {skipped_not_sold}건, "
        f"세일 {len(auction_ids)}회"
    )
    return loaded
