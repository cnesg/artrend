"""Phillips(www.phillips.com) 낙찰 결과 크롤러 — 미술 부문(Contemporary/Editions/
Photographs)만 대상. `timed.phillips.com`(별도 서브도메인, Auction Mobility LLC 약관에
크롤링 명시 금지)은 절대 건드리지 않는다 — 오직 `www.phillips.com`만.

2026-09-22 `docs/경매소스확장_20260922.md` A-3절에서 "조건부 가능(미착수)"로 남겨 뒀던 것을
`docs/logs/경매확장_phillips_20260922.md`에서 더 깊게 파서 실제 착수함. 판단 근거 요약
(전문은 그 로그 파일 참고):

  - robots.txt(2026-09-22 재확인): `Disallow: /bin/ /message/optin/ /Search /search /SEARCH
    /phillips/otis /*/filter/` 뿐 — `/auctions/past`, `/auction/<saleNumber>` 모두 허용.
    `/*/filter/`만 피하면 된다(과거경매 탐색 UI의 필터 링크 경로).
  - 일반 이용약관(Terms of Use) 페이지 자체가 사이트에 **없다** — `/sitemap`(Site Map) 페이지가
    스스로 나열하는 전체 사이트 구조에 Privacy/Cookie/Modern Slavery Policy 셋뿐이고
    "Terms"/"Legal" 카테고리가 아예 없음을 확인(부존재의 강한 정황 증거 — 완전한 사이트맵
    문서 자체가 그렇게 말하고 있음). Google 검색도 동일하게 "terms of use" 전용 페이지를
    찾지 못함. Wayback Machine CDX API로 phillips.com/terms* 과거 스냅샷도 조회 시도했으나
    Internet Archive 자체가 일시 장애(504/"Temporarily Offline")라 결론에 반영하지 못함 —
    이 부재가 "한 번도 존재한 적 없음"까지 증명하진 않는다.
  - Privacy Policy 본문에 크롤링/스크래핑/로봇/데이터마이닝 금지 문구 없음(직접 확인).
  - **결론(조건부 진행)**: robots 명시 허용 + Privacy Policy에 금지 문구 없음 + ToU 자체가
    게시돼 있지 않음(사이트맵으로 재확인) 조합으로 가벼운 point-in-time 수집을 조건부
    진행한다. 명시적 금지 조항을 나중에라도 발견하면 즉시 중단해야 한다.
  - `timed.phillips.com`(Auction Mobility LLC 약관, robots 무관하게 명시적 크롤링 금지 문구
    있음)은 이 파일이 건드리는 어떤 URL에도 포함되지 않는다 — 전부 `www.phillips.com` 경로.

구조: `/auctions/past`가 SSR인데다 `PhillipsReact.PastAuctions`에 하이드레이션용 JSON이
그대로 박혀 있다(`ReactDOM.hydrate(React.createElement(PhillipsReact.PastAuctions, {...}),
document.getElementById(...))`) — 과거 세일 897건의 saleNumber/제목/지역/날짜/부서가 목록
요청 **한 번**으로 전부 나온다(연도 필터 쿼리 파라미터를 줘도 서버가 같은 전체 목록을
그대로 반환 — 필터링은 클라이언트 JS 몫이라 실제로는 무의미. 그래서 index는 1회 요청으로
충분하다). 세일별 상세 페이지(`/auction/<saleNumber>`)도 완전 SSR이라 로트 그리드
(로트번호·작가·작품명·추정가·낙찰가)가 plain HTML에 그대로 있다(`curl`만으로 확인,
JS 실행 불필요). 통화는 지역별로 다르고(£/CHF/HK$/€/$...) 별도 환산 없이 원문 그대로
보존한다.

2단계로 수집한다:
  1) index — `/auctions/past` 1회 요청·저장. 임베드 JSON에서 세일 메타 전체를 뽑아
     department가 {Contemporary, Editions, Photographs}로만 이루어진(디자인·시계·주얼리가
     섞이지 않은) 세일만 고른다 — 프로젝트 스코프(미술품)를 지키기 위함
     (Bonhams WOA 제외, e뮤지엄 제외와 같은 기준).
  2) auctions — 위에서 고른 세일마다 `/auction/<saleNumber>` 상세 페이지 저장(로트 그리드
     SSR 전체).

사용법:
    python phillips.py --phase index
    python phillips.py --phase auctions --limit 20
    python phillips.py --phase all --limit 20
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

SITE_NAME = "phillips"
BASE = "https://www.phillips.com"
INDEX_URL = f"{BASE}/auctions/past"
AUCTION_URL = f"{BASE}/auction/{{sale_number}}"
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}
DELAY = 1.5  # 대형 경매사라 서버 부담 특히 조심 — 요청 간 최소 1.5초

# 이 셋으로만 이루어진 세일만 미술로 본다. 하나라도 Design/Watches/Jewelry가 섞이면
# 통째로 제외한다(로트 단위 부서 구분이 목록 JSON에 없어 세일 단위로만 걸러낼 수 있음 —
# 혼합 세일을 절반만 걸러 넣느니 통째로 빼는 쪽이 안전하다는 기존 프로젝트 관례를 따름).
ART_DEPARTMENTS = {"Contemporary", "Editions", "Photographs"}
IGNORE_TAGS = {"Online"}  # 채널 태그일 뿐 부서가 아님

LICENSE_NOTE = (
    "Phillips(www.phillips.com) 과거경매 결과 SSR HTML — robots.txt 명시 허용"
    "(Disallow: /Search /SEARCH /*/filter/ 등, /auctions/past·/auction/* 미포함), "
    "일반 이용약관 페이지 부재(사이트맵으로 재확인) + Privacy Policy에 크롤링 금지 문구 "
    "없음을 근거로 조건부 수집(2026-09-22). timed.phillips.com(별도 서브도메인, 명시적 "
    "크롤링 금지)과는 무관 — www.phillips.com만 수집."
)

CREATE_ELEMENT_MARKER = "React.createElement(PhillipsReact.PastAuctions, "


def _get(url: str, params: dict | None = None) -> requests.Response:
    def _do():
        resp = requests.get(url, params=params, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return resp

    return with_retry(_do, attempts=4, base_delay=5.0)


def _extract_past_auctions_json(html_text: str) -> dict:
    """`React.createElement(PhillipsReact.PastAuctions, {...}), document.getElementById(...)`
    에서 JSON 객체 부분만 괄호 균형(문자열 이스케이프 인식)으로 잘라내 파싱한다."""
    start = html_text.find(CREATE_ELEMENT_MARKER)
    if start < 0:
        raise ValueError("PastAuctions 하이드레이션 스크립트를 찾지 못했습니다")
    start += len(CREATE_ELEMENT_MARKER)

    depth = 0
    in_str = False
    esc = False
    end = None
    for i in range(start, len(html_text)):
        c = html_text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise ValueError("PastAuctions JSON 괄호 균형을 맞추지 못했습니다")
    return json.loads(html_text[start:end])


def pick_art_sales(index_html: str) -> list[dict]:
    """미술 부서로만 구성된 세일만 골라 (saleNumber, title, location, date) 리스트로."""
    obj = _extract_past_auctions_json(index_html)
    picked = []
    for record in obj.get("data", []):
        dept_names = {
            d.get("departmentName")
            for d in record.get("departments", [])
            if d.get("departmentName") not in IGNORE_TAGS
        }
        if not dept_names or not dept_names <= ART_DEPARTMENTS:
            continue
        sale_number = record.get("saleNumber")
        if not sale_number:
            continue
        picked.append(
            {
                "sale_number": sale_number,
                "title": record.get("auctionTitle"),
                "location": record.get("locationName"),
                "start_date": record.get("startDateTimeOffset"),
                "departments": sorted(dept_names),
            }
        )
    return picked


def crawl_index() -> None:
    resp = _get(INDEX_URL)
    save_raw(
        SITE_NAME,
        "index",
        resp.text,
        url=INDEX_URL,
        license_note=LICENSE_NOTE,
        ext="html",
    )
    picked = pick_art_sales(resp.text)
    print(f"[phillips:index] 저장 완료 — 전체 과거경매 중 미술 부서 전용 세일 {len(picked)}건")


def crawl_auctions(limit: int | None, skip_existing: bool) -> None:
    index_path = RAW_ROOT / SITE_NAME / "index.html"
    if not index_path.exists():
        print("[phillips:auctions] index.html이 없습니다 — 먼저 --phase index 실행 필요")
        return
    index_html = index_path.read_text(encoding="utf-8")
    picked = pick_art_sales(index_html)
    print(f"[phillips:auctions] 미술 부서 전용 세일 {len(picked)}건 중 수집 시작")

    saved = 0
    for sale in picked:
        if limit is not None and saved >= limit:
            break
        sale_number = sale["sale_number"]
        record_id = f"auction_{sale_number}"
        if skip_existing and already_fetched(SITE_NAME, record_id, ext="html"):
            continue

        url = AUCTION_URL.format(sale_number=sale_number)
        try:
            resp = _get(url)
        except requests.RequestException as exc:
            print(f"[phillips:auctions] {sale_number} 요청 실패, 건너뜀: {exc}")
            time.sleep(DELAY)
            continue

        save_raw(
            SITE_NAME,
            record_id,
            resp.text,
            url=url,
            license_note=LICENSE_NOTE,
            ext="html",
        )
        saved += 1
        if saved % 10 == 0:
            print(f"[phillips:auctions] {saved}세일 저장 진행 중... (최근: {sale_number})")
        time.sleep(DELAY)

    print(f"[phillips:auctions] 완료 — {saved}세일 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phillips(www.phillips.com) 낙찰 결과 크롤러")
    parser.add_argument("--phase", choices=["index", "auctions", "all"], default="all")
    parser.add_argument("--limit", type=int, default=None, help="이번 실행에서 저장할 최대 세일 수")
    parser.add_argument(
        "--no-skip-existing", dest="skip_existing", action="store_false",
        help="이미 저장된 세일도 다시 수집",
    )
    args = parser.parse_args()

    if args.phase in ("index", "all"):
        crawl_index()
    if args.phase in ("auctions", "all"):
        crawl_auctions(args.limit, args.skip_existing)
