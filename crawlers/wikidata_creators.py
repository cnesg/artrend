"""Wikidata 미술관 소장품의 creator QID/ULAN 보강 수집 — 2026-09-15 작업분담 §W9.

wikidata_museums.py SPARQL은 ?creatorLabel(사람이 읽을 이름 문자열)만 가져오고
creator의 Wikidata QID 자체는 저장하지 않는다. 이 스크립트는 같은 미술관 QID
목록(wikidata_museums.MUSEUMS 재사용, 새 미술관 추가 없음)에 대해 별도로
item(작품 QID) -> creator(작가 QID/ULAN/생몰/국적)만 뽑아 저장한다 — 기존 소스의
누락 컬럼 보강이지 새 소스가 아니다.

**DB에는 적재하지 않는다** — artists 백필은 메인(artrend-ca) 몫. 이 크롤러는
raw 저장만 한다.

저장 위치: crawlers/raw/wikidata_creators/<museum_key>.json 한 파일에 그
미술관의 item->creator 매핑 전체를 담는다(레코드 단위 저장이 아님 — save_raw를
그대로 재사용해 site_name="wikidata_creators", record_id=<museum_key>로 저장).
이미 있으면 스킵(already_fetched).

레이트리밋: Wikidata 쿼리서비스 사용 정책에 따라 User-Agent 명시, 미술관 요청
사이 1초 이상 간격, 실패 시 with_retry(지수 백오프)로 재시도.

사용법:
    python crawlers/wikidata_creators.py --museum prado
    python crawlers/wikidata_creators.py --museum all
    python crawlers/wikidata_creators.py --museum all --no-skip-existing
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import requests

from common import already_fetched, save_raw, with_retry
from wikidata_museums import MUSEUMS

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"}
SITE_NAME = "wikidata_creators"
LICENSE_NOTE = "Wikidata SPARQL (P170 creator + P245 ULAN 보강, wikidata_creators.py) — Wikidata 데이터 자체는 CC0. DB 미적재, raw 보강 수집만."

QUERY_TEMPLATE = """
SELECT ?item ?creator ?creatorLabel ?ulan ?born ?died ?country ?countryLabel WHERE {{
  ?item wdt:P195 wd:{qid} .
  ?item wdt:P170 ?creator .
  OPTIONAL {{ ?creator wdt:P245 ?ulan. }}
  OPTIONAL {{ ?creator wdt:P569 ?born. }}
  OPTIONAL {{ ?creator wdt:P570 ?died. }}
  OPTIONAL {{ ?creator wdt:P27 ?country. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,ko". }}
}}
"""


def _run_query(qid: str) -> list[dict]:
    query = QUERY_TEMPLATE.format(qid=qid)

    def _do():
        resp = requests.get(SPARQL_URL, params={"query": query, "format": "json"}, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return resp.json()

    data = with_retry(_do, attempts=3, base_delay=5.0)
    return data["results"]["bindings"]


def crawl(museum_key: str, skip_existing: bool) -> dict | None:
    display_name, qid = MUSEUMS[museum_key]

    if skip_existing and already_fetched(SITE_NAME, museum_key):
        print(f"[wikidata_creators:{museum_key}] 이미 수집됨 — 스킵")
        return None

    bindings = _run_query(qid)

    mappings = []
    for row in bindings:
        item_uri = row["item"]["value"]
        creator_uri = row["creator"]["value"]
        mappings.append(
            {
                "item_qid": item_uri.rsplit("/", 1)[-1],
                "creator_qid": creator_uri.rsplit("/", 1)[-1],
                "creator_label": row.get("creatorLabel", {}).get("value"),
                "ulan_id": row.get("ulan", {}).get("value"),
                "birth_date": row.get("born", {}).get("value"),
                "death_date": row.get("died", {}).get("value"),
                "country_qid": (row.get("country", {}).get("value") or "").rsplit("/", 1)[-1] or None,
                "country_label": row.get("countryLabel", {}).get("value"),
            }
        )

    record = {
        "museum_key": museum_key,
        "museum_name": display_name,
        "museum_qid": qid,
        "mapping_count": len(mappings),
        "creator_count_distinct": len({m["creator_qid"] for m in mappings}),
        "ulan_count": sum(1 for m in mappings if m["ulan_id"]),
        "mappings": mappings,
    }

    save_raw(
        SITE_NAME,
        museum_key,
        json.dumps(record, ensure_ascii=False, indent=2),
        url=f"https://query.wikidata.org/#{qid}",
        license_note=LICENSE_NOTE,
    )
    print(
        f"[wikidata_creators:{museum_key}] {display_name} — item {len(mappings)}건 / "
        f"작가(distinct) {record['creator_count_distinct']}명 / ULAN보유 {record['ulan_count']}건 저장"
    )
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wikidata 미술관 소장품 creator QID/ULAN 보강 크롤러")
    parser.add_argument("--museum", type=str, default="all", help="wikidata_museums.MUSEUMS 키 (all 또는 쉼표 구분)")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 미술관도 다시 수집",
    )
    args = parser.parse_args()
    keys = list(MUSEUMS.keys()) if args.museum == "all" else args.museum.split(",")

    total_museums = 0
    total_mappings = 0
    total_creators = 0
    total_ulan = 0
    for key in keys:
        if key not in MUSEUMS:
            print(f"[wikidata_creators] 알 수 없는 미술관 키: {key}")
            continue
        result = crawl(key, args.skip_existing)
        if result is not None:
            total_museums += 1
            total_mappings += result["mapping_count"]
            total_creators += result["creator_count_distinct"]
            total_ulan += result["ulan_count"]
        time.sleep(1.0)

    print(
        f"\n[wikidata_creators] 완료 — 신규 수집 미술관 {total_museums}개 / "
        f"item-creator 매핑 {total_mappings}건 / creator(distinct) {total_creators}명 / ULAN보유 {total_ulan}건"
    )
