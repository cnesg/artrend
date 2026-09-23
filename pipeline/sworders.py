"""Sworders(raw/sworders/) -> auction_houses/auctions/auction_lots 적재.

`crawlers/sworders.py`가 저장한 두 종류의 HTML을 읽는다(실제 도메인은 sworder.co.uk 단수형 —
`crawlers/sworders.py` 모듈독스트링의 도메인 정정 메모 참고. `SITE_NAME`/디렉터리명만
"sworders"로 유지).

1. `sales_<연도>.html` — `/results/?y=YYYY` 연도별 세일 목록. 세일 카드 하나:
     `<a href='/auction/details/<slug>?au=<id>'>` … `<H4>세일명</H4>` …
     `Sale number: A1322` … 날짜는 두 형식이 섞여 있다(과거 연도는 "Date: 11th Dec, 2019
     13:00", 진행 중인 올해는 `<h5>Tuesday 15 September 2026 | 10am</h5>`). 세일 목록 자체는
     로트 데이터가 없으므로 `sources`로 적재하지 않는다(grisebach의 `auction_*.html`,
     kanauction의 `year_*.html`과 같은 위치 — 날짜/식별자 조회용 참고자료).

2. `lot_<au_id>_p<페이지>.html` — `/auction/details/<slug>/?au=<id>&pn=N&pp=96` 로트 목록
   (완전 SSR, 페이지당 최대 96건). 로트 카드 하나(`auction-grid-lot`로 분리):
     `<span class='lot-title cat-N'>Lot <번호><br/><span class="req-tag">...</span>
       <본문 텍스트, 줄바꿈으로 구분>
       [선택: <span class='sub-title ...'>부제(=작품명인 경우가 많다)</span>]
     </span>`
     `<strong>Sold for £X</strong>` 또는 `<strong>Estimated at £X - £Y</strong>`(유찰)

   sale-type(부서)에 따라 본문 텍스트 형식이 둘로 갈린다 — 직접 확인한 두 예:
     · Fine Interiors류(가구/장식미술 포함): 본문에 짧은 설명 + `sub-title` span에 제작연대
       ("A George III tortoiseshell... tea caddy" / sub-title "late 18th/early 19th century,")
     · Modern British and 20th Century Art류: `sub-title` 없이 본문이 그대로
       "작가명 (생몰년)\n작품명\n매체/설명"으로 줄바꿈 구분.

   **작가 판정 기준(스코프 필터)**: 첫 줄이 "이름 (국적, YYYY-YYYY)" / "이름 (YYYY-YYYY)" /
   "이름 (b.YYYY)" 패턴에 매치할 때만 작가로 인정한다 — 괄호 안에 4자리 연도가 없으면
   (가구·도자기 등 장식미술, "English School" 같은 익명 귀속) 작가를 비워 둔다. 이 자체가
   Bonhams의 WOA 부서 제외(장식미술 스코프 제외)와 같은 효과를 낸다 — 별도 부서 필터 없이도
   가구/장식품이 자연히 걸러진다. "After / Attributed to / Circle of / Manner of / Follower
   of / School of / Studio of / In the manner of" 같은 귀속 한정어 접두사는 원작자 표기가
   아니므로 이름에서 제거하지 않고 **통째로 스킵**한다(원작자로 잘못 연결하지 않기 위함 —
   `get_or_create_artist_safe`의 정확 이름 매칭 원칙과 같은 보수적 태도).

   작가는 이름 정확 매칭만 쓴다(이름 유사도 병합 금지). 통화는 전부 GBP(£) 고정.
"""
from __future__ import annotations

import html as html_lib
import re

from raw_iter import RAW_ROOT, iter_records

SITE_NAME = "sworders"
HOUSE_NAME = "Sworders"

# --- sales_*.html 파싱 ---------------------------------------------------

SALE_CARD_SPLIT = 'class="auction-calendar-item'
SLUG_AU_RE = re.compile(r"/auction/details/([a-z0-9-]+)\?au=(\d+)")
SALE_NUMBER_RE = re.compile(r"Sale number:\s*([^<]+?)\s*<")
TITLE_RE = re.compile(r"<H4>(.*?)</H4>", re.I | re.S)
# 과거 연도: "Date: 11th Dec, 2019 13:00"
DATE_TEXT_RE = re.compile(r"Date:\s*(\d{1,2})(?:st|nd|rd|th)\s+([A-Za-z]{3,9}),?\s*(\d{4})")
# 진행 중인 올해: "<h5>Tuesday 15 September 2026 | 10am</h5>" 또는 기간 표기
# "<h5>Tuesday 8 September - Monday 14 September 2026</h5>"(첫날만 취한다)
DATE_H5_RE = re.compile(
    r"<h5>[A-Za-z]+\s+(\d{1,2})\s+([A-Za-z]+)"
    r"(?:\s*-\s*[A-Za-z]+\s+\d{1,2}\s+[A-Za-z]+)?\s+(\d{4})",
    re.I,
)
# 이틀짜리 세일: "Lot: 1 to 506 - 3rd Dec, 2019 10:00"(첫날만 취한다)
DATE_LOT_RANGE_RE = re.compile(
    r"Lot:\s*\d+\s*to\s*\d+\s*-\s*(\d{1,2})(?:st|nd|rd|th)\s+([A-Za-z]{3,9}),?\s*(\d{4})"
)
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _month_num(name: str) -> int | None:
    return MONTHS.get(name[:3].lower())


def parse_sales(page_html: str) -> list[dict]:
    sales: list[dict] = []
    for chunk in page_html.split(SALE_CARD_SPLIT)[1:]:
        chunk = chunk[:2500]
        slug_au = SLUG_AU_RE.search(chunk)
        if not slug_au:
            continue
        slug, au_id = slug_au.groups()

        sale_number = SALE_NUMBER_RE.search(chunk)
        title = TITLE_RE.search(chunk)

        date_str = None
        for pattern in (DATE_TEXT_RE, DATE_H5_RE, DATE_LOT_RANGE_RE):
            m = pattern.search(chunk)
            if not m:
                continue
            day, mon, year = m.groups()
            mnum = _month_num(mon)
            if mnum:
                date_str = f"{int(year):04d}-{mnum:02d}-{int(day):02d}"
                break

        sales.append(
            {
                "slug": slug,
                "au_id": au_id,
                "sale_number": html_lib.unescape(sale_number.group(1)).strip() if sale_number else None,
                "title": html_lib.unescape(TAG_RE.sub(" ", title.group(1))).strip() if title else None,
                "auction_date": date_str,
            }
        )
    return sales


def _sale_meta() -> dict[str, dict]:
    """저장된 sales_*.html 전부에서 au_id -> {sale_number, auction_date, title} 표를 만든다."""
    meta: dict[str, dict] = {}
    for path in sorted((RAW_ROOT / SITE_NAME).glob("sales_*.html")):
        for item in parse_sales(path.read_text(encoding="utf-8")):
            meta.setdefault(item["au_id"], item)
    return meta


# --- lot_<au_id>_p<N>.html 파싱 -------------------------------------------

LOT_CARD_SPLIT = "auction-grid-lot"
LOT_TITLE_RE = re.compile(r"<span class='lot-title[^']*'>Lot\s*(\d+)<br\s*/?>(.*?)</span>\s*</a>", re.S)
REQ_TAG_RE = re.compile(r'<span class="req-tag">.*?</span>', re.S)
SUBTITLE_RE = re.compile(r"<span class='sub-title[^']*'>(.*?)</span>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
SOLD_RE = re.compile(r"Sold for\s*£\s*([\d,]+)")
ESTIMATE_RE = re.compile(r"Estimated at\s*£\s*([\d,]+)\s*-\s*£\s*([\d,]+)")

# "이름 (국적, YYYY-YYYY)" / "이름 (YYYY-YYYY)" / "이름 (b.YYYY)" / "이름 (British, b. 1950)"
ARTIST_LINE_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<paren>[^()]*)\)\s*$")
YEAR_IN_PAREN_RE = re.compile(r"(?:^|,\s*)(?:b\.\s*)?(\d{4})(?:\s*[-–]\s*(\d{4}))?\s*$")
# 원작자가 아니라 귀속 한정어가 붙은 경우 — 원작자로 잘못 연결하지 않기 위해 스킵한다.
ATTRIBUTION_QUALIFIER_RE = re.compile(
    r"^(after|attributed to|circle of|manner of|in the manner of|follower of|school of|studio of|style of)\b",
    re.I,
)


def _clean_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(TAG_RE.sub(" ", fragment))).strip()


GENERIC_LEAD_RE = re.compile(r"^(a|an|the)\b", re.I)


def _parse_artist_line(line: str) -> tuple[str | None, str | None, int | None, int | None]:
    m = ARTIST_LINE_RE.match(line.strip())
    if not m:
        return None, None, None, None
    name = m.group("name").strip()
    if ATTRIBUTION_QUALIFIER_RE.match(name):
        return None, None, None, None
    # 장식미술 설명문 끝에 우연히 역사적 인물의 생몰년이 괄호로 붙는 경우가 있다
    # (예: "A rare ... centaur in the form of General Redvers Buller (1839-1908)" —
    # 이건 C J Spooner가 만든 회전목마 장식이지 Buller가 작가가 아니다). 사람 이름은
    # 보통 짧으므로(존칭·후명사 포함해도 대개 60자 미만) 길거나 "A/An/The"로 시작하는
    # 설명문 스타일 줄은 작가 귀속으로 보지 않는다.
    if len(name) > 60 or GENERIC_LEAD_RE.match(name):
        return None, None, None, None
    paren = m.group("paren").strip()
    ym = YEAR_IN_PAREN_RE.search(paren)
    if not ym:
        return None, None, None, None
    birth = int(ym.group(1))
    death = int(ym.group(2)) if ym.group(2) else None
    nationality = paren[: ym.start()].rstrip(", ").strip() or None
    return name, nationality, birth, death


def parse_lots(page_html: str) -> list[dict]:
    items: list[dict] = []
    for chunk in page_html.split(LOT_CARD_SPLIT)[1:]:
        chunk = chunk[:4000]
        title_match = LOT_TITLE_RE.search(chunk)
        if not title_match:
            continue
        lot_number, body = title_match.groups()
        body = REQ_TAG_RE.sub("", body)

        subtitle_match = SUBTITLE_RE.search(body)
        if subtitle_match:
            main_text = body[: subtitle_match.start()]
            trailing_lines: list[str] = []
            title = _clean_text(subtitle_match.group(1)).rstrip(",").strip("'\" ").strip()
        else:
            main_text = body
            trailing_lines = []
            title = None

        lines = [_clean_text(x) for x in main_text.split("\n")]
        lines = [x for x in lines if x]

        artist_name = nationality = None
        birth_year = death_year = None
        rest_lines = lines
        if lines:
            artist_name, nationality, birth_year, death_year = _parse_artist_line(lines[0])
            if artist_name:
                rest_lines = lines[1:]

        if artist_name is None:
            continue  # 스코프 밖(장식미술/익명/귀속한정어) — 적재하지 않는다

        if title is None:
            title = rest_lines[0].strip("'\" ").strip() if rest_lines else None
            medium_lines = rest_lines[1:]
        else:
            medium_lines = rest_lines
        medium = " / ".join(medium_lines + trailing_lines) or None

        sold = SOLD_RE.search(chunk)
        estimate = ESTIMATE_RE.search(chunk)

        items.append(
            {
                "lot_number": lot_number,
                "artist_name": artist_name,
                "nationality": nationality,
                "birth_year": birth_year,
                "death_year": death_year,
                "title": title or "(제목 미상)",
                "medium": medium,
                "hammer_price": float(sold.group(1).replace(",", "")) if sold else None,
                "estimate_low": float(estimate.group(1).replace(",", "")) if estimate else None,
                "estimate_high": float(estimate.group(2).replace(",", "")) if estimate else None,
            }
        )
    return items


def load(store) -> int:
    sale_meta = _sale_meta()
    loaded = 0
    skipped_not_sold = 0
    skipped_no_artist_pages = 0
    auction_ids: dict[str, str] = {}

    house_id = store.get_or_create_auction_house(HOUSE_NAME, country="GB")

    for record_id, page_html, meta in iter_records(SITE_NAME, ext="html"):
        if not record_id.startswith("lot_"):
            continue  # sales_*.html은 세일 메타(날짜/세일번호) 조회용 — sources로 적재하지 않는다
        if store.source_already_loaded(meta["raw_path"]):
            continue

        au_id = record_id.split("_")[1]
        items = parse_lots(page_html)
        if not items:
            skipped_no_artist_pages += 1
            continue
        source_id = store.insert_source(meta)

        info = sale_meta.get(au_id, {})
        auction_id = auction_ids.get(au_id)
        if auction_id is None:
            auction_id = store.get_or_create_auction(
                house_id,
                info.get("auction_date"),
                source_id=source_id,
                sale_key=info.get("sale_number") or f"au{au_id}",
            )
            auction_ids[au_id] = auction_id

        for item in items:
            if item["hammer_price"] is None:
                skipped_not_sold += 1
                continue

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
                medium=item["medium"],
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

    store.commit()
    print(
        f"[pipeline:sworders] {loaded}건 적재, 유찰/작가없음 스킵 {skipped_not_sold}건, "
        f"작가 매치 로트 0건 페이지 {skipped_no_artist_pages}개, 세일 {len(auction_ids)}개"
    )
    return loaded
