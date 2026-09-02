"""The Met (Metropolitan Museum of Art) Open Access API 크롤러.

https://metmuseum.github.io/ — 인증 불필요, CC0.
부서(department)별 오브젝트 ID 목록을 받아 오브젝트를 하나씩 조회해 원본 JSON을 저장한다.
Met API는 오브젝트당 요청을 한 번씩 날리는 구조라 대량 수집은 오래 걸린다.

사용법:
    python crawlers/met.py --limit 50 --department-ids 11
    python crawlers/met.py --limit 300000 --department-ids 9,11,12,15,19,21   # 미술 관련 부서 전체
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

API_BASE = "https://collectionapi.metmuseum.org/public/collection/v1"
SITE_NAME = "met"
LICENSE_NOTE = "CC0 - The Met Open Access (https://www.metmuseum.org/about-the-met/policies-and-documents/open-access)"

# 미술(회화/조각/드로잉·판화/사진/근현대미술) 관련 부서만 — 무기/의상/악기 등 유물성 부서는 제외.
ART_DEPARTMENT_IDS = [9, 11, 12, 15, 19, 21]


def fetch_object_ids(department_id: int) -> list[int]:
    def _do():
        resp = requests.get(f"{API_BASE}/objects", params={"departmentIds": department_id}, timeout=30)
        resp.raise_for_status()
        return resp.json().get("objectIDs") or []

    return with_retry(_do)


def fetch_object(object_id: int) -> dict:
    def _do():
        resp = requests.get(f"{API_BASE}/objects/{object_id}", timeout=30)
        resp.raise_for_status()
        return resp.json()

    return with_retry(_do)


def crawl(limit: int, department_ids: list[int], delay: float, skip_existing: bool) -> None:
    object_ids: list[int] = []
    seen: set[int] = set()
    for dept_id in department_ids:
        try:
            ids = fetch_object_ids(dept_id)
        except requests.RequestException as exc:
            print(f"[met] 부서 {dept_id} 목록 조회 실패, 건너뜀: {exc}")
            continue
        print(f"[met] 부서 {dept_id}: 오브젝트 {len(ids)}건 확인")
        for oid in ids:
            if oid not in seen:
                seen.add(oid)
                object_ids.append(oid)
    print(f"[met] 중복 제거 후 총 {len(object_ids)}건 대상")

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
        if saved % 1000 == 0:
            print(f"[met] {saved}건 진행 중...")
        time.sleep(delay)

    print(f"[met] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="The Met Open Access API 크롤러")
    parser.add_argument("--limit", type=int, default=50, help="이번 실행에서 수집할 최대 오브젝트 수")
    parser.add_argument(
        "--department-ids",
        type=str,
        default=",".join(str(d) for d in ART_DEPARTMENT_IDS),
        help="쉼표로 구분한 Met 부서 ID 목록 (기본: 미술 관련 부서 전체)",
    )
    parser.add_argument("--delay", type=float, default=0.15, help="요청 간 대기(초) — API 예의상 부하 조절")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 오브젝트도 다시 수집",
    )
    args = parser.parse_args()
    department_ids = [int(d) for d in args.department_ids.split(",")]
    crawl(args.limit, department_ids, args.delay, args.skip_existing)
