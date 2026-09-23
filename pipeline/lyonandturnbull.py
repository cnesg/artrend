"""Lyon & Turnbull(raw/lyonandturnbull/) -> auction_houses/auctions/auction_lots 적재.

`crawlers/lyonandturnbull.py`가 저장한 두 종류의 JSON을 읽는다(모두 사이트의 Next.js
`__NEXT_DATA__` 블록을 원문 그대로 저장한 것 — 재직렬화 없음).

1. `past_auctions_list.json` — `/auctions/past-auctions`의 `props.pageProps.auctionsListData`
   (경매 310건: title/saleNumber/date/arrowLink/auctionId/department). 로트 데이터가 없으므로
   sources로 적재하지 않는다(sworders의 sales_*.html과 같은 위치 — 목록 조회 전용).

2. `sale_<saleNumber>.json` — 개별 경매 페이지의 `props.pageProps`. 핵심은
   `pageProps.lots`(로트 배열). 로트 하나(실측 스키마):
     {
       "lot_no": "2", "title": {"en": "LEON MORROCCO R.S.A., R.G.I. (SCOTTISH 1942-)"},
       "dynamic_fields": {"en": {"sub_title": "AFTERNOON BRUNCH AT BOMBAY - 2010"}},
       "low": "600.00", "high": "800.00", "hammer_price": "850.00",
       "status": "sold" | "unsold",
       "auction": {"currency": {"symbol": "£"}, "start_date": "...Z"},
       "session_date": "...Z",
     }

   **작가는 별도 필드가 없다** — `title.en`이 "이름 (전미)  (국적 YYYY-YYYY)" 형태로 작가명과
   생몰년을 담고, 실제 작품명은 `dynamic_fields.sub_title`에 있다(sworders/grisebach와 반대
   레이아웃). 이 사이트는 Bonhams류처럼 정형화된 작가 표기를 쓰고, 장식미술(Asian Art 등)은
   parenthetical 없이 순수 설명문 제목만 나와 자연히 걸러진다(직접 확인: 913회 Asian Works of
   Art 254개 로트 중 237개가 괄호 없음 = 작가 없음으로 정확히 스킵됨).

   **작가 판정 기준**: title이 `이름 (괄호내용)` 로 끝날 때만 후보로 본다(선행 "[...]" 출처
   브래킷은 벗겨낸다). 다음은 전부 스킵(작가로 연결하지 않음):
     - 이름 또는 괄호 안에 " AND "가 있으면(공동작가·복수인물) — auction_lots.artist_id는
       하나뿐이라 잘못 연결하는 대신 스킵.
     - 이름이 "After / Attributed to / Circle of / Manner of / In the manner of / Follower of /
       School of / Studio of / Style of"로 시작하면(원작자 귀속 한정어) — 원작자로 오연결 방지.
     - 괄호 안에 "CA." / "AC." / "POSS"(possibly)가 있으면(불확실한 활동시기·귀속) — 스킵.
     - 괄호 안에 4자리 연도가 하나도 없으면 — 작가 아님(장식미술 설명문).
   국적은 괄호 내용에서 연도 앞부분을 취하고 "FL./B./D./CA./AC." 접미 약어를 제거해 정리한다.

   이름/존칭(예: "SIR WILLIAM RUSSELL FLINT P.R.A., ...")은 그대로 저장한다(sworders와 동일
   원칙 — 이름 유사도 병합 금지, 정확 매칭만). **알려진 한계**: 같은 인물도 판마다 존칭 나열
   순서가 달라 서로 다른 artists 행으로 들어갈 수 있다(직접 확인: "ANNE REDPATH O.B.E., R.S.A.,
   A.R.A., A.R.W.S., ..." vs "..., A.R.A., L.L.D., A.R.W.S., ..." — 순서만 다름). 이름 유사도
   병합은 프로젝트 정책상 금지라 자동 정리하지 않는다 — 필요하면 별도 authority-ID 기반 병합
   과제로 남긴다.

   경매 단위 식별은 saleNumber(파일명에서 추출)를 sale_key로 쓴다. 날짜는 로트의
   `auction.start_date`(ISO, 없으면 `session_date`)에서 YYYY-MM-DD만 취한다. 통화는 전부
   GBP(£) 고정.
"""
from __future__ import annotations

import html as html_lib
import re

from raw_iter import RAW_ROOT, iter_records

SITE_NAME = "lyonandturnbull"
HOUSE_NAME = "Lyon & Turnbull"

BRACKET_PREFIX_RE = re.compile(r"^\[[^\]]*\]\s*")
ARTIST_LINE_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<paren>[^()]*)\)\s*$")
ATTRIBUTION_QUALIFIER_RE = re.compile(
    r"\b(after|attributed to|circle of|manner of|in the manner of|follower of|school of|studio of|style of)\b",
    re.I,
)
# 장식미술/가구/공예품은 "A/An/The ..." 식 설명문으로 시작하는 경우가 압도적으로 많다
# (sworders.py에서 검증된 패턴 재사용 — 예: "A SCOTTISH OAK ORKNEY CHAIR, REYNOLD EUNSON").
# 이런 설명문 안에 우연히 제작자 이름+생몰년이 괄호로 붙어도 작가로 연결하지 않는다.
GENERIC_LEAD_RE = re.compile(r"^(a|an|the)\b", re.I)
YEAR_RE = re.compile(r"\d{4}")
TRAILING_DATE_ABBR_RE = re.compile(r"\b(fl\.?|b\.|d\.|ca\.|ac\.)\s*$", re.I)


def _parse_artist_from_title(title_en: str) -> tuple[str | None, str | None, int | None, int | None]:
    if not title_en:
        return None, None, None, None
    text = BRACKET_PREFIX_RE.sub("", title_en.strip())
    m = ARTIST_LINE_RE.match(text)
    if not m:
        return None, None, None, None
    name = m.group("name").strip()
    paren = m.group("paren").strip()

    if not name or not paren:
        return None, None, None, None
    if " AND " in name.upper() or " AND " in paren.upper():
        return None, None, None, None  # 공동작가/복수인물 — 단일 artist_id로 연결 못 함
    if ATTRIBUTION_QUALIFIER_RE.search(name):
        return None, None, None, None  # 귀속 한정어(문중 어디에 있든) — 원작자 아님
    if GENERIC_LEAD_RE.match(name) or len(name) > 60:
        return None, None, None, None  # 설명문 스타일(장식미술/가구 등) — 작가 아님
    if re.search(r"\d", name):
        return None, None, None, None  # 사람 이름에 숫자 없음 — 위스키 연산("LAPHROAIG 15
        # YEAR OLD (1990)") 같은 상품명이 괄호 안 연도와 우연히 매치되는 오탐 방지
    if re.search(r"\bca\.|\bac\.|\bposs|\bcirca\b|\bfl\.?\b|\bc\.?\s?\d{4}", paren, re.I):
        # fl.(flourished/활동시기)는 생몰년이 아니라 활동 확인 시점이라 birth_year/death_year에
        # 넣으면 사실과 다른 데이터가 된다 — 저장하지 않고 보수적으로 스킵. "C1685-1767"처럼
        # circa를 공백/마침표 없이 "C"+연도로 축약한 표기도 실측으로 확인해 같이 잡는다
        # (직접 확인: "CHRISTIAN FRIEDRICH ZINCKE (GERMAN C1685-1767)").
        return None, None, None, None  # 불확실한 활동시기/귀속 — 보수적으로 스킵

    years = YEAR_RE.findall(paren)
    if not years:
        return None, None, None, None  # 연도 없음 = 장식미술 설명문일 가능성 높음

    first_year_pos = YEAR_RE.search(paren).start()
    nationality_raw = paren[:first_year_pos]
    nationality = TRAILING_DATE_ABBR_RE.sub("", nationality_raw).strip(" ,.")
    nationality = nationality or None

    birth_year = int(years[0])
    death_year = int(years[1]) if len(years) > 1 else None
    return name, nationality, birth_year, death_year


def _sale_key_and_date(record_id: str, lots: list[dict]) -> tuple[str, str | None]:
    sale_key = record_id.split("_", 1)[1] if "_" in record_id else record_id
    auction_date = None
    for lot in lots:
        raw_date = (lot.get("auction") or {}).get("start_date") or lot.get("session_date")
        if raw_date:
            auction_date = str(raw_date)[:10]
            break
    return sale_key, auction_date


def parse_lots(page_data: dict) -> list[dict]:
    pp = page_data.get("props", {}).get("pageProps", {})
    lots = pp.get("lots") or []
    items: list[dict] = []
    for lot in lots:
        if lot.get("status") != "sold":
            continue
        hammer_raw = lot.get("hammer_price")
        try:
            hammer_price = float(hammer_raw) if hammer_raw is not None else None
        except (TypeError, ValueError):
            hammer_price = None
        if not hammer_price:
            continue

        title_en = ((lot.get("title") or {}).get("en") or "").strip()
        artist_name, nationality, birth_year, death_year = _parse_artist_from_title(title_en)
        if artist_name is None:
            continue

        sub_title = ((lot.get("dynamic_fields") or {}).get("en") or {}).get("sub_title")
        work_title = html_lib.unescape(sub_title).strip() if sub_title else None
        if work_title:
            work_title = work_title.strip("'\" -").strip()

        def _num(key: str) -> float | None:
            raw = lot.get(key)
            try:
                return float(raw) if raw is not None else None
            except (TypeError, ValueError):
                return None

        items.append(
            {
                "lot_number": lot.get("lot_no"),
                "artist_name": artist_name,
                "nationality": nationality,
                "birth_year": birth_year,
                "death_year": death_year,
                "title": work_title or "(제목 미상)",
                "hammer_price": hammer_price,
                "estimate_low": _num("low"),
                "estimate_high": _num("high"),
            }
        )
    return items, lots


def load(store) -> int:
    loaded = 0
    skipped_no_artist = 0
    auction_ids: dict[str, str] = {}

    house_id = store.get_or_create_auction_house(HOUSE_NAME, country="GB")

    for record_id, data, meta in iter_records(SITE_NAME, ext="json"):
        if record_id == "past_auctions_list":
            continue  # 목록 전용, 로트 데이터 없음 — sources로 적재하지 않는다
        if not record_id.startswith("sale_"):
            continue
        if store.source_already_loaded(meta["raw_path"]):
            continue

        items, all_lots = parse_lots(data)
        if not all_lots:
            continue
        source_id = store.insert_source(meta)

        sale_key, auction_date = _sale_key_and_date(record_id, all_lots)
        auction_id = auction_ids.get(sale_key)
        if auction_id is None:
            auction_id = store.get_or_create_auction(
                house_id, auction_date, source_id=source_id, sale_key=sale_key,
            )
            auction_ids[sale_key] = auction_id

        for item in items:
            artist_id = store.get_or_create_artist_safe(
                item["artist_name"],
                nationality=item["nationality"],
                birth_year=item["birth_year"],
                death_year=item["death_year"],
                source_id=source_id,
            )
            artwork_id = store.insert_artwork(
                artist_id=artist_id,
                title=item["title"],
                source_id=source_id,
            )
            store.insert_auction_lot_batch(
                auction_id=auction_id,
                artwork_id=artwork_id,
                lot_number=item["lot_number"],
                estimate_low=item["estimate_low"],
                estimate_high=item["estimate_high"],
                currency="GBP",
                hammer_price=item["hammer_price"],
                sold=True,
                source_id=source_id,
            )
            loaded += 1
        skipped_no_artist += len(all_lots) - len(items)

    store.commit()
    print(
        f"[pipeline:lyonandturnbull] {loaded}건 적재, 작가없음/유찰 등 스킵 {skipped_no_artist}건, "
        f"세일 {len(auction_ids)}개"
    )
    return loaded
