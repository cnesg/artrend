"""칸옥션(raw/kanauction/) -> auction_houses/auctions/auction_lots 적재.

`crawlers/kanauction.py`가 저장한 지난경매 목록 페이지 HTML(10건/페이지)을 파싱한다.
한 항목의 구조:

    <ul class="article">
      <!--li …>A000006736</li-->                         ← 로트 고유 id
      <span class="">제44회 미술품경매</span>             ← 회차(세일) 이름
      <span class="lot">Lot. 001</span>
      <span class="title">
        평보 平步 <span class='title'>서희환 徐喜煥</span> 1934-1998 이천 利川 <br /></span>
                     ↑ 호·한자        ↑ 작가명(한글+한자)   ↑ 생몰년  ↑ 본관
      <span class="aucTitle">믿음은 산 같이<br/>
        1979년 | 종이에 먹 | 31.5x130cm</span>
      <span class="price">추정가 KRW 800,000 - 2,000,000</span>
      <span class="price">낙찰가 KRW <font>1,300,000</font></span>   ← 유찰이면 아예 없음

작가 판정에 주의할 점이 두 가지 있다.

1. 안쪽 `<span class='title'>`이 **작가가 아니라 작품명인 경우가 있다**
   (예: "금강산십곡병 金剛山十曲屛" — 작자 미상 고미술). 이때는 span 뒤에 생몰년 대신
   " - "만 온다. 그래서 **span 바로 뒤에 4자리 연도가 오는 경우에만** 작가로 인정한다.
2. 한 로트에 작가가 둘인 경우가 있다(예: "백윤문 白潤文 화" + "정인보 鄭寅普 제" =
   그림과 글씨를 다른 사람이 함). artworks.artist_id가 하나뿐이라 **첫 번째만** 연결한다.

작가명은 "서희환 徐喜煥"처럼 한글+한자가 붙어 오므로 앞쪽 한글 덩어리만 canonical name으로
쓴다(`^[가-힣]+`). 이름 유사도 병합은 하지 않는다 — `get_or_create_artist_safe`의
정확 이름 매칭만 쓴다.

경매 날짜: 목록에 **날짜가 없다**(회차명만). 지어내지 않기 위해 크롤러가 연도별 검색
필터로 "그 해의 첫 회차/마지막 회차"만 따로 받아 두었고(`year_*.html`), 목록이 날짜
오름차순이라는 성질을 이용해 회차→연도를 정확히 판정한 뒤 `YYYY-01-01`로 적재한다
(연도만 아는 소스를 다루는 기존 관례, raw_iter.year_to_date와 같은 방식).
연·월·일까지 필요한 2022년 이후 국내 로트는 K-ARTMARKET 소스 쪽에 정확한 날짜와 함께
들어 있다.
"""
from __future__ import annotations

import html
import re

from raw_iter import RAW_ROOT, iter_records, year_to_date

SITE_NAME = "kanauction"
HOUSE_NAME = "칸옥션"

ITEM_SPLIT = '<ul class="article">'
ITEM_ID_RE = re.compile(r">(A\d{6,})<")
SALE_RE = re.compile(r'<span class="">([^<]*)</span>')
LOT_RE = re.compile(r'<span class="lot">\s*Lot\.\s*([^<]*)</span>')
ARTIST_BLOCK_RE = re.compile(r'<span class="title">(.*?)</span>\s*(?=<span class="aucTitle")', re.S)
INNER_ARTIST_RE = re.compile(r"<span class='title'>(.*?)</span>(.{0,40})", re.S)
AUC_TITLE_RE = re.compile(r'<span class="aucTitle">(.*?)</span>\s*<br', re.S)
ESTIMATE_RE = re.compile(r"추정가\s*<span class=\"won\">KRW</span>\s*([\d,]+)\s*-\s*([\d,]+)")
HAMMER_RE = re.compile(r"낙찰가\s*<span class=\"won\">KRW</span>\s*<font[^>]*>\s*([\d,]+)\s*</font>")
BR_RE = re.compile(r"<br\s*/?>")
SPWORD_RE = re.compile(r'<span class="spWord">\|</span>')
TAG_RE = re.compile(r"<[^>]+>")
HANGUL_RUN_RE = re.compile(r"[가-힣]+(?:\s+[가-힣]+)*")
BIRTH_AFTER_RE = re.compile(r"^\s*(\d{4})\s*-\s*(\d{4})?")


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", fragment))).strip()


def _to_int(value: str | None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_artist(chunk: str) -> tuple[str | None, int | None, int | None]:
    block = ARTIST_BLOCK_RE.search(chunk)
    if not block:
        return None, None, None
    for inner, after in INNER_ARTIST_RE.findall(block.group(1)):
        raw_name = _text(inner)
        if not raw_name:
            continue
        birth = BIRTH_AFTER_RE.match(html.unescape(TAG_RE.sub(" ", after)))
        if not birth:
            # 생몰년이 안 붙으면 작가가 아니라 작품명일 수 있다(작자미상 고미술) — 건너뛴다.
            continue
        hangul = HANGUL_RUN_RE.match(raw_name)
        name = (hangul.group(0) if hangul else raw_name).strip()
        return name or None, _to_int(birth.group(1)), _to_int(birth.group(2))
    return None, None, None


def parse_items(page_html: str) -> list[dict]:
    items: list[dict] = []
    for chunk in page_html.split(ITEM_SPLIT)[1:]:
        chunk = chunk.split("</ul>")[0]
        id_match = ITEM_ID_RE.search(chunk)
        if not id_match:
            continue

        title = year_created = medium = dimensions = None
        auc = AUC_TITLE_RE.search(chunk)
        if auc:
            parts = BR_RE.split(auc.group(1))
            title = _text(parts[0]) or None
            if len(parts) > 1:
                fields = [_text(x) for x in SPWORD_RE.split(parts[1])]
                year_created = fields[0] if len(fields) > 0 and fields[0] else None
                medium = fields[1] if len(fields) > 1 and fields[1] else None
                dimensions = fields[2] if len(fields) > 2 and fields[2] else None

        estimate = ESTIMATE_RE.search(chunk)
        hammer = HAMMER_RE.search(chunk)
        sale = SALE_RE.search(chunk)
        lot = LOT_RE.search(chunk)
        artist_name, birth_year, death_year = _parse_artist(chunk)

        items.append(
            {
                "item_id": id_match.group(1),
                "sale_name": _text(sale.group(1)) if sale else None,
                "lot_number": _text(lot.group(1)) if lot else None,
                "artist_name": artist_name,
                "birth_year": birth_year,
                "death_year": death_year,
                "title": title,
                "year_created": year_created,
                "medium": medium,
                "dimensions": dimensions,
                "estimate_low": float(estimate.group(1).replace(",", "")) if estimate else None,
                "estimate_high": float(estimate.group(2).replace(",", "")) if estimate else None,
                "hammer_price": float(hammer.group(1).replace(",", "")) if hammer else None,
            }
        )
    return items


def _sale_year_map() -> dict[str, int]:
    """year_*.html(연도별 첫/마지막 회차)로 '회차명 -> 연도' 표를 만든다.

    목록 전체가 날짜 오름차순이므로, 연도 Y의 첫 회차와 마지막 회차 사이에 있는 회차는
    전부 Y년 것이다. 여기서는 그 경계 회차명 자체만 모으면 되고, 사이를 메우는 건
    load()가 전체 목록 순서를 훑으면서 한다.
    """
    bounds: dict[int, list[str]] = {}
    for path in sorted((RAW_ROOT / SITE_NAME).glob("year_*.html")):
        year = int(path.stem.split("_")[1])
        items = parse_items(path.read_text(encoding="utf-8"))
        names = [i["sale_name"] for i in items if i["sale_name"]]
        if not names:
            continue
        bounds.setdefault(year, [])
        bounds[year].append(names[0] if path.stem.endswith("first") else names[-1])
    return {name: year for year, names in bounds.items() for name in names}


def load(store) -> int:
    boundary_year = _sale_year_map()
    loaded = 0
    skipped_not_sold = 0
    seen_items: set[str] = set()
    auction_ids: dict[str, str] = {}
    sale_year: dict[str, int] = {}
    current_year: int | None = None

    house_id = store.get_or_create_auction_house(HOUSE_NAME, country="KR")

    for _record_id, page_html, meta in iter_records(SITE_NAME, ext="html"):
        if _record_id.startswith("year_"):
            continue  # 연도 경계표는 sources로 적재하지 않는다(파생 참고자료)
        if store.source_already_loaded(meta["raw_path"]):
            continue

        items = parse_items(page_html)
        if not items:
            continue
        source_id = store.insert_source(meta)

        for item in items:
            if item["item_id"] in seen_items:
                continue
            seen_items.add(item["item_id"])

            sale_name = item["sale_name"] or "(회차 미상)"
            # 날짜 오름차순 순회 중이므로, 경계 회차를 만나면 그 이후는 그 해로 본다.
            if sale_name in boundary_year:
                current_year = boundary_year[sale_name]
            if sale_name not in sale_year and current_year is not None:
                sale_year[sale_name] = current_year

            if item["hammer_price"] is None:
                skipped_not_sold += 1
                continue

            auction_id = auction_ids.get(sale_name)
            if auction_id is None:
                auction_id = store.get_or_create_auction(
                    house_id,
                    year_to_date(sale_year.get(sale_name)),
                    source_id=source_id,
                    sale_key=sale_name,
                )
                auction_ids[sale_name] = auction_id

            artist_id = store.get_or_create_artist_safe(
                item["artist_name"],
                birth_year=item["birth_year"],
                death_year=item["death_year"],
                # 국적은 넣지 않는다 — 국내 경매사지만 중국 작가(옹동화 翁同龢 등)도
                # 다루므로 경매사 소재지로 국적을 추정하면 틀린 값이 들어간다.
                source_id=source_id,
            ) if item["artist_name"] else None

            artwork_id = store.insert_artwork(
                artist_id=artist_id,
                title=item["title"] or "(제목 미상)",
                year_created=item["year_created"],
                medium=item["medium"],
                dimensions=item["dimensions"],
                source_id=source_id,
            )
            store.insert_auction_lot_batch(
                auction_id=auction_id,
                artwork_id=artwork_id,
                lot_number=item["lot_number"],
                estimate_low=item["estimate_low"],
                estimate_high=item["estimate_high"],
                currency="KRW",
                hammer_price=item["hammer_price"],
                sold=True,
                source_id=source_id,
            )
            loaded += 1

    store.commit()
    print(
        f"[pipeline:kanauction] {loaded}건 적재, 유찰(낙찰가 없음) 스킵 {skipped_not_sold}건, "
        f"세일 {len(auction_ids)}개, 연도 판정된 세일 {len(sale_year)}개"
    )
    return loaded
