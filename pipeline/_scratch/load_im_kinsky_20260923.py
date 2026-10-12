"""1회성 실행 스크립트 — Auktionshaus im Kinsky(raw/im_kinsky/) 적재. 2026-09-23.

`pipeline/run.py`를 거치지 않고 `pipeline/im_kinsky.py` 로더를 직접 import해서 돌린다
(여러 세션이 동시에 DB를 쓰는 중이라 run.py 공용 진입점을 건드리지 않기 위함 — duran/
lempertz 1회성 스크립트와 동일 패턴).

    python pipeline/_scratch/load_im_kinsky_20260923.py                # 파싱 샘플 검수 + dry-run
    python pipeline/_scratch/load_im_kinsky_20260923.py --apply        # 실제 적재
    python pipeline/_scratch/load_im_kinsky_20260923.py --apply --limit 200

DB 접속 실패 시 넉넉히(기본 최대 ~5분) 재시도한다 — pgportable이 오늘도 여러 번 죽었다
살아난 이력이 있어서다.
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

import im_kinsky  # noqa: E402
from raw_iter import iter_records  # noqa: E402
from store import DryRunStore, PgStore  # noqa: E402


def connect_with_retry(attempts: int = 40, delay: float = 10.0):
    """최대 attempts회, delay초 간격으로 재시도(기본 40 x 10초 ≈ 6분 40초)."""
    import psycopg2

    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL이 없다 — 조용한 dry-run을 막기 위해 여기서 중단한다.")
    last = None
    for i in range(1, attempts + 1):
        try:
            conn = psycopg2.connect(url, connect_timeout=10)
            conn.set_client_encoding("UTF8")
            if i > 1:
                print(f"[load_im_kinsky] DB 재접속 성공 ({i}번째 시도)")
            return conn
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"[load_im_kinsky] DB 접속 실패({exc}) — {delay:.0f}초 후 재시도 ({i}/{attempts})")
            time.sleep(delay)
    raise SystemExit(f"[load_im_kinsky] DB 접속 최종 실패: {last}")


def sample_parse(n: int) -> None:
    """적재 전 사람이 눈으로 검수할 샘플 + 전체 파싱 집계."""
    shown = 0
    stats = {
        "total": 0, "parse_fail": 0, "no_hammer": 0, "no_artist": 0,
        "anon_label": 0, "object_lot": 0, "with_provenance": 0, "multi_artist": 0,
    }
    for record_id, text, _meta in iter_records(im_kinsky.SITE_NAME, ext="html"):
        stats["total"] += 1
        p = im_kinsky.parse_lot(text)
        if p is None:
            stats["parse_fail"] += 1
            continue
        if p["hammer_price"] is None:
            stats["no_hammer"] += 1
        if not p["artist_name"]:
            stats["no_artist"] += 1
        if p["anon_artist_label"]:
            stats["anon_label"] += 1
        if p["object_name"]:
            stats["object_lot"] += 1
        if p["provenance"]:
            stats["with_provenance"] += 1
        if len(p["artist_names"]) > 1:
            stats["multi_artist"] += 1
        if shown < n and p["hammer_price"] is not None:
            shown += 1
            print("-" * 72)
            print(f"  record_id   : {record_id}")
            for k in ("sale_title", "auction_date", "lot_number", "artist_name",
                      "attribution_qualifier", "birth_year", "death_year", "title",
                      "year_created", "medium", "dimensions", "estimate_low",
                      "estimate_high", "hammer_price", "realized_price", "currency"):
                print(f"  {k:<22}: {p[k]!r}")
            print(f"  description           : {(p['description'] or '')[:260]!r}")
    print("\n[샘플] 집계:", stats)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 DB 적재")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--samples", type=int, default=5)
    args = ap.parse_args()

    if not args.apply:
        sample_parse(args.samples)
        store = DryRunStore()
        im_kinsky.load(store, limit=args.limit)
        print("[dry-run] counts:", store.counts)
        return

    conn = connect_with_retry()
    store = PgStore(conn)
    try:
        n = im_kinsky.load(store, limit=args.limit)
        print(f"[load_im_kinsky] 적재 완료: {n}건")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
