"""Bukowskis(raw/bukowskis/) -> auction_houses/auctions/auction_lots 적재.

`crawlers/bukowskis.py`가 저장한 로트 그리드 HTML(`grid_<auction_id>_pNNNN.html`,
100로트/페이지)을 파싱한다. 항목 하나(`data-lot-id="..."`로 시작)의 구조:

    <div class="c-lot-index-lot ..." data-lot-id="2376445" id="lot-2376445">
      <a ... href="/en/auctions/673/1-a-swedish-late-baroque-...">...</a>
      <a class="c-lot-index-lot__title-link" href="...">
        <div class="c-lot-index-lot__title-block">
          <div class="c-lot-index-lot__catalogue-number">1</div>
          <div class="c-lot-index-lot__artist">A Swedish late baroque burr-alder cabinet,</div>
          <div class="c-lot-index-lot__title u-line-clamp">first part 18th century.</div>
        </div>
      </a>
      <div class="c-lot-index-lot__price-block">
        <div class="c-lot-index-lot__result-row">
          <div class="c-lot-index-lot__result">
            <div class="c-lot-index-lot__result-caption">Hammer price </div>
            <div class="c-lot-index-lot__result-value">16 000 SEK</div>   ← 유찰이면 없음
          </div>
        </div>
        <div class="c-lot-index-lot__estimate">
          <div class="c-lot-index-lot__estimate-caption">Estimate</div>
          <div class="c-lot-index-lot__estimate-value">30 000 - 40 000 SEK</div>
        </div>
      </div>
    </div>

**작가 판정에 주의할 점** — Bukowskis는 칸옥션/그리자바흐와 달리 미술품 전문이 아니라
가구·디자인·보석·와인까지 파는 종합 경매사(본햄스와 동일 성격)다. `__artist` div가
실제로는 "작가명"이 아니라 **설명 문장의 앞부분**인 경우가 흔하다(예: 위 캐비닛 예시 —
"A Swedish late baroque burr-alder cabinet,"). 본햄스는 부서 코드(department.code)로
가구/장식(WOA)을 걸러냈는데, 이 그리드에는 부서 코드가 없어 **텍스트 휴리스틱으로
대체**한다:

  - 끝이 쉼표(,)나 마침표(.)로 끝나면 → 문장이 title로 이어지는 설명이다(작가명 아님).
    진짜 작가명은 그리드에서 쉼표/마침표 없이 끝난다("Damien Hirst", "Arman (Armand
    Pierre Fernandez)", "Nathalie Djurberg & Hans Berg" 등 2026-09-22 표본 확인).
  - 앞 단어가 부정관사/수량사(A/An/The/Two/Pair/Set/Group/...)면 설명 문장이다.

이 휴리스틱을 통과하지 못하면 **그 로트는 아예 적재하지 않는다**(본햄스 WOA 제외와
같은 스코프 판단 — 작가 미상으로 남기는 게 아니라 가구/장식으로 보고 건너뛴다). 정확한
부서 분류가 아니라 텍스트 근사치이므로 오탐(진짜 작가인데 걸러짐)이 있을 수 있다는
점은 `docs/logs/경매확장_bukowskis_20260922.md`에 기록해 둔다.

작가는 `get_or_create_artist_safe`의 정확 이름 매칭만 쓴다(이름 유사도 병합 금지).
경매 날짜는 그리드에 없다 — auctions.auction_date는 NULL로 두고 `sale_key`(auction_id)로
세일을 구분한다(그리자바흐가 경매번호로 한 것과 같은 패턴). 이미지는 저장하지 않는다.
"""
from __future__ import annotations

import html
import re

from raw_iter import iter_records

SITE_NAME = "bukowskis"
HOUSE_NAME = "Bukowskis"

ITEM_SPLIT = 'data-lot-id="'
RECORD_ID_RE = re.compile(r"^grid_(?P<auction_id>[A-Za-z0-9]+)_p\d+$")

CATALOGUE_NUMBER_RE = re.compile(r'c-lot-index-lot__catalogue-number">([^<]*)<')
ARTIST_RE = re.compile(r'c-lot-index-lot__artist">(.*?)</div>', re.S)
TITLE_RE = re.compile(r'c-lot-index-lot__title(?:\s[^"]*)?">(.*?)</div>', re.S)
RESULT_VALUE_RE = re.compile(r'c-lot-index-lot__result-value">([^<]*)<')
ESTIMATE_VALUE_RE = re.compile(r'c-lot-index-lot__estimate-value">([^<]*)<')
TAG_RE = re.compile(r"<[^>]+>")

# 실제 작가명이면 쉼표/마침표로 끝나지 않는다(문장이 title로 이어지지 않는다는 뜻).
LEADING_STOPWORDS = {
    "a", "an", "the", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "pair", "pairs", "set", "sets", "group", "groups",
    "collection", "suite", "large", "small", "part", "parts",
}

AMOUNT_RE = re.compile(r"([\d\s.,]+)")
CURRENCY_RE = re.compile(r"([A-Z]{3})\s*$")
RANGE_RE = re.compile(r"^\s*([\d\s.,]+?)\s*-\s*([\d\s.,]+?)\s+([A-Z]{3})\s*$")
SINGLE_RE = re.compile(r"^\s*([\d\s.,]+?)\s+([A-Z]{3})\s*$")


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", fragment))).strip()


def _to_number(raw: str) -> float | None:
    cleaned = raw.replace("\xa0", " ").replace(" ", "").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _looks_like_artist(text: str) -> bool:
    """휴리스틱: 설명 문장(가구·장식)이 아니라 사람/작가 이름처럼 보이는지."""
    t = text.strip()
    if not t or len(t) > 80:
        return False
    if t[-1] in ",.":
        return False
    first_word = re.split(r"\s+", t, 1)[0].strip(".,()").lower()
    if first_word in LEADING_STOPWORDS:
        return False
    return True


def _parse_price(raw: str | None) -> tuple[float | None, str | None]:
    if not raw:
        return None, None
    m = SINGLE_RE.match(raw)
    if not m:
        return None, None
    amount = _to_number(m.group(1))
    return amount, m.group(2)


def _parse_estimate(raw: str | None) -> tuple[float | None, float | None, str | None]:
    if not raw:
        return None, None, None
    m = RANGE_RE.match(raw)
    if m:
        return _to_number(m.group(1)), _to_number(m.group(2)), m.group(3)
    m = SINGLE_RE.match(raw)
    if m:
        amount = _to_number(m.group(1))
        return amount, amount, m.group(2)
    return None, None, None


def parse_items(page_html: str) -> list[dict]:
    items: list[dict] = []
    for chunk in page_html.split(ITEM_SPLIT)[1:]:
        lot_data_id, _, rest = chunk.partition('"')
        if not lot_data_id.isdigit():
            continue
        rest = rest[:8000]  # 다음 로트 블록까지 안 넘어가게 넉넉히 자름(이미지 base64 없음이라 충분)

        cat_match = CATALOGUE_NUMBER_RE.search(rest)
        artist_match = ARTIST_RE.search(rest)
        title_match = TITLE_RE.search(rest)
        result_match = RESULT_VALUE_RE.search(rest)
        estimate_match = ESTIMATE_VALUE_RE.search(rest)

        artist_raw = _text(artist_match.group(1)) if artist_match else ""
        title_raw = _text(title_match.group(1)) if title_match else ""
        hammer_price, currency = _parse_price(_text(result_match.group(1)) if result_match else None)
        est_low, est_high, est_currency = _parse_estimate(
            _text(estimate_match.group(1)) if estimate_match else None
        )

        items.append(
            {
                "lot_data_id": lot_data_id,
                "lot_number": _text(cat_match.group(1)) if cat_match else None,
                "artist_raw": artist_raw,
                "title_raw": title_raw,
                "hammer_price": hammer_price,
                "currency": currency or est_currency,
                "estimate_low": est_low,
                "estimate_high": est_high,
            }
        )
    return items


def load(store) -> int:
    loaded = 0
    skipped_not_sold = 0
    skipped_unattributed = 0
    seen_lots: set[str] = set()
    auction_ids: dict[str, str] = {}

    house_id = store.get_or_create_auction_house(HOUSE_NAME, country="SE")

    for record_id, page_html, meta in iter_records(SITE_NAME, ext="html"):
        m = RECORD_ID_RE.match(record_id)
        if not m:
            continue
        if store.source_already_loaded(meta["raw_path"]):
            continue

        items = parse_items(page_html)
        if not items:
            continue
        source_id = store.insert_source(meta)
        sale_key = m.group("auction_id")

        for item in items:
            if item["lot_data_id"] in seen_lots:
                continue
            seen_lots.add(item["lot_data_id"])

            if item["hammer_price"] is None:
                skipped_not_sold += 1
                continue

            if not _looks_like_artist(item["artist_raw"]):
                # 본햄스 WOA(가구/장식) 제외와 같은 스코프 판단 — 부서 코드가 없어
                # 텍스트 휴리스틱으로 근사한다(모듈 독스트링 참고).
                skipped_unattributed += 1
                continue

            auction_id = auction_ids.get(sale_key)
            if auction_id is None:
                auction_id = store.get_or_create_auction(
                    house_id, None, source_id=source_id, sale_key=sale_key
                )
                auction_ids[sale_key] = auction_id

            artist_id = store.get_or_create_artist_safe(item["artist_raw"], source_id=source_id)
            artwork_id = store.insert_artwork(
                artist_id=artist_id,
                title=item["title_raw"] or "(제목 미상)",
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
        f"[pipeline:bukowskis] {loaded}건 적재, 유찰 스킵 {skipped_not_sold}건, "
        f"작가 미확인(가구/장식 추정) 스킵 {skipped_unattributed}건, 세일 {len(auction_ids)}개"
    )
    return loaded
