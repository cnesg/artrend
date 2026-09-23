"""Auktionshaus im Kinsky(raw/im_kinsky/) -> auction_houses/auctions/auction_lots 적재.

`crawlers/im_kinsky.py`가 저장한 로트 상세 페이지 HTML(로트 1건 = 파일 1건)을 읽는다.
수집 경위·robots.txt/ToS 판정 근거는 크롤러 독스트링과
`docs/logs/경매확장_imkinsky_20260923.md`.

로트 상세 페이지는 완전 SSR이고 구조가 매우 일정하다(`<article data-art-object="...">`):

    <header><h2>Auction: Contemporary Art</h2><p class="intro">30. June 2022, 5:00 pm</p></header>
    <div class="txt">
      <h1>2228</h1>                                    <- 로트번호
      <div class="artist"><h3><a href="/en/artists/108312">Xenia Hausner</a>*</h3>
                          <p>(Wien 1951)</p></div>     <- 작가 + 생몰 표기
      <p>제목<br>제작연도<br>재질<br>규격<br>서명</p>
      <h3>Provenance</h3><p>...</p>                    <- 소장이력 원문
      <h3>Exhibition</h3><p>...</p>
      <h3>Literature</h3><p>...</p>
      <p class="price">Estimate: € 50.000 - 80.000<br>Realized price: € 111.850
                       (incl. fees and Austrian VAT)<br>Hammer Price: € 85.000</p>
    </div>

**가격 정의가 이 소스의 강점이다.** im Kinsky는 수수료·VAT 포함가("Realized price")와
순수 낙찰가("Hammer Price")를 **분리해서** 표기한다. `auction_lots.hammer_price`에는
**Hammer Price(수수료 제외)** 를 넣는다 — Lempertz(`offers.price` = 프리미엄 포함),
Durán("VENDIDO POR", 포함 여부 불명)과 정의가 다르니 소스 간 가격 비교 시 주의.
수수료 포함가는 버리지 않고 description에 `[Realized price (incl. fees/VAT)]` 라벨로 보존한다.

추정가는 `Estimate: € low - high` 구간이 기본이지만, 2026년 일부 로트처럼
`Starting bid: € 50.000` 단일값만 있는 경우가 있다 — 그때는 kogirekai/Durán 로더와 같은
관례로 `estimate_low`에만 넣고 `estimate_high`는 None으로 둔다.

**Provenance / Exhibition / Literature로 provenance_records·collectors·exhibitions 행을
만들지 않는다.** 원문이 세미콜론으로 이어 붙은 자유 텍스트(`"1996 Galerie Heike Curtze
(Berliner Kunstausstellung); since then private property, Germany"`)라 그대로 구조화하면
"private property"류 익명 일반명사가 collectors에 쌓인다 — 2026-09-15 재진단에서 걷어낸
가비지 유형이다(Durán 로더와 동일 원칙). `artworks.description`에 라벨 줄로 원문만
보존하고, 구조화는 나중에 `provenance_extract.py` 계열 후처리에 맡긴다.

**작가 이름은 원문 표기 그대로 둔다**(im Kinsky는 "이름 성" 정순으로 표기). 생몰년은
작가 링크가 **정확히 1명**일 때만 괄호 표기에서 읽는다 — 공동작 로트는 괄호 안에 두 작가의
연도가 섞여 있어 잘못 매칭될 수 있다. 국적은 넣지 않는다(경매사 소재지로 국적을 추정하면
다른 국적 작가에 틀린 값이 들어간다 — nagel/kanauction/Durán과 동일 원칙).
공동작 로트는 첫 작가를 `artworks.artist_id`로 쓰고 전체 명단을 description에 보존한다.

`sale_key`는 세일 경로(`"139/723/2"`) — 같은 경매(회차) 안에서도 부문별 세션마다 별개
auctions 행이 된다. `auctions.name`에는 "<경매명> — <세션명>"을 채운다(경매명은 크롤러가
남긴 `raw/im_kinsky/_index.json`에서 가져온다).
"""
from __future__ import annotations

import html as html_mod
import json
import re

from bs4 import BeautifulSoup

from raw_iter import RAW_ROOT, iter_records

SITE_NAME = "im_kinsky"
HOUSE_NAME = "Auktionshaus im Kinsky"
HOUSE_COUNTRY = "Austria"
CURRENCY_DEFAULT = "EUR"

INDEX_PATH = RAW_ROOT / SITE_NAME / "_index.json"

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    # 독문 표기가 섞인 오래된 세일 대비
    "jänner": 1, "januar": 1, "februar": 2, "märz": 3, "mai": 5, "juni": 6,
    "juli": 7, "oktober": 10, "dezember": 12,
}

DATE_RE = re.compile(r"(\d{1,2})\.\s*([A-Za-zÄÖÜäöüß]+)\s+(\d{4})")
# "1996" / "2025 - 2026" / "1970/71" / "um 1900" / "(1930)" 처럼 '연도만'인 줄
YEAR_LINE_RE = re.compile(
    r"^(?:um|ca\.?|about|circa|c\.)?\s*\(?\s*\d{3,4}\s*(?:[-/–—]\s*\d{2,4}\s*)?\)?$", re.I
)
# 연도가 아니라 '세기/시기' 표기인 줄 — 골동품(Antiques) 로트는 제작연도 대신 이런 줄이 온다.
# 예: "15th/16th century", "France, 15th century", "probably France, 1st half 17th century",
#     "late 15th century", "15th/16th century (poles), 17th century (angels)"
PERIOD_LINE_RE = re.compile(r"(?i)\bcentur(?:y|ies)\b|\bjahrhundert\b")
# 사이트 작가 페이지로 링크돼 있지만 실제 인물이 아니라 '작가 미상' 표기인 항목.
# 이런 이름으로 artists 행을 만들면 2026-09-15 재진단에서 걷어낸 익명 가비지가 다시 쌓인다.
# ("Master of ..."류 notname은 미술사에서 통용되는 정식 명칭이므로 제외하지 않는다.)
ANON_ARTIST_RE = re.compile(
    r"(?i)^(?:artists?|painters?|sculptors?|k(?:ü|ue)nstler)\s+(?:of|des|der)\s+.*|"
    r"^(?:anonym|anonymous|unknown|unbekannt)\b"
)
# "Studio of <a>Michael Pacher</a>" 처럼 작가 링크 앞에 붙는 귀속 한정어.
ATTRIBUTION_TRAIL_RE = re.compile(r"\s*(?:,|;|\*)+\s*$")
# "150 x 126 cm" / "H. 24 cm" / "34,5 x 27 cm (Blattmaß)"
DIM_RE = re.compile(r"\d[\d\s.,]*\s*(?:x|×)?\s*[\d\s.,]*\s*(?:cm|mm)\b", re.I)
MONEY_RE = re.compile(r"(?:(€|EUR|ATS|öS|S)\s*)?([\d][\d.\s]*(?:,\d+)?)")
SECTION_LABELS = {"provenance", "exhibition", "literature", "expertise", "certificate"}


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    text = html_mod.unescape(text)
    text = text.replace("\xa0", " ").replace("​", "")
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text or None


def _lines(tag) -> list[str]:
    """<br>로 끊어진 <p> 하나를 줄 리스트로."""
    raw = tag.decode_contents()
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", "", raw)
    out = []
    for line in raw.splitlines():
        line = _clean(line)
        if line:
            out.append(line)
    return out


def _to_float(raw: str | None) -> float | None:
    """'50.000' / '111.850' / '34,5' -> float (유럽 표기: . = 천 단위, , = 소수점)."""
    if not raw:
        return None
    s = raw.replace(" ", "").replace("\xa0", "")
    s = s.replace(".", "").replace(",", ".")
    try:
        value = float(s)
    except ValueError:
        return None
    return value


def _money(fragment: str) -> tuple[float | None, str | None]:
    m = MONEY_RE.search(fragment)
    if not m:
        return None, None
    symbol = (m.group(1) or "").strip()
    currency = None
    if symbol in ("€", "EUR"):
        currency = "EUR"
    elif symbol in ("ATS", "öS", "S"):
        currency = "ATS"
    return _to_float(m.group(2)), currency


def parse_date(date_text: str | None) -> str | None:
    """'30. June 2022, 5:00 pm' -> '2022-06-30'."""
    if not date_text:
        return None
    m = DATE_RE.search(date_text)
    if not m:
        return None
    day, month_name, year = m.group(1), m.group(2).lower(), m.group(3)
    month = MONTHS.get(month_name)
    if not month:
        return None
    return f"{int(year):04d}-{month:02d}-{int(day):02d}"


def parse_prices(price_text: str) -> dict:
    """p.price 텍스트에서 추정가/수수료포함가/순수낙찰가를 뽑는다."""
    text = _clean(price_text) or ""
    # '▲'(정상과세 표시) 등 기호는 값 추출에 방해만 되므로 제거
    text = text.replace("▲", " ")
    out = {
        "estimate_low": None, "estimate_high": None, "hammer_price": None,
        "realized_price": None, "currency": None, "estimate_is_starting_bid": False,
    }

    def _segment(label: str) -> str | None:
        m = re.search(
            rf"{label}\s*:?(.*?)(?=Estimate|Starting bid|Realized price|Hammer Price|Auction is|$)",
            text, re.I | re.S,
        )
        return m.group(1) if m else None

    est = _segment("Estimate")
    if est:
        parts = re.split(r"\s[-–—]\s", est)
        low, cur = _money(parts[0])
        out["estimate_low"] = low
        out["currency"] = out["currency"] or cur
        if len(parts) > 1:
            high, cur2 = _money(parts[1])
            out["estimate_high"] = high
            out["currency"] = out["currency"] or cur2
    else:
        start = _segment("Starting bid")
        if start:
            low, cur = _money(start)
            out["estimate_low"] = low
            out["estimate_is_starting_bid"] = True
            out["currency"] = out["currency"] or cur

    realized = _segment("Realized price")
    if realized:
        value, cur = _money(realized)
        out["realized_price"] = value
        out["currency"] = out["currency"] or cur

    hammer = _segment("Hammer Price")
    if hammer:
        value, cur = _money(hammer)
        out["hammer_price"] = value
        out["currency"] = out["currency"] or cur

    return out


def parse_lot(page_html: str) -> dict | None:
    soup = BeautifulSoup(page_html, "html.parser")
    article = soup.select_one("article[data-art-object]")
    if article is None:
        return None
    txt = article.select_one("div.txt")
    if txt is None:
        return None

    lot_id = article.get("data-art-object")

    sale_title = None
    header = article.find("header")
    if header:
        h2 = header.find("h2")
        if h2:
            sale_title = re.sub(r"(?i)^\s*auction\s*:\s*", "", _clean(h2.get_text(" ")) or "").strip() or None
    intro = article.select_one("p.intro")
    date_text = _clean(intro.get_text(" ")) if intro else None

    h1 = txt.find("h1")
    lot_number = _clean(h1.get_text(" ")) if h1 else None

    # 작가는 **사이트 작가 페이지로 링크된 <a>만** 인정한다. 골동품(Antiques) 로트는 같은
    # 자리에 링크 없는 <h3>로 사물 이름("Gothic cassette")이 들어오는데, 그걸 작가로 받으면
    # 익명/사물명 가비지가 artists에 쌓인다(2026-09-15 재진단에서 걷어낸 유형).
    artist_names: list[str] = []
    artist_site_ids: list[str] = []
    anon_artist_label = None
    object_name = None
    attribution_qualifier = None
    birth_year = death_year = None
    artist_div = txt.select_one("div.artist")
    if artist_div:
        h3 = artist_div.find("h3")
        links = artist_div.select("h3 a[href*='/artists/']")
        for a in links:
            name = _clean(a.get_text(" "))
            if not name:
                continue
            href = a.get("href") or ""
            am = re.search(r"/artists/(\d+)", href)
            if ANON_ARTIST_RE.match(name):
                anon_artist_label = anon_artist_label or name
                continue
            artist_names.append(name)
            if am:
                artist_site_ids.append(am.group(1))
        if links and h3 is not None:
            # 링크 앞의 텍스트("Studio of", "Attributed to" 등)를 귀속 한정어로 분리한다.
            head = h3.decode_contents().split("<a", 1)[0]
            head = _clean(re.sub(r"(?s)<[^>]+>", " ", head))
            if head:
                attribution_qualifier = ATTRIBUTION_TRAIL_RE.sub("", head).strip().lower() or None
        if not links and h3 is not None:
            object_name = _clean(ATTRIBUTION_TRAIL_RE.sub("", h3.get_text(" ")))
        # 생몰년은 작가가 정확히 1명일 때만(공동작은 괄호 안에 두 작가 연도가 섞임)
        years_p = artist_div.find("p")
        if years_p is not None and len(artist_names) == 1:
            years = [int(y) for y in re.findall(r"\b(\d{4})\b", years_p.get_text(" "))]
            years = [y for y in years if 1000 <= y <= 2100]
            if len(years) == 1:
                birth_year = years[0]
            elif len(years) >= 2:
                birth_year, death_year = years[0], years[-1]
                if death_year < birth_year:
                    birth_year = death_year = None

    # 본문: div.artist 다음의 첫 <p>(클래스 없음)가 제목/연도/재질/규격/서명 블록
    detail_lines: list[str] = []
    sections: dict[str, str] = {}
    price_text = None
    seen_body = False
    current_label = None
    for child in txt.find_all(["p", "h3"], recursive=False):
        classes = child.get("class") or []
        if child.name == "h3":
            label = (_clean(child.get_text(" ")) or "").rstrip(":")
            current_label = label if label.lower() in SECTION_LABELS else label
            continue
        if "price" in classes:
            price_text = child.get_text("\n")
            continue
        if current_label:
            value = "\n".join(_lines(child))
            if value:
                sections[current_label] = value
            current_label = None
            continue
        if not seen_body:
            detail_lines = _lines(child)
            seen_body = True

    # 작가 링크가 없는 로트(골동품 등)는 <h3>의 사물 이름이 제목이고 본문은 전부
    # 제작시기/재질/규격이다. 작가가 있는 로트는 본문 첫 줄이 제목이다.
    if object_name:
        title = object_name
        body_lines = detail_lines
    else:
        title = detail_lines[0] if detail_lines else None
        body_lines = detail_lines[1:]
    # 제목은 독일식 인용부호로 감싸여 온다(„Untitled“) — 바깥 한 겹만 벗긴다.
    if title and title.startswith("„") and title.endswith("“"):
        title = title[1:-1].strip() or title

    year_created = medium = dimensions = None
    leftovers: list[str] = []
    for line in body_lines:
        if year_created is None and (YEAR_LINE_RE.match(line) or PERIOD_LINE_RE.search(line)):
            if not DIM_RE.search(line):
                # 괄호로 '감싸인' 경우에만 벗긴다 — "…(poles), 17th century (angels)"처럼
                # 괄호가 문장 중간에 있는 줄에 strip("()")를 쓰면 닫는 괄호만 잘려 나간다.
                if line.startswith("(") and line.endswith(")"):
                    line = line[1:-1].strip()
                year_created = line
                continue
        if dimensions is None and DIM_RE.search(line):
            dimensions = line
            continue
        if medium is None:
            medium = line
            continue
        leftovers.append(line)

    prices = parse_prices(price_text or "")

    desc_parts: list[str] = []
    if len(artist_names) > 1:
        desc_parts.append("[Artists] " + "; ".join(artist_names))
    if anon_artist_label:
        # artists 행은 만들지 않되 원문 표기는 버리지 않는다.
        desc_parts.append(f"[Attribution] {anon_artist_label}")
    if attribution_qualifier:
        # "studio of" / "attributed to" 등 귀속 한정어. `artworks.attribution_qualifier`
        # 컬럼이 있지만 `store.insert_artwork`의 배치 컬럼 목록에 없어 지금은 채울 수 없다
        # (store.py는 다른 세션이 동시에 수정 중이라 건드리지 않는다). 원문을 여기 보존해
        # 두면 나중에 `mark_getty_attribution.py`류 후처리가 컬럼으로 승격할 수 있다.
        desc_parts.append(f"[Attribution] {attribution_qualifier}")
    if leftovers:
        desc_parts.append("[Details] " + " / ".join(leftovers))
    for label in ("Provenance", "Exhibition", "Literature"):
        for key, value in sections.items():
            if key.lower() == label.lower():
                desc_parts.append(f"[{label}] {value}")
    for key, value in sections.items():
        if key.lower() not in ("provenance", "exhibition", "literature"):
            desc_parts.append(f"[{key}] {value}")
    if prices["realized_price"] is not None:
        desc_parts.append(
            f"[Realized price (incl. fees/VAT)] {prices['currency'] or CURRENCY_DEFAULT} "
            f"{prices['realized_price']:.0f}"
        )
    if prices["estimate_is_starting_bid"]:
        desc_parts.append("[Note] estimate_low is a starting bid, not an estimate range")

    return {
        "lot_id": lot_id,
        "lot_number": lot_number,
        "sale_title": sale_title,
        "date_text": date_text,
        "auction_date": parse_date(date_text),
        "artist_name": artist_names[0] if artist_names else None,
        "artist_names": artist_names,
        "artist_site_ids": artist_site_ids,
        "attribution_qualifier": attribution_qualifier,
        "anon_artist_label": anon_artist_label,
        "object_name": object_name,
        "birth_year": birth_year,
        "death_year": death_year,
        "title": title,
        "year_created": year_created,
        "medium": medium,
        "dimensions": dimensions,
        "description": "\n".join(desc_parts) or None,
        "provenance": sections.get("Provenance"),
        "estimate_low": prices["estimate_low"],
        "estimate_high": prices["estimate_high"],
        "hammer_price": prices["hammer_price"],
        "realized_price": prices["realized_price"],
        "currency": prices["currency"] or CURRENCY_DEFAULT,
    }


def _sale_path_from_record_id(record_id: str) -> str:
    # "139_723_2_91213" -> "139/723/2"
    parts = record_id.split("_")
    return "/".join(parts[:3]) if len(parts) >= 4 else record_id


def _auction_titles() -> dict[str, str]:
    """크롤러가 남긴 _index.json에서 sale_path -> '<경매명> — <세션명>' 표를 만든다."""
    if not INDEX_PATH.exists():
        return {}
    try:
        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    for sale in index.get("sales", []):
        path = (sale.get("path") or "").replace("/en/auction-results/", "")
        if not path:
            continue
        auction_title = _clean(sale.get("auction_title"))
        sale_title = _clean(sale.get("title"))
        name = " — ".join(part for part in (auction_title, sale_title) if part)
        if name:
            out[path] = name
    return out


def load(store, limit: int | None = None) -> int:
    loaded = 0
    skipped_no_price = 0
    skipped_unparsed = 0
    auction_ids: dict[str, str] = {}

    house_id = store.get_or_create_auction_house(HOUSE_NAME, country=HOUSE_COUNTRY)
    sale_names = _auction_titles()
    print(f"[pipeline:im_kinsky] 경매명 표 {len(sale_names)}건(_index.json)")

    for record_id, page_html, meta in iter_records(SITE_NAME, ext="html"):
        if limit is not None and loaded >= limit:
            break
        if store.source_already_loaded(meta["raw_path"]):
            continue

        parsed = parse_lot(page_html)
        if parsed is None:
            skipped_unparsed += 1
            continue
        if parsed["hammer_price"] is None:
            # 유찰/미공개 로트 — 기존 경매 로더들과 동일하게 스킵한다.
            skipped_no_price += 1
            continue

        source_id = store.insert_source(meta)

        sale_key = _sale_path_from_record_id(record_id)
        auction_id = auction_ids.get(sale_key)
        if auction_id is None:
            auction_id = store.get_or_create_auction(
                house_id, parsed["auction_date"], source_id=source_id, sale_key=sale_key
            )
            auction_ids[sale_key] = auction_id
            # auctions.name은 store 인터페이스가 채우지 않아 여기서 직접 채운다
            # (세일 이름이 없으면 같은 날짜의 여러 부문 세션을 구분할 수 없다).
            name = sale_names.get(sale_key) or parsed["sale_title"]
            if name and hasattr(store, "cur"):
                store.cur.execute(
                    "update auctions set name = %s where id = %s and name is null",
                    (name, auction_id),
                )

        artist_id = store.get_or_create_artist_safe(
            parsed["artist_name"],
            birth_year=parsed["birth_year"],
            death_year=parsed["death_year"],
            source_id=source_id,
        )
        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=parsed["title"] or "(제목 미상)",
            year_created=parsed["year_created"],
            medium=parsed["medium"],
            dimensions=parsed["dimensions"],
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
        f"[pipeline:im_kinsky] {loaded}건 적재, 낙찰가 없어 스킵 {skipped_no_price}건, "
        f"파싱 실패 {skipped_unparsed}건, 경매(세션 단위) {len(auction_ids)}개"
    )
    return loaded
