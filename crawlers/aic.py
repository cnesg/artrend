"""Art Institute of Chicago Open Access API 크롤러.

https://api.artic.edu/docs/ — 인증 불필요.
Object(작품) 목록을 페이지 단위로 받아 각 레코드를 저장한다.

사용법:
    python crawlers/aic.py --limit 50
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import requests

from common import already_fetched, save_raw

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

API_BASE = "https://api.artic.edu/api/v1"
SITE_NAME = "aic"
LICENSE_NOTE = "CC0 / CC-BY (설명 필드만 CC-BY) - Art Institute of Chicago Open Access (https://www.artic.edu/open-access)"

FIELDS = ",".join(
    [
        "id",
        "title",
        "artist_display",
        "artist_title",
        "date_display",
        "date_start",
        "date_end",
        "medium_display",
        "dimensions",
        "credit_line",
        "provenance_text",
        "publication_history",
        "exhibition_history",
        "is_public_domain",
    ]
)


def crawl(limit: int, page_size: int, delay: float, skip_existing: bool) -> None:
    saved = 0
    page = 1
    while saved < limit:
        resp = requests.get(
            f"{API_BASE}/artworks",
            params={"page": page, "limit": page_size, "fields": FIELDS},
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        items = body.get("data") or []
        if not items:
            break

        for item in items:
            if saved >= limit:
                break
            object_id = item["id"]
            if skip_existing and already_fetched(SITE_NAME, str(object_id)):
                continue

            url = f"{API_BASE}/artworks/{object_id}"
            save_raw(
                SITE_NAME,
                str(object_id),
                json.dumps(item, ensure_ascii=False),
                url=url,
                license_note=LICENSE_NOTE,
            )
            saved += 1
            time.sleep(delay)

        page += 1

    print(f"[aic] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Art Institute of Chicago Open Access API 크롤러")
    parser.add_argument("--limit", type=int, default=50, help="이번 실행에서 수집할 최대 작품 수")
    parser.add_argument("--page-size", type=int, default=50, help="페이지당 요청 개수")
    parser.add_argument("--delay", type=float, default=0.1, help="요청 간 대기(초)")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 작품도 다시 수집",
    )
    args = parser.parse_args()
    crawl(args.limit, args.page_size, args.delay, args.skip_existing)
