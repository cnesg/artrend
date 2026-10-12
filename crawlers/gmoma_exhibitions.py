"""경기도미술관(GMoMA) 전시 이력 크롤러 — R5-기관.

gmoma.py(소장품)와 동일 사이트 — 개별 전시 페이지(`/exhibitions/<id>`)를
ID 순차 브루트포스로 스캔한다(목록 페이지가 JS 무한스크롤이라 전체 ID를
정적으로 못 얻는 것도 동일, 2026-09-15 확인 기준 유효 ID가 1~207 사이에
분포). robots.txt(2026-09-08 확인, 2026-09-15 재확인 동일)는
`/attachment/`, `/storage/upload/`, `/wp-content/uploads/`만 Disallow —
`/exhibitions/*`는 허용 범위.

상세 페이지 `dl.meta`에서 장소(dt=장소)/참여작가(dt=참여작가, 콤마 구분
자유텍스트) 추출, `<meta property="startDate"/"endDate">`에서 기간 추출
(이 두 메타 태그가 없으면 날짜 미상으로 스킵 — 최근 10년 필터를 적용할
기준이 없기 때문).

사용법:
    python crawlers/gmoma_exhibitions.py --start-id 1 --end-id 215
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

from common import already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

BASE_URL = "https://gmoma.ggcf.kr"
SITE_NAME = "gmoma_exhibitions"
LICENSE_NOTE = "경기도미술관 전시 페이지 (robots.txt 허용 경로, 2026-09-15 확인 — ID 순차 브루트포스, 결번은 404로 자연 skip)"
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}
CUTOFF_YEAR = 2016
DATE_RE = re.compile(r'property="(startDate|endDate)"\s+datetime="(\d{4}-\d{2}-\d{2})"')


def parse_exhibition_page(html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("title")
    if not title_el:
        return None
    title = title_el.get_text(strip=True)

    dates = dict(DATE_RE.findall(html))
    start_date = dates.get("startDate")
    end_date = dates.get("endDate")
    if not start_date:
        return None

    fields: dict[str, str] = {}
    dl = soup.select_one("dl.meta")
    if dl:
        for dt in dl.find_all("dt"):
            label = dt.get_text(strip=True)
            dd = dt.find_next_sibling("dd")
            value = dd.get_text(" ", strip=True) if dd else ""
            fields[label] = value

    return {
        "title": title,
        "start_date": start_date,
        "end_date": end_date,
        "venue": fields.get("장소"),
        "artists_raw": fields.get("참여작가"),
    }


def crawl(start_id: int, end_id: int, delay: float, skip_existing: bool) -> None:
    saved = 0
    skipped_old = 0
    missing = 0

    for eid in range(start_id, end_id + 1):
        record_id = str(eid)
        if skip_existing and already_fetched(SITE_NAME, record_id):
            continue

        url = f"{BASE_URL}/exhibitions/{eid}"

        def _fetch():
            resp = requests.get(url, headers=HEADERS, timeout=30)
            return resp

        resp = with_retry(_fetch)
        if resp.status_code == 404:
            missing += 1
            time.sleep(delay)
            continue
        resp.raise_for_status()

        record = parse_exhibition_page(resp.text)
        if not record:
            missing += 1
            time.sleep(delay)
            continue

        if int(record["start_date"][:4]) < CUTOFF_YEAR:
            skipped_old += 1
            time.sleep(delay)
            continue

        save_raw(
            SITE_NAME,
            record_id,
            json.dumps(record, ensure_ascii=False),
            url=url,
            license_note=LICENSE_NOTE,
        )
        saved += 1
        if saved % 20 == 0:
            print(f"[gmoma_exhibitions] {eid}까지 스캔, 누적 {saved}건 저장", flush=True)
        time.sleep(delay)

    print(f"[gmoma_exhibitions] 완료 — 저장 {saved}건, 결번/파싱실패 {missing}건, 2016년 이전 스킵 {skipped_old}건")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="경기도미술관 전시 이력 크롤러")
    parser.add_argument("--start-id", type=int, default=1)
    parser.add_argument("--end-id", type=int, default=215)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    args = parser.parse_args()
    crawl(args.start_id, args.end_id, args.delay, args.skip_existing)
