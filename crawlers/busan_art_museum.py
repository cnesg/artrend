"""부산시립미술관(Busan Museum of Art) 소장품 크롤러.

공식 API/벌크덤프 없음, Wikidata P195 폴백도 사실상 커버리지 없음(한국
지역 미술관 공통 한계, docs/크롤러현황.md 참고) — 소장품 검색 페이지를
직접 스크래핑한다.

robots.txt(2026-09-08 확인, `art.busan.go.kr/robots.txt`)는 `Allow: /`에
`/uploadfiles/`, `/mng/`, `/cms/` 등 관리자/업로드 경로만 Disallow — 목록
페이지(`/tblTsite07ArtworkExp/listClient.nm`)는 크롤링 허용 범위.

**상세페이지는 이번 스코프에서 제외**: 상세 URL(`viewClient.nm`)이 세션
쿠키 + 목록 페이지마다 새로 발급되는 대형 `pagingParams` 토큰을 요구하는
것으로 보이는 서버사이드 CMS("U2 CMS")라 별도 요청으로 안정적으로 재현이
안 됨(테스트 중 매번 "페이지 주소가 잘못됨" 에러). 대신 목록 페이지
자체에 작가명/제목/제작연도/썸네일 이미지가 이미 노출돼 있어(MMCA 초기
버전과 동일한 스코프 제약) 이 필드만 우선 수집 — 재료/규격/설명은 비워둠.

목록: `/tblTsite07ArtworkExp/listClient.nm?page_no=N` (GET, 8건/페이지,
2026-09-08 확인 기준 마지막 페이지 378 = 총 약 3,019건).

사용법:
    python crawlers/busan_art_museum.py --limit 100
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

BASE_URL = "https://art.busan.go.kr"
LIST_URL = f"{BASE_URL}/tblTsite07ArtworkExp/listClient.nm"
SITE_NAME = "busan_art_museum"
LICENSE_NOTE = (
    "부산시립미술관 소장품 검색 (robots.txt 허용 경로, 목록 페이지 필드만 수집 — "
    "상세페이지는 세션토큰 요구로 이번 스코프 제외, 이미지는 URL만 저장)"
)
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}

ATTR_KVAL_RE = re.compile(r"idx=(\d+)&id=([^&]*)&manage_no=([^\"']*)")


def parse_list_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for li in soup.select("div.listTypeC li"):
        a = li.find("a", attrs={"name": "btnUpdate"})
        if not a:
            continue
        m = ATTR_KVAL_RE.search(a.get("attr-kval", ""))
        if not m:
            continue
        idx, record_id, manage_no = m.groups()

        img = li.select_one(".thumb_img img")
        image_url = img.get("src") if img else None
        if image_url and not image_url.startswith("http"):
            image_url = BASE_URL + image_url

        spans = li.select(".infor span.txt2")
        title = spans[0].get_text(strip=True) if spans else None
        year = spans[1].get_text(strip=True) if len(spans) > 1 else None
        name_el = li.select_one(".infor span.name")
        artist = name_el.get_text(strip=True) if name_el else None

        items.append(
            {
                "idx": idx,
                "id": record_id,
                "manageNo": manage_no,
                "wriName": artist,
                "artKname": title,
                "year": year,
                "imageUrl": image_url,
            }
        )
    return items


def crawl(limit: int, delay: float, skip_existing: bool, start_page: int) -> None:
    saved = 0
    page = start_page

    while saved < limit:
        def _fetch_list():
            resp = requests.get(LIST_URL, headers=HEADERS, params={"page_no": page}, timeout=30)
            resp.raise_for_status()
            return resp.text

        try:
            html = with_retry(_fetch_list)
        except requests.RequestException as exc:
            print(f"[busan_art_museum] {page}페이지 조회 실패, 중단: {exc}")
            break

        items = parse_list_page(html)
        if not items:
            print(f"[busan_art_museum] {page}페이지에 항목 없음 — 종료(마지막 페이지 도달로 추정)")
            break

        for item in items:
            if saved >= limit:
                break
            record_id = item["idx"]
            if skip_existing and already_fetched(SITE_NAME, record_id):
                continue

            save_raw(
                SITE_NAME,
                record_id,
                json.dumps(item, ensure_ascii=False),
                url=f"{LIST_URL}?page_no={page}",
                license_note=LICENSE_NOTE,
            )
            saved += 1

        print(f"[busan_art_museum] {saved}건 진행 중... ({page}페이지)", flush=True)
        page += 1
        time.sleep(delay)

    print(f"[busan_art_museum] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="부산시립미술관 소장품 크롤러")
    parser.add_argument("--limit", type=int, default=50, help="이번 실행에서 수집할 최대 작품 수")
    parser.add_argument("--delay", type=float, default=0.5, help="페이지 요청 간 대기(초)")
    parser.add_argument("--start-page", type=int, default=1, help="시작할 목록 페이지 번호")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 작품도 다시 수집",
    )
    args = parser.parse_args()
    crawl(args.limit, args.delay, args.skip_existing, args.start_page)
