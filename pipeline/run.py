"""crawlers/raw/ -> DB 정규화 파이프라인 실행기.

사용법:
    python pipeline/run.py --site all                # DATABASE_URL 있으면 실제 적재, 없으면 dry-run
    python pipeline/run.py --site nga --limit 1000    # NGA는 28만 행이라 --limit으로 검증 가능
    python pipeline/run.py --site met --dry-run       # DB 연결 없이 파싱만 검증
"""
from __future__ import annotations

import argparse
import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

import aic
import auctions
import barnes
import bonhams
import busan_art_museum
import cleveland
import europeana
import galleries
import getty
import getty_provenance_sales
import gmoma
import japan_museums
import leeum
import louvre
import mia
import walters
import met
import mmca
import moma
import nga
import pinault
import rijksmuseum
import sema
import smithsonian
import smk
import tate
import wikidata_museums
import vam
from db import get_connection
from store import DryRunStore, PgStore

LOADERS = {
    "met": met.load,
    "aic": aic.load,
    "cleveland": cleveland.load,
    "smithsonian": smithsonian.load,
    "mmca": mmca.load,
    "smk": smk.load,
    "galleries": galleries.load,
    "moma": moma.load,
    "tate": tate.load,
    "louvre": louvre.load,
    "rijksmuseum": rijksmuseum.load,
    "wikidata_museums": wikidata_museums.load,
    "japan_museums": japan_museums.load,
    "getty": getty.load,
    "barnes": barnes.load,
    "walters": walters.load,
    "mia": mia.load,
    "auctions": auctions.load,
    "vam": vam.load,
    "getty_provenance_sales": getty_provenance_sales.load,
    "europeana": europeana.load,
    "bonhams": bonhams.load,
    "sema": sema.load,
    "busan_art_museum": busan_art_museum.load,
    "gmoma": gmoma.load,
    "leeum": leeum.load,
    "pinault": pinault.load,
}
ALL_SITES = [
    "met", "aic", "cleveland", "nga", "smithsonian", "mmca", "smk", "galleries",
    "moma", "tate", "louvre", "rijksmuseum", "wikidata_museums", "japan_museums",
    "getty", "barnes", "walters", "mia", "auctions", "vam", "getty_provenance_sales",
    "europeana", "bonhams", "sema", "busan_art_museum", "gmoma", "leeum", "pinault",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="아트그래프 raw -> DB 정규화 파이프라인")
    parser.add_argument("--site", choices=["all", *ALL_SITES], default="all")
    parser.add_argument("--limit", type=int, default=None, help="nga 전용 — 처리할 최대 행 수")
    parser.add_argument("--dry-run", action="store_true", help="DB에 쓰지 않고 파싱 결과만 집계")
    args = parser.parse_args()

    dry_run = args.dry_run or not os.environ.get("DATABASE_URL")
    if dry_run:
        print("[pipeline] DRY-RUN 모드 — DB에 쓰지 않고 집계만 합니다" + ("" if args.dry_run else " (DATABASE_URL 미설정)"))
        store = DryRunStore()
    else:
        store = PgStore(get_connection())

    sites = ALL_SITES if args.site == "all" else [args.site]
    for site in sites:
        if site == "nga":
            nga.load(store, limit=args.limit)
        else:
            LOADERS[site](store)

    if isinstance(store, DryRunStore):
        print("\n[pipeline] dry-run 집계:", store.counts)
        if store.samples:
            print("[pipeline] 샘플 artwork 레코드:")
            for sample in store.samples:
                print(" ", sample)


if __name__ == "__main__":
    main()
