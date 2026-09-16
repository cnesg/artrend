"""리움미술관(Leeum Museum of Art) 소장품 크롤러.

공식 오픈 API/벌크덤프는 없지만, 소장품 검색 페이지가 쓰는 내부 JSON
엔드포인트를 그대로 이용한다(MMCA와 동일 패턴). robots.txt는 없음(404,
japan_museums/gmoma 등 기존 세션과 동일 판단 기준으로 진행) — ToS/공지에도
스크래핑 금지 문구 없음 확인(2026-09-08).

두 소장품 카테고리:
- traditional(고미술): `/leeum/collection/api/traditional?&page=N`, 167건
- modern(현대미술): `/leeum/collection/api/modern?&page=N`, 285건

응답은 `{"total": N, "paging": {"maxPage": M, ...}, "list": [...]}` 형태의
페이지네이션된 JSON. 항목별로 title(국문/영문)/creater(작가, 고미술은
대부분 공백)/createDate(시대·연도<br>재료기법 결합 문자열)/psize(크기)/
content(설명, 있는 경우만) 등을 담고 있다 — `pcode`를 레코드 id로 사용.

사용법:
    python crawlers/leeum.py --category traditional
    python crawlers/leeum.py --category modern
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

BASE_URL = "https://www.leeumhoam.org"
SITE_NAME = "leeum"
LICENSE_NOTE = "리움미술관 소장품 검색 내부 API (robots.txt 없음, ToS에 스크래핑 금지 문구 없음 확인 — MMCA와 동일 판단)"
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}


def crawl(category: str, limit: int, delay: float, skip_existing: bool) -> None:
    saved = 0
    page = 1
    max_page = None

    while saved < limit:
        url = f"{BASE_URL}/leeum/collection/api/{category}?&page={page}"

        def _fetch():
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.json()

        try:
            body = with_retry(_fetch)
        except requests.RequestException as exc:
            print(f"[leeum:{category}] {page}페이지 조회 실패, 중단: {exc}")
            break

        if max_page is None:
            max_page = body.get("paging", {}).get("maxPage")
            print(f"[leeum:{category}] 총 {body.get('total')}건, {max_page}페이지 확인")

        items = body.get("list") or []
        if not items:
            break

        for item in items:
            if saved >= limit:
                break
            record_id = (item.get("pcode") or "").strip()
            if not record_id:
                continue
            if skip_existing and already_fetched(SITE_NAME, record_id):
                continue

            save_raw(
                SITE_NAME,
                record_id,
                json.dumps(item, ensure_ascii=False),
                url=url,
                license_note=LICENSE_NOTE,
            )
            saved += 1

        print(f"[leeum:{category}] {saved}건 진행 중... ({page}/{max_page}페이지)", flush=True)
        if max_page and page >= max_page:
            break
        page += 1
        time.sleep(delay)

    print(f"[leeum:{category}] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="리움미술관(Leeum) 소장품 크롤러")
    parser.add_argument("--category", choices=["traditional", "modern"], required=True)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--delay", type=float, default=0.4)
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
    )
    args = parser.parse_args()
    crawl(args.category, args.limit, args.delay, args.skip_existing)
