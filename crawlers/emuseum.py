"""국립중앙박물관 e뮤지엄 유물정보 OpenAPI 크롤러 (스켈레톤 — API 키 발급 후 완성 필요).

https://www.data.go.kr/data/15104964/openapi.do

data.go.kr은 API 키를 발급받은 계정에게만 정확한 요청 URL/파라미터 스펙을
"OpenAPI 정보" 탭에서 보여준다 (로그인 필요) — 그래서 ENDPOINT/파라미터명은
확정 전 자리표시자다. API 키 발급 후 아래 TODO만 채우면 나머지(원본 저장 방식)는
met.py/aic.py와 동일한 패턴이라 바로 재사용 가능하다.

사용법 (키 발급 후):
    export EMUSEUM_API_KEY=발급받은키   # 또는 --api-key 인자로 전달
    python crawlers/emuseum.py --limit 50
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests

from common import already_fetched, save_raw

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# TODO: data.go.kr에서 API 키 발급 후 "OpenAPI 정보" 탭에서 정확한 엔드포인트로 교체
# data.go.kr 표준 패턴은 보통 http://apis.data.go.kr/{기관코드}/{서비스명}/{동작명} 형태.
ENDPOINT = "https://apis.data.go.kr/PLACEHOLDER/emuseum/relic"  # 실제 값으로 교체 필요

SITE_NAME = "emuseum"
LICENSE_NOTE = "공공데이터 - 국립중앙박물관 e뮤지엄 유물정보 (data.go.kr, 무료)"


def fetch_page(api_key: str, page: int, rows: int) -> dict:
    params = {
        "serviceKey": api_key,
        "pageNo": page,
        "numOfRows": rows,
        "type": "json",
    }
    resp = requests.get(ENDPOINT, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def crawl(api_key: str, limit: int, page_size: int, delay: float, skip_existing: bool) -> None:
    saved = 0
    page = 1
    while saved < limit:
        body = fetch_page(api_key, page, page_size)
        # TODO: 실제 응답 구조 확인 후 items 추출 경로 수정
        items = body.get("response", {}).get("body", {}).get("items", [])
        if not items:
            break

        for item in items:
            if saved >= limit:
                break
            record_id = item.get("id") or item.get("relicId")
            if skip_existing and already_fetched(SITE_NAME, str(record_id)):
                continue

            save_raw(
                SITE_NAME,
                str(record_id),
                json.dumps(item, ensure_ascii=False),
                url=ENDPOINT,
                license_note=LICENSE_NOTE,
            )
            saved += 1
            time.sleep(delay)

        page += 1

    print(f"[emuseum] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="e뮤지엄 유물정보 OpenAPI 크롤러")
    parser.add_argument("--api-key", default=os.environ.get("EMUSEUM_API_KEY"), help="data.go.kr 발급 서비스키")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--page-size", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit(
            "API 키가 없습니다. data.go.kr에서 'e뮤지엄 유물정보' 활용신청 후 "
            "EMUSEUM_API_KEY 환경변수 또는 --api-key로 전달하세요."
        )

    crawl(args.api_key, args.limit, args.page_size, args.delay, args.skip_existing)
