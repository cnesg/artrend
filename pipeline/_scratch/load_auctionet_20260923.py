"""1회성 실행 스크립트 — Auctionet(raw/auctionet/) 파일럿 적재. 2026-09-23.

`pipeline/run.py`를 거치지 않고 `pipeline/auctionet.py` 로더를 직접 import해서 돌린다
(여러 세션이 동시에 DB를 쓰는 중이라 run.py 공용 진입점을 건드리지 않기 위함).

    python pipeline/_scratch/load_auctionet_20260923.py            # 샘플 검수 + DryRun
    python pipeline/_scratch/load_auctionet_20260923.py --apply    # 실제 적재

DB 접속 실패 시 5분 넘게 재시도한다(pgportable이 오늘 여러 번 죽었다 살아난 이력).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

import auctionet  # noqa: E402
from raw_iter import iter_records  # noqa: E402
from store import DryRunStore, PgStore  # noqa: E402


def connect_with_retry(attempts: int = 25, base_delay: float = 3.0):
    """최대 ~6분간 재시도(3,6,9…20초 상한). pgportable이 잠깐 죽어도 포기하지 않는다."""
    import psycopg2

    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL이 없다 — 조용한 dry-run을 막기 위해 여기서 중단한다.")
    last = None
    for i in range(1, attempts + 1):
        try:
            conn = psycopg2.connect(url, connect_timeout=10)
            conn.set_client_encoding("UTF8")
            return conn
        except Exception as exc:  # noqa: BLE001
            last = exc
            wait = min(base_delay * i, 20)
            print(f"[load_auctionet] DB 접속 실패({exc}) — {wait:.0f}초 후 재시도 ({i}/{attempts})")
            time.sleep(wait)
    raise SystemExit(f"[load_auctionet] DB 접속 최종 실패: {last}")


def sample_parse(n: int) -> None:
    """적재 전 눈으로 검수 — 통화/상태/작가/경매사 매핑이 제대로 되는지."""
    shown = 0
    stats = {"total": 0, "sold": 0, "unsold": 0, "other_state": 0,
             "no_artist": 0, "fx_mismatch": 0, "no_house": 0}
    houses: dict[str, int] = {}
    currencies: dict[str, int] = {}
    for _rid, data, _meta in iter_records(auctionet.SITE_NAME):
        stats["total"] += 1
        vip = data.get("vip_item") or {}
        details = data.get("details") or {}
        thumb = data.get("thumb") or {}
        sections = data.get("sections") or {}
        state = vip.get("state")
        stats["sold" if state == "sold" else "unsold" if state == "unsold" else "other_state"] += 1
        if data.get("display_currency") != data.get("original_currency"):
            stats["fx_mismatch"] += 1
        if not (details.get("House") or "").strip():
            stats["no_house"] += 1
        artists = data.get("artists") or []
        name = auctionet._artist_name(artists[0]["label"]) if artists else None
        if not name:
            stats["no_artist"] += 1
        houses[details.get("House") or "?"] = houses.get(details.get("House") or "?", 0) + 1
        cur = data.get("original_currency") or "?"
        currencies[cur] = currencies.get(cur, 0) + 1
        # 실제로 적재될 레코드(작가 링크 있음)를 우선 보여 준다 — 검수 목적에 맞게.
        if shown < n and name:
            shown += 1
            print("-" * 74)
            print(f"  item_id      : {data.get('item_id')}")
            print(f"  house        : {details.get('House')!r} / {details.get('Address')!r}")
            print(f"  artist       : {name!r}  (label={artists[0]['label'] if artists else None!r})")
            print(f"  title(원어)  : {(sections.get('Title') or '')[:90]!r}")
            print(f"  title_en     : {(auctionet._title_en(thumb.get('longTitle'), data.get('item_id')) or '')[:90]!r}")
            cur = thumb.get("currency")
            print(f"  state/sold   : {state!r} (hammer_auction={vip.get('hammer_auction')!r}, "
                  f"label={thumb.get('amountLabel')!r})")
            print(f"  estimate     : {thumb.get('estimate')!r} ~ "
                  f"{auctionet._estimate_high(thumb.get('amountTitle'), cur)!r} {cur!r} "
                  f"(amountTitle={thumb.get('amountTitle')!r})")
            hammer = (auctionet._amount(thumb.get("amountValue"), cur)
                      if state == "sold" else None)
            print(f"  hammer       : {hammer!r} "
                  f"(amountValue={thumb.get('amountValue')!r}, "
                  f"vip.top_bid={vip.get('top_bid_amount')!r} <- 쓰지 않음. "
                  f"유찰이면 amountValue가 추정가라 낙찰가로 쓰지 않는다)")
            print(f"  lot_number   : {thumb.get('catalogNumber')!r}  event={thumb.get('eventTitle')!r}")
            print(f"  date         : {auctionet._auction_date(vip.get('ends_at'))!r} "
                  f"(sale_key=auctionet:{vip.get('auction_id')})")
            print(f"  bids 제거?   : {vip.get('_bids_redacted')!r}, bids 키 남음={'bids' in vip}")
    print("\n[샘플] 집계:", stats)
    print("[샘플] 통화:", currencies)
    print("[샘플] 경매사 상위:", sorted(houses.items(), key=lambda kv: -kv[1])[:12])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 DB 적재")
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--include-artistless", dest="require_artist", action="store_false",
                    help="작가 엔티티 링크가 없는 로트도 적재(기본은 스킵)")
    ap.add_argument("--min-age-days", type=int, default=3,
                    help="종료 후 이 일수가 안 지난 로트는 보류(낙찰 상태 미확정). 기본 3")
    args = ap.parse_args()

    if not args.apply:
        sample_parse(args.samples)
        store = DryRunStore()
        auctionet.load(store, require_artist=args.require_artist,
                       min_age_days=args.min_age_days)
        print("[dry-run] counts:", store.counts)
        return

    conn = connect_with_retry()
    store = PgStore(conn)
    try:
        n = auctionet.load(store, require_artist=args.require_artist,
                           min_age_days=args.min_age_days)
        print(f"[load_auctionet] 적재 완료: {n}건")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
