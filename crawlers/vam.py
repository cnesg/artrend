"""V&A(Victoria and Albert Museum, 런던) Open API 크롤러.

https://developers.vam.ac.uk/ — 인증 불필요, Open Government Licence.
전체 소장품은 130만 건(가구/텍스타일/패션 등 디자인·공예 전반)이라 스코프(미술품)를
벗어나므로, objectType으로 회화/드로잉/판화/조각/사진/수채화/세밀화만 필터링해 수집한다.

사용법:
    python crawlers/vam.py --limit 500
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

API_BASE = "https://api.vam.ac.uk/v2"
SITE_NAME = "vam"
LICENSE_NOTE = "Open Government Licence - V&A Collections API (https://developers.vam.ac.uk/)"

# 미술품 스코프에 해당하는 objectType만 필터링 (가구/텍스타일/패션/도자기 등 디자인 소장품 제외)
ART_OBJECT_TYPES = [
    "Painting",
    "Drawing",
    "Print",
    "Sculpture",
    "Photograph",
    "Watercolour",
    "Miniature",
]


def crawl(limit_per_type: int, page_size: int, delay: float, skip_existing: bool) -> None:
    total_saved = 0

    for object_type in ART_OBJECT_TYPES:
        saved = 0
        page = 1
        while saved < limit_per_type:
            def _fetch_page():
                resp = requests.get(
                    f"{API_BASE}/objects/search",
                    params={
                        "q_object_type": object_type,
                        "page": page,
                        "page_size": page_size,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                return resp.json()

            try:
                body = with_retry(_fetch_page)
            except requests.RequestException as exc:
                print(f"[vam:{object_type}] {page}페이지 조회 실패, 중단: {exc}")
                break

            records = body.get("records") or []
            if not records:
                break

            for rec in records:
                if saved >= limit_per_type:
                    break
                system_number = rec.get("systemNumber")
                if not system_number:
                    continue
                record_id = f"{object_type}_{system_number}"
                if skip_existing and already_fetched(SITE_NAME, record_id):
                    saved += 1
                    continue

                rec["_object_type_query"] = object_type
                url = f"https://collections.vam.ac.uk/item/{system_number}"
                save_raw(
                    SITE_NAME,
                    record_id,
                    json.dumps(rec, ensure_ascii=False),
                    url=url,
                    license_note=LICENSE_NOTE,
                )
                saved += 1
                total_saved += 1

            print(f"[vam:{object_type}] {saved}건 진행 중...", flush=True)
            time.sleep(delay)
            page += 1

        print(f"[vam:{object_type}] 완료 — {saved}건")

    print(f"[vam] 전체 완료 — {total_saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V&A Museum Open API 크롤러 (미술품 objectType만)")
    parser.add_argument("--limit", type=int, default=1000, help="objectType당 수집할 최대 건수")
    parser.add_argument("--page-size", type=int, default=100, help="페이지당 요청 개수")
    parser.add_argument("--delay", type=float, default=0.2, help="요청 간 대기(초)")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 레코드도 다시 수집",
    )
    args = parser.parse_args()
    crawl(args.limit, args.page_size, args.delay, args.skip_existing)
