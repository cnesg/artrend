"""Lyon & Turnbull(에든버러/영국, lyonandturnbull.com — 스코틀랜드 최대 미술품 경매사) 낙찰 결과 크롤러.

2026-09-22 실제 확인 결과:
  - robots.txt: `User-agent: *` — `/account/ /auth/ /search /collection_story /collection_event
    /collection_location`만 차단. `/auctions/past-auctions`와 개별 경매 페이지(`/auctions/<slug>`)는
    제한 없음. SemrushBot/SiteAuditBot에만 `Crawl-delay: 5`가 있고 `User-agent: *`에는
    crawl-delay 명시가 없다 — 예의상 최소 1.5초 간격을 지킨다(오케스트레이터 지시).
  - 이용약관: `/terms`(Website Terms of Use)와 `/conditions-of-sale`(경매 매매조건) 전문 확인.
    crawling/scraping/spidering/robot/harvest/data mining/automated collection/personal,
    non-commercial 키워드 전혀 없음. "Acceptable Use" 조항은 스팸·보안침해·명예훼손 등을
    금지할 뿐 자동 수집을 언급하지 않는다. `/privacy`도 확인 — 관련 조항 없음.
    저작권 조항(웹사이트 콘텐츠는 Lyon & Turnbull 소유, 재사용 시 출처 표시 요구)만 있어
    **이미지는 수집하지 않고 텍스트 사실 데이터(작가·작품명·낙찰가 등)만 저장**한다.
  - 구조: Next.js SSR 사이트. `/auctions/past-auctions`의 `__NEXT_DATA__` 스크립트 안에
    과거 경매 **310건 전체가 페이지네이션 없이 한 번에** 들어있다
    (`props.pageProps.auctionsListData`: title/saleNumber/date/arrowLink/auctionId/department).
    개별 경매 페이지(`/auctions/<slug>`)의 `__NEXT_DATA__`에는 `props.pageProps.lots` 배열에
    로트별 lot_no/title/dynamic_fields.sub_title/low/high/start_price/hammer_price/status
    (sold/unsold)/session_date가 **원본 그대로 구조화된 JSON**으로 들어있다 — HTML 텍스트를
    정규식으로 긁을 필요 없이 서버가 준 JSON을 그대로 저장하면 된다.
  - 통화: 전부 GBP(£, `auction.currency.symbol`로 확인).

이미지는 저장하지 않는다(사실 데이터만 필요).

save_raw에는 __NEXT_DATA__ 스크립트 태그 안의 JSON 텍스트를 **원본 그대로**(재직렬화하지 않고)
저장한다 — 서버가 실제로 내려준 바이트와 동일해야 "원본 저장" 원칙에 맞는다.

2단계로 수집한다:
  1) list — `/auctions/past-auctions` 1회 요청으로 과거 경매 전체 목록 저장.
  2) sales — 위 목록의 각 경매(arrowLink)를 순회하며 로트 JSON 저장.

사용법:
    python lyonandturnbull.py --phase list
    python lyonandturnbull.py --phase sales
    python lyonandturnbull.py --phase sales --max-sales 5   # 파일럿
    python lyonandturnbull.py --phase all
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time

import requests

from common import RAW_ROOT, already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

SITE_NAME = "lyonandturnbull"
BASE = "https://www.lyonandturnbull.com"
PAST_AUCTIONS_URL = f"{BASE}/auctions/past-auctions"
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}
# robots.txt(2026-09-22)에 User-agent: * 용 crawl-delay가 없다 — 지시서의 최소 기준(1.5초)을 지킨다.
CRAWL_DELAY = 1.5
LIST_RECORD_ID = "past_auctions_list"

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S
)

LICENSE_NOTE = (
    "Lyon & Turnbull(www.lyonandturnbull.com) 공개 낙찰 결과 페이지 — robots.txt는 "
    "/account/ /auth/ /search /collection_story /collection_event /collection_location만 "
    "차단(과거경매·경매 상세 경로 제한 없음), Website Terms of Use(/terms)·Conditions of "
    "Sale(/conditions-of-sale)·Privacy(/privacy) 전문에 크롤링/스크래핑/데이터마이닝/자동수집/ "
    "personal-non-commercial-only 금지 조항 없음 확인(2026-09-22). 페이지에 Next.js "
    "__NEXT_DATA__로 내려오는 구조화 JSON(작가/작품명/낙찰가/추정가/상태)을 원문 그대로 저장 — "
    "이미지는 수집하지 않는다(웹사이트 콘텐츠 저작권 조항 준수)."
)


def _get(url: str) -> requests.Response:
    def _do():
        resp = requests.get(url, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return resp

    return with_retry(_do, attempts=4, base_delay=5.0)


def _extract_next_data(html_text: str) -> str | None:
    m = NEXT_DATA_RE.search(html_text)
    return m.group(1) if m else None


def crawl_list(skip_existing: bool) -> None:
    if skip_existing and already_fetched(SITE_NAME, LIST_RECORD_ID, ext="json"):
        print("[lyonandturnbull:list] 이미 수집됨 — 스킵")
        return
    resp = _get(PAST_AUCTIONS_URL)
    next_data = _extract_next_data(resp.text)
    if not next_data:
        print("[lyonandturnbull:list] __NEXT_DATA__를 못 찾음 — 수집 중단")
        return
    parsed = json.loads(next_data)
    auctions = parsed["props"]["pageProps"]["auctionsListData"]
    save_raw(
        SITE_NAME, LIST_RECORD_ID, next_data,
        url=PAST_AUCTIONS_URL, license_note=LICENSE_NOTE, ext="json",
    )
    print(f"[lyonandturnbull:list] 과거 경매 {len(auctions)}건 목록 저장 완료")


def _load_auction_list() -> list[dict]:
    path = RAW_ROOT / SITE_NAME / f"{LIST_RECORD_ID}.json"
    if not path.exists():
        print("[lyonandturnbull:sales] 목록이 없다 — 먼저 --phase list부터 실행해라")
        return []
    parsed = json.loads(path.read_text(encoding="utf-8"))
    return parsed["props"]["pageProps"]["auctionsListData"]


def crawl_sales(skip_existing: bool, max_sales: int | None) -> None:
    auctions = _load_auction_list()
    if not auctions:
        return
    print(f"[lyonandturnbull:sales] 경매 {len(auctions)}건 대상")

    processed = 0
    saved = 0
    for item in auctions:
        if max_sales is not None and processed >= max_sales:
            break
        sale_number = item.get("saleNumber")
        arrow_link = item.get("arrowLink")
        if not sale_number or not arrow_link:
            continue
        record_id = f"sale_{sale_number}"
        processed += 1
        if skip_existing and already_fetched(SITE_NAME, record_id, ext="json"):
            continue
        url = f"{BASE}{arrow_link}"
        try:
            resp = _get(url)
        except requests.RequestException as exc:
            print(f"[lyonandturnbull:sales] {record_id} 요청 실패, 건너뜀: {exc}")
            continue
        next_data = _extract_next_data(resp.text)
        if not next_data:
            print(f"[lyonandturnbull:sales] {record_id} __NEXT_DATA__ 없음 — 건너뜀")
            continue
        save_raw(
            SITE_NAME, record_id, next_data,
            url=url, license_note=LICENSE_NOTE, ext="json",
        )
        saved += 1
        if saved % 10 == 0:
            print(f"[lyonandturnbull:sales] {saved}건 저장 (진행 {processed}/{len(auctions)})")
        time.sleep(CRAWL_DELAY)

    print(f"[lyonandturnbull:sales] 완료 — {saved}건 신규 저장 (대상 {processed}건)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lyon & Turnbull(lyonandturnbull.com) 낙찰 결과 크롤러")
    parser.add_argument("--phase", choices=["list", "sales", "all"], default="all")
    parser.add_argument("--max-sales", type=int, default=None, help="sales 단계에서 처리할 경매 수 제한(파일럿용)")
    parser.add_argument(
        "--no-skip-existing", dest="skip_existing", action="store_false",
        help="이미 저장된 페이지도 다시 수집",
    )
    args = parser.parse_args()

    if args.phase in ("list", "all"):
        crawl_list(args.skip_existing)
    if args.phase in ("sales", "all"):
        crawl_sales(args.skip_existing, args.max_sales)
