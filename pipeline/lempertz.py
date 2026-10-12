"""Lempertz(raw/lempertz/) -> auction_houses/auctions/auction_lots 적재.

`crawlers/lempertz.py`가 저장한 로트 상세 페이지 HTML(로트 1건 = 파일 1건)을 읽는다.

각 페이지의 `<script type="application/ld+json">` Product 스키마가 가장 신뢰도 높은
구조화 데이터를 준다(HTML 클래스 파싱보다 이걸 우선 신뢰):
  - `name`: "작가 - 제목" 형태(그대로는 안 쓰고 아래 별도 필드로 분리해서 받음)
  - `description`: 재질/규격/서명 등 원문(대개 독일어)
  - `offers.priceCurrency` / `offers.lowPrice` / `offers.highPrice` / `offers.price`
    (`price` = 낙찰가, **구매수수료 포함가** — "Result: … (incl. premium)". Grisebach·
    Bonhams·Getty와도 가격 정의가 다르니 소스 간 비교 시 주의, 기존 관례와 동일)
  - `offers.creator[]`: `[{"@type":"Person","name":"Picasso, Pablo"}]` — **"성, 이름" 순서
    그대로 둔다.** 이름 순서를 뒤집는 추측성 변환은 하지 않는다 — 그건
    `pipeline/merge_name_order_dup_artists.py` 같은 별도의 명시적 병합 단계 몫이다
    (로더 단계에서 하면 실패한 변환이 추측성 매칭으로 남는다).

JSON-LD에 없는 나머지는 HTML에서 직접 뽑는다:
  - 경매번호/세션: URL 경로(`/catalogues/lot/<경매번호>-<세션>/...`, 예 "822-1")를
    그대로 `sale_key`로 쓴다 — 같은 경매번호라도 세션이 다르면 별개 auctions 행이 된다.
  - 경매일자: `data-end="YYYY-MM-DD HH:MM:SS"`(입찰 마감 카운트다운) 첫 값.
  - 로트번호: breadcrumb의 `Lot <번호>`.

낙찰가(`offers.price`)가 없는 로트(진행 중/유찰/비공개 추정가만)는 스킵한다 — Grisebach
로더와 동일 관례.

auctions 중복 방지는 Grisebach 로더와 동일 패턴을 쓴다: `get_or_create_auction`의 캐시는
실행 단위라, 재실행 시 같은 세일에 auctions 행이 하나씩 더 생기는 걸 막으려고 DB에서
(경매사, 날짜) -> auction_id 표를 먼저 만들어 재사용한다. 단, 같은 날짜에 서로 다른
sale_key(세션)가 있으면 이 방식이 그 둘을 하나로 합칠 수 있다는 한계도 Grisebach와 동일하게
안고 간다(발견되면 후속 과제로 남길 것 — sale_key까지 DB 컬럼으로 남기려면 스키마 변경 필요).
"""
from __future__ import annotations

import html
import json
import re

from raw_iter import iter_records

SITE_NAME = "lempertz"
HOUSE_NAME = "Kunsthaus Lempertz"

JSONLD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
DATE_RE = re.compile(r'data-end="\s*(\d{4}-\d{2}-\d{2})')
# breadcrumb의 itemprop="name" 배지는 작가 링크가 있는 로트에만 나온다 — 작가 미상(부족
# 미술품 등)인 로트엔 breadcrumb 자체가 다른 모양이라 안 잡힌다(2026-09-22 파일럿 실측,
# African/Oceanic Art 로트 13건에서 전부 미검출로 발견). 항상 존재하는
# `<h1 class="h5 lot-number ...">Lot 50</h1>` 쪽을 대신 쓴다.
LOT_NUMBER_RE = re.compile(r'class="[^"]*\blot-number\b[^"]*">\s*Lot\s+(\d+)')
URL_SALE_KEY_RE = re.compile(r"/catalogues/lot/([^/]+)/")
# JSON-LD의 description은 "&hellip;"로 잘린 요약이다(사이트가 자체적으로 truncate).
# 전문은 별도 <div class="lot-description"><p>...</p></div>에 있다 — 이쪽을 우선 쓴다.
LOT_DESCRIPTION_RE = re.compile(r'<div class="lot-description">\s*<p>(.*?)</p>\s*</div>', re.S)
# JSON-LD의 name도 마찬가지로 원본 데이터 품질 문제가 있다: 작가가 있는 로트는
# "작가 - 제목"으로 멀쩡하지만, 작가 미상 로트는 원래 여러 줄(제목/산지/재질)인 걸 JSON-LD
# 생성 시 구분자 없이 그대로 이어 붙여 "Zulu hat ( Isicholo )Msinga District, South
# AfricaHuman hair..." 처럼 뭉개진다(2026-09-22 실측). `<h2 class="lot-title">`는 같은
# 내용을 줄바꿈 그대로 갖고 있어 첫 줄만 취하면 제목만 깔끔하게 뽑힌다 — 이쪽을 우선 쓴다.
LOT_TITLE_RE = re.compile(r'<h2 class="lot-title">(.*?)</h2>', re.S)
TAG_RE = re.compile(r"<[^>]+>")


def _first_nonempty_line(fragment: str) -> str | None:
    fragment = TAG_RE.sub("", fragment)
    for line in fragment.splitlines():
        line = html.unescape(line).strip()
        if line:
            return line
    return None


def _title_from_h2(page_html: str) -> str | None:
    m = LOT_TITLE_RE.search(page_html)
    if not m:
        return None
    return _first_nonempty_line(m.group(1))


def _full_description(page_html: str) -> str | None:
    m = LOT_DESCRIPTION_RE.search(page_html)
    if not m:
        return None
    fragment = re.sub(r"<br\s*/?>", "\n", m.group(1))
    fragment = TAG_RE.sub("", fragment)
    lines = [html.unescape(line).strip() for line in fragment.splitlines()]
    text = "\n".join(line for line in lines if line)
    return text or None


def _to_float(value) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_lot(page_html: str, url: str | None) -> dict | None:
    m = JSONLD_RE.search(page_html)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None

    offers = data.get("offers") or {}
    hammer_price = _to_float(offers.get("price"))

    creators = offers.get("creator") or []
    artist_name = None
    if isinstance(creators, list) and creators:
        first = creators[0]
        if isinstance(first, dict):
            artist_name = (first.get("name") or "").strip() or None

    title = _title_from_h2(page_html) or (data.get("name") or "").strip() or None
    description = _full_description(page_html) or (
        html.unescape((data.get("description") or "").strip()) or None
    )

    sale_key = None
    if url:
        sm = URL_SALE_KEY_RE.search(url)
        if sm:
            sale_key = sm.group(1)  # 예: "822-1"

    auction_date = None
    dm = DATE_RE.search(page_html)
    if dm:
        auction_date = dm.group(1)

    lot_number = None
    lm = LOT_NUMBER_RE.search(page_html)
    if lm:
        lot_number = lm.group(1)

    return {
        "artist_name": artist_name,
        "title": title,
        "description": description,
        "currency": (offers.get("priceCurrency") or "").strip() or None,
        "estimate_low": _to_float(offers.get("lowPrice")),
        "estimate_high": _to_float(offers.get("highPrice")),
        "hammer_price": hammer_price,
        "sale_key": sale_key,
        "auction_date": auction_date,
        "lot_number": lot_number,
    }


def load(store) -> int:
    loaded = 0
    skipped_no_price = 0
    skipped_unparsed = 0
    auction_ids: dict[str, str] = {}

    house_id = store.get_or_create_auction_house(HOUSE_NAME, country="DE")

    # 증분 재실행 대비: 이미 DB에 있는 Lempertz auctions 행을 날짜로 찾아 재사용
    # (Grisebach 로더와 동일 패턴 — 모듈 독스트링 참고).
    date_to_auction_id: dict[str, str] = {}
    if hasattr(store, "cur"):
        store.cur.execute(
            "select id, auction_date from auctions where auction_house_id = %s and auction_date is not null",
            (house_id,),
        )
        date_to_auction_id = {str(d): str(aid) for aid, d in store.cur.fetchall()}

    for record_id, page_html, meta in iter_records(SITE_NAME, ext="html"):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        parsed = parse_lot(page_html, meta.get("url"))
        if parsed is None:
            skipped_unparsed += 1
            continue
        if parsed["hammer_price"] is None:
            skipped_no_price += 1
            continue

        source_id = store.insert_source(meta)

        sale_key = parsed["sale_key"] or "(경매 미상)"
        auction_id = auction_ids.get(sale_key)
        if auction_id is None:
            auction_date = parsed["auction_date"]
            auction_id = date_to_auction_id.get(auction_date) if auction_date else None
            if auction_id is None:
                auction_id = store.get_or_create_auction(
                    house_id, auction_date, source_id=source_id, sale_key=sale_key
                )
                if auction_date:
                    date_to_auction_id[auction_date] = auction_id
            auction_ids[sale_key] = auction_id

        artist_id = store.get_or_create_artist_safe(parsed["artist_name"], source_id=source_id)
        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=parsed["title"] or "(제목 미상)",
            description=parsed["description"],
            source_id=source_id,
        )
        store.insert_auction_lot_batch(
            auction_id=auction_id,
            artwork_id=artwork_id,
            lot_number=parsed["lot_number"],
            estimate_low=parsed["estimate_low"],
            estimate_high=parsed["estimate_high"],
            currency=parsed["currency"],
            hammer_price=parsed["hammer_price"],
            sold=True,
            source_id=source_id,
        )
        loaded += 1

    store.commit()
    print(
        f"[pipeline:lempertz] {loaded}건 적재, 낙찰가 없어 스킵 {skipped_no_price}건, "
        f"JSON-LD 파싱 실패 {skipped_unparsed}건, 경매(세션 단위) {len(auction_ids)}개"
    )
    return loaded
