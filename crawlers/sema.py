"""서울시립미술관(SeMA) 소장품 크롤러.

공식 오픈API/벌크덤프 없음(Wikidata P195 폴백도 0건 확인됨, docs/크롤러현황.md
참고) — mmca.py와 동일한 이유로 소장품 검색 페이지를 직접 스크래핑한다.
MMCA와 달리 내부 JSON 엔드포인트가 아니라 서버렌더링 HTML 목록/상세 페이지.

robots.txt(2026-09-08 확인, `sema.seoul.go.kr/robots.txt`) 기준
`/kr/knowledge_research`는 명시적으로 Allow(막힌 건 대출/복제 신청 폼인
`/kr/knowledge_research/cllctn_rqstAD1`뿐) — 소장품 목록/상세 경로는
크롤링 허용 범위.

2단계 수집:
1. 목록 페이지(`/kr/knowledge_research/collection/list?currentPage=N`,
   GET) — `doDetail('WORK_xxx', 'CODE', '작가명', '제목')` 형태로 작품ID/
   분류코드/작가/제목이 이미 기계가 읽기 쉬운 형태로 박혀있어 정규식으로
   추출.
2. 상세 페이지(`/kr/knowledge_research/collection/collection_detail`,
   POST — artSeq/artCode1/wriName/artKname 필요) — 제작연도/재료·기법/
   작품규격/액자규격/관리번호/전시상태/기증자/작품설명/대표이미지 URL.

이미지 저작권 표시가 개별 필드로 없어(MMCA의 copyrightAllowYn 같은 것 없음)
메타데이터만 저장하고 이미지는 URL만 남긴다(다운로드하지 않음).

사용법:
    python crawlers/sema.py --limit 100
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

BASE_URL = "https://sema.seoul.go.kr"
LIST_URL = f"{BASE_URL}/kr/knowledge_research/collection/list"
DETAIL_URL = f"{BASE_URL}/kr/knowledge_research/collection/collection_detail"
SITE_NAME = "sema"
LICENSE_NOTE = "서울시립미술관 소장품 검색 (robots.txt 허용 경로, 메타데이터만 수집 — 이미지는 URL만 저장, 다운로드/저작권 확인 별도 필요)"
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}

DO_DETAIL_RE = re.compile(
    r"doDetail\('([^']*)',\s*'([^']*)',\s*'([^']*)',\s*'([^']*)'\)"
)
TOTAL_PAGE_RE = re.compile(r"\d+\s*/\s*(\d+)\s*페이지")


def parse_list_page(html: str) -> list[dict]:
    items = []
    for m in DO_DETAIL_RE.finditer(html):
        art_seq, art_code, artist, title = m.groups()
        items.append({"artSeq": art_seq, "artCode1": art_code, "wriName": artist, "artKname": title})
    return items


def fetch_detail(art_seq: str, art_code: str, wri_name: str, art_kname: str) -> dict:
    def _fetch():
        resp = requests.post(
            DETAIL_URL,
            headers=HEADERS,
            data={"artSeq": art_seq, "artCode1": art_code, "wriName": wri_name, "artKname": art_kname},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.text

    html = with_retry(_fetch)
    soup = BeautifulSoup(html, "html.parser")

    fields: dict[str, str] = {}
    for li in soup.select("ul.o_tbl_list li"):
        label_el = li.select_one("span.o_h1")
        if not label_el:
            continue
        label = label_el.get_text(strip=True)
        value_el = li.select_one("span:not(.o_h1)")
        value = value_el.get_text(" ", strip=True) if value_el else ""
        fields[label] = value

    img_el = soup.select_one("#mainImage")
    image_url = img_el.get("src") if img_el else None
    if image_url and image_url.startswith("//"):
        image_url = "https:" + image_url

    desc_el = soup.select_one("#exDesc .t-body")
    description = desc_el.get_text(" ", strip=True) if desc_el else None

    category_el = soup.select_one("a[href*='doArtCodeSearch']")
    category_label = category_el.get_text(strip=True) if category_el else None

    return {
        "artSeq": art_seq,
        "artCode1": art_code,
        "categoryLabel": category_label,
        "wriName": wri_name,
        "artKname": art_kname,
        "year": fields.get("제작연도"),
        "medium": fields.get("재료/기법"),
        "dimensions": fields.get("작품규격"),
        "frameDimensions": fields.get("액자규격"),
        "accessionNumber": fields.get("관리번호"),
        "exhibitionStatus": fields.get("전시상태"),
        "donor": fields.get("기증자"),
        "description": description,
        "imageUrl": image_url,
        "detailUrl": DETAIL_URL,
    }


def crawl(limit: int, delay: float, skip_existing: bool, start_page: int) -> None:
    saved = 0
    page = start_page
    total_pages = None

    while saved < limit:
        def _fetch_list():
            resp = requests.get(LIST_URL, headers=HEADERS, params={"currentPage": page}, timeout=30)
            resp.raise_for_status()
            return resp.text

        try:
            html = with_retry(_fetch_list)
        except requests.RequestException as exc:
            print(f"[sema] {page}페이지 목록 조회 실패, 중단: {exc}")
            break

        if total_pages is None:
            m = TOTAL_PAGE_RE.search(html)
            total_pages = int(m.group(1)) if m else None
            print(f"[sema] 총 {total_pages}페이지 확인")

        items = parse_list_page(html)
        if not items:
            print(f"[sema] {page}페이지에 항목 없음 — 종료")
            break

        for item in items:
            if saved >= limit:
                break
            art_seq = item["artSeq"]
            if skip_existing and already_fetched(SITE_NAME, art_seq):
                continue

            try:
                detail = with_retry(
                    lambda: fetch_detail(art_seq, item["artCode1"], item["wriName"], item["artKname"])
                )
            except requests.RequestException as exc:
                print(f"[sema] {art_seq} 상세 조회 실패, 건너뜀: {exc}")
                continue

            save_raw(
                SITE_NAME,
                art_seq,
                json.dumps(detail, ensure_ascii=False),
                url=f"{LIST_URL}?currentPage={page}",
                license_note=LICENSE_NOTE,
            )
            saved += 1
            time.sleep(delay)

        print(f"[sema] {saved}건 진행 중... ({page}/{total_pages or '?'}페이지)", flush=True)
        if total_pages and page >= total_pages:
            print("[sema] 마지막 페이지 도달 — 종료")
            break
        page += 1

    print(f"[sema] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="서울시립미술관(SeMA) 소장품 크롤러")
    parser.add_argument("--limit", type=int, default=50, help="이번 실행에서 수집할 최대 작품 수")
    parser.add_argument("--delay", type=float, default=0.3, help="상세페이지 요청 간 대기(초)")
    parser.add_argument("--start-page", type=int, default=1, help="시작할 목록 페이지 번호")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 작품도 다시 수집",
    )
    args = parser.parse_args()
    crawl(args.limit, args.delay, args.skip_existing, args.start_page)
