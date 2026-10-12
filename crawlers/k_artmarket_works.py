"""K-ARTMARKET 낙찰 작품 DB(`/member/work/WorkList.do`) 크롤러 — 로트 단위 국내 낙찰가.

기존 `crawlers/kams_stats.py`가 같은 사이트의 **연도별 집계표**만 가져오고 있었고,
`docs/경매소스재조사_20260917.md` B-3절은 "K-ARTMARKET에 로트 단위 공개 검색 페이지는
없다"고 결론 냈었다. 2026-09-22 재조사에서 이 결론이 **틀렸음**이 확인됐다 —
`/member/work/WorkList.do`가 로그인 없이 **작품 55,729건**(2022-01~2026-09, 국내 경매사
10곳)을 서버 렌더링 HTML로 공개하고 있다. 당시엔 `/member/auction/` 경로만 뒤져서
`/member/work/` 경로를 못 봤던 것으로 보인다.

이 소스를 고른 근거:
  - 운영 주체가 문화체육관광부 + 예술경영지원센터 + 한국미술시가감정협회로, 사이트 스스로
    "국내 10개 경매사의 최근 5년간의 미술품 낙찰 작품의 정보(작가, 작품명, 낙찰가 등)를
    공개합니다"라고 밝히는 **공적 공개 데이터**다.
  - robots.txt(2026-09-22 재확인)에 `Disallow`가 한 줄도 없다(`User-agent: *` / `Allow: /`).
  - 서울옥션·케이옥션처럼 **자사 사이트 고지로는 크롤링을 명시 금지한 경매사**의 낙찰
    데이터도 여기 들어 있는데, 이건 그 경매사 사이트를 긁는 게 아니라 **공적 기관이
    회원사 동의 아래 직접 공개한 별개 소스**를 읽는 것이라 성격이 다르다
    (docs/경매소스확장_20260922.md에 이 구분을 기록해 둠).
  - 각 작품에 **UCI 식별자**(`I805-…`, KISTI 계열 국가 표준 식별자)가 붙어 있어 재실행 시
    로트 동일성 판정이 문자열 추측 없이 가능하다.

정렬을 `sortKey=end_dt_asc`(날짜 오래된 순)로 고정한다 — 기본값은 최신순이라 신규 낙찰이
쌓일 때마다 페이지 경계가 통째로 밀려 재실행 시 중복/누락이 생긴다. 과거순으로 고정하면
신규 로트는 항상 마지막 페이지에 붙는다.

이미지는 저장하지 않는다(사실 데이터만 수집).

사용법:
    python k_artmarket_works.py
    python k_artmarket_works.py --start-page 500 --max-pages 100
    python k_artmarket_works.py --refetch-last 3   # 마지막 N페이지는 강제 재수집(증분 갱신용)
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

SITE_NAME = "k_artmarket_works"
LIST_URL = "https://k-artmarket.kr/member/work/WorkList.do"
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}
RECORDS_PER_PAGE = 48
DELAY = 1.5

LICENSE_NOTE = (
    "K-ARTMARKET(문체부·예술경영지원센터·한국미술시가감정협회) 낙찰 작품 DB "
    "/member/work/WorkList.do 목록 페이지 SSR HTML — robots.txt에 Disallow 없음(전체 허용), "
    "국내 경매사 10곳 최근 5년 낙찰 정보를 공적 기관이 직접 공개, 2026-09-22 확인"
)

UCI_RE = re.compile(r'data-ucicd="([^"]+)"')


def _fetch(page: int) -> str:
    params = {
        "pageNo": page,
        "recordCountPerPage": RECORDS_PER_PAGE,
        "sortKey": "end_dt_asc",
    }

    def _do():
        resp = requests.get(LIST_URL, params=params, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return resp.text

    return with_retry(_do, attempts=4, base_delay=5.0)


def _last_saved_page() -> int:
    pages = [
        int(p.stem.split("_p")[-1])
        for p in (RAW_ROOT / SITE_NAME).glob("list_p*.html")
    ]
    return max(pages) if pages else 0


def crawl(start_page: int, max_pages: int | None, skip_existing: bool, refetch_last: int) -> None:
    # 증분 갱신: 마지막으로 저장된 N페이지는 새 낙찰이 붙어 내용이 바뀌었을 수 있으므로
    # already_fetched를 무시하고 다시 받는다.
    force_from = None
    if refetch_last > 0:
        last = _last_saved_page()
        if last:
            force_from = max(1, last - refetch_last + 1)
            print(f"[k_artmarket_works] page {force_from}~{last} 은 강제 재수집")

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
        ucis = UCI_RE.findall(html)
        if not ucis:
            print(f"[k_artmarket_works] page {page} 결과 0건 — 마지막 페이지로 판단하고 종료")
            break

        save_raw(
            SITE_NAME,
            record_id,
            html,
            url=f"{LIST_URL}?pageNo={page}&recordCountPerPage={RECORDS_PER_PAGE}&sortKey=end_dt_asc",
            license_note=LICENSE_NOTE,
            ext="html",
        )
        saved += 1
        if saved % 25 == 0:
            print(f"[k_artmarket_works] {saved}페이지 저장 (현재 page={page}, {len(ucis)}건/페이지)")
        page += 1
        time.sleep(DELAY)

    print(f"[k_artmarket_works] 완료 — {saved}페이지 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="K-ARTMARKET 낙찰 작품 DB 크롤러")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--refetch-last", type=int, default=0, help="마지막 N페이지 강제 재수집")
    parser.add_argument(
        "--no-skip-existing", dest="skip_existing", action="store_false",
        help="이미 저장된 페이지도 다시 수집",
    )
    args = parser.parse_args()
    crawl(args.start_page, args.max_pages, args.skip_existing, args.refetch_last)
