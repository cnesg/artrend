"""SMK(Statens Museum for Kunst, 덴마크 국립미술관) Open Data API 크롤러.

https://www.smk.dk/en/article/smk-api/ — 인증키 불필요, 무료.
순수 미술관(회화/판화/조각/드로잉)이라 e뮤지엄/MMCA와 달리 부서 필터링 없이
전체를 그대로 수집해도 유물 걱정이 없다.

사용법:
    python crawlers/smk.py --limit 100
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

API_BASE = "https://api.smk.dk/api/v1"
SITE_NAME = "smk"
LICENSE_NOTE = "SMK Open (https://www.smk.dk/en/article/smk-api/) — 저작권은 레코드별 rights/public_domain 필드로 개별 확인 필요"
ROWS_PER_PAGE = 2000


def crawl(limit: int, delay: float, skip_existing: bool) -> None:
    saved = 0
    offset = 0
    total = None

    while saved < limit:
        def _fetch_page():
            resp = requests.get(
                f"{API_BASE}/art/search/",
                params={"keys": "*", "offset": offset, "rows": min(ROWS_PER_PAGE, limit - saved)},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()

        try:
            body = with_retry(_fetch_page)
        except requests.RequestException as exc:
            print(f"[smk] offset={offset} 조회 실패, 중단: {exc}")
            break

        if total is None:
            total = body.get("found")
            print(f"[smk] 소장품 총 {total}건")

        items = body.get("items") or []
        if not items:
            break

        for item in items:
            if saved >= limit:
                break
            object_id = item["id"]
            if skip_existing and already_fetched(SITE_NAME, object_id):
                continue

            save_raw(
                SITE_NAME,
                object_id,
                json.dumps(item, ensure_ascii=False),
                url=item.get("frontend_url") or item.get("object_url"),
                license_note=LICENSE_NOTE,
            )
            saved += 1

        offset += len(items)
        print(f"[smk] {saved}건 진행 중...", flush=True)
        time.sleep(delay)

    print(f"[smk] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SMK(덴마크 국립미술관) Open Data API 크롤러")
    parser.add_argument("--limit", type=int, default=50, help="이번 실행에서 수집할 최대 작품 수")
    parser.add_argument("--delay", type=float, default=0.2, help="요청 간 대기(초)")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 작품도 다시 수집",
    )
    args = parser.parse_args()
    crawl(args.limit, args.delay, args.skip_existing)
