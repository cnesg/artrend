"""Cleveland Museum of Art Open Access API 크롤러.

https://openaccess-api.clevelandart.org/ — 인증 불필요.
작품 목록을 skip/limit으로 페이지네이션하며 저장한다.

사용법:
    python crawlers/cleveland.py --limit 50
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

API_BASE = "https://openaccess-api.clevelandart.org/api"
SITE_NAME = "cleveland"
LICENSE_NOTE = "Open Access - Cleveland Museum of Art (https://www.clevelandart.org/open-access)"

PAGE_SIZE = 100


def crawl(limit: int, delay: float, skip_existing: bool) -> None:
    saved = 0
    skip = 0
    while saved < limit:
        resp = requests.get(
            f"{API_BASE}/artworks/",
            params={"skip": skip, "limit": min(PAGE_SIZE, limit - saved)},
            timeout=30,
        )
        resp.raise_for_status()
        items = resp.json().get("data") or []
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

        skip += len(items)

    print(f"[cleveland] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cleveland Museum of Art Open Access API 크롤러")
    parser.add_argument("--limit", type=int, default=50, help="이번 실행에서 수집할 최대 작품 수")
    parser.add_argument("--delay", type=float, default=0.1, help="요청 간 대기(초)")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 작품도 다시 수집",
    )
    args = parser.parse_args()
    crawl(args.limit, args.delay, args.skip_existing)
