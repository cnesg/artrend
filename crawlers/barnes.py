"""반스재단(Barnes Foundation, 미국 필라델피아) 크롤러.

/api/search는 페이지네이션 파라미터(page/size/from 등)를 전부 무시하고
항상 같은 첫 10건만 반환하는 버그성 동작이라(2026-09-02 확인) 쓸 수 없다.
대신 sitemap.xml에서 오브젝트 ID를 뽑고, 개별 /api/objects/<id> 엔드포인트
(정상 동작 확인됨)로 하나씩 가져온다. robots.txt 없음(404).

사용법:
    python barnes.py
"""
from __future__ import annotations

import argparse
import re
import sys
import time

import requests

from common import already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

SITE_NAME = "barnes"
SITEMAP_URL = "https://collection.barnesfoundation.org/sitemap.xml"
OBJECT_API = "https://collection.barnesfoundation.org/api/objects/{id}"
LICENSE_NOTE = "Barnes Foundation Collection API (collection.barnesfoundation.org) — robots.txt 없음, 2026-09-02"
HEADERS = {"User-Agent": "artgraph-research-bot/1.0"}


def collect_ids() -> list[str]:
    def _do():
        resp = requests.get(SITEMAP_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.text

    xml = with_retry(_do)
    ids = sorted(set(re.findall(r"/objects/(\d+)/", xml)), key=int)
    return ids


def crawl(limit: int | None, delay: float, skip_existing: bool) -> None:
    ids = collect_ids()
    if limit:
        ids = ids[:limit]
    print(f"[barnes] 오브젝트 {len(ids)}건 확인, 저장 시작")

    saved = 0
    for record_id in ids:
        if skip_existing and already_fetched(SITE_NAME, record_id):
            continue

        url = OBJECT_API.format(id=record_id)

        def _do(u=url):
            resp = requests.get(u, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.text

        try:
            content = with_retry(_do)
        except requests.RequestException as exc:
            print(f"[barnes] {record_id} 조회 실패: {exc}")
            continue

        save_raw(SITE_NAME, record_id, content, url=url, license_note=LICENSE_NOTE)
        saved += 1
        if saved % 500 == 0:
            print(f"[barnes] {saved}건 저장 진행 중...")
        time.sleep(delay)

    print(f"[barnes] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="반스재단 컬렉션 크롤러")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument(
        "--no-skip-existing", dest="skip_existing", action="store_false"
    )
    args = parser.parse_args()
    crawl(args.limit, args.delay, args.skip_existing)
