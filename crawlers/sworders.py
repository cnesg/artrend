"""Sworders(영국, 1782년 설립) 낙찰 결과 크롤러.

**도메인 정정(2026-09-22, 중요)**: 오케스트레이터 지시서와 `docs/경매소스확장_20260922.md`
B-5절의 "Sworders(sworders.co.uk)"는 **틀린 도메인**이다. `sworders.co.uk`(복수형 s)는
Sworders와 무관한 제3자가 소유한 호스팅사(3itltd.co.uk) 플레이스홀더 "under construction"
페이지였다(TLS 인증서 SNI mismatch까지 확인 — schannel이 `SEC_E_WRONG_PRINCIPAL`을 던졌고,
`-k`로 무시하고 받아도 실제 콘텐츠는 플레이스홀더뿐이었다. Anthropic 인프라를 통한 WebFetch로도
동일하게 확인해 로컬 네트워크 문제가 아님을 배제했다). **실제 공식 도메인은 `sworder.co.uk`
(단수형)** — WebSearch로 재확인. 이 크롤러는 실제 도메인을 쓴다. `SITE_NAME`은 기존 조사
문서와의 연속성을 위해 "sworders"로 유지한다(raw 캐시 디렉터리명·pipeline 로더명도 동일).

2026-09-22 실제 확인 결과:
  - robots.txt: `User-agent: *` — `/account/ /admin/ /cms/lotdetailspdf/ /elmah/ /error/
    /imagebrowser/ /language/ /profile/ /seo/`만 차단, **`crawl-delay: 10`** 명시. 결과·경매·
    로트 경로에는 아무 제한 없음.
  - 이용약관: 일반 "웹사이트 이용약관"은 없고 경매 유형별 매매 조건(Specialist/Homes and
    Interiors/Online Timed) 3종뿐이다. **3종 전문에 crawling/scraping/spidering/robot/bot/
    data mining/harvesting/systematic downloading 키워드가 전혀 없다**(직접 확인). 저작권
    조항(사진·카탈로그 텍스트 저작권은 Sworders 소유)만 있어 **사진은 수집하지 않고 텍스트
    사실 데이터만 저장**한다.
  - 구조: `/results/?y=YYYY`(연도별 세일 목록, 완전 SSR, "Date:"/"Sale number:" 텍스트로
    노출)와 `/auction/details/<slug>/?au=<id>&pn=<page>&pp=96`(세일별 로트 목록, 완전 SSR,
    "Lot N", 작가명(국적, 생몰년), 작품명, "Sold for £X" 또는 "Estimated at £X - £Y"가 전부
    원본 HTML 텍스트) — curl로 직접 확인, JS 없이 그대로 나온다. 페이지가 로트 0건을 반환하면
    그게 마지막 페이지라는 신호(예: 415로트/96개=5페이지, pn=6은 200에 로트 0건).
  - 연도 범위: `/results/` 필터의 Year 셀렉트가 2018~2026을 제공(2017은 0건으로 실측 확인).

이미지는 저장하지 않는다(사실 데이터만 필요).

2단계로 수집한다:
  1) sales — `/results/?y=YYYY` 연도별 세일 목록 저장(세일당: 슬러그/au id/세일번호/날짜).
  2) lots  — 위에서 파싱한 (슬러그, au id) 조합마다 `/auction/details/...&pn=N&pp=96`을
             로트 0건이 나올 때까지 순회 저장.

사용법:
    python sworders.py --phase sales
    python sworders.py --phase lots
    python sworders.py --phase all
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
import time

import requests

from common import RAW_ROOT, already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

SITE_NAME = "sworders"
BASE = "https://www.sworder.co.uk"
RESULTS_URL = f"{BASE}/results/"
DETAILS_URL = f"{BASE}/auction/details/{{slug}}/"
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}
# robots.txt(2026-09-22)가 crawl-delay: 10을 명시 — 그대로 지킨다.
CRAWL_DELAY = 10.0
FIRST_YEAR = 2018  # /results/ Year 셀렉트 최솟값(2026-09-22 실측, 2017은 0건)
PAGE_SIZE = 96  # /auction/details/ 관찰된 페이지당 로트 수(그 이상 요청해도 96으로 고정됨)

LICENSE_NOTE = (
    "Sworders(www.sworder.co.uk) 공개 낙찰 결과 페이지 SSR HTML — robots.txt "
    "`crawl-delay: 10`만 명시, 결과/경매 경로 제한 없음, 매매조건 3종(Specialist/Homes and "
    "Interiors/Online Timed) 전문에 크롤링·스크래핑 금지 조항 없음 확인(사진 저작권 조항만 "
    "있어 이미지는 수집 안 함), 2026-09-22. 도메인 정정 주의: sworders.co.uk(복수형)는 무관한 "
    "제3자 플레이스홀더 — 실제 사이트는 sworder.co.uk(단수형)."
)

SLUG_AU_RE = re.compile(r"/auction/details/([a-z0-9-]+)\?au=(\d+)")
# 로트 카드 존재 여부 판정용. 주의: 페이지 본문에 항상 떠 있는 내비게이션("Lot Alerts",
# "Lot Archive", 정렬 옵션 "Lot number")에도 "Lot "이 그대로 들어 있어서, 순진하게
# `"Lot " in html` 로 마지막 페이지를 판정하면 **절대 참이 되지 않아 무한 루프**에 빠진다
# (2026-09-22 실제로 겪음 — au=753 세일이 pn=90+까지 갔다가 429를 맞고서야 드러남, 진짜
# 마지막 유효 페이지는 pn=3이었다). 실제 로트 카드에만 있는 `class='lot-title` 로 판정한다.
LOT_CARD_MARKER = "class='lot-title"


def _get(url: str, params: dict | None = None) -> requests.Response:
    def _do():
        resp = requests.get(url, params=params, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return resp

    return with_retry(_do, attempts=4, base_delay=5.0)


def crawl_sales(first_year: int, last_year: int, skip_existing: bool) -> None:
    saved = 0
    for year in range(first_year, last_year + 1):
        record_id = f"sales_{year}"
        if skip_existing and already_fetched(SITE_NAME, record_id, ext="html"):
            continue
        resp = _get(RESULTS_URL, params={"y": year})
        if not SLUG_AU_RE.search(resp.text):
            print(f"[sworders:sales] {year}년 결과 0건 — 저장은 하되 다음 연도 계속")
        save_raw(
            SITE_NAME, record_id, resp.text,
            url=f"{RESULTS_URL}?y={year}", license_note=LICENSE_NOTE, ext="html",
        )
        saved += 1
        print(f"[sworders:sales] {year}년 저장 완료")
        time.sleep(CRAWL_DELAY)
    print(f"[sworders:sales] 완료 — {saved}개 연도 저장")


def _sale_list() -> list[tuple[str, str]]:
    """저장된 sales_*.html에서 (slug, au_id) 유니크 목록을 만든다(au_id 기준 중복 제거)."""
    seen: dict[str, str] = {}
    for path in sorted((RAW_ROOT / SITE_NAME).glob("sales_*.html")):
        html_text = path.read_text(encoding="utf-8")
        for slug, au_id in SLUG_AU_RE.findall(html_text):
            seen.setdefault(au_id, slug)
    return [(slug, au_id) for au_id, slug in seen.items()]


def crawl_lots(skip_existing: bool, max_sales: int | None) -> None:
    sales = _sale_list()
    if not sales:
        print("[sworders:lots] sales_*.html이 없다 — 먼저 --phase sales부터 실행해라")
        return
    print(f"[sworders:lots] 세일 {len(sales)}개 대상")

    processed = 0
    total_pages = 0
    for slug, au_id in sorted(sales, key=lambda kv: int(kv[1])):
        if max_sales is not None and processed >= max_sales:
            break
        processed += 1
        url = DETAILS_URL.format(slug=slug)
        page = 1
        sale_pages = 0
        while True:
            record_id = f"lot_{au_id}_p{page:03d}"
            if skip_existing and already_fetched(SITE_NAME, record_id, ext="html"):
                page += 1
                sale_pages += 1
                if sale_pages > 200:  # 안전장치 — 이 규모의 세일은 없다
                    break
                continue
            try:
                resp = _get(url, params={"au": au_id, "pn": page, "pp": PAGE_SIZE})
            except requests.RequestException as exc:
                print(f"[sworders:lots] au={au_id} page={page} 요청 실패, 세일 중단: {exc}")
                break
            if LOT_CARD_MARKER not in resp.text:
                break  # 로트 0건 — 이 세일의 마지막 페이지
            save_raw(
                SITE_NAME, record_id, resp.text,
                url=f"{url}?au={au_id}&pn={page}&pp={PAGE_SIZE}",
                license_note=LICENSE_NOTE, ext="html",
            )
            sale_pages += 1
            total_pages += 1
            page += 1
            if sale_pages > 300:  # 방어적 안전장치 — 실측 최대는 5페이지(415로트) 수준
                print(f"[sworders:lots] au={au_id} 300페이지 초과 — 이상 상황으로 보고 중단")
                break
            time.sleep(CRAWL_DELAY)
        if processed % 10 == 0:
            print(f"[sworders:lots] {processed}/{len(sales)}개 세일 처리, 누적 {total_pages}페이지 저장")

    print(f"[sworders:lots] 완료 — 세일 {processed}개, {total_pages}페이지 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sworders(sworder.co.uk) 낙찰 결과 크롤러")
    parser.add_argument("--phase", choices=["sales", "lots", "all"], default="all")
    parser.add_argument("--first-year", type=int, default=FIRST_YEAR)
    parser.add_argument("--last-year", type=int, default=datetime.date.today().year)
    parser.add_argument("--max-sales", type=int, default=None, help="lots 단계에서 처리할 세일 수 제한(파일럿용)")
    parser.add_argument(
        "--no-skip-existing", dest="skip_existing", action="store_false",
        help="이미 저장된 페이지도 다시 수집",
    )
    args = parser.parse_args()

    if args.phase in ("sales", "all"):
        crawl_sales(args.first_year, args.last_year, args.skip_existing)
    if args.phase in ("lots", "all"):
        crawl_lots(args.skip_existing, args.max_sales)
