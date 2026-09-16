"""경기도미술관(GMoMA, Gyeonggi Museum of Modern Art) 소장품 크롤러.

공식 API/벌크덤프 없음 — `gmoma.ggcf.kr/collections/<id>` 개별 작품
페이지를 ID 순차 스캔(브루트포스, 404는 결번으로 skip)해서 수집한다.
목록 페이지(`/collections`)가 JS 무한스크롤이라 전체 ID 목록을 정적으로
못 얻어서(첫 배치 ~18개만 서버렌더링됨) 이 방식을 택함 — 2026-09-08
확인 기준 유효 ID가 대략 1~188 사이에 듬성듬성 분포(전체 소장품이 아니라
"소장품 하이라이트"급 큐레이션 컬렉션으로 추정, 개별 페이지에 상세
비평/설명 에세이가 붙어있는 게 특징).

robots.txt(2026-09-08 확인)는 `/attachment/`, `/storage/upload/`,
`/wp-content/uploads/`(업로드 파일 경로)만 차단 — `/collections/*`는
크롤링 허용 범위.

각 페이지에서 작가명(.collet-creator)/제목(.collet-tit)/설명 본문
(.section-02 p, 첫 collet-cont 블록 제외)/재료·크기·제작연도(dl.meta
dt-dd 쌍)/대표이미지(.section-01 img)를 추출.

사용법:
    python crawlers/gmoma.py --start-id 1 --end-id 188
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import requests
from bs4 import BeautifulSoup

from common import already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

BASE_URL = "https://gmoma.ggcf.kr"
SITE_NAME = "gmoma"
LICENSE_NOTE = "경기도미술관 소장품 페이지 (robots.txt 허용 경로, ID 순차 브루트포스 스캔 — 결번은 404로 자연 skip)"
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}


def parse_detail_page(html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one(".collet-tit")
    if not title_el:
        return None
    creator_el = soup.select_one(".collet-creator")

    desc_parts = []
    for p in soup.select(".section-02 > p"):
        if p.select_one(".collet-cont"):
            continue
        text = p.get_text(" ", strip=True)
        if text:
            desc_parts.append(text)
    description = "\n\n".join(desc_parts) or None

    fields: dict[str, str] = {}
    dl = soup.select_one("dl.meta")
    if dl:
        dts = dl.find_all("dt")
        for dt in dts:
            label = dt.get_text(strip=True)
            dd = dt.find_next_sibling("dd")
            value = dd.get_text(" ", strip=True) if dd else ""
            fields[label] = value

    img_el = soup.select_one(".section-01 img")
    image_url = img_el.get("src") if img_el else None
    if image_url and image_url.startswith("/"):
        image_url = BASE_URL + image_url

    return {
        "wriName": creator_el.get_text(strip=True) if creator_el else None,
        "artKname": title_el.get_text(strip=True),
        "description": description,
        "medium": fields.get("재료"),
        "dimensions": fields.get("크기"),
        "year": fields.get("제작연도"),
        "imageUrl": image_url,
    }


def crawl(start_id: int, end_id: int, delay: float, skip_existing: bool) -> None:
    saved = 0
    missing = 0

    for cid in range(start_id, end_id + 1):
        record_id = str(cid)
        if skip_existing and already_fetched(SITE_NAME, record_id):
            continue

        url = f"{BASE_URL}/collections/{cid}"

        def _fetch():
            resp = requests.get(url, headers=HEADERS, timeout=30)
            return resp

        resp = with_retry(_fetch)
        if resp.status_code == 404:
            missing += 1
            continue
        resp.raise_for_status()

        detail = parse_detail_page(resp.text)
        if detail is None:
            missing += 1
            continue

        save_raw(
            SITE_NAME,
            record_id,
            json.dumps(detail, ensure_ascii=False),
            url=url,
            license_note=LICENSE_NOTE,
        )
        saved += 1
        time.sleep(delay)

        if (saved + missing) % 20 == 0:
            print(f"[gmoma] id={cid} 진행 중... (저장 {saved}건 / 결번 {missing}건)", flush=True)

    print(f"[gmoma] 완료 — {saved}건 저장, {missing}건 결번/파싱실패")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="경기도미술관(GMoMA) 소장품 크롤러")
    parser.add_argument("--start-id", type=int, default=1)
    parser.add_argument("--end-id", type=int, default=188)
    parser.add_argument("--delay", type=float, default=0.3, help="요청 간 대기(초)")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 작품도 다시 수집",
    )
    args = parser.parse_args()
    crawl(args.start_id, args.end_id, args.delay, args.skip_existing)
