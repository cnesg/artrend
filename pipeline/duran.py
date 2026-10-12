"""Durán Arte y Subastas(raw/duran/) -> auction_houses/auctions/auction_lots 적재.

`crawlers/duran.py`가 저장한 로트 상세 페이지 HTML(로트 1건 = 파일 1건)과 경매 목록
페이지(`_index.html`)를 읽는다. 수집 경위·ToS 판정 근거는 크롤러 독스트링과
`docs/logs/경매확장_setdart_20260923.md`.

구조화 필드는 전부 가시 HTML의 라벨-값 쌍(`div.caracteristicas-ficha` 안의
`col-xs-4`=라벨 / `col-xs-8`=값)에 있다:
  - `Autor`   -> "MIRÓ FERRÁ, JOAN (1893 - 1983)" — **"성, 이름" 순서 그대로 둔다**
                 (Lempertz 로더와 동일 원칙: 이름 순서를 뒤집는 추측성 변환은 로더가
                 하지 않는다. 그건 `merge_name_order_dup_artists.py` 같은 명시적 병합 단계 몫).
                 괄호 안 생몰년은 `(1893 - 1983)` / `(1957)` 형태일 때만 숫자로 받고,
                 `(S. XX)`(세기 표기)처럼 연도가 아닌 것은 버린다.
  - `Título`, `Técnica`(->medium), `Medidas`(->dimensions), `Procedencia`, `Observaciones`
  - 자유 기술: `div.single-lot-desc-content > p`
  - 가격: `p.pre-title`("Precio salida") / `p.pre-title-principal`("VENDIDO POR") 옆의
    `p.pre-price`. 통화 기호는 €(EUR) 고정.

**낙찰가는 "VENDIDO POR"** 하나뿐이고 수수료 포함 여부가 사이트에 명시돼 있지 않다 —
Lempertz(프리미엄 포함)·Grisebach와 가격 정의가 다를 수 있으니 소스 간 비교 시 주의.

**추정가 구간이 없다.** Durán은 "Precio salida"(출발가) 한 값만 공개한다 — kogirekai
로더와 같은 관례로 `estimate_low`에만 넣고 `estimate_high`는 None으로 둔다(추정가 구간이
아니라 단일 출발가라는 뜻).

**`Procedencia`로 provenance_records/collectors를 만들지 않는다.** 실제 값이 "Colección
particular"(개인 소장) 같은 익명 일반명사가 대부분이라 그대로 collectors 행을 만들면
2026-09-15 재진단에서 걷어낸 익명/일반명사 가비지를 다시 쌓게 된다. 대신 artworks.description
끝에 `[Procedencia] ...` 라벨 줄로 원문만 보존한다(나중에 실명 컬렉션만 골라 구조화할 때 근거로 씀).

**`ANÓNIMO ...`(익명) 작가 행은 만들지 않는다.** 카탈로그에 "ANÓNIMO ESPAÑOL S. XX" 류가
다수 있는데, 이는 작가가 아니라 작가 미상 표기다 — 같은 재진단에서 확정된 가비지 유형이라
artist_id=None으로 두고 artwork만 적재한다.

경매일자는 로트 페이지가 아니라 `_index.html`(과거 경매 목록)의 카드에서 읽는다
(`AUCTION_<refSession>_<codSub>.jpg` 썸네일 + `div.fechas > p`의 dd-mm-yyyy). 로트 페이지에도
세션 시작시각이 있지만 그건 실시간 입찰 블롭 안에 있고, 그 블롭은 입찰자 개인정보 때문에
크롤러가 저장 전에 제거한다.

`sale_key`는 경매 회차 코드(예 "658") — 같은 날짜에 다른 회차가 열려도 별개 auctions 행이 된다.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from raw_iter import iter_records

SITE_NAME = "duran"
HOUSE_NAME = "Durán Arte y Subastas"
HOUSE_COUNTRY = "Spain"  # 기존 auction_houses 행(Q138110615)의 표기와 맞춘다

INDEX_RECORD_ID = "_index"

# 경매 카드: 썸네일 파일명(AUCTION_<refSession>_<codSub>.jpg) 뒤의 div.fechas > p
AUCTION_CARD_RE = re.compile(
    r'AUCTION_(\d+)_(\d+)\.jpg.*?class="[^"]*\bfechas\b[^"]*">\s*<p>\s*(\d{2})-(\d{2})-(\d{4})',
    re.S,
)
AUCTION_TITLE_RE = re.compile(r'alt="([^"]*)"')
LOT_NUMBER_RE = re.compile(r"Lote\s*:?\s*(\d+)")
# "MIRÓ FERRÁ, JOAN (1893 - 1983)" / "ALBACETE, ALFONSO (1950)" / "BARBA, JORDI (s.XX)"
ARTIST_YEARS_RE = re.compile(r"^(.*?)\s*\((\d{3,4})\s*(?:-\s*(\d{3,4}))?\s*\)\s*$")
PRICE_RE = re.compile(r"([\d.,]+)")


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _to_float(raw: str | None) -> float | None:
    """'1.250 €' / '150 €' -> 1250.0 / 150.0 (스페인 표기: . = 천 단위 구분자)."""
    if not raw:
        return None
    m = PRICE_RE.search(raw.replace("\xa0", " "))
    if not m:
        return None
    s = m.group(1).replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_index(index_html: str) -> dict[str, dict]:
    """경매 목록 페이지 -> {codSub: {'date': 'YYYY-MM-DD', 'name': '...'}}.

    이름은 카드 썸네일의 alt 텍스트(예 "Subasta 658 Julio 2026"). `auctions.name`은
    공용 `get_or_create_auction`이 채우지 않으므로 로더가 따로 UPDATE한다(load() 참고).
    """
    out: dict[str, dict] = {}
    for m in AUCTION_CARD_RE.finditer(index_html):
        _ref, cod_sub, dd, mm, yyyy = m.groups()
        tm = AUCTION_TITLE_RE.search(index_html, m.start(), m.start() + 600)
        out.setdefault(
            cod_sub,
            {"date": f"{yyyy}-{mm}-{dd}", "name": tm.group(1).strip() if tm else None},
        )
    return out


def split_artist_years(raw: str) -> tuple[str, int | None, int | None]:
    """'MIRÓ FERRÁ, JOAN (1893 - 1983)' -> ('MIRÓ FERRÁ, JOAN', 1893, 1983).

    괄호가 연도가 아니면(예 '(S. XX)', '(s.XX)') 괄호째 이름에 남겨둔 채 연도는 None.
    """
    m = ARTIST_YEARS_RE.match(raw)
    if not m:
        return raw.strip(), None, None
    name = m.group(1).strip()
    birth = int(m.group(2))
    death = int(m.group(3)) if m.group(3) else None
    if not (1 <= birth <= 2100) or (death is not None and not (1 <= death <= 2100)):
        return raw.strip(), None, None
    return (name or raw.strip()), birth, death


def parse_lot(page_html: str) -> dict | None:
    soup = BeautifulSoup(page_html, "html.parser")

    fields: dict[str, str] = {}
    for block in soup.select("div.caracteristicas-ficha"):
        for row in block.select("div.row"):
            label_el = row.select_one("div.col-xs-4")
            value_el = row.select_one("div.col-xs-8")
            if not label_el or not value_el:
                continue
            label = _clean(label_el.get_text(" "))
            value = _clean(value_el.get_text(" "))
            if label and value:
                fields.setdefault(label, value)

    # 가격: "Precio salida"(출발가) / "VENDIDO POR"(낙찰가)
    salida = hammer = None
    for p in soup.select("p.pre-title, p.pre-title-principal"):
        label = (_clean(p.get_text(" ")) or "").upper()
        price_el = p.find_next("p", class_="pre-price")
        if price_el is None:
            continue
        value = _to_float(price_el.get_text(" "))
        if "SALIDA" in label:
            salida = salida if salida is not None else value
        elif "VENDIDO" in label:
            hammer = hammer if hammer is not None else value

    lot_number = None
    ref_el = soup.select_one("div.referencia-ficha")
    if ref_el:
        m = LOT_NUMBER_RE.search(ref_el.get_text(" "))
        if m:
            lot_number = m.group(1)

    desc_el = soup.select_one("div.single-lot-desc-content")
    description = _clean(desc_el.get_text("\n")) if desc_el else None

    display_title = None
    title_el = soup.select_one("div.titleficha")
    if title_el:
        display_title = _clean(title_el.get_text(" "))

    artist_raw = fields.get("Autor")
    artist_name = birth_year = death_year = None
    if artist_raw:
        name, birth_year, death_year = split_artist_years(artist_raw)
        # 익명 표기는 작가 행으로 만들지 않는다(모듈 독스트링 참고).
        if not re.match(r"(?i)^an[oó]nimo\b", name):
            artist_name = name
        else:
            birth_year = death_year = None

    # Procedencia/Observaciones는 구조화하지 않고 description 끝에 라벨 줄로 보존.
    extra = []
    for label in ("Procedencia", "Observaciones"):
        if fields.get(label):
            extra.append(f"[{label}] {fields[label]}")
    if extra:
        description = "\n".join(([description] if description else []) + extra)

    return {
        "artist_name": artist_name,
        "artist_raw": artist_raw,
        "birth_year": birth_year,
        "death_year": death_year,
        "title": fields.get("Título") or display_title,
        "medium": fields.get("Técnica"),
        "dimensions": fields.get("Medidas"),
        "description": description,
        "lot_number": lot_number,
        "estimate_low": salida,
        "hammer_price": hammer,
    }


def load(store, limit: int | None = None) -> int:
    loaded = 0
    skipped_no_price = 0
    skipped_unparsed = 0
    auction_ids: dict[str, str] = {}

    house_id = store.get_or_create_auction_house(HOUSE_NAME, country=HOUSE_COUNTRY)

    # 경매 표: _index.html에서 codSub -> {date, name}
    auction_meta: dict[str, dict] = {}
    for record_id, text, _meta in iter_records(SITE_NAME, ext="html"):
        if record_id == INDEX_RECORD_ID:
            auction_meta = parse_index(text)
            break
    print(f"[pipeline:duran] 경매 표 {len(auction_meta)}건")

    # 증분 재실행 대비: 이미 DB에 있는 Durán auctions 행을 날짜로 재사용
    # (Lempertz/Grisebach 로더와 동일 패턴).
    date_to_auction_id: dict[str, str] = {}
    if hasattr(store, "cur"):
        store.cur.execute(
            "select id, auction_date from auctions "
            "where auction_house_id = %s and auction_date is not null",
            (house_id,),
        )
        date_to_auction_id = {str(d): str(aid) for aid, d in store.cur.fetchall()}

    for record_id, page_html, meta in iter_records(SITE_NAME, ext="html"):
        if record_id == INDEX_RECORD_ID:
            continue
        if limit is not None and loaded >= limit:
            break
        if store.source_already_loaded(meta["raw_path"]):
            continue

        parsed = parse_lot(page_html)
        if parsed is None:
            skipped_unparsed += 1
            continue
        if parsed["hammer_price"] is None:
            skipped_no_price += 1
            continue

        cod_sub = record_id.split("-", 1)[0]
        source_id = store.insert_source(meta)

        auction_id = auction_ids.get(cod_sub)
        if auction_id is None:
            info = auction_meta.get(cod_sub) or {}
            auction_date = info.get("date")
            auction_id = date_to_auction_id.get(auction_date) if auction_date else None
            if auction_id is None:
                auction_id = store.get_or_create_auction(
                    house_id, auction_date, source_id=source_id, sale_key=cod_sub
                )
                if auction_date:
                    date_to_auction_id[auction_date] = auction_id
            auction_ids[cod_sub] = auction_id

        artist_id = store.get_or_create_artist_safe(
            parsed["artist_name"],
            birth_year=parsed["birth_year"],
            death_year=parsed["death_year"],
            # 국적은 넣지 않는다 — 경매사 소재지(스페인)로 국적을 추정하면 다른 국적
            # 작가에 틀린 값이 들어간다(nagel/kanauction과 동일 원칙).
            source_id=source_id,
        )
        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=parsed["title"] or "(제목 미상)",
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
            estimate_high=None,  # Durán은 출발가 단일값만 공개(모듈 독스트링 참고)
            currency="EUR",
            hammer_price=parsed["hammer_price"],
            sold=True,
            source_id=source_id,
        )
        loaded += 1

    store.commit()

    # `auctions.name` 보충 — 공용 get_or_create_auction이 name 컬럼을 채우지 않아서,
    # 경매 목록 카드의 제목("Subasta 658 Julio 2026")을 날짜로 매칭해 따로 넣는다.
    # `name is null`인 행만 건드리므로 재실행해도 결과가 같고(idempotent), 다른 소스가
    # 이미 붙여 둔 이름은 덮어쓰지 않는다.
    named = 0
    if hasattr(store, "cur"):
        for info in auction_meta.values():
            if not (info.get("name") and info.get("date")):
                continue
            store.cur.execute(
                "update auctions set name = %s "
                "where auction_house_id = %s and auction_date = %s and name is null",
                (info["name"], house_id, info["date"]),
            )
            named += store.cur.rowcount
        store.conn.commit()

    print(
        f"[pipeline:duran] {loaded}건 적재, 낙찰가 없어 스킵 {skipped_no_price}건, "
        f"파싱 실패 {skipped_unparsed}건, 경매 {len(auction_ids)}개, 경매명 보충 {named}건"
    )
    return loaded
