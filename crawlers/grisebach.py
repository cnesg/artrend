"""Villa Grisebach(베를린) 낙찰 아카이브 수집 — 공개 "Archive Collection" 목록 페이지 SSR 파싱.

2026-09-22 경매 소스 확장 조사에서 찾은 신규 소스. 이 사이트를 고른 근거:

  - robots.txt(2026-09-22 직접 확인)가 **`anthropic-ai`와 `ClaudeBot`을 이름으로 지목해
    명시적으로 허용**한다(`Disallow:` 빈 값 + `Crawl-delay: 2`). 차단 대상은 Baiduspider·
    SemrushBot·Bytespider·AhrefsBot 등 SEO/스크래퍼 계열뿐이고, 결과 아카이브 경로에는
    아무 제한이 없다. 지금까지 수집한 어떤 소스보다 명확한 허용 시그널이다.
  - Impressum(`/en/imprint`)·개인정보·Conditions of sale 전문에 크롤링/스크래핑/데이터마이닝/
    자동화 수집 금지 조항이 없고, 독일 사이트에서 흔한 §44b UrhG **TDM 유보(Vorbehalt) 문구도
    없다**(2026-09-22 확인). robots.txt 통과 + ToS 통과 둘 다 충족.
  - 아카이브가 완전 SSR이라 헤드리스 브라우저 없이 평문 GET만으로 읽힌다. 게다가
    `?sortBy=auction_number&sortDirection=asc`가 GET으로 먹혀서 **정렬이 시간에 따라 흔들리지
    않는다** — 기본 정렬(낙찰가 내림차순)로 받으면 새 경매가 추가될 때마다 페이지 경계가
    밀려서 재실행 시 중복/누락이 생기는데, 경매번호 오름차순으로 고정하면 신규 로트는 항상
    맨 뒤 페이지에 붙어서 기존 페이지가 그대로 유지된다.

규모: 경매번호 186~377, 약 39,700건(50건/페이지 × 약 794페이지, 2026-09-22 기준).

2단계로 수집한다:
  1) list  — `/en/auctions/archive-collection?page=N` 목록 페이지 HTML 저장.
             작가/경매번호/로트번호/제목·제작연도/낙찰가(프리미엄 포함)/오브젝트 상세 id가
             전부 이 목록에 들어 있어 로트 단위 수집은 이것만으로 끝난다.
  2) dates — 목록에 **경매 날짜가 없다**. 상세 페이지(`/en/object-archive/<id>`)에만
             "Selected Works, Thursday, 26.11.2015" 형태로 있는데 한 장이 700KB가 넘어
             4만 건 전수 수집은 서버에도 과하다. 대신 **경매번호별로 대표 1건만** 받아
             경매번호→날짜 표를 만든다(약 190회 요청). 날짜는 경매번호 단위 속성이라
             이걸로 충분하다.

이미지 파일은 저장하지 않는다(사실 데이터만 수집).

사용법:
    python grisebach.py --phase list
    python grisebach.py --phase dates
    python grisebach.py --phase all
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

SITE_NAME = "grisebach"
BASE = "https://www.grisebach.com"
LIST_URL = f"{BASE}/en/auctions/archive-collection"
DETAIL_URL = f"{BASE}/en/object-archive/{{object_id}}"
HEADERS = {"User-Agent": "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"}
# robots.txt가 ClaudeBot/anthropic-ai 모두에 Crawl-delay 2를 걸어 뒀다 — 그대로 지킨다.
CRAWL_DELAY = 2.0

LICENSE_NOTE = (
    "Villa Grisebach 공개 낙찰 아카이브(Archive Collection) 목록 페이지 SSR HTML — "
    "robots.txt가 ClaudeBot/anthropic-ai를 이름으로 명시 허용(Crawl-delay 2), "
    "Imprint/Conditions of sale에 크롤링·TDM 금지 조항 없음 확인, 2026-09-22"
)

OBJECT_ID_RE = re.compile(r"/en/object-archive/(\d+)")
# 목록 항목 한 건은 `href=".../object-archive/<id>"` 로 시작하고, 그 안에서 같은 모양의
# 배지 <p>가 두 번 나온다 — 첫 번째가 경매번호, 두 번째가 로트번호. 여기서는 경매번호만
# 필요하다(로트 단위 파싱은 pipeline/grisebach.py 몫).
BADGE_RE = re.compile(r'min-w-10 rounded-sm[^>]*>\s*<!--\[if BLOCK\]><!\[endif\]-->\s*([^\s<]+)')


def _get(url: str, params: dict | None = None) -> requests.Response:
    def _do():
        resp = requests.get(url, params=params, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return resp

    return with_retry(_do, attempts=4, base_delay=5.0)


def crawl_list(start_page: int, max_pages: int | None, skip_existing: bool) -> None:
    saved = 0
    consecutive_failures = 0
    page = start_page
    while True:
        if max_pages is not None and saved >= max_pages:
            break
        if consecutive_failures >= 10:
            print(f"[grisebach:list] 연속 실패 {consecutive_failures}회 — 중단(page={page})")
            break
        record_id = f"list_p{page:04d}"

        if skip_existing and already_fetched(SITE_NAME, record_id, ext="html"):
            page += 1
            continue

        # 정렬을 경매번호 오름차순으로 고정 — 기본 정렬(낙찰가 순)은 신규 경매가 들어오면
        # 페이지 경계가 통째로 밀린다(위 모듈 독스트링 참고).
        params = {"page": page, "sortBy": "auction_number", "sortDirection": "asc"}
        try:
            resp = _get(LIST_URL, params)
        except requests.RequestException as exc:
            # 사이트 쪽 항구적 500이 특정 오프셋에 있다(2026-09-22 기준 page=60·147·151 …
            # 약 2% 빈도). 같은 페이지를 기본 정렬로 부르면 200이고, desc로 대응되는
            # 오프셋도 똑같이 500이라 방향과 무관하게 그 오프셋 자체가 깨진 그쪽 정렬
            # 쿼리 버그로 판단했다. 재시도까지 다 실패하면 그 페이지만 건너뛰고 계속한다 —
            # 한 페이지 때문에 4만 건 수집 전체가 죽으면 안 된다.
            # (빠진 2%를 회수하려면 기본 정렬로 전체를 한 번 더 돌아 object id로 합치면
            #  된다 — pipeline/grisebach.py가 이미 object id로 중복을 거른다.)
            print(f"[grisebach:list] page {page} 수집 실패, 건너뜀: {exc}")
            consecutive_failures += 1
            page += 1
            time.sleep(CRAWL_DELAY)
            continue
        consecutive_failures = 0
        object_ids = OBJECT_ID_RE.findall(resp.text)
        if not object_ids:
            print(f"[grisebach:list] page {page} 결과 0건 — 마지막 페이지로 판단하고 종료")
            break

        save_raw(
            SITE_NAME,
            record_id,
            resp.text,
            url=f"{LIST_URL}?page={page}&sortBy=auction_number&sortDirection=asc",
            license_note=LICENSE_NOTE,
            ext="html",
        )
        saved += 1
        if saved % 20 == 0:
            print(f"[grisebach:list] {saved}페이지 저장 (현재 page={page}, 로트 {len(set(object_ids))}건/페이지)")
        page += 1
        time.sleep(CRAWL_DELAY)

    print(f"[grisebach:list] 완료 — {saved}페이지 저장")


def _auction_to_object_map() -> dict[str, str]:
    """이미 저장한 목록 HTML에서 (경매번호 -> 대표 오브젝트 id) 표를 만든다."""
    mapping: dict[str, str] = {}
    site_dir = RAW_ROOT / SITE_NAME
    for path in sorted(site_dir.glob("list_p*.html")):
        html = path.read_text(encoding="utf-8")
        for chunk in html.split('href="https://www.grisebach.com/en/object-archive/')[1:]:
            object_id = chunk.split('"', 1)[0]
            badges = BADGE_RE.findall(chunk[:4000])
            if not badges or not object_id.isdigit():
                continue
            auction_number = badges[0]
            mapping.setdefault(auction_number, object_id)
    return mapping


def crawl_dates(skip_existing: bool) -> None:
    mapping = _auction_to_object_map()
    print(f"[grisebach:dates] 경매번호 {len(mapping)}개에 대해 대표 상세 페이지 수집")

    saved = 0
    for auction_number, object_id in sorted(mapping.items(), key=lambda kv: kv[0]):
        record_id = f"auction_{auction_number}"
        if skip_existing and already_fetched(SITE_NAME, record_id, ext="html"):
            continue
        url = DETAIL_URL.format(object_id=object_id)
        try:
            resp = _get(url)
        except requests.RequestException as exc:
            print(f"[grisebach:dates] 경매 {auction_number} 상세 요청 실패, 건너뜀: {exc}")
            continue
        save_raw(SITE_NAME, record_id, resp.text, url=url, license_note=LICENSE_NOTE, ext="html")
        saved += 1
        if saved % 20 == 0:
            print(f"[grisebach:dates] {saved}건 저장 진행 중...")
        time.sleep(CRAWL_DELAY)

    print(f"[grisebach:dates] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Villa Grisebach 낙찰 아카이브 크롤러")
    parser.add_argument("--phase", choices=["list", "dates", "all"], default="all")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--max-pages", type=int, default=None, help="이번 실행에서 저장할 최대 페이지 수")
    parser.add_argument(
        "--no-skip-existing", dest="skip_existing", action="store_false",
        help="이미 저장된 페이지도 다시 수집",
    )
    args = parser.parse_args()

    if args.phase in ("list", "all"):
        crawl_list(args.start_page, args.max_pages, args.skip_existing)
    if args.phase in ("dates", "all"):
        crawl_dates(args.skip_existing)
