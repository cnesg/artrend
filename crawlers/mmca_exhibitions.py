"""국립현대미술관(MMCA) 전시 이력 크롤러 — R5-기관(docs/최신성보강안_20260915.md).

소장품 크롤러(mmca.py)와 동일한 이유로 전시 목록 페이지가 쓰는 내부 JSON
엔드포인트(/exhibitions/AjaxExhibitionList.do)를 그대로 이용한다.
robots.txt(2026-09-15 재확인, https://www.mmca.go.kr/robots.txt)는
/about/vision.do, /html/Temporary/, /pr/collectionsGuideList.do,
/jpn/membership/membershipIntroduction.do 4개 경로만 제한 — /exhibitions/
계열은 막지 않음. 소장품 크롤러 때와 같은 결론(내부 AJAX 엔드포인트, 페이지당
부하만 낮게 유지).

startDate/endDate 파라미터를 서버가 실제로 필터링해줘서(확인: 2026-09-15)
최근 10년(2016-01-01~)만 요청 단계에서 제한한다 — 그 이전 전시는 이번
스코프 밖(R5는 "최신성" 보강이 목적).

exhArtist 필드는 자유 텍스트(예: "이중섭, 김환기 등 100여명")라 구조화된
작가 목록이 아니다 — 콤마로 분리해 최선 매칭을 시도하되, DB 적재는
별도 스크립트(pipeline/mmca_exhibitions_load.py)에서 처리하고 여기서는
raw JSON만 보존한다.

사용법:
    python crawlers/mmca_exhibitions.py --limit 400
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date

import requests

from common import already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

BASE_URL = "https://www.mmca.go.kr"
LIST_URL = f"{BASE_URL}/exhibitions/AjaxExhibitionList.do"
SITE_NAME = "mmca_exhibitions"
LICENSE_NOTE = "국립현대미술관 전시 목록 (robots.txt 허용 경로, 2026-09-15 확인)"
START_DATE = "2016-01-01"


def crawl(limit: int, delay: float, skip_existing: bool) -> None:
    saved = 0
    page = 1
    total = None
    end_date = date.today().isoformat()

    while saved < limit:
        def _fetch_page():
            resp = requests.post(
                LIST_URL,
                headers={"User-Agent": "Mozilla/5.0 (artgraph-research-bot)", "X-Requested-With": "XMLHttpRequest"},
                data={
                    "exhFlag": "03",
                    "searchExhPlaCd": "",
                    "searchExhCd": "",
                    "sort": "1",
                    "pageIndex": page,
                    "startDate": START_DATE,
                    "endDate": end_date,
                },
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()

        try:
            body = with_retry(_fetch_page)
        except requests.RequestException as exc:
            print(f"[mmca_exhibitions] {page}페이지 조회 실패, 중단: {exc}")
            break

        if total is None:
            total = body.get("paginationInfo", {}).get("totalRecordCount")
            print(f"[mmca_exhibitions] {START_DATE} 이후 전시 총 {total}건")

        items = body.get("exhibitionsList") or []
        if not items:
            break

        for item in items:
            if saved >= limit:
                break
            record_id = str(item.get("exhId"))
            if skip_existing and already_fetched(SITE_NAME, record_id):
                continue

            url = f"{BASE_URL}/exhibitions/exhibitionsDetail.do?exhId={item.get('exhId')}"
            save_raw(
                SITE_NAME,
                record_id,
                json.dumps(item, ensure_ascii=False),
                url=url,
                license_note=LICENSE_NOTE,
            )
            saved += 1

        print(f"[mmca_exhibitions] {saved}건 진행 중...", flush=True)
        time.sleep(delay)
        page += 1

    print(f"[mmca_exhibitions] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="국립현대미술관(MMCA) 전시 이력 크롤러")
    parser.add_argument("--limit", type=int, default=400, help="이번 실행에서 수집할 최대 전시 수")
    parser.add_argument("--delay", type=float, default=1.0, help="요청 간 대기(초)")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 전시도 다시 수집",
    )
    args = parser.parse_args()
    crawl(args.limit, args.delay, args.skip_existing)
