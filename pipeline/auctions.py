"""경매 낙찰 기록(raw/auctions_wikidata/) -> auction_houses/auctions/auction_lots 적재.

crawlers/auctions.py가 Wikidata SPARQL(P793=auction 필터)로 모은 레코드를 정규화한다.
organizer(경매사)가 없는 레코드는 auction_houses.name FK를 만들 수 없어 건너뛴다 —
Wikidata에 낙찰가/로트번호는 있어도 주최 경매사가 비어있는 경우가 실제로 존재함.
"""
from __future__ import annotations

from urllib.parse import urlparse

from raw_iter import iter_records

SITE_NAME = "auctions_wikidata"

# organizerLabel(P664)이 비어있는 레코드를 위한 보조 매핑 — refUrl(P854, 레퍼런스로만 인용된
# 원본 카탈로그 URL) 도메인이 특정 경매사 하나로 확실히 좁혀지는 경우만 등록.
# invaluable.com/artsy.net/artinfo.pl/onebid.pl/web.archive.org 등 여러 경매사를 묶어 보여주는
# 애그리게이터/아카이브/도록 사이트는 단일 경매사로 단정할 수 없어 제외.
DOMAIN_TO_HOUSE: dict[str, str] = {
    "www.sothebys.com": "Sotheby's",
    "www.christies.com": "Christie's",
    "www.bonhams.com": "Bonhams",
    "www.lempertz.com": "Lempertz",
    "www.desa.pl": "DESA Unicum",
    "desa.art.pl": "DESA Unicum",
    "www.sda.pl": "Sopocki Dom Aukcyjny",
    "www.polswissart.pl": "Polswiss Art",
    "rempex.com.pl": "Rempex Dom Aukcyjny",
    "bruun-rasmussen.dk": "Bruun Rasmussen Kunstauktioner",
    "www.kettererkunst.de": "Ketterer Kunst",
    "www.blomqvist.no": "Blomqvist Kunsthandel",
    "www.karlundfaber.de": "Karl & Faber",
    "sztuka.agraart.pl": "Dom Aukcyjny Agra-Art",
    "gwpa.no": "Grev Wedels Plass Auksjoner",
    "krakowskidomaukcyjny.pl": "Krakowski Dom Aukcyjny",
    "desa.pl": "DESA Unicum",
    "bid.desa.pl": "DESA Unicum",
    "online.polswissart.pl": "Polswiss Art",
    "www.kollerauktionen.ch": "Koller Auktionen",
    "www.van-ham.com": "Van Ham Kunstauktionen",
    "polskidomaukcyjny.com.pl": "Polski Dom Aukcyjny",
    "www.beaussantlefevre.com": "Beaussant Lefèvre",
    "www.aukcjeostoya.pl": "Dom Aukcyjny Ostoya",
    "www.dorotheum.com": "Dorotheum",
    "www.duran-subastas.com": "Durán Arte y Subastas",
    "www.grisebach.com": "Villa Grisebach",
    "www.christies.com.cn": "Christie's",
    "www.galeriekodl.cz": "Galerie Kodl",
    "artlibra.pl": "Art Libra Dom Aukcyjny",
    # 2026-09-22 추가 — --broad 수집분에서 organizer가 비어 스킵되던 레코드의 refUrl
    # 도메인 분포를 보고, 단일 경매사로 확실히 좁혀지는 것만 넣음(애그리게이터 제외 원칙 유지).
    "onlineonly.christies.com": "Christie's",
    "www.groganco.com": "Grogan & Company",
}

# 2026-09-22 — `crawlers/auctions.py --broad`가 P793 값 고정을 풀면서 **경매가 아닌 사건**까지
# 딸려 들어온다(구입/수여/소유권 변경/평가 등). 이것들은 낙찰가가 아니라 거래가·평가액이라
# auction_lots에 섞이면 안 된다. eventLabel이 아래에 해당하면 적재하지 않는다.
# (auction/art auction/sale, 그리고 "Lempertz Auction 1155 …"처럼 세일 자체가 아이템인
#  경우는 전부 통과시킨다 — 이쪽이 --broad로 얻으려던 본체다.)
NON_AUCTION_EVENT_LABELS = {
    "purchasing",
    "commission",
    "acquisition",
    "change of ownership",
    "valuation",
    "listed for sale",
    "donation",
    "bequest",
}

# priceUnit Wikidata QID -> 통화 코드/명칭 (crawlers/raw/auctions_wikidata 실제 등장 값 기준, 2026-09-03)
CURRENCY_MAP: dict[str, str] = {
    "http://www.wikidata.org/entity/Q4917": "USD",
    "http://www.wikidata.org/entity/Q4916": "EUR",
    "http://www.wikidata.org/entity/Q25224": "GBP",
    "http://www.wikidata.org/entity/Q123213": "PLN",
    "http://www.wikidata.org/entity/Q132643": "NOK",
    "http://www.wikidata.org/entity/Q25417": "DKK",
    "http://www.wikidata.org/entity/Q131016": "CZK",
    "http://www.wikidata.org/entity/Q259502": "AUD",
    "http://www.wikidata.org/entity/Q189097": "ESP(peseta)",
    "http://www.wikidata.org/entity/Q155009": "Reichsmark",
    "http://www.wikidata.org/entity/Q184172": "FRF",
    "http://www.wikidata.org/entity/Q918094": "guinea",
}


def _currency(price_unit: str | None) -> str | None:
    if not price_unit:
        return None
    return CURRENCY_MAP.get(price_unit, price_unit.rsplit("/", 1)[-1])


def load(store) -> int:
    loaded = 0
    skipped_no_organizer = 0
    skipped_not_auction = 0

    for _record_id, data, meta in iter_records(SITE_NAME):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        if (data.get("eventLabel") or "").strip().lower() in NON_AUCTION_EVENT_LABELS:
            skipped_not_auction += 1
            continue

        organizer_name = (data.get("organizerLabel") or "").strip()
        if not organizer_name or organizer_name.startswith("Q"):
            # organizerLabel이 비어있거나 라벨 서비스가 못 찾아 QID 그대로 남은 경우
            # (예: "Q892447") — refUrl 도메인으로 보조 매칭 시도, 그래도 안 되면 skip
            ref_url = data.get("refUrl")
            domain = urlparse(ref_url).netloc if ref_url else None
            organizer_name = DOMAIN_TO_HOUSE.get(domain, "")
            if not organizer_name:
                skipped_no_organizer += 1
                continue

        source_id = store.insert_source(meta)

        auction_house_id = store.get_or_create_auction_house(organizer_name)

        auction_date = data.get("date")
        auction_date = auction_date[:10] if auction_date else None
        auction_id = store.get_or_create_auction(auction_house_id, auction_date, source_id=source_id)

        artist_name = (data.get("creatorLabel") or "").strip() or None
        artist_id = store.get_or_create_artist(artist_name, source_id=source_id) if artist_name else None

        title = (data.get("itemLabel") or "").strip() or "(제목 미상)"
        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=title,
            source_id=source_id,
        )

        price = data.get("price")
        hammer_price = float(price) if price is not None else None

        store.insert_auction_lot(
            auction_id=auction_id,
            artwork_id=artwork_id,
            lot_number=data.get("lotNumber"),
            hammer_price=hammer_price,
            currency=_currency(data.get("priceUnit")),
            sold=True if hammer_price is not None else None,
            source_id=source_id,
        )
        loaded += 1

    store.commit()
    print(
        f"[pipeline:auctions] {loaded}건 적재, organizer 없어 스킵 {skipped_no_organizer}건, "
        f"경매 아닌 사건이라 스킵 {skipped_not_auction}건"
    )
    return loaded
