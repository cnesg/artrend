"""Villa Grisebach(raw/grisebach/) -> auction_houses/auctions/auction_lots 적재.

`crawlers/grisebach.py`가 저장한 두 종류의 HTML을 읽는다.

1. `list_pNNNN.html` — 낙찰 아카이브 목록(50건/페이지). 항목 하나가
   `href=".../en/object-archive/<id>"`로 시작하고 그 안에:
     · `<p class="… font-serif … uppercase">` → 작가명
     · 같은 모양의 배지 `<p>` 두 개 → 첫 번째가 **경매번호**, 두 번째가 **로트번호**
     · `<p class="text-h4 font-text mt-2">` → "제목. 제작연도"
     · `<p class="text-h4 font-text">Sold for 1,045,000 EUR (incl. premium)`
   낙찰가는 **구매수수료 포함가**다(해머 프라이스가 아님) — 원문 표기를 그대로
   auction_lots.hammer_price에 넣되 이 차이를 여기 기록해 둔다. Bonhams(해머)와
   Getty(당시 통화 낙찰가)도 각각 정의가 달라, 소스 간 가격 비교는 원래부터
   source를 봐야 하는 구조다.

2. `auction_<경매번호>.html` — 경매번호별 대표 상세 페이지 한 장. 목록에는 경매
   날짜가 없어서 여기서 "Selected Works, Thursday, 26.11.2015" 형태의 날짜만 뽑아
   경매번호→날짜 표로 쓴다(auctions.auction_date용). 이 파일들은 sources로 적재하지
   않는다 — 날짜 조회용 참고자료다.

작가는 `get_or_create_artist_safe`의 정확 이름 매칭만 쓴다(이름 유사도 병합 금지).
제목 끝의 제작연도(". 1936", ". 1929–1935")는 artworks.year_created로 분리한다.
"""
from __future__ import annotations

import html
import re

from raw_iter import RAW_ROOT, iter_records

SITE_NAME = "grisebach"
HOUSE_NAME = "Villa Grisebach"

ITEM_SPLIT = 'href="https://www.grisebach.com/en/object-archive/'
BLOCK_RE = re.compile(r"<!--\[if BLOCK\]><!\[endif\]-->(.*?)<!--\[if ENDBLOCK\]><!\[endif\]-->", re.S)
ARTIST_RE = re.compile(r'<p class="text-h4 font-serif[^"]*">(.*?)</p>', re.S)
BADGE_RE = re.compile(r'min-w-10 rounded-sm[^>]*>(.*?)</p>', re.S)
TITLE_RE = re.compile(r'<p class="text-h4 font-text mt-2">(.*?)</p>', re.S)
SOLD_RE = re.compile(r"Sold for\s+([\d.,]+)\s+([A-Z]{3})")
# 상세 페이지의 "…, Thursday, 26.11.2015" 형태
DETAIL_DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.((?:19|20)\d{2})\b")
TAG_RE = re.compile(r"<[^>]+>")
# 제목 끝의 제작연도: ". 1936" / ". 1929–1935" / ". um 1910"
YEAR_SUFFIX_RE = re.compile(r"\.\s*((?:um |ca\.? )?(?:1[5-9]|20)\d{2}(?:\s*[–\-/]\s*\d{2,4})?)\s*$")


def _text(fragment: str) -> str:
    fragment = BLOCK_RE.sub(r"\1", fragment)
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", fragment))).strip()


def parse_items(page_html: str) -> list[dict]:
    items: list[dict] = []
    for chunk in page_html.split(ITEM_SPLIT)[1:]:
        object_id, _, rest = chunk.partition('"')
        if not object_id.isdigit():
            continue
        rest = rest[:6000]

        badges = [_text(b) for b in BADGE_RE.findall(rest)]
        artist_match = ARTIST_RE.search(rest)
        title_match = TITLE_RE.search(rest)
        sold_match = SOLD_RE.search(TAG_RE.sub(" ", rest))

        title = _text(title_match.group(1)) if title_match else None
        year_created = None
        if title:
            ym = YEAR_SUFFIX_RE.search(title)
            if ym:
                year_created = ym.group(1).strip()
                title = title[: ym.start()].strip() or None

        items.append(
            {
                "object_id": object_id,
                "artist_name": (_text(artist_match.group(1)) if artist_match else None) or None,
                "auction_number": badges[0] if len(badges) > 0 else None,
                "lot_number": badges[1] if len(badges) > 1 else None,
                "title": title,
                "year_created": year_created,
                "hammer_price": float(sold_match.group(1).replace(",", "")) if sold_match else None,
                "currency": sold_match.group(2) if sold_match else None,
            }
        )
    return items


def _auction_dates() -> dict[str, str]:
    """auction_<번호>.html에서 경매번호 -> 'YYYY-MM-DD' 표를 만든다."""
    dates: dict[str, str] = {}
    for path in sorted((RAW_ROOT / SITE_NAME).glob("auction_*.html")):
        auction_number = path.stem.split("_", 1)[1]
        text = TAG_RE.sub(" ", path.read_text(encoding="utf-8"))
        # "Sold for" 근처 문단에 세일 제목과 날짜가 같이 있다 — 그 뒤쪽만 본다.
        anchor = text.find("Sold for")
        window = text[anchor : anchor + 1500] if anchor >= 0 else text
        m = DETAIL_DATE_RE.search(window)
        if m:
            dates[auction_number] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return dates


def load(store) -> int:
    auction_dates = _auction_dates()
    loaded = 0
    skipped_not_sold = 0
    seen_objects: set[str] = set()
    auction_ids: dict[str, str] = {}

    house_id = store.get_or_create_auction_house(HOUSE_NAME, country="DE")

    # 증분 재실행 대비: 이미 DB에 있는 Grisebach auctions 행을 날짜로 찾아 재사용한다.
    # store.get_or_create_auction의 캐시는 실행 단위라, 이걸 안 하면 두 번째 실행에서
    # 같은 경매번호에 auctions 행이 하나 더 생긴다(수집을 여러 번에 나눠 하므로 실제 위험).
    # Grisebach는 경매번호마다 날짜가 하나라 (경매사, 날짜)로 충분히 특정된다.
    date_to_auction_id: dict[str, str] = {}
    if hasattr(store, "cur"):
        store.cur.execute(
            "select id, auction_date from auctions where auction_house_id = %s and auction_date is not null",
            (house_id,),
        )
        date_to_auction_id = {str(d): str(aid) for aid, d in store.cur.fetchall()}

    for record_id, page_html, meta in iter_records(SITE_NAME, ext="html"):
        if not record_id.startswith("list_p"):
            continue  # auction_*.html은 날짜 참고자료 — sources로 적재하지 않는다
        if store.source_already_loaded(meta["raw_path"]):
            continue

        items = parse_items(page_html)
        if not items:
            continue
        source_id = store.insert_source(meta)

        for item in items:
            if item["object_id"] in seen_objects:
                continue
            seen_objects.add(item["object_id"])

            if item["hammer_price"] is None:
                skipped_not_sold += 1
                continue

            auction_number = item["auction_number"] or "(회차 미상)"
            auction_id = auction_ids.get(auction_number)
            if auction_id is None:
                auction_date = auction_dates.get(auction_number)
                auction_id = date_to_auction_id.get(auction_date) if auction_date else None
                if auction_id is None:
                    auction_id = store.get_or_create_auction(
                        house_id, auction_date, source_id=source_id, sale_key=auction_number
                    )
                    if auction_date:
                        date_to_auction_id[auction_date] = auction_id
                auction_ids[auction_number] = auction_id

            artist_id = store.get_or_create_artist_safe(item["artist_name"], source_id=source_id)
            artwork_id = store.insert_artwork(
                artist_id=artist_id,
                title=item["title"] or "(제목 미상)",
                year_created=item["year_created"],
                source_id=source_id,
            )
            store.insert_auction_lot_batch(
                auction_id=auction_id,
                artwork_id=artwork_id,
                lot_number=item["lot_number"],
                currency=item["currency"],
                hammer_price=item["hammer_price"],
                sold=True,
                source_id=source_id,
            )
            loaded += 1

    store.commit()
    print(
        f"[pipeline:grisebach] {loaded}건 적재, 낙찰가 없어 스킵 {skipped_not_sold}건, "
        f"경매 {len(auction_ids)}회차(날짜 확보 {len(auction_dates)}회차)"
    )
    return loaded
