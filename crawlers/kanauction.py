"""칸옥션(kanauction.kr) 지난경매 낙찰 결과 크롤러.

`docs/경매ToS확인_20260917.md`가 "사이트 가용성이 낮아 약관을 못 열어봤다"며 **불명확**으로
남겨 뒀던 곳. 2026-09-22 재확인 결과 가용성 문제는 해소됐고 약관도 찾았다:

  - robots.txt(2026-09-22): `User-agent: *` / `Allow: /` / `Disallow: /admin/` `/common/`
    — 지난경매 경로에 제한 없음.
  - 약관은 푸터가 아니라 경매참여 안내 페이지 본문에 실려 있었다
    (`/information/application`, "주식회사 칸옥션 약관"). 전문에 크롤링/스크래핑/자동수집/
    로봇/데이터마이닝/무단복제 금지 조항이 **없다**. 저작권 관련 조항은 제7조 ③
    "회사는 경매 출품을 위한 촬영한 작품 사진에 대한 사용권 및 저작권을 갖습니다" 하나뿐 —
    **작품 사진은 수집하지 않고 텍스트 사실 데이터만 저장**하는 것으로 이 조항을 지킨다.

같은 재조사에서 K-Auction(k-auction.com)은 전 페이지 공통 푸터에 "크롤링/스크래핑은 엄격히
금지됩니다"가 명시돼 있어 **불가 확정**으로 뒤집혔다(서울옥션·Sotheby's와 동급) —
`docs/경매소스확장_20260922.md` 참고.

지난경매 목록(`/auction/past/main`)이 완전 SSR이라 목록 페이지만으로 회차명/로트번호/
작가(호·한자·생몰년 포함)/작품명/제작연도/재질/규격/추정가/낙찰가가 전부 텍스트로 나온다.
상세 페이지가 따로 없으므로(목록의 `<a href="#">`) 목록만 받으면 끝이다.

정렬을 `sort=date_asc`(오래된 순)로 고정한다 — 기본값(최신순)은 신규 경매가 열릴 때마다
페이지 경계가 밀려 재실행 시 중복/누락이 생긴다. 2026-09-22 기준 634페이지 × 10건 ≈ 6,340건
(제1회~제44회, 낙찰가가 없는 유찰 로트 포함 — 낙찰 여부 판정은 pipeline 몫).

사용법:
    python kanauction.py
    python kanauction.py --refetch-last 3   # 마지막 N페이지 강제 재수집(증분 갱신용)
"""
from __future__ import annotations

import argparse
import re
import sys
import time

import requests

from common import RAW_ROOT, already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

SITE_NAME = "kanauction"
LIST_URL = "http://www.kanauction.kr/auction/past/main"
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}
DELAY = 1.5

LICENSE_NOTE = (
    "칸옥션 지난경매 목록 페이지 SSR HTML — robots.txt `Allow: /`(관리자 경로만 차단), "
    "약관(/information/application)에 크롤링·스크래핑 금지 조항 없음 확인(작품 사진 저작권 "
    "조항만 있어 이미지는 수집 안 함), 2026-09-22"
)

ITEM_ID_RE = re.compile(r">(A\d{6,})<")


def _fetch(page: int) -> str:
    def _do():
        resp = requests.get(
            LIST_URL, params={"page": page, "sort": "date_asc"}, headers=HEADERS, timeout=60
        )
        resp.raise_for_status()
        return resp.text

    return with_retry(_do, attempts=4, base_delay=5.0)


def _last_saved_page() -> int:
    pages = [int(p.stem.split("_p")[-1]) for p in (RAW_ROOT / SITE_NAME).glob("list_p*.html")]
    return max(pages) if pages else 0


def crawl(start_page: int, max_pages: int | None, skip_existing: bool, refetch_last: int) -> None:
    force_from = None
    if refetch_last > 0:
        last = _last_saved_page()
        if last:
            force_from = max(1, last - refetch_last + 1)
            print(f"[kanauction] page {force_from}~{last} 은 강제 재수집")

    saved = 0
    page = start_page
    while True:
        if max_pages is not None and saved >= max_pages:
            break
        record_id = f"list_p{page:04d}"

        forced = force_from is not None and page >= force_from
        if skip_existing and not forced and already_fetched(SITE_NAME, record_id, ext="html"):
            page += 1
            continue

        html = _fetch(page)
        if not ITEM_ID_RE.search(html):
            print(f"[kanauction] page {page} 결과 0건 — 마지막 페이지로 판단하고 종료")
            break

        save_raw(
            SITE_NAME,
            record_id,
            html,
            url=f"{LIST_URL}?page={page}&sort=date_asc",
            license_note=LICENSE_NOTE,
            ext="html",
        )
        saved += 1
        if saved % 25 == 0:
            print(f"[kanauction] {saved}페이지 저장 (현재 page={page})")
        page += 1
        time.sleep(DELAY)

    print(f"[kanauction] 완료 — {saved}페이지 저장")


TOTAL_PAGES_RE = re.compile(r"/\s*&nbsp;&nbsp;(\d+)</div>")


def crawl_years(first_year: int, last_year: int, skip_existing: bool) -> None:
    """연도별 '첫 회차 / 마지막 회차'만 받아 회차→연도 경계표를 만든다.

    목록에 **경매 날짜가 아예 없다** — 회차명(제N회 …)만 나온다. 그렇다고 날짜를
    지어내면 안 되므로, 검색 폼의 경매일자 필터(svSS/svSE)를 연 단위로 걸어
    "그 해의 첫 회차와 마지막 회차"만 확인한다. 목록이 날짜 오름차순으로 고정돼 있어서
    이 두 경계만 알면 그 사이 회차는 전부 그 해 것으로 **정확히** 판정된다.
    연 단위라 pipeline에서는 `YYYY-01-01`로 적재한다(raw_iter.year_to_date와 같은
    기존 관례 — 연도만 아는 소스를 다루는 방식).

    비용은 연도당 최대 2회 요청(약 26회)뿐이다.
    """
    for year in range(first_year, last_year + 1):
        for which in ("first", "last"):
            record_id = f"year_{year}_{which}"
            if skip_existing and already_fetched(SITE_NAME, record_id, ext="html"):
                continue

            def _do(page: int) -> str:
                resp = requests.get(
                    LIST_URL,
                    params={
                        "page": page,
                        "sort": "date_asc",
                        "svSS": f"{year}-01-01",
                        "svSE": f"{year}-12-31",
                    },
                    headers=HEADERS,
                    timeout=60,
                )
                resp.raise_for_status()
                return resp.text

            html_first = with_retry(lambda: _do(1), attempts=4, base_delay=5.0)
            if not ITEM_ID_RE.search(html_first):
                break  # 그 해에 경매 없음 — last도 볼 필요 없다
            if which == "first":
                page_html, page_no = html_first, 1
            else:
                m = TOTAL_PAGES_RE.search(html_first)
                page_no = int(m.group(1)) if m else 1
                page_html = html_first if page_no == 1 else with_retry(
                    lambda: _do(page_no), attempts=4, base_delay=5.0
                )

            save_raw(
                SITE_NAME, record_id, page_html,
                url=f"{LIST_URL}?page={page_no}&sort=date_asc&svSS={year}-01-01&svSE={year}-12-31",
                license_note=LICENSE_NOTE, ext="html",
            )
            time.sleep(DELAY)
    print(f"[kanauction] 연도 경계표 수집 완료 ({first_year}~{last_year})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="칸옥션 지난경매 낙찰 결과 크롤러")
    parser.add_argument("--phase", choices=["list", "years", "all"], default="list")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--refetch-last", type=int, default=0, help="마지막 N페이지 강제 재수집")
    parser.add_argument("--first-year", type=int, default=2013)
    parser.add_argument("--last-year", type=int, default=2026)
    parser.add_argument(
        "--no-skip-existing", dest="skip_existing", action="store_false",
        help="이미 저장된 페이지도 다시 수집",
    )
    args = parser.parse_args()
    if args.phase in ("list", "all"):
        crawl(args.start_page, args.max_pages, args.skip_existing, args.refetch_last)
    if args.phase in ("years", "all"):
        crawl_years(args.first_year, args.last_year, args.skip_existing)
