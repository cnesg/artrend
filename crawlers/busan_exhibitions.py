"""부산시립미술관(Busan Museum of Art) 전시 이력 크롤러 — R5-기관.

busan_art_museum.py(소장품)와 동일 사이트, 동일 제약. robots.txt(2026-09-15
재확인, `art.busan.go.kr/robots.txt`)는 `/uploadfiles/`, `/mng/`, `/cms/`,
`/ubiCustomMenu/`, `/ubiPaCommonVal_ex/`만 Disallow — 목록 페이지
(`/tblTsite07Display/listPastClient.nm`)는 허용 범위.

**상세페이지는 스코프 제외** — busan_art_museum.py와 같은 이유(U2 CMS,
세션 바인딩 `pagingParams` 토큰이 페이지마다 새로 발급돼 상세 요청 재현이
불안정). 목록 페이지 자체에 제목/기간이 이미 노출돼 있어 이 필드만 수집한다
— 작가 정보는 목록에 없어 이번 수집분은 전시-작가 링크 없이 exhibitions만
채운다(venue=부산시립미술관 단일 기관).

최근 10년(2016-01-01~) 시작일까지만 페이지네이션.

사용법:
    python crawlers/busan_exhibitions.py --max-pages 60
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time

import requests

from common import already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

BASE_URL = "https://art.busan.go.kr"
LIST_URL = f"{BASE_URL}/tblTsite07Display/listPastClient.nm"
SITE_NAME = "busan_exhibitions"
LICENSE_NOTE = "부산시립미술관 과거전시 목록 (robots.txt 허용 경로, 2026-09-15 확인 — 목록 필드만, 상세페이지 제외)"
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}
CUTOFF_YEAR = 2016

ITEM_RE = re.compile(
    r'attr-kval="id=(?P<id>\d+)"[\s\S]*?alt="(?P<alt>[^"]*)"[\s\S]*?'
    r'<span class="tit">(?P<title>[^<]*)</span>\s*'
    r'<span class="date">(?P<start>\d{4}-\d{2}-\d{2})\s*[–-]\s*(?P<end>\d{4}-\d{2}-\d{2})</span>',
)


def crawl(max_pages: int, delay: float, skip_existing: bool) -> None:
    saved = 0
    page = 1
    stop = False

    while page <= max_pages and not stop:
        def _fetch():
            resp = requests.get(LIST_URL, headers=HEADERS, params={"page_no": page}, timeout=30)
            resp.raise_for_status()
            return resp.text

        try:
            html = with_retry(_fetch)
        except requests.RequestException as exc:
            print(f"[busan_exhibitions] {page}페이지 조회 실패, 중단: {exc}")
            break

        items = list(ITEM_RE.finditer(html))
        if not items:
            print(f"[busan_exhibitions] {page}페이지에서 항목 없음 — 종료")
            break

        for m in items:
            start_year = int(m.group("start")[:4])
            if start_year < CUTOFF_YEAR:
                stop = True
                continue

            record_id = m.group("id")
            if skip_existing and already_fetched(SITE_NAME, record_id):
                continue

            record = {
                "id": record_id,
                "title": m.group("title").strip(),
                "start_date": m.group("start"),
                "end_date": m.group("end"),
                "alt": m.group("alt").strip(),
            }
            save_raw(
                SITE_NAME,
                record_id,
                json.dumps(record, ensure_ascii=False),
                url=f"{LIST_URL}?page_no={page}",
                license_note=LICENSE_NOTE,
            )
            saved += 1

        print(f"[busan_exhibitions] {page}페이지 처리, 누적 {saved}건 저장", flush=True)
        time.sleep(delay)
        page += 1

    print(f"[busan_exhibitions] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="부산시립미술관 전시 이력 크롤러")
    parser.add_argument("--max-pages", type=int, default=60)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    args = parser.parse_args()
    crawl(args.max_pages, args.delay, args.skip_existing)
