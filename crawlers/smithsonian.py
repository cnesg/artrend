"""Smithsonian Open Access API 크롤러.

https://www.si.edu/openaccess — api.data.gov 발급 키 필요 (SMITHSONIAN_API_KEY 환경변수).
검색 엔드포인트로 CC0 개방 이미지 오브젝트를 페이지 단위로 받아 저장한다.

사용법:
    python crawlers/smithsonian.py --limit 50 --query "painting"
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
sys.stdout.reconfigure(line_buffering=True)

API_BASE = "https://api.si.edu/openaccess/api/v1.0"
SITE_NAME = "smithsonian"
LICENSE_NOTE = "CC0 - Smithsonian Open Access (https://www.si.edu/openaccess)"
ROWS_PER_PAGE = 1000

# 유물/과학표본 부서를 걷어내고 미술 소장 부서만 남긴다.
ART_UNITS = [
    "SAAM",   # Smithsonian American Art Museum
    "HMSG",   # Hirshhorn Museum and Sculpture Garden
    "NPG",    # National Portrait Gallery
    "CHNDM",  # Cooper Hewitt, Smithsonian Design Museum
    "FSG",    # National Museum of Asian Art (Freer)
    "NMAfA",  # National Museum of African Art
]


def _build_query(query: str, units: list[str]) -> str:
    unit_clause = " OR ".join(f"unit_code:{u}" for u in units)
    return f"{query} AND online_media_type:Images AND ({unit_clause})"


def crawl(limit: int, query: str, units: list[str], delay: float, skip_existing: bool) -> None:
    api_key = os.environ.get("SMITHSONIAN_API_KEY")
    if not api_key:
        print("[smithsonian] SMITHSONIAN_API_KEY 환경변수가 없습니다. crawlers/.env에 설정하세요.")
        return

    q = _build_query(query, units)
    saved = 0
    start = 0
    total = None
    while saved < limit:
        resp = requests.get(
            f"{API_BASE}/search",
            params={
                "q": q,
                "api_key": api_key,
                "rows": min(ROWS_PER_PAGE, limit - saved),
                "start": start,
            },
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json().get("response") or {}
        if total is None:
            total = body.get("rowCount")
            print(f"[smithsonian] 검색 결과 총 {total}건 (쿼리: {q})")
        rows = body.get("rows") or []
        if not rows:
            break

        for item in rows:
            if saved >= limit:
                break
            object_id = item["id"]
            if skip_existing and already_fetched(SITE_NAME, object_id):
                continue

            url = f"{API_BASE}/content/{object_id}"
            save_raw(
                SITE_NAME,
                object_id,
                json.dumps(item, ensure_ascii=False),
                url=url,
                license_note=LICENSE_NOTE,
            )
            saved += 1

        start += len(rows)
        print(f"[smithsonian] {saved}건 진행 중...", flush=True)
        time.sleep(delay)

    print(f"[smithsonian] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smithsonian Open Access API 크롤러")
    parser.add_argument("--limit", type=int, default=50, help="이번 실행에서 수집할 최대 오브젝트 수")
    parser.add_argument("--query", type=str, default="*:*", help="검색어 (기본 전체, 온라인 이미지 보유 항목만 필터)")
    parser.add_argument(
        "--units",
        type=str,
        default=",".join(ART_UNITS),
        help="쉼표로 구분한 유닛 코드 (기본: 미술 소장 부서만)",
    )
    parser.add_argument("--delay", type=float, default=0.2, help="요청 간 대기(초)")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 오브젝트도 다시 수집",
    )
    args = parser.parse_args()
    crawl(args.limit, args.query, args.units.split(","), args.delay, args.skip_existing)
