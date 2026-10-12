"""Wikidata SPARQL을 통한 경매 낙찰 기록 수집.

공식 경매/가격 데이터 소스(Christie's/Sotheby's/Phillips/서울옥션/K-Auction/Artsy)는
전부 ToS에 스크래핑 금지 조항이 명시돼 있거나(docs/크롤러현황.md 참고) robots.txt로
결과·검색 페이지가 막혀 있어 직접 크롤링을 포기했다.

대신 Wikidata의 "중요 사건(P793) = auction(Q177923)" 구조화 statement를 이용한다.
이 statement는 작품 항목에 딸린 것으로, qualifier로
  - P664 (organizer)   : 경매를 주최한 경매사 (Wikidata item)
  - P585 (point in time): 낙찰 일자
  - P4775 (lot number)  : 로트 번호 (string)
  - P2284 (price)       : 낙찰가 (amount + currency unit QID)
를 갖는다. 레퍼런스에 원 경매사 카탈로그 URL(P854)이 인용되는 경우가 많지만,
우리가 실제로 요청하는 건 Wikidata SPARQL 엔드포인트뿐이며 CC0 라이선스로 재사용 가능하다.
(레퍼런스 URL 자체는 그대로 저장만 하고 따로 fetch하지 않는다 — 재크롤링 아님.)

커버리지 확인(2026-09-03): painting(Q3305213) 821건 + drawing(Q93184) 637건 +
sculpture(Q860861) 5건 + print/photograph/work_of_art 각 1~2건 — 소규모지만
실제 organizer/date/lot/price가 다 채워진 구조화 데이터.

2026-09-22 추가: P793의 **값**을 Q177923 하나로 못 박은 탓에 art auction(Q74570489)·
sale(Q194189)·경매사별 개별 세일 아이템 등에 달린 낙찰가를 통째로 놓치고 있었다.
`--broad`가 값 고정을 풀고 "가격(P2284) 한정자가 붙은 P793 statement 전부"를 가져온다
(자세한 근거는 BROAD_QUERY_TEMPLATE 위 주석, docs/경매소스확장_20260922.md).

사용법:
    python auctions.py --type all
    python auctions.py --type painting
    python auctions.py --type all --broad
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import requests

from common import already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"}
LICENSE_NOTE = (
    "Wikidata SPARQL (P793=auction significant-event 필터) — CC0, "
    "경매사 공식 사이트는 ToS/robots.txt로 직접 크롤링 불가해 Wikidata 구조화 데이터로 대체, 2026-09-03"
)

AUCTION_EVENT_QID = "Q177923"  # auction

# site key -> instance-of QID (P31 필터)
ART_TYPES: dict[str, str] = {
    "painting": "Q3305213",
    "drawing": "Q93184",
    "sculpture": "Q860861",
    "print": "Q11060274",
    "photograph": "Q125191",
    "work_of_art": "Q838948",
    "collage": "Q220659",
    "visual_artwork": "Q4502142",
    # 2026-09-03 확장 — P793(auction) 걸린 아이템 전체의 P31 타입 분포를 직접 조회해서 발견.
    # 기존 문서에 "pastel은 0건"이라 기록돼 있었는데, 이는 안료(Q189085)를 조회한 탓이었고
    # 실제 파스텔 작품의 instance-of는 Q12043905(pastel artwork)로 480건이나 있었음 — 가장 큰 추가분.
    "pastel_artwork": "Q12043905",
    "watercolor_painting": "Q18761202",
    "lithograph_print": "Q15123870",
    "etching_print": "Q18218093",
    "woodcut_print": "Q18219090",
    "bookplate": "Q188456",
    "self_portrait": "Q192110",
    "oil_sketch": "Q1964917",
    "portrait": "Q134307",
    "statue": "Q179700",
    "triptych": "Q79218",
    "tondo": "Q848330",
    "double_sided_painting": "Q5299612",
    "altarpiece": "Q15711026",
    "group_of_paintings": "Q18573970",
    "cycle_of_paintings": "Q16905563",
    "artist_book": "Q1062404",
    "illuminated_manuscript": "Q48498",
}

# 2026-09-22 확장 — 기존 질의는 P793(중요 사건)의 값이 **정확히 Q177923(auction)** 인
# statement만 봤다. 실제로 pq:P2284(가격) 한정자가 붙은 P793 statement의 값 분포를 직접
# 조회해 보니 Q177923은 956건뿐이고, Q74570489(art auction) 615, Q194189(sale) 83,
# Q1369832(purchasing) 34, Q110817391(listed for sale) 32에 더해 "Christie's Old masters
# evening sale, 3 dec 2019", Lempertz 개별 세일처럼 **세일 자체가 별도 아이템으로 만들어진
# 값**이 51종 더 있었다(총 1,959 statement). 즉 값을 하나로 못 박으면 상당수를 놓친다.
# --broad 모드는 값을 고정하지 않고 "가격 한정자가 붙은 P793"을 전부 가져온다.
BROAD_QUERY_TEMPLATE = """
SELECT ?item ?itemLabel ?creator ?creatorLabel ?stmt ?event ?eventLabel ?organizer ?organizerLabel
       ?date ?lotNumber ?price ?priceUnit ?priceUnitLabel ?refUrl WHERE {{
  ?item wdt:P31 wd:{type_qid} .
  ?item p:P793 ?stmt .
  ?stmt ps:P793 ?event .
  ?stmt pqv:P2284 ?priceValue .
  ?priceValue wikibase:quantityAmount ?price .
  ?priceValue wikibase:quantityUnit ?priceUnit .
  OPTIONAL {{ ?item wdt:P170 ?creator. }}
  OPTIONAL {{ ?stmt pq:P664 ?organizer. }}
  OPTIONAL {{ ?stmt pq:P585 ?date. }}
  OPTIONAL {{ ?stmt pq:P4775 ?lotNumber. }}
  OPTIONAL {{ ?stmt prov:wasDerivedFrom/pr:P854 ?refUrl. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,ko". }}
}}
"""

QUERY_TEMPLATE = """
SELECT ?item ?itemLabel ?creator ?creatorLabel ?stmt ?organizer ?organizerLabel
       ?date ?lotNumber ?price ?priceUnit ?priceUnitLabel ?refUrl WHERE {{
  ?item wdt:P31 wd:{type_qid} .
  ?item p:P793 ?stmt .
  ?stmt ps:P793 wd:{auction_qid} .
  OPTIONAL {{ ?item wdt:P170 ?creator. }}
  OPTIONAL {{ ?stmt pq:P664 ?organizer. }}
  OPTIONAL {{ ?stmt pq:P585 ?date. }}
  OPTIONAL {{ ?stmt pq:P4775 ?lotNumber. }}
  OPTIONAL {{
    ?stmt pqv:P2284 ?priceValue.
    ?priceValue wikibase:quantityAmount ?price.
    ?priceValue wikibase:quantityUnit ?priceUnit.
  }}
  OPTIONAL {{ ?stmt prov:wasDerivedFrom/pr:P854 ?refUrl. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,ko". }}
}}
"""


def _run_query(type_qid: str, broad: bool = False) -> list[dict]:
    template = BROAD_QUERY_TEMPLATE if broad else QUERY_TEMPLATE
    query = template.format(type_qid=type_qid, auction_qid=AUCTION_EVENT_QID)

    def _do():
        resp = requests.get(SPARQL_URL, params={"query": query, "format": "json"}, headers=HEADERS, timeout=90)
        resp.raise_for_status()
        return resp.json()

    data = with_retry(_do, attempts=3, base_delay=5.0)
    return data["results"]["bindings"]


def crawl(type_key: str, skip_existing: bool, broad: bool = False) -> None:
    type_qid = ART_TYPES[type_key]
    site_name = "auctions_wikidata"

    bindings = _run_query(type_qid, broad=broad)
    print(f"[auctions:{type_key}] 낙찰 기록 {len(bindings)}건 조회됨")

    saved = 0
    for row in bindings:
        stmt_uri = row["stmt"]["value"]
        # statement URI 끝의 "QID-GUID"를 레코드 id로 그대로 쓴다(2026-09-16 수정 —
        # 예전엔 f"{type_key}_" 접두사를 붙였는데, 한 작품이 두 미술유형 범주의
        # instance-of를 동시에 만족하면(예: painting이자 self_portrait) 완전히
        # 같은 statement가 두 범주 질의에 모두 걸려서 접두사만 다른 별개 파일로
        # 중복 저장됐다 — already_fetched가 파일명 전체로 비교하다 보니 이미 저장된
        # 걸 못 알아챔. QID-GUID는 statement 자체의 고유 식별자라 접두사 없이도
        # "같은 작품이 여러 번 경매에 나온 정상 케이스"(다른 GUID)는 그대로 각각
        # 구분되고, "같은 statement 중복 크롤"(같은 GUID)만 제대로 스킵된다.
        # art_type은 record 내용에는 그대로 남아있어 유실 없음(하단 참고).
        record_id = stmt_uri.rsplit("/", 1)[-1].replace("$", "_")

        if skip_existing and already_fetched(site_name, record_id):
            continue

        record = {k: v.get("value") for k, v in row.items()}
        record["art_type"] = type_key
        item_uri = row["item"]["value"]
        record["wikidata_qid"] = item_uri.rsplit("/", 1)[-1]

        save_raw(site_name, record_id, json.dumps(record, ensure_ascii=False), url=item_uri, license_note=LICENSE_NOTE)
        saved += 1
        if saved % 200 == 0:
            print(f"[auctions:{type_key}] {saved}건 저장 진행 중...")
        time.sleep(0.02)

    print(f"[auctions:{type_key}] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wikidata 기반 경매 낙찰 기록 크롤러")
    parser.add_argument("--type", type=str, default="all", help="ART_TYPES 키 (all 또는 쉼표 구분)")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 레코드도 다시 수집",
    )
    parser.add_argument(
        "--broad",
        action="store_true",
        help="P793 값을 auction(Q177923)으로 고정하지 않고, 가격(P2284) 한정자가 붙은 "
             "P793 statement를 전부 수집(art auction/sale/개별 세일 아이템 등 포함)",
    )
    args = parser.parse_args()
    keys = list(ART_TYPES.keys()) if args.type == "all" else args.type.split(",")
    for key in keys:
        if key not in ART_TYPES:
            print(f"[auctions] 알 수 없는 타입 키: {key} (사용 가능: {list(ART_TYPES.keys())})")
            continue
        crawl(key, args.skip_existing, broad=args.broad)
