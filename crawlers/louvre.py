"""루브르 박물관(collections.louvre.fr) 소장품 메타데이터 크롤러.

robots.txt(2026-09-02 확인)는 GPTBot/ClaudeBot/CCBot 등 AI봇을 이미지 파일
확장자(.jpg/.jpeg/.png/.webp)에 대해서만 명시 차단한다 — JSON 메타데이터
경로는 막지 않는다. 다만 검색 페이지(/recherche)는 WAF 봇 검증("I am not
a robot")에 막혀 있어 프로그래밍적으로 우회하지 않고, 대신 robots.txt가
허용하는 sitemap.xml에서 오브젝트 ID(ark:/...)를 뽑아 개별 .json
엔드포인트만 호출한다. **이미지는 수집하지 않는다** (봇 차단 대상이자
사용자 확인 결과 메타데이터만 수집하기로 함, 2026-09-02).

사용법:
    python louvre.py --limit 5000 --delay 0.3
"""
from __future__ import annotations

import argparse
import re
import sys

import requests

from common import already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

SITE_NAME = "louvre"
SITEMAP_INDEX = "https://collections.louvre.fr/sitemap.xml"
LICENSE_NOTE = "collections.louvre.fr 공개 JSON API — 메타데이터만 수집(이미지 제외, robots.txt AI봇 차단 대상), 2026-09-02"
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}

ARK_RE = re.compile(r"<loc>https://collections\.louvre\.fr/ark:/([^<]+)</loc>")


def _fetch(url: str, timeout: int = 30) -> str:
    def _do():
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.text

    return with_retry(_do)


def collect_ark_ids() -> list[str]:
    index_xml = _fetch(SITEMAP_INDEX)
    sitemap_urls = re.findall(r"<loc>([^<]+)</loc>", index_xml)
    ark_ids: set[str] = set()
    for i, sm_url in enumerate(sitemap_urls, 1):
        xml = _fetch(sm_url, timeout=60)
        found = ARK_RE.findall(xml)
        ark_ids.update(found)
        print(f"[louvre] sitemap {i}/{len(sitemap_urls)} 처리 — 누적 오브젝트 {len(ark_ids)}개")
    return sorted(ark_ids)


def crawl(limit: int | None, delay: float, skip_existing: bool) -> None:
    ark_ids = collect_ark_ids()
    if limit:
        ark_ids = ark_ids[:limit]
    print(f"[louvre] 오브젝트 ID {len(ark_ids)}개 확인, 저장 시작")

    saved = 0
    for i, ark_id in enumerate(ark_ids, 1):
        record_id = f"ark_{ark_id.replace('/', '_')}"
        if skip_existing and already_fetched(SITE_NAME, record_id):
            continue

        url = f"https://collections.louvre.fr/ark:/{ark_id}.json"
        try:
            content = _fetch(url)
        except requests.RequestException as exc:
            print(f"[louvre] {url} 조회 실패: {exc}")
            continue

        save_raw(SITE_NAME, record_id, content, url=url, license_note=LICENSE_NOTE)
        saved += 1
        if saved % 1000 == 0:
            print(f"[louvre] {saved}건 저장 진행 중... ({i}/{len(ark_ids)})")
        import time
        time.sleep(delay)

    print(f"[louvre] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="루브르 박물관 메타데이터 크롤러")
    parser.add_argument("--limit", type=int, default=None, help="수집할 오브젝트 수 제한")
    parser.add_argument("--delay", type=float, default=0.3, help="요청 간 대기(초)")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 오브젝트도 다시 수집",
    )
    args = parser.parse_args()
    crawl(args.limit, args.delay, args.skip_existing)
