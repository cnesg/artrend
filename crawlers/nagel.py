"""Nagel Auktionen(슈투트가르트) 낙찰 로트 수집 — 카탈로그 목록 + 로트 상세 SSR 파싱.

2026-09-22 독일 경매사 확장 조사(Grisebach 성공 이후 후속)에서 찾은 신규 소스.
자세한 판정 근거는 `docs/logs/경매확장_nagel_20260922.md` 참고. 이 사이트를 고른 근거 요약:

  - 사용자가 지시한 도메인 `nagel-auktionen.com`은 **존재하지 않는 도메인**이다(DNS
    NXDOMAIN, 2026-09-22 직접 확인). 실제 공식 도메인은 **`www.auction.de`**다
    (웹 검색으로 재확인 — Wikipedia·공식 소셜 계정·명함 전화번호가 모두 이 도메인을
    가리킨다).
  - robots.txt(`https://www.auction.de/robots.txt`, 2026-09-22 확인): `User-agent: *` /
    `Disallow:`(빈 값, 즉 전면 허용) — 유일한 제한은 워드프레스 폼 업로드 경로
    (`/wp-content/uploads/wpforms/`)뿐이고 이 크롤러가 건드리는 `/en/auction-*/`,
    `/en/auctions/lot/`, `/en/service/result-lists/` 경로는 전부 허용 범위다.
    Grisebach처럼 `anthropic-ai`/`ClaudeBot`을 이름으로 지목한 명시적 허용은 없지만,
    (Lempertz·K-ARTMARKET과 같은 패턴으로) AI 봇을 이름으로 차단하지도 않는다.
  - Conditions of Sale(영문/독문 둘 다 원문 확인) — crawl/scrape/spider/robot/
    data mining/harvest/automat/§44b UrhG TDM 유보 키워드 전부 미검출.
  - Legal Notice(`/en/legal-notice/`)에 범용 저작권 고지가 있다: "The content of these
    websites may not be copied, distributed, modified or made accessible to third
    parties **for commercial purposes**." — 크롤링/스크래핑을 특정해 금지하는 문구가
    아니라 상업적 재배포를 금지하는 통상적인 저작권 고지다(Grisebach·Lempertz·
    K-ARTMARKET에도 있는 것과 동급 — 이 프로젝트가 지금까지 적용해 온 "크롤링 특정
    금지 키워드가 있는지"를 기준으로 하면 통과). 이미지는 저장하지 않고(사실 데이터만
    수집) 상업적 이용도 하지 않는다.
  - 구조가 Grisebach보다 오히려 낫다: 로트 상세 페이지 한 장에 작가명·생몰년(또는
    무명 공예품이면 산지·시대)·치수·설명·추정가·**낙찰가(data-value 속성으로 깔끔하게
    분리돼 있음)**가 전부 완전 SSR로 들어 있다.

3단계로 수집한다:
  1) codes  — `/en/service/result-lists/`(경매 코드·부문명·날짜·연도 표, 2020~2026)
              저장. 코드 목록과 날짜 판정의 근거.
  2) list   — 코드별 카탈로그 목록(`/en/auction-<code>/?items_per_page=500`) 저장.
              **카탈로그 페이지는 최근 회차만 남아 있다**(2026-09-22 확인 결과 대략
              811회차/2023년 이후만 200, 그 이전은 404 — 사이트 쪽 보존 기간으로
              추정). 카탈로그가 없는 회차는 로트별 작가 귀속이 불가능해(PDF
              결과지에는 로트번호+낙찰가만 있고 작가명이 없다) 건너뛴다.
  3) lots   — list 단계에서 저장한 카탈로그 HTML에서 로트 상세 링크
              (`/en/auctions/lot/?auction_uid=<code>&lot_id=<n>&suffix=<a|''>`)를
              추출해 각각 저장.

Crawl-delay는 robots.txt에 명시가 없어 사용자 지시대로 요청 간 1.75초를 둔다.
이미지 파일은 저장하지 않는다(사실 데이터만 수집).

사용법:
    python nagel.py --phase codes
    python nagel.py --phase list
    python nagel.py --phase lots [--max-auctions N] [--max-lots-per-auction N]
    python nagel.py --phase all
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

SITE_NAME = "nagel"
BASE = "https://www.auction.de"
RESULT_LISTS_URL = f"{BASE}/en/service/result-lists/"
CATALOG_URL_TMPL = f"{BASE}/en/auction-{{code}}/"
LOT_URL = f"{BASE}/en/auctions/lot/"
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}
# robots.txt에 Crawl-delay 지정이 없어 사용자 지시대로 1.75초(1.5~2초 범위) 사용.
CRAWL_DELAY = 1.75

LICENSE_NOTE = (
    "Nagel Auktionen(www.auction.de) 공개 카탈로그/로트 상세 SSR 페이지 — "
    "robots.txt 전면 허용(wpforms 경로만 예외), Conditions of Sale/Legal Notice에 "
    "크롤링·스크래핑·데이터마이닝 특정 금지 조항 없음(범용 상업적 재배포 금지 "
    "고지만 있음, 이미지 미수집/비상업적 이용으로 준수) 확인, 2026-09-22. "
    "지시받은 도메인 nagel-auktionen.com은 존재하지 않아 공식 도메인 auction.de로 대체."
)

LOT_HREF_RE = re.compile(
    r'auctions/lot/\?auction_uid=(\d+)&lot_id=(\d+)&suffix=([^&"]*)'
)
RESULT_ROW_RE = re.compile(
    r"<h1[^>]*itemprop=\"headline\"[^>]*>(\d{4})</h1>|"
    r"<td[^>]*>(\d+)</td>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>"
    r"<a href=\"(/Result/\d+\.pdf)\"",
    re.S,
)


def _get(url: str, params: dict | None = None) -> requests.Response:
    def _do():
        resp = requests.get(url, params=params, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return resp

    return with_retry(_do, attempts=4, base_delay=5.0)


def crawl_codes(skip_existing: bool) -> None:
    if skip_existing and already_fetched(SITE_NAME, "result_lists", ext="html"):
        print("[nagel:codes] 이미 저장됨 — 스킵")
        return
    resp = _get(RESULT_LISTS_URL)
    save_raw(
        SITE_NAME,
        "result_lists",
        resp.text,
        url=RESULT_LISTS_URL,
        license_note=LICENSE_NOTE,
        ext="html",
    )
    print("[nagel:codes] result-lists 페이지 저장 완료")


def _load_codes() -> list[str]:
    """저장된 result_lists.html에서 경매 코드 목록을 뽑는다(연도 판정은 pipeline 몫)."""
    path = RAW_ROOT / SITE_NAME / "result_lists.html"
    if not path.exists():
        raise SystemExit("[nagel] result_lists.html이 없다 — 먼저 --phase codes 실행")
    html_text = path.read_text(encoding="utf-8")
    codes = []
    for m in RESULT_ROW_RE.finditer(html_text):
        if m.group(2):
            codes.append(m.group(2))
    # 최신 회차부터(카탈로그가 남아있을 확률이 높다) 처리
    seen = set()
    ordered = []
    for c in sorted(set(codes), key=lambda x: -int(x)):
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def crawl_list(max_auctions: int | None, skip_existing: bool) -> None:
    codes = _load_codes()
    if max_auctions is not None:
        codes = codes[:max_auctions]
    print(f"[nagel:list] 경매 코드 {len(codes)}개 처리 시작")

    saved = 0
    not_found = 0
    for code in codes:
        record_id = f"catalog_{code}"
        if skip_existing and already_fetched(SITE_NAME, record_id, ext="html"):
            continue
        url = CATALOG_URL_TMPL.format(code=code)
        try:
            resp = requests.get(
                url, params={"items_per_page": 500}, headers=HEADERS, timeout=60
            )
        except requests.RequestException as exc:
            print(f"[nagel:list] 코드 {code} 요청 실패, 건너뜀: {exc}")
            time.sleep(CRAWL_DELAY)
            continue
        if resp.status_code == 404:
            # 카탈로그 보존 기간이 지난 옛 회차 — 작가 귀속이 불가능해 건너뛴다
            # (PDF 결과지에는 낙찰가만 있고 작가명이 없다).
            not_found += 1
            time.sleep(CRAWL_DELAY)
            continue
        resp.raise_for_status()
        save_raw(
            SITE_NAME,
            record_id,
            resp.text,
            url=str(resp.url),
            license_note=LICENSE_NOTE,
            ext="html",
        )
        saved += 1
        print(f"[nagel:list] 코드 {code} 저장 ({saved}건 완료, 카탈로그 없음 {not_found}건)")
        time.sleep(CRAWL_DELAY)

    print(f"[nagel:list] 완료 — {saved}개 카탈로그 저장, 카탈로그 없음(404) {not_found}개")


def _iter_lot_refs():
    """저장된 catalog_<code>.html에서 (auction_uid, lot_id, suffix)를 뽑는다."""
    site_dir = RAW_ROOT / SITE_NAME
    for path in sorted(site_dir.glob("catalog_*.html"), key=lambda p: -int(p.stem.split("_")[1])):
        code = path.stem.split("_", 1)[1]
        html_text = path.read_text(encoding="utf-8")
        seen = set()
        for auction_uid, lot_id, suffix in LOT_HREF_RE.findall(html_text):
            key = (auction_uid, lot_id, suffix)
            if key in seen:
                continue
            seen.add(key)
            yield code, auction_uid, lot_id, suffix


def crawl_lots(max_auctions: int | None, max_lots_per_auction: int | None, skip_existing: bool) -> None:
    saved = 0
    consecutive_failures = 0
    current_code = None
    per_auction_count = 0
    auctions_done = 0

    for code, auction_uid, lot_id, suffix in _iter_lot_refs():
        if code != current_code:
            if max_auctions is not None and auctions_done >= max_auctions:
                break
            current_code = code
            per_auction_count = 0
            auctions_done += 1
            print(f"[nagel:lots] 코드 {code} 로트 수집 시작")

        if max_lots_per_auction is not None and per_auction_count >= max_lots_per_auction:
            continue
        per_auction_count += 1

        record_id = f"lot_{code}_{lot_id}{suffix}"
        if skip_existing and already_fetched(SITE_NAME, record_id, ext="html"):
            continue
        if consecutive_failures >= 10:
            print(f"[nagel:lots] 연속 실패 {consecutive_failures}회 — 중단")
            break

        try:
            resp = _get(LOT_URL, {"auction_uid": auction_uid, "lot_id": lot_id, "suffix": suffix})
        except requests.RequestException as exc:
            print(f"[nagel:lots] {record_id} 요청 실패, 건너뜀: {exc}")
            consecutive_failures += 1
            time.sleep(CRAWL_DELAY)
            continue
        consecutive_failures = 0

        save_raw(
            SITE_NAME,
            record_id,
            resp.text,
            url=str(resp.url),
            license_note=LICENSE_NOTE,
            ext="html",
        )
        saved += 1
        if saved % 25 == 0:
            print(f"[nagel:lots] {saved}건 저장 진행 중... (현재 코드 {code})")
        time.sleep(CRAWL_DELAY)

    print(f"[nagel:lots] 완료 — {saved}건 저장, 경매 {auctions_done}회차 처리")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nagel Auktionen(auction.de) 낙찰 로트 크롤러")
    parser.add_argument("--phase", choices=["codes", "list", "lots", "all"], default="all")
    parser.add_argument("--max-auctions", type=int, default=None, help="처리할 최대 경매 회차 수(list/lots 공통)")
    parser.add_argument("--max-lots-per-auction", type=int, default=None, help="회차당 수집할 최대 로트 수(파일럿용)")
    parser.add_argument(
        "--no-skip-existing", dest="skip_existing", action="store_false",
        help="이미 저장된 페이지도 다시 수집",
    )
    args = parser.parse_args()

    if args.phase in ("codes", "all"):
        crawl_codes(args.skip_existing)
    if args.phase in ("list", "all"):
        crawl_list(args.max_auctions, args.skip_existing)
    if args.phase in ("lots", "all"):
        crawl_lots(args.max_auctions, args.max_lots_per_auction, args.skip_existing)
