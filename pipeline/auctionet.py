"""Auctionet raw(crawlers/raw/auctionet/) -> auction_houses/auctions/auction_lots 적재.

**애그리게이터 처리 방침**: Auctionet(auctionet.com)은 경매사가 아니라 Auction Network
Sweden AB가 운영하는 온라인 마켓플레이스다. 실제 판매자는 입점 경매사 약 83곳(스웨덴·덴마크·
핀란드·독일·스페인·영국)이고, Auctionet ToU도 "Auctionet shall by no means be regarded as
seller of the Auction Items"라고 못 박는다. 그래서 **`auction_houses`에는 'Auctionet' 행을
만들지 않고**, 로트마다 상세 페이지의 `House` 필드(개별 경매사)를 auction_houses로 쓴다.
Auctionet은 `sources`(수집 출처) 로만 남는다 — Wikidata 경매 로더(`pipeline/auctions.py`)가
invaluable/artsy 같은 애그리게이터 도메인을 단일 경매사로 단정하지 않기로 한 것과 같은 원칙.

**금액은 전부 목록(thumb) JSON에서 읽는다 — vip_item의 금액을 쓰면 안 된다.**
두 가지 이유가 있고 둘 다 실측으로 확인했다(2026-09-23):

1. **현장 슬래그옥션(`hammer_auction: true`) 로트는 상세 페이지가 `?currency=` 지정을 무시한다.**
   `?currency=SEK`로 받아도 `vip_item.currency`가 `EUR`로 돌아오고 `estimate`/`upper_estimate`가
   환산값이 된다(예: id=4615780 → vip 887/1064 EUR, 원값 10,000–12,000 SEK). 목록 JSON은
   지정한 통화를 정확히 따른다.
2. **슬래그옥션 로트의 `bids[]`는 사전입찰(pre-bid)만 담는다.** 실제 낙찰은 현장에서 나므로
   `top_bid_amount`가 낙찰가가 아니다 — 같은 로트가 사전입찰 최고 798 SEK인데 실제 낙찰가는
   **9,000 SEK**였다. 이걸 낙찰가로 적재했으면 **10배 넘게 틀린 값**이 들어갔을 것이다.

그래서 통화·추정가·낙찰가·로트번호를 전부 thumb에서 읽는다:
`thumb.currency`(원 통화), `thumb.estimate`(하한), `thumb.amountTitle`("Estimate: 10,000 –
12,000 SEK" → 상한), `thumb.amountValue`("9,000 SEK" / 유찰이면 "-"), `thumb.catalogNumber`.
`vip_item`에서는 **금액이 아닌 것만** 쓴다(`state`, `ends_at`, `hammer_auction`).
크롤러가 `thumb.currency != 표시통화`인 로트는 애초에 저장하지 않으므로 환산이 개입할 여지가
없고, 로더도 통화 접미사를 한 번 더 대조한다.

**경매일**: 로트 종료 시각(`vip_item.ends_at`, unix)을 플랫폼 본거지 시간대인
Europe/Stockholm 기준 날짜로 변환한다(페이지의 `ends_at_string`은 수집 당시 클라이언트
시간대로 렌더돼 KST가 박혀 있어 쓰지 않는다).

**작가**: 목록 JSON에는 작가 필드가 없고 제목 문자열에 뭉쳐 있다. 제목을 쪼개 작가를 추측하지
않고, 상세 페이지 "Artist/designer" 섹션의 작가 엔티티 링크만 쓴다. 라벨에 붙은 생몰년
(`(1921–2005)`, `(Born 1941)`)은 **이름에서 떼어내기만 하고 artists 메타로 채우지 않는다** —
생몰년 백필은 Wikidata/ULAN authority 매칭으로만 한다는 프로젝트 규칙을 따른다.

**작가 링크가 없는 로트는 기본적으로 적재하지 않는다**(`require_artist=True`). Auctionet은
경매사가 작가 엔티티를 태깅한 로트만 링크를 달아 주는데, 지방 소형 경매사의 저가 로트는
제목에 작가명이 있어도("WILHELM SKOGLUND, OLJA PÅ DUK") 링크가 없다. 제목에서 작가를 문자열로
떼어내는 추측은 금지고, 작가 NULL 로트를 대량으로 넣는 것은 2026-09-15 재진단이
**가비지로 지목한 패턴**(Bonhams 작가 NULL 90K)을 그대로 반복하는 일이다. 관계망에 기여하지
않는 행을 늘리지 않기 위해 기본값을 스킵으로 둔다(`--include-artistless`로 해제 가능).

**갓 끝난 로트는 적재하지 않는다(`min_age_days`, 기본 3일)**. 종료 직후에는 `state`가 아직
`unsold`로 남아 있다가 경매사가 정산하면서 `sold`로 바뀐다 — 종료일별 낙찰률 실측
(2026-09-23, 표본 48건/페이지):

| 종료일 | 경과 | 낙찰률 |
|---|---|---|
| 9/23(당일) | 0일 | 38~67% |
| 9/22 | 1일 | 38~50% |
| 9/21 | 2일 | **83%** |
| 9/19 | 4일 | 77% |
| 9/11 | 12일 | 79% |
| 9/5~6 | 17일 | 90% |
| 2011년 아카이브 | — | 98% |

0~1일짜리를 그대로 넣으면 **낙찰된 로트가 유찰로 박제된다.** 2일을 넘기면 80% 전후로
안정되므로 기본 3일을 격리 기간으로 둔다(주간 갱신 주기라면 실질 손실이 없다).

**경매 묶음(auctions)**: Auctionet 온라인 경매는 로트마다 종료 시각이 달라 `auction_id`가
**사실상 로트마다 하나씩** 발급된다(표본 45건 전부 서로 다른 값). 이걸 sale_key로 쓰면
auctions 행이 로트 수만큼 생긴다. 그래서 **현장 슬래그옥션처럼 `eventTitle`이 있는 경우에만**
그걸 sale_key로 쓰고, 그 외에는 (경매사, 종료일) 기본 묶음을 쓴다.

**중복 경매사 방지**: 이미 DB에 다른 표기로 들어 있는 경매사는 HOUSE_ALIAS로 손으로 확인한
것만 매핑한다(문자열 유사도 자동 병합 금지 규칙).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from raw_iter import iter_records

SITE_NAME = "auctionet"

# 주소 꼬리의 국가명 -> ISO-3166 alpha-2 (기존 auction_houses.country 표기와 맞춤).
COUNTRY_TO_ISO = {
    "Sweden": "SE",
    "Denmark": "DK",
    "Finland": "FI",
    "Germany": "DE",
    "Spain": "ES",
    "United Kingdom": "GB",
    "Norway": "NO",
}

# 이미 DB에 다른 이름으로 존재하는 경매사 — 손으로 대조해 확인한 것만 넣는다.
# (Auctionet 표기 -> DB 기존 표기). 문자열 유사도 자동 매칭은 하지 않는다.
HOUSE_ALIAS = {
    # Auctionet "Lawrences Auctioneers"(Crewkerne) == DB 기존 "Lawrences Auctioneers of
    # Crewkerne". Auctionet 경매사 페이지의 소재지도 Crewkerne으로 같다(2026-09-23 확인).
    "Lawrences Auctioneers": "Lawrences Auctioneers of Crewkerne",
}
# 매핑하지 않기로 한 유사 후보(2026-09-23 대조):
#   Auctionet "Young's Auctions"(Surrey) vs DB "Young" / "Young (Hickman)" — 뒤 둘은 Getty
#   provenance 문자열에서 온 성씨 형태라 서리의 이 경매사와 동일하다고 볼 근거가 없다. 신규 생성.
# 나머지 84곳은 DB에 같은 이름도 유사 후보도 없어 그대로 신규 생성된다
# (Stockholms Auktionsverk 계열·Uppsala Auktionskammare·Göteborgs Auktionsverk 포함).
# Bukowskis는 DB에 이미 있지만 Auctionet 입점사가 아니라 충돌하지 않는다.

# Europe/Stockholm. zoneinfo(tzdata)가 없는 환경도 있어 고정 오프셋으로 근사한다 —
# 경매 '날짜'만 쓰기 때문에 서머타임 1시간 차이로 날짜가 바뀌는 경계 케이스만 영향이 있다.
_STOCKHOLM_OFFSETS = (timedelta(hours=1), timedelta(hours=2))


def _auction_date(ends_at) -> str | None:
    """unix 초 -> Europe/Stockholm 기준 'YYYY-MM-DD'."""
    if not isinstance(ends_at, (int, float)):
        return None
    utc = datetime.fromtimestamp(ends_at, tz=timezone.utc)
    # 대략적인 유럽 서머타임(3월 마지막 일요일~10월 마지막 일요일) 판정
    offset = _STOCKHOLM_OFFSETS[1] if 3 < utc.month < 11 else _STOCKHOLM_OFFSETS[0]
    return (utc + offset).date().isoformat()


def _country_from_address(address: str | None) -> str | None:
    if not address:
        return None
    for name, iso in COUNTRY_TO_ISO.items():
        if address.strip().endswith(name):
            return iso
    return None


def _artist_name(label: str | None) -> str | None:
    """'Karl Axel Pehrson (1921–2005)' / 'Bo Åke Adamsson (Born 1941)' -> 이름만."""
    if not label:
        return None
    # 라벨에 연속 공백이 들어오는 경우가 있어("GEORG  GUDNI") 정규화한다 —
    # 같은 작가가 공백 차이로 두 행이 되는 걸 막는다.
    name = re.sub(r"\s+", " ", label.split("(")[0]).strip().strip(",")
    return name or None


# "9,000 SEK" / "1 100 SEK" / "45,000 SEK" -> (9000.0, "SEK"). 유찰이면 "-"라 None.
_AMOUNT_RE = re.compile(r"^\s*([\d][\d\s,. ]*)\s*([A-Z]{3})\s*$")
# "Estimate: 10,000 – 12,000 SEK" -> 상한 12000. 단일값이면 상한 없음.
_RANGE_RE = re.compile(
    r"([\d][\d\s,. ]*)\s*[–\-—]\s*([\d][\d\s,. ]*)\s*([A-Z]{3})\s*$"
)


def _num(raw: str) -> float | None:
    """'10,000' / '1 100' / '1 100' -> float. 소수점은 이 소스에 등장하지 않는다."""
    digits = re.sub(r"[^\d]", "", raw)
    return float(digits) if digits else None


def _amount(value: str | None, expect_currency: str | None) -> float | None:
    """thumb.amountValue -> 금액. 통화 접미사가 기대 통화와 다르면 환산값이므로 버린다."""
    if not value:
        return None
    m = _AMOUNT_RE.match(value)
    if not m:
        return None  # 유찰 표시 "-" 등
    if expect_currency and m.group(2) != expect_currency:
        return None
    return _num(m.group(1))


def _estimate_high(amount_title: str | None, expect_currency: str | None) -> float | None:
    if not amount_title:
        return None
    m = _RANGE_RE.search(amount_title)
    if not m:
        return None
    if expect_currency and m.group(3) != expect_currency:
        return None
    return _num(m.group(2))


def _title_en(long_title: str | None, item_id) -> str | None:
    """'5306319. KARL AXEL PEHRSON. Nature composition...' 앞의 로트 id 접두사를 뗀다."""
    if not long_title:
        return None
    prefix = f"{item_id}. "
    return long_title[len(prefix):].strip() if long_title.startswith(prefix) else long_title.strip()


def load(store, require_artist: bool = True, min_age_days: int = 3) -> int:
    loaded = 0
    skipped_fx = 0
    skipped_no_house = 0
    skipped_no_title = 0
    skipped_no_artist = 0
    skipped_too_fresh = 0

    cutoff = datetime.now(tz=timezone.utc).timestamp() - min_age_days * 86400

    for _record_id, data, meta in iter_records(SITE_NAME):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        vip_peek = data.get("vip_item") or {}
        ends_at = vip_peek.get("ends_at")
        if min_age_days and isinstance(ends_at, (int, float)) and ends_at > cutoff:
            # 종료 직후라 낙찰 상태가 아직 확정되지 않았다(모듈 주석의 실측 표 참고).
            skipped_too_fresh += 1
            continue

        # 통화 기준은 목록(thumb) — 상세는 슬래그옥션에서 ?currency를 무시한다(모듈 주석 참고).
        display = data.get("display_currency")
        original = ((data.get("thumb") or {}).get("currency")
                    or data.get("original_currency"))
        if not original or display != original:
            # 표시통화 != 원 통화 => 금액이 환산값. 원 통화 차례에 다시 수집된다.
            skipped_fx += 1
            continue

        details = data.get("details") or {}
        house_name = (details.get("House") or "").strip()
        if not house_name:
            skipped_no_house += 1
            continue
        house_name = HOUSE_ALIAS.get(house_name, house_name)

        thumb = data.get("thumb") or {}
        vip = data.get("vip_item") or {}
        sections = data.get("sections") or {}
        item_id = data.get("item_id")

        # 원어 제목(Title 섹션)이 원본. 없으면 영문 표기를 제목으로 쓴다.
        title_en = _title_en(thumb.get("longTitle"), item_id)
        title = (sections.get("Title") or "").strip() or title_en
        if not title:
            skipped_no_title += 1
            continue

        artists = data.get("artists") or []
        artist_name = _artist_name(artists[0]["label"]) if artists else None
        if require_artist and not artist_name:
            skipped_no_artist += 1
            continue

        source_id = store.insert_source(meta)

        house_id = store.get_or_create_auction_house(
            house_name, _country_from_address(details.get("Address"))
        )
        auction_date = _auction_date(vip.get("ends_at"))
        # 온라인 경매는 로트마다 auction_id가 따로라 sale_key로 쓰면 안 된다(모듈 주석 참고).
        event_title = (thumb.get("eventTitle") or "").strip() or None
        auction_id = store.get_or_create_auction(
            house_id,
            auction_date,
            source_id=source_id,
            sale_key=f"{event_title}|{auction_date}" if event_title else None,
        )

        # 생몰년은 라벨에 있지만 채우지 않는다 — authority(QID/ULAN) 매칭 전용 필드.
        artist_id = (
            store.get_or_create_artist_safe(artist_name, source_id=source_id)
            if artist_name else None
        )

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=title,
            title_en=title_en if title_en and title_en != title else None,
            description=(sections.get("Description") or None),
            source_id=source_id,
        )

        state = vip.get("state")
        if state not in ("sold", "unsold"):
            # thumb 라벨을 보조로 쓴다(슬래그옥션은 "Sold"/"Unsold"로 표시).
            label = (thumb.get("amountLabel") or "").strip().lower()
            state = "sold" if label == "sold" else ("unsold" if label == "unsold" else None)
        sold = True if state == "sold" else (False if state == "unsold" else None)

        # 금액은 전부 thumb에서. vip의 estimate/top_bid_amount는 쓰지 않는다(모듈 주석 참고).
        hammer_price = _amount(thumb.get("amountValue"), original) if sold else None
        est_low = thumb.get("estimate")
        estimate_low = float(est_low) if isinstance(est_low, (int, float)) else None
        estimate_high = _estimate_high(thumb.get("amountTitle"), original)

        store.insert_auction_lot_batch(
            auction_id=auction_id,
            artwork_id=artwork_id,
            lot_number=(str(thumb["catalogNumber"]) if thumb.get("catalogNumber") else None),
            estimate_low=estimate_low,
            estimate_high=estimate_high,
            currency=original,
            hammer_price=hammer_price,
            sold=sold,
            source_id=source_id,
        )
        loaded += 1

    store.commit()
    print(
        f"[pipeline:auctionet] {loaded}건 적재 "
        f"(종료 {min_age_days}일 미만이라 보류 {skipped_too_fresh}건, "
        f"작가 링크 없어 스킵 {skipped_no_artist}건, 환산통화라 보류 {skipped_fx}건, "
        f"경매사 없음 {skipped_no_house}건, 제목 없음 {skipped_no_title}건)"
    )
    return loaded
