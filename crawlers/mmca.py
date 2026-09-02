"""국립현대미술관(MMCA) 소장품 크롤러.

공식 오픈API가 없어 소장품 검색 페이지가 쓰는 내부 JSON 엔드포인트
(/collections/AjaxCollectionsList.do)를 그대로 이용한다.
robots.txt(2026-09-02 확인)는 /pr/collectionsGuideList.do 등 일부 경로만
제한하고 이 엔드포인트는 막지 않음 — 단, 페이지당 요청 부하를 낮게 유지할 것.

사용법:
    python crawlers/mmca.py --limit 100
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

BASE_URL = "https://www.mmca.go.kr"
LIST_URL = f"{BASE_URL}/collections/AjaxCollectionsList.do"
SITE_NAME = "mmca"
LICENSE_NOTE = "국립현대미술관 소장품 검색 (robots.txt 허용 경로, 이미지 별도 저작권 확인 필요 — copyrightAllowYn 필드 참고)"
PAGE_SIZE = 100


def crawl(limit: int, delay: float, skip_existing: bool) -> None:
    saved = 0
    page = 1
    total = None

    while saved < limit:
        def _fetch_page():
            resp = requests.post(
                LIST_URL,
                headers={"User-Agent": "Mozilla/5.0 (artgraph-research-bot)", "X-Requested-With": "XMLHttpRequest"},
                data={"pageIndex": page, "pageUnit": PAGE_SIZE, "recordCountPerPage": PAGE_SIZE},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()

        try:
            body = with_retry(_fetch_page)
        except requests.RequestException as exc:
            print(f"[mmca] {page}페이지 조회 실패, 중단: {exc}")
            break

        if total is None:
            total = body.get("paginationInfo", {}).get("totalRecordCount")
            print(f"[mmca] 소장품 총 {total}건")

        items = body.get("collectionsList") or []
        if not items:
            break

        for item in items:
            if saved >= limit:
                break
            record_id = f"{item.get('museumId')}-{item.get('wrkinfoSeqno')}"
            if skip_existing and already_fetched(SITE_NAME, record_id):
                continue

            url = f"{BASE_URL}/collections/collectionsDetailPage.do?wrkinfoSeqno={item.get('wrkinfoSeqno')}"
            save_raw(
                SITE_NAME,
                record_id,
                json.dumps(item, ensure_ascii=False),
                url=url,
                license_note=LICENSE_NOTE,
            )
            saved += 1

        print(f"[mmca] {saved}건 진행 중...", flush=True)
        time.sleep(delay)
        page += 1

    print(f"[mmca] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="국립현대미술관(MMCA) 소장품 크롤러")
    parser.add_argument("--limit", type=int, default=50, help="이번 실행에서 수집할 최대 작품 수")
    parser.add_argument("--delay", type=float, default=0.5, help="요청 간 대기(초) — 공식 API가 아니라 부하 여유 있게")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 작품도 다시 수집",
    )
    args = parser.parse_args()
    crawl(args.limit, args.delay, args.skip_existing)
