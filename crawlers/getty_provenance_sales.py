"""Getty Provenance Index — Sales Catalogs 데이터셋 (경매/개인계약 판매 기록) 벌크 다운로드.

Getty Research Institute가 CC0로 공개한 `thegetty/provenance-index-csv` GitHub 저장소의
sales_catalogs 데이터셋. Wikidata P793(783건, 현대 위주)·Bonhams(진행 중, SSR JSON,
현대 위주)와 달리 **1650~1945년 유럽(벨기에/프랑스/독일/영국/네덜란드/스칸디나비아/
오스트리아/스위스) 경매·개인계약 판매 기록**을 다뤄 시대적으로 크게 보완된다.

- 100만+ 로트 레코드(`sales_contents_1~13.csv`), 22,000+ 세일 설명(`sales_descriptions.csv`),
  50,000+ 실물 카탈로그 소재 정보(`sales_catalogs_info.csv`) — CC0 1.0 Universal.
- 로트별로 artist_name/art_authority(ULAN ID)/title/object_type/materials/dimensions,
  sell_name(판매자)/buy_name(구매자), price_amount+price_currency(낙찰가),
  est_price/start_price/asking_price, auction_house_1(경매사) 등이 채워져 있어
  auction_houses/auctions/auction_lots 스키마에 직접 매핑 가능.
- 파일은 GitHub 저장소가 아니라 연결된 S3 버킷(`jpgt-or-prd-provenance-index-csv.s3.
  us-west-2.amazonaws.com`)에서 직접 받는다 — Git LFS 아님, 일반 HTTPS GET.

사용법:
    python getty_provenance_sales.py
"""
from __future__ import annotations

import sys

import requests

from common import already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

SITE_NAME = "getty_provenance_sales"
BASE_URL = "https://jpgt-or-prd-provenance-index-csv.s3.us-west-2.amazonaws.com/sales_catalogs"
LICENSE_NOTE = (
    "Getty Research Institute, CSV exports of the Getty Provenance Index (Sales Catalogs) — "
    "CC0 1.0 Universal, https://github.com/thegetty/provenance-index-csv, 2026-09-03"
)

FILES = [f"sales_contents_{i}.csv" for i in range(1, 14)] + [
    "sales_descriptions.csv",
    "sales_catalogs_info.csv",
]


def crawl(skip_existing: bool = True) -> None:
    for filename in FILES:
        record_id = filename.replace(".csv", "")
        if skip_existing and already_fetched(SITE_NAME, record_id, ext="csv"):
            print(f"[getty_provenance_sales] {filename} 이미 수집됨, 스킵")
            continue

        url = f"{BASE_URL}/{filename}"

        def _do():
            resp = requests.get(url, timeout=300)
            resp.raise_for_status()
            return resp.content

        content = with_retry(_do, attempts=4, base_delay=8.0)
        save_raw(SITE_NAME, record_id, content, url=url, license_note=LICENSE_NOTE, ext="csv")
        print(f"[getty_provenance_sales] {filename} 저장 ({len(content) / 1_000_000:.1f}MB)")

    print("[getty_provenance_sales] 완료")


if __name__ == "__main__":
    crawl()
