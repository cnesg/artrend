"""Pinault Collection(프랑수아 피노 컬렉션) 소장 작품 크롤러.

https://lesoeuvres.pinaultcollection.com/ — 부르스 드 코메르스(파리)/팔라초
그라시·푼타 델라 도가나(베니스) 등에 전시된 현대미술 컬렉션의 공식 작품
데이터베이스(Drupal 기반, 정적 서버렌더링). robots.txt(2026-09-09 확인)에
AI 봇 차단 없음, /artworks·/artwork/* 경로 전부 허용.

목록 페이지(`/en/artworks?page=N`)를 순회하며 `/en/artwork/<slug>` 링크를
모으고, 각 상세 페이지(작가/제작년도/매체/크기/설명/전시이력 포함)를
raw_html로 저장한다.

사용법:
    python crawlers/pinault.py --limit 50   # 테스트
    python crawlers/pinault.py               # 전체
"""
from __future__ import annotations

import argparse
import re
import sys
import time

import requests

from common import already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

BASE_URL = "https://lesoeuvres.pinaultcollection.com"
SITE_NAME = "pinault"
LICENSE_NOTE = (
    "Pinault Collection 공식 작품 데이터베이스 — robots.txt AI봇 차단 없음, "
    "/artworks 경로 허용 확인 (https://lesoeuvres.pinaultcollection.com/robots.txt, 2026-09-09)"
)
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}

ARTWORK_LINK_RE = re.compile(r'href="(/en/artwork/[^"?#]+)"')


def fetch_list_page(page: int) -> str:
    def _do():
        resp = requests.get(f"{BASE_URL}/en/artworks", params={"page": page}, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.text

    return with_retry(_do)


def fetch_detail(slug: str) -> str:
    def _do():
        resp = requests.get(f"{BASE_URL}/en/artwork/{slug}", headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.text

    return with_retry(_do)


def collect_slugs(delay: float) -> list[str]:
    slugs: list[str] = []
    seen: set[str] = set()
    page = 0
    while True:
        html = fetch_list_page(page)
        found = [m.split("/")[-1] for m in ARTWORK_LINK_RE.findall(html)]
        new = [s for s in found if s not in seen]
        if not new:
            break
        for s in new:
            seen.add(s)
            slugs.append(s)
        print(f"[pinault] 목록 {page}페이지 처리 완료 — 누적 {len(slugs)}건")
        page += 1
        time.sleep(delay)
    return slugs


def crawl(limit: int, delay: float, skip_existing: bool) -> None:
    slugs = collect_slugs(delay)
    print(f"[pinault] 작품 slug 총 {len(slugs)}건 확인, 저장 시작")

    saved = 0
    for slug in slugs:
        if saved >= limit:
            break
        if skip_existing and already_fetched(SITE_NAME, slug):
            continue
        try:
            html = fetch_detail(slug)
        except requests.RequestException as exc:
            print(f"[pinault] {slug} 요청 실패: {exc}")
            continue

        save_raw(
            SITE_NAME,
            slug,
            html,
            url=f"{BASE_URL}/en/artwork/{slug}",
            license_note=LICENSE_NOTE,
        )
        saved += 1
        if saved % 200 == 0:
            print(f"[pinault] {saved}건 진행 중...")
        time.sleep(delay)

    print(f"[pinault] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pinault Collection 소장 작품 크롤러")
    parser.add_argument("--limit", type=int, default=5000, help="이번 실행에서 수집할 최대 작품 수")
    parser.add_argument("--delay", type=float, default=0.4, help="요청 간 대기(초)")
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    args = parser.parse_args()
    crawl(args.limit, args.delay, args.skip_existing)
