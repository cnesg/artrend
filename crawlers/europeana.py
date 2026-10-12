"""Europeana(유럽 통합 문화유산 아카이브) Search API 크롤러.

이전에 docs/크롤러현황.md는 공개 데모키(api2demo)를 "테스트용 저용량 키"로
기록해뒀지만, 실제로 요청해보니 응답 헤더에 `ratelimit-policy: q=1000000;w=3600`
— 프로젝트(데모키 전체 공유) 기준 시간당 100만 요청 한도로 확인됨(2026-09-02).
전혀 저용량이 아니라 이 프로젝트 규모에선 사실상 무제한에 가까움 — 기존 문서
기록이 틀렸던 것. 그렇다고 정식 키 신청(본인 이메일 필요, 사용자 몫)이 불필요한
건 아니지만, 데모키만으로도 상당량 수집 가능해 바로 크롤러를 만듦.

Europeana는 미술관뿐 아니라 도서관·기록보관소·시청각 아카이브까지 아우르는
범유럽 문화유산 통합체라 원본 그대로 긁으면 유물/문서/음향 등이 섞인다.
프로젝트 스코프(미술품)에 맞춰 다음으로 제한:
  - TYPE:IMAGE (텍스트/사운드/3D/비디오 제외)
  - reusability:open (재사용 가능한 퍼블릭도메인/오픈 라이선스만)
  - qf=what:<카테고리> — painting/drawing/sculpture/print만 (공예/의상/사진 등은 제외)

https://api.europeana.eu/ — 데모키 api2demo, 인증 불필요(공개 키).

사용법:
    python crawlers/europeana.py --limit 5000
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

API_URL = "https://api.europeana.eu/record/v2/search.json"
SITE_NAME = "europeana"
API_KEY = "api2demo"
LICENSE_NOTE = "Europeana Search API (데모키 api2demo, 공개) - reusability:open 필터 적용"

# 미술품 카테고리만 (유물/공예/의상/사진 아카이브 등은 제외)
ART_CATEGORIES = ["painting", "drawing", "sculpture", "print"]


def fetch_page(category: str, cursor: str, rows: int) -> dict:
    def _do():
        resp = requests.get(
            API_URL,
            params={
                "wskey": API_KEY,
                "query": "*",
                "reusability": "open",
                "qf": [f"TYPE:IMAGE", f"what:{category}"],
                "cursor": cursor,
                "rows": rows,
                "profile": "rich",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    return with_retry(_do)


def crawl(limit: int, delay: float, skip_existing: bool) -> None:
    saved = 0
    for category in ART_CATEGORIES:
        cursor = "*"
        print(f"[europeana] 카테고리 '{category}' 수집 시작")
        while saved < limit:
            data = fetch_page(category, cursor, rows=100)
            items = data.get("items") or []
            if not items:
                break

            for item in items:
                record_id = (item.get("id") or "").strip("/").replace("/", "-")
                if not record_id:
                    continue
                if skip_existing and already_fetched(SITE_NAME, record_id):
                    continue
                save_raw(
                    SITE_NAME,
                    record_id,
                    json.dumps(item, ensure_ascii=False),
                    url=f"https://www.europeana.eu/item/{item.get('id', '')}",
                    license_note=LICENSE_NOTE,
                )
                saved += 1

            print(f"[europeana] {saved}건 진행 중... (카테고리: {category})")
            next_cursor = data.get("nextCursor")
            if not next_cursor or saved >= limit:
                break
            cursor = next_cursor
            time.sleep(delay)

    print(f"[europeana] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Europeana Search API 크롤러 (데모키, 미술품 카테고리만)")
    parser.add_argument("--limit", type=int, default=5000, help="이번 실행에서 수집할 최대 레코드 수")
    parser.add_argument("--delay", type=float, default=0.2, help="요청 간 대기(초)")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 레코드도 다시 수집",
    )
    args = parser.parse_args()
    crawl(args.limit, args.delay, args.skip_existing)
