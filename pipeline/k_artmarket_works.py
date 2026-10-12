"""K-ARTMARKET 낙찰 작품 DB(raw/k_artmarket_works/) -> auction_houses/auctions/auction_lots 적재.

`crawlers/k_artmarket_works.py`가 저장한 목록 페이지 HTML(48건/페이지)을 파싱한다.
한 항목이 주는 필드:
    list-name       작가명(한글)
    list-engName    작가명(영문)   → artists.name_en 후보이지만 **여기서는 쓰지 않는다**
                                    (기존 artists 행을 이름 유사도로 건드리지 않는다는 원칙)
    list-title      작품명(한글+한자 병기가 섞임)
    list-info-a     재질
    list-info-b     규격(cm / inch / 호수)
    list-price      낙찰가(KRW)
    (그 뒤 span 2개)  경매명, 경매사명
    <P>YYYY-MM-DD</P> 경매일
    data-ucicd      UCI 국가 표준 식별자(I805-…) — 로트 고유 키

경매사(auction_houses)는 한글 이름 그대로 쓴다(서울옥션/케이옥션/칸옥션/마이아트옥션 등).
auctions 행은 **(경매사, 경매일, 경매명)** 조합마다 하나씩 만든다 — store.get_or_create_auction이
(경매사, 날짜)로만 캐싱해서 같은 날 여러 세일이 한 행으로 합쳐지는 기존 한계가 있는데,
K-ARTMARKET은 경매명이 같이 오므로 로더 안에서 (날짜, 경매명) 캐시를 따로 들고
**경매명이 다르면 다른 auctions 행**이 되도록 했다(Bonhams/Getty 로더의 한계를 여기선 회피).

낙찰가만 공개되는 DB라 전 행이 sold=True다(추정가·유찰 정보는 원본에 없음).
UCI가 이미 적재된 로트는 건너뛴다 — 페이지 재수집(--refetch-last)으로 같은 로트가 여러 raw
페이지에 걸쳐 들어와도 중복 적재되지 않는다.
"""
from __future__ import annotations

import html
import re

from raw_iter import iter_records

SITE_NAME = "k_artmarket_works"
INT32_MAX = 2147483647.0  # 출처 쪽 오버플로 sentinel (아래 load() 참고)

ITEM_SPLIT = '<div class="list-box">'
UCI_RE = re.compile(r'data-ucicd="([^"]+)"')
NAME_RE = re.compile(r'<div class="list-name">(.*?)</div>', re.S)
ENG_NAME_RE = re.compile(r'<div class="list-engName">(.*?)</div>', re.S)
TITLE_RE = re.compile(r'<div class="list-title">(.*?)</div>', re.S)
MEDIUM_RE = re.compile(r'<p class="list-info-a">(.*?)</p>', re.S)
INFO_B_RE = re.compile(r'<p class="list-info-b">(.*?)</p>', re.S)
PRICE_RE = re.compile(r'<div class="list-price">(.*?)</div>', re.S)
PRICE_VALUE_RE = re.compile(r"<span>([A-Z]{3})</span>\s*<b>([\d,]+)</b>")
DATE_RE = re.compile(r"<P>(\d{4}-\d{2}-\d{2})</P>")
SPAN_RE = re.compile(r"<span>(.*?)</span>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def _text(fragment: str | None) -> str:
    if not fragment:
        return ""
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", fragment))).strip()


def _first(pattern: re.Pattern[str], chunk: str) -> str:
    m = pattern.search(chunk)
    return _text(m.group(1)) if m else ""


def _person_name(raw: str) -> str | None:
    """작가명 칸이 '-' 같은 자리표시자면 이름이 없는 것으로 본다.

    출처가 작자 미상 행의 작가명 칸에 하이픈만 넣어 두는 경우가 있다
    (예: '백자청화불수감문호'의 작가명이 '-'). 그대로 두면 artists에 '-'라는
    작가 행이 생긴다.
    """
    name = (raw or "").strip()
    if not name or not any(ch.isalnum() for ch in name):
        return None
    return name


def parse_items(page_html: str) -> list[dict]:
    """목록 페이지 HTML에서 로트 dict 목록을 뽑는다."""
    items: list[dict] = []
    for index, chunk in enumerate(page_html.split(ITEM_SPLIT)[1:]):
        # UCI(국가표준식별자)가 **없는 로트가 전체의 약 5%(55,729건 중 2,912건) 있다**.
        # 처음엔 UCI를 필수로 보고 건너뛰었는데, 그러면 그 5%가 통째로 유실된다
        # (2026-09-23 발견 — list-box 블록 수와 파싱 건수를 대조해서 잡았다).
        # UCI는 있으면 실행 내 중복 제거 키로 쓰고, 없으면 페이지 내 순번으로 대체한다.
        uci_match = UCI_RE.search(chunk)
        # 다음 항목까지 넘어가지 않도록 잘라낸다 — UCI가 있으면 그 뒤, 없으면 블록 끝까지.
        chunk = chunk[: uci_match.end() + 200] if uci_match else chunk

        price_block = PRICE_RE.search(chunk)
        currency = hammer_price = None
        if price_block:
            pv = PRICE_VALUE_RE.search(price_block.group(1))
            if pv:
                currency = pv.group(1)
                hammer_price = float(pv.group(2).replace(",", ""))

        # 가격 div 뒤 ~ 날짜 <P> 앞 구간에 span 두 개가 (경매명, 경매사명) 순서로 온다.
        # 위치로만 읽는다(빈 span을 걸러내면 자리가 밀린다).
        # 주의: **출처 데이터 자체가 경매사 칸에 경매명을 그대로 넣어 둔 행이 있다**
        # (예: 두 span 모두 "서울옥션 3월 22일 온라인 경매"). 그대로 쓰면 auction_houses에
        # 세일 이름이 새 경매사로 들어간다 — 2026-09-22 첫 적재에서 실제로 발생해 재적재로
        # 정정했다. 보정은 load()의 `_normalise_house`가 한다(문자열 유사도 아니라,
        # 정상 행에서 모은 경매사 목록에 대한 **정확 접두 일치**만).
        date_match = DATE_RE.search(chunk)
        tail = ""
        if price_block:
            end = date_match.start() if date_match else len(chunk)
            tail = chunk[price_block.end() : end]
        tail_spans = [_text(x) for x in SPAN_RE.findall(tail)]
        sale_name = tail_spans[0] if len(tail_spans) >= 1 else None
        auction_house = tail_spans[1] if len(tail_spans) >= 2 else None
        sale_name = sale_name or None
        auction_house = auction_house or None

        info_b = _first(INFO_B_RE, chunk)

        items.append(
            {
                "uci": uci_match.group(1) if uci_match else f"(no-uci)#{index}",
                "artist_name": _person_name(_first(NAME_RE, chunk)),
                "artist_name_en": _person_name(_first(ENG_NAME_RE, chunk)),
                "title": _first(TITLE_RE, chunk) or None,
                "medium": _first(MEDIUM_RE, chunk) or None,
                "dimensions": info_b or None,
                "currency": currency,
                "hammer_price": hammer_price,
                "sale_name": sale_name,
                "auction_house": auction_house,
                "auction_date": date_match.group(1) if date_match else None,
            }
        )
    return items


def _known_houses() -> list[str]:
    """정상 행(경매사 칸과 경매명 칸이 다른 행)에서 경매사 이름 목록을 모은다.

    출처에 경매사 칸이 경매명으로 채워진 행이 있어(위 parse_items 주석) 그대로 믿으면
    세일 이름이 경매사로 둔갑한다. 여기서 모은 목록은 그런 행을 되살리는 데만 쓰고,
    매칭은 **정확 접두 일치**만 한다(문자열 유사도 매칭 금지 원칙).
    한 글자짜리("꼬" — 출처가 '꼬모옥션'을 잘라 넣은 값)는 제외한다.
    """
    houses: set[str] = set()
    for _record_id, page_html, _meta in iter_records(SITE_NAME, ext="html"):
        for item in parse_items(page_html):
            house, sale = item["auction_house"], item["sale_name"]
            if house and house != sale and len(house) >= 2:
                houses.add(house)
    # 긴 이름부터 맞춰야 "서울옥션"이 "서울옥션스페셜"을 가로채지 않는다.
    return sorted(houses, key=len, reverse=True)


def _normalise_house(item: dict, known: list[str]) -> str | None:
    house, sale = item["auction_house"], item["sale_name"]
    if house and house != sale and len(house) >= 2:
        return house
    # 경매사 칸이 망가진 행 — 경매명 앞부분이 알려진 경매사와 정확히 일치하면 그걸 쓴다.
    for candidate in known:
        if sale and sale.startswith(candidate):
            return candidate
    return None


def build_en_artist_index(store) -> dict[str, str]:
    """영문명 -> artist_id 인덱스. **정확 일치만** 하고, 모호하면 넣지 않는다.

    출처에 한글 작가명이 비고 영문명만 있는 행이 1,103건 있다(전부 한국 작가의 로마자
    표기 — "Paik Nam June", "Pyon Kwan Sik" 등). 이걸 그대로 `get_or_create_artist_safe`에
    넘기면 기존 "백남준"과 별개의 로마자 작가 행이 새로 생겨 **교차언어 중복**을 만든다
    (이 프로젝트가 자동으로 하지 않기로 한 바로 그것). 그래서 새로 만들지는 않고,
    **이미 DB에 있는 artists의 name_en / name과 정확히 일치할 때만** 연결한다.
    같은 name_en을 가진 작가가 둘 이상이면 동명이인 위험이 있어 연결하지 않는다.
    """
    if not hasattr(store, "cur"):
        return {}
    index: dict[str, str] = {}
    store.cur.execute("select lower(name_en), min(id::text), count(*) from artists where name_en is not null group by 1")
    for name_en, artist_id, cnt in store.cur.fetchall():
        if cnt == 1 and name_en:
            index[name_en] = artist_id
    store.cur.execute("select lower(name), min(id::text), count(*) from artists group by 1")
    for name, artist_id, cnt in store.cur.fetchall():
        if cnt == 1 and name and name not in index:
            index[name] = artist_id
    return index


def resolve_artist(store, item: dict, en_index: dict[str, str], source_id: str | None) -> str | None:
    """한글명이 있으면 기존 방식(정확 이름 매칭, 없으면 생성).
    한글명이 없고 영문명만 있으면 **기존 작가와 정확 일치할 때만** 연결(신규 생성 안 함)."""
    if item["artist_name"]:
        return store.get_or_create_artist_safe(item["artist_name"], source_id=source_id)
    name_en = (item["artist_name_en"] or "").strip().lower()
    return en_index.get(name_en) if name_en else None


def load(store) -> int:
    known_houses = _known_houses()
    en_index = build_en_artist_index(store)
    loaded = 0
    skipped_no_house = 0
    skipped_no_price = 0
    skipped_dup = 0
    skipped_bad_price = 0

    # 한 번의 실행 안에서 같은 UCI가 두 페이지에 걸쳐 들어오는 경우를 막는다
    # (정렬 고정 덕에 거의 없지만, 수집 중 신규 낙찰이 들어오면 경계에서 발생 가능).
    # 실행 사이의 중복은 sources.raw_path 기준 스킵이 막는다 — 다만 그 때문에
    # **이미 적재한 페이지를 --refetch-last로 다시 받아도 재적재되지 않는다**.
    # 증분은 "새로 생긴 뒷페이지"로만 들어온다(UCI를 저장할 컬럼이 없어 로트 단위
    # 재판정을 못 하므로, 스키마를 건드리지 않는 선에서 택한 절충).
    seen_uci: set[str] = set()

    auction_cache: dict[tuple[str, str | None, str | None], str] = {}

    for _record_id, page_html, meta in iter_records(SITE_NAME, ext="html"):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        items = parse_items(page_html)
        if not items:
            continue

        source_id = store.insert_source(meta)

        for item in items:
            uci = item["uci"]
            if uci in seen_uci:
                skipped_dup += 1
                continue
            seen_uci.add(uci)

            house_name = _normalise_house(item, known_houses)
            if not house_name:
                skipped_no_house += 1
                continue
            if item["hammer_price"] is None:
                skipped_no_price += 1
                continue
            if item["hammer_price"] == INT32_MAX:
                # 출처 쪽 int32 오버플로 — 서울옥션 홍콩세일 로트 하나가 정확히
                # 2,147,483,647 KRW로 찍혀 있다(2026-09-22 확인, 원본 HTML 값 자체가 그러함).
                # 실제 낙찰가가 아니라 잘린 값이므로 적재하지 않는다.
                skipped_bad_price += 1
                continue

            cache_key = (house_name, item["auction_date"], item["sale_name"])
            auction_id = auction_cache.get(cache_key)
            if auction_id is None:
                house_id = store.get_or_create_auction_house(house_name, country="KR")
                auction_id = store.get_or_create_auction(
                    house_id,
                    item["auction_date"],
                    source_id=source_id,
                    sale_key=f"{item['auction_date']}|{item['sale_name']}",
                )
                auction_cache[cache_key] = auction_id

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
                lot_number=None,  # K-ARTMARKET은 로트번호를 공개하지 않는다
                currency=item["currency"],
                hammer_price=item["hammer_price"],
                sold=True,
                source_id=source_id,
            )
            loaded += 1

    store.commit()
    print(
        f"[pipeline:k_artmarket_works] {loaded}건 적재, "
        f"경매사 없어 스킵 {skipped_no_house}건, 낙찰가 없어 스킵 {skipped_no_price}건, "
        f"출처 가격 오버플로 스킵 {skipped_bad_price}건, 중복 UCI 스킵 {skipped_dup}건"
    )
    return loaded
