"""The Met (Metropolitan Museum of Art) Open Access API 크롤러.

https://metmuseum.github.io/ — 인증 불필요, CC0.
부서(department)별 오브젝트 ID 목록을 받아 오브젝트를 하나씩 조회해 원본 JSON을 저장한다.

사용법:
    python crawlers/met.py --limit 50 --department-id 11
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

API_BASE = "https://collectionapi.metmuseum.org/public/collection/v1"
SITE_NAME = "met"
LICENSE_NOTE = "CC0 - The Met Open Access (https://www.metmuseum.org/about-the-met/policies-and-documents/open-access)"


def fetch_object_ids(department_id: int | None) -> list[int]:
    params = {"departmentIds": department_id} if department_id else {}
    resp = requests.get(f"{API_BASE}/objects", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("objectIDs") or []


def fetch_object(object_id: int) -> dict:
    resp = requests.get(f"{API_BASE}/objects/{object_id}", timeout=30)
    resp.raise_for_status()
    return resp.json()


def crawl(limit: int, department_id: int | None, delay: float, skip_existing: bool) -> None:
    object_ids = fetch_object_ids(department_id)
    print(f"[met] 부서 {department_id}: 오브젝트 {len(object_ids)}건 확인")

    saved = 0
    for object_id in object_ids:
        if saved >= limit:
            break
        if skip_existing and already_fetched(SITE_NAME, str(object_id)):
            continue

        url = f"{API_BASE}/objects/{object_id}"
        try:
            data = fetch_object(object_id)
        except requests.RequestException as exc:
            print(f"[met] {object_id} 요청 실패: {exc}")
            continue

        save_raw(
            SITE_NAME,
            str(object_id),
            json.dumps(data, ensure_ascii=False),
            url=url,
            license_note=LICENSE_NOTE,
        )
        saved += 1
        time.sleep(delay)

    print(f"[met] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="The Met Open Access API 크롤러")
    parser.add_argument("--limit", type=int, default=50, help="이번 실행에서 수집할 최대 오브젝트 수")
    parser.add_argument(
        "--department-id",
        type=int,
        default=11,
        help="Met 부서 ID (기본 11 = European Paintings). 전체 부서는 생략 시 None으로 사용 불가하므로 명시 필요",
    )
    parser.add_argument("--delay", type=float, default=0.2, help="요청 간 대기(초) — API 예의상 부하 조절")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 오브젝트도 다시 수집",
    )
    args = parser.parse_args()
    crawl(args.limit, args.department_id, args.delay, args.skip_existing)
