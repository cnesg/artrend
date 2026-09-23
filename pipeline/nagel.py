"""Nagel Auktionen(raw/nagel/) -> auction_houses/auctions/auction_lots 적재.

`crawlers/nagel.py`가 저장한 세 종류의 HTML을 읽는다.

1. `result_lists.html` — 경매 코드·부문명·날짜(연도 헤더 + 표)를 담은 단일 페이지.
   sources로는 적재하지 않고(파생 참고자료) 코드 -> 날짜 표를 만드는 데만 쓴다.
2. `catalog_<code>.html` — 코드별 카탈로그 목록(사전판매용 추정가만, 낙찰가 없음).
   sources로도 적재하지 않는다 — `crawlers/nagel.py`가 로트 링크 추출용으로만 쓴 것이고
   실제 로트 데이터는 전부 로트 상세 페이지에 있다.
3. `lot_<code>_<lot_id><suffix>.html` — 로트 상세 페이지 한 장에 필요한 게 전부 있다:

    <p><span style="color: #808080;">Lot 79</span></p>
    <h1><b>Chagall, Marc</b></h1>                              ← 작가명 또는 무명 공예품 제목
    <p>Estimated Value:</p><h4><strong>1.000 € - 2.000 €</strong></h4>
    <section class="… zuschlagspreis" data-value="3.108 €">    ← 낙찰가(구매수수료 포함).
      …                                                            유찰이면 data-value=""
    <div class="… auction-description"><h4>Description:</h4>
      Witebsk, 1887 - Saint-Paul-de-Vence, 1985<br />37 x 28 cm, R.<br />
      Untitled, 1948. Colour lithograph from the series "…".<br />…
    </div>

   **작가 판정에 주의할 점**(칸옥션과 같은 함정): Description 첫 줄이 "도시, YYYY - 도시,
   YYYY" 생몰년 패턴이면 h1 내용을 작가명으로, 아니면(예: "Ancient Gandhara region,
   2nd/3rd cent. AD" 같은 산지·시대 표기) h1 내용을 무명 공예품의 작품 제목으로 본다.
   생몰년 패턴이 확인된 경우에만 `get_or_create_artist_safe`에 이름+생몰년을 넘긴다
   (LLM 생성 아님 — 원문에서 직접 파싱한 사실 데이터, 칸옥션 로더와 동일 원칙).

낙찰가는 **구매수수료+부가세 포함가**다("incl. Premium and VAT") — Grisebach(구매수수료
포함, 부가세 별도 표기)·Bonhams(해머 프라이스)와 각각 정의가 달라, 소스 간 가격 비교는
원래부터 source를 봐야 하는 구조다.

카탈로그 페이지가 남아있는 회차만(2026-09-22 확인 기준 대략 2023년 이후) 로트 상세를
수집하므로, 이 로더가 처리하는 lot_*.html도 자연히 그 범위로 한정된다.
"""
from __future__ import annotations

import html
import re

from raw_iter import RAW_ROOT, iter_records

SITE_NAME = "nagel"
HOUSE_NAME = "Nagel Auktionen"

TAG_RE = re.compile(r"<[^>]+>")
LOT_NUM_RE = re.compile(r'<p><span style="color: #808080;">Lot ([^<]+)</span></p>')
NAME_RE = re.compile(r"<h1><b>(.*?)</b></h1>", re.S)
ESTIMATE_RE = re.compile(r"<p>Estimated Value:</p>\s*<h4><strong>([^<]*)</strong></h4>")
RESULT_RE = re.compile(r'class="av_textblock_section zuschlagspreis" data-value="([^"]*)"')
DESC_RE = re.compile(
    r'<div class="avia_textblock auction-description"[^>]*>\s*<h4>Description:</h4>\s*(.*?)\s*</div>',
    re.S,
)
BR_RE = re.compile(r"<br\s*/?>")

# "Witebsk, 1887 - Saint-Paul-de-Vence, 1985" / "Berlin, 1900 - 1980" 같은 생몰년 패턴.
# "Ancient Gandhara region, 2nd/3rd cent. AD" 같은 산지·시대 표기는 매치되지 않는다.
LIFE_DATES_RE = re.compile(r",\s*(1[4-9]\d{2}|20\d{2})\s*[-–]\s*(?:[^,]*,\s*)?(1[4-9]\d{2}|20\d{2})\.?\s*$")
DIM_RE = re.compile(r"[\d.,]+(?:\s*x\s*[\d.,]+)?\s*cm\b", re.I)
YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")

LOT_URL_RE = re.compile(r"auction_uid=(\d+)&lot_id=(\d+)&suffix=([^&]*)")

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "januar": 1, "februar": 2, "märz": 3, "mai": 5, "juni": 6, "juli": 7,
    "oktober": 10, "dezember": 12,
}
FULL_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
YEAR_IN_TEXT_RE = re.compile(r"\b(20\d{2})\b")
DAY_MONTH_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\.?\s+([A-Za-zÄÖÜäöü]+)")
MONTH_DAY_RE = re.compile(r"([A-Za-zÄÖÜäöü]+)\s+(\d{1,2})(?:st|nd|rd|th)?")

YEAR_HEADER_RE = re.compile(r'itemprop="headline"[^>]*>(\d{4})</h1>')
RESULT_ROW_RE = re.compile(
    r"<td[^>]*>(\d+)</td>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>",
    re.S,
)
# 연도 헤더와 표 행을 문서 순서대로 함께 훑기 위한 결합 패턴
ROW_OR_YEAR_RE = re.compile(
    r'itemprop="headline"[^>]*>(?P<year>\d{4})</h1>'
    r"|<td[^>]*>(?P<code>\d+)</td>\s*<td[^>]*>(?P<division>[^<]*)</td>\s*<td[^>]*>(?P<datetext>[^<]*)</td>",
    re.S,
)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", fragment))).strip()


def _parse_price_de(text: str | None) -> float | None:
    if not text:
        return None
    text = text.replace("€", "").strip()
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_estimate(text: str | None) -> tuple[float | None, float | None]:
    if not text:
        return None, None
    parts = text.split("-")
    if len(parts) != 2:
        return None, None
    return _parse_price_de(parts[0]), _parse_price_de(parts[1])


def parse_lot(page_html: str) -> dict:
    lot_m = LOT_NUM_RE.search(page_html)
    name_m = NAME_RE.search(page_html)
    est_m = ESTIMATE_RE.search(page_html)
    result_m = RESULT_RE.search(page_html)
    desc_m = DESC_RE.search(page_html)

    lot_number = _text(lot_m.group(1)) if lot_m else None
    name_text = _text(name_m.group(1)) if name_m else None
    estimate_low, estimate_high = _parse_estimate(est_m.group(1)) if est_m else (None, None)
    hammer_price = _parse_price_de(result_m.group(1)) if result_m else None

    lines = []
    if desc_m:
        lines = [_text(chunk) for chunk in BR_RE.split(desc_m.group(1))]
        lines = [l for l in lines if l]

    artist_name = None
    birth_year = death_year = None
    title = name_text
    year_created = None
    dimensions = None

    if lines:
        life_m = LIFE_DATES_RE.search(lines[0])
        if life_m and name_text:
            artist_name = name_text
            birth_year = int(life_m.group(1))
            death_year = int(life_m.group(2))
            rest = lines[1:]
            if rest and DIM_RE.search(rest[0]) and len(rest[0]) < 40:
                dimensions = rest[0]
                rest = rest[1:]
            title = " ".join(rest).strip() or None
            if title:
                ym = YEAR_RE.search(title)
                if ym:
                    year_created = ym.group(1)
        else:
            # 무명 공예품 — h1이 이미 제목이고, description 전체가 산지·시대·설명이다.
            for l in lines[:2]:
                dm = DIM_RE.search(l)
                if dm:
                    dimensions = dm.group(0)
                    break

    description_text = " ".join(lines) if lines else None

    return {
        "lot_number": lot_number,
        "artist_name": artist_name,
        "birth_year": birth_year,
        "death_year": death_year,
        "title": title or name_text,
        "year_created": year_created,
        "dimensions": dimensions,
        "description": description_text,
        "estimate_low": estimate_low,
        "estimate_high": estimate_high,
        "hammer_price": hammer_price,
    }


def _parse_auction_date(date_text: str, section_year: int | None) -> str | None:
    m = FULL_DATE_RE.search(date_text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"

    ym = YEAR_IN_TEXT_RE.search(date_text)
    year = int(ym.group(1)) if ym else section_year

    dm = DAY_MONTH_RE.search(date_text)
    if dm:
        day, month_name = dm.group(1), dm.group(2)
    else:
        dm2 = MONTH_DAY_RE.search(date_text)
        day, month_name = (dm2.group(2), dm2.group(1)) if dm2 else (None, None)

    if month_name:
        month = MONTHS.get(month_name.lower())
        if month and day and year:
            try:
                return f"{year:04d}-{month:02d}-{int(day):02d}"
            except ValueError:
                pass

    if year:
        return f"{year:04d}-01-01"
    return None


def _auction_meta() -> dict[str, dict]:
    """result_lists.html에서 코드 -> {division, date_text, year, auction_date} 표를 만든다."""
    path = RAW_ROOT / SITE_NAME / "result_lists.html"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    meta: dict[str, dict] = {}
    current_year: int | None = None
    for m in ROW_OR_YEAR_RE.finditer(text):
        if m.group("year"):
            current_year = int(m.group("year"))
            continue
        code = m.group("code")
        division = html.unescape(m.group("division")).strip()
        date_text = html.unescape(m.group("datetext")).strip()
        meta[code] = {
            "division": division,
            "date_text": date_text,
            "year": current_year,
            "auction_date": _parse_auction_date(date_text, current_year),
        }
    return meta


RAW_PATH_CODE_RE = re.compile(r"lot_(\d+)_")


def _code_to_auction_id(store, house_id: str) -> dict[str, str]:
    """이미 DB에 있는 nagel auction_lots를 raw_path에서 코드로 역산해 code -> auction_id 표를 만든다.

    Grisebach 로더가 겪은 것과 같은 문제(재실행 시 같은 경매에 auctions 행이 하나 더 생기는 것)를
    막기 위함 — auctions 테이블 자체에는 코드를 저장할 컬럼이 없어서(sale_key는 클라이언트 캐시일
    뿐 영속화되지 않음), 이미 적재된 로트의 source raw_path에서 역으로 코드를 구해 재사용한다.
    날짜가 아니라 코드로 매칭하는 이유: 같은 날 다른 부문 경매가 동시에 열리는 경우가 있어서
    (예: 836·837이 둘 다 2025-11-11) auction_date만으로는 서로 다른 경매가 합쳐질 위험이 있다.
    """
    mapping: dict[str, str] = {}
    if not hasattr(store, "cur"):
        return mapping
    store.cur.execute(
        """
        select distinct s.raw_path, al.auction_id
        from auction_lots al
        join sources s on s.id = al.source_id
        where s.site_name = 'nagel' and al.auction_id in (
            select id from auctions where auction_house_id = %s
        )
        """,
        (house_id,),
    )
    for raw_path, auction_id in store.cur.fetchall():
        m = RAW_PATH_CODE_RE.search(raw_path)
        if m:
            mapping.setdefault(m.group(1), str(auction_id))
    return mapping


def load(store) -> int:
    auction_meta = _auction_meta()
    loaded = 0
    skipped_not_sold = 0
    skipped_no_lot_number = 0

    house_id = store.get_or_create_auction_house(HOUSE_NAME, country="DE")
    auction_ids: dict[str, str] = _code_to_auction_id(store, house_id)

    for record_id, page_html, meta in iter_records(SITE_NAME, ext="html"):
        if not record_id.startswith("lot_"):
            continue  # result_lists.html / catalog_*.html은 파생 참고자료 — sources로 적재 안 함
        if store.source_already_loaded(meta["raw_path"]):
            continue

        url_m = LOT_URL_RE.search(meta.get("url") or "")
        code = url_m.group(1) if url_m else None
        if code is None:
            continue

        item = parse_lot(page_html)
        if not item["lot_number"]:
            skipped_no_lot_number += 1
            continue
        if item["hammer_price"] is None:
            skipped_not_sold += 1
            continue

        source_id = store.insert_source(meta)

        auction_id = auction_ids.get(code)
        if auction_id is None:
            am = auction_meta.get(code, {})
            auction_id = store.get_or_create_auction(
                house_id,
                am.get("auction_date"),
                source_id=source_id,
                sale_key=code,
            )
            auction_ids[code] = auction_id

        artist_id = (
            store.get_or_create_artist_safe(
                item["artist_name"],
                birth_year=item["birth_year"],
                death_year=item["death_year"],
                # 국적은 넣지 않는다 — 경매사 소재지(독일)로 국적을 추정하면
                # 프랑스/러시아 등 다른 국적 작가에 틀린 값이 들어간다(칸옥션과 동일 원칙).
                source_id=source_id,
            )
            if item["artist_name"]
            else None
        )

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=item["title"] or "(제목 미상)",
            year_created=item["year_created"],
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
            currency="EUR",
            hammer_price=item["hammer_price"],
            sold=True,
            source_id=source_id,
        )
        loaded += 1

    store.commit()
    print(
        f"[pipeline:nagel] {loaded}건 적재, 유찰/미상 스킵 {skipped_not_sold}건, "
        f"로트번호 없음 스킵 {skipped_no_lot_number}건, 경매 {len(auction_ids)}회차"
    )
    return loaded
