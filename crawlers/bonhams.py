"""Bonhams 경매 결과 수집 (Next.js SSR 임베디드 JSON 방식).

Christie's/Sotheby's/Phillips/서울옥션/K-Auction/Artsy/Dorotheum/Hauser & Wirth/
Gagosian은 robots.txt 또는 ToU에 명시적 크롤링 금지 시그널이 있어 전부 제외했으나
(docs/크롤러현황.md 참고), Bonhams는 재검토 결과 둘 다 막힘 시그널이 없다:
  - robots.txt(2026-09-03 확인): `/ldc/`, `/vms-assets/`, `*/aggregate`, `*/head_image*`만
    차단. Bytespider만 User-agent로 명시 차단, 그 외 일반 크롤러는 허용.
  - Conditions of website use(bonhams.com/legals/9944/): "affect the functioning of
    the web site"를 금지하는 일반 조항은 있으나 스크래핑/데이터마이닝을 명시 금지하지 않음.

개별 세일 페이지(`/auctions/<id>/`)는 Next.js SSR이라 `<script id="__NEXT_DATA__">`
안에 `props.pageProps.auction`(세일 메타데이터)과 `props.pageProps.lotData.auctionLots`
(로트별 구조화 데이터: 제목/로트번호/추정가/낙찰가/상태/부서)가 그대로 박혀 있어
별도 API 호출이나 헤드리스 브라우저 없이 단순 HTTP GET + JSON 파싱으로 수집 가능.

세일 목록은 `sitemap.xml` → `sitemap-sale.xml`에서 전수 확보(2026-09-03 기준 11,369건).
Bonhams는 미술품뿐 아니라 자동차/시계/와인/보석 등 전 카테고리를 취급하므로, 크롤러
단계에서는 부서 필터 없이 전부 원본 저장하고(다른 크롤러들과 동일하게 정규화는
pipeline/ 몫으로 미룸) — 부서 코드가 `PIC-`(Pictures/회화) 또는 `PHO`(Photographs)로
시작하는 세일만 나중에 pipeline에서 auction_lots로 적재한다.

확인된 샘플(세일 11764, Medals 부서): 48개 로트 중 41개 SOLD(낙찰가 실값 포함),
7개 BI(bought-in, 유찰) — status 필드로 구분 가능. 즉 이 방식으로 얻는 낙찰가는
Wikidata P793 방식(783건)보다 훨씬 큰 규모가 될 것으로 기대.

사용법:
    python bonhams.py --limit 500
    python bonhams.py --start-index 3000 --limit 1000
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time

import requests

from common import already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

HEADERS = {"User-Agent": "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"}
SITE_NAME = "bonhams"
SALE_SITEMAP_URL = "https://www.bonhams.com/sitemap-sale.xml"
LICENSE_NOTE = (
    "Bonhams 세일 페이지 SSR에 임베디드된 __NEXT_DATA__ JSON(pageProps.auction + "
    "pageProps.lotData) — robots.txt/ToU 모두 스크래핑 명시 금지 조항 없음 확인, 2026-09-03"
)

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL
)
SALE_ID_RE = re.compile(r"/auctions/(\d+)/")


def fetch_sale_ids() -> list[str]:
    def _do():
        resp = requests.get(SALE_SITEMAP_URL, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return resp.text

    xml = with_retry(_do, attempts=3, base_delay=5.0)
    ids = SALE_ID_RE.findall(xml)
    # 순서 유지하며 중복 제거
    seen: set[str] = set()
    ordered: list[str] = []
    for sale_id in ids:
        if sale_id not in seen:
            seen.add(sale_id)
            ordered.append(sale_id)
    return ordered


def fetch_sale(sale_id: str) -> dict | None:
    url = f"https://www.bonhams.com/auctions/{sale_id}/"

    def _do():
        resp = requests.get(url, headers=HEADERS, timeout=30)
        return resp

    resp = with_retry(_do, attempts=3, base_delay=4.0)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()

    match = NEXT_DATA_RE.search(resp.text)
    if not match:
        return None

    data = json.loads(match.group(1))
    page_props = data.get("props", {}).get("pageProps", {})
    auction = page_props.get("auction")
    lot_data = page_props.get("lotData")
    if not auction or not lot_data:
        return None

    return {
        "sale_id": sale_id,
        "url": url,
        "auction": auction,
        "lotData": {
            "departments": lot_data.get("departments"),
            "auctionLots": lot_data.get("auctionLots"),
        },
    }


def crawl(start_index: int, limit: int | None, skip_existing: bool) -> None:
    print(f"[bonhams] 세일 목록 조회 중...")
    sale_ids = fetch_sale_ids()
    print(f"[bonhams] 세일 {len(sale_ids)}건 확보 (sitemap-sale.xml)")

    sale_ids = sale_ids[start_index:]
    if limit is not None:
        sale_ids = sale_ids[:limit]

    saved = 0
    skipped = 0
    empty = 0
    for i, sale_id in enumerate(sale_ids, start=1):
        if skip_existing and already_fetched(SITE_NAME, sale_id):
            skipped += 1
            continue

        try:
            record = fetch_sale(sale_id)
        except requests.RequestException as exc:
            print(f"[bonhams] 세일 {sale_id} 요청 실패, 건너뜀: {exc}")
            continue

        if record is None:
            empty += 1
            # 빈 결과도 마커로 저장해 재수집 방지
            save_raw(
                SITE_NAME, sale_id, json.dumps({"sale_id": sale_id, "empty": True}),
                url=f"https://www.bonhams.com/auctions/{sale_id}/", license_note=LICENSE_NOTE,
            )
            continue

        save_raw(
            SITE_NAME, sale_id, json.dumps(record, ensure_ascii=False),
            url=record["url"], license_note=LICENSE_NOTE,
        )
        saved += 1

        if (saved + skipped + empty) % 100 == 0:
            print(f"[bonhams] 진행: {i}/{len(sale_ids)} (저장 {saved}, 스킵 {skipped}, 빈결과 {empty})")

        time.sleep(0.5)

    print(f"[bonhams] 완료 — 저장 {saved}건, 스킵 {skipped}건, 빈결과 {empty}건")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bonhams 세일 결과 크롤러")
    parser.add_argument("--start-index", type=int, default=0, help="sitemap 순서 기준 시작 인덱스")
    parser.add_argument("--limit", type=int, default=None, help="이번 실행에서 처리할 최대 세일 수")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 레코드도 다시 수집",
    )
    args = parser.parse_args()
    crawl(args.start_index, args.limit, args.skip_existing)
