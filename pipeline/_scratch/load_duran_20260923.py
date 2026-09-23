"""1회성 실행 스크립트 — Durán(raw/duran/) 파일럿 적재. 2026-09-23.

`pipeline/run.py`를 거치지 않고 `pipeline/duran.py` 로더를 직접 import해서 돌린다
(여러 세션이 동시에 DB를 쓰는 중이라 run.py 공용 진입점을 건드리지 않기 위함).

    python pipeline/_scratch/load_duran_20260923.py --dry-run     # 파싱만 검증(샘플 출력)
    python pipeline/_scratch/load_duran_20260923.py --apply       # 실제 적재
    python pipeline/_scratch/load_duran_20260923.py --apply --limit 100

DB 접속 실패 시 넉넉히 재시도한다(pgportable이 불안정한 이력이 있음).
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

import duran  # noqa: E402
from raw_iter import iter_records  # noqa: E402
from store import DryRunStore, PgStore  # noqa: E402


def connect_with_retry(attempts: int = 10, base_delay: float = 3.0):
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
            print(f"[load_duran] DB 접속 실패({exc}) — {wait:.0f}초 후 재시도 ({i}/{attempts})")
            time.sleep(wait)
    raise SystemExit(f"[load_duran] DB 접속 최종 실패: {last}")


def sample_parse(n: int) -> None:
    """파싱 결과 샘플을 눈으로 검수한다(적재 전 필수)."""
    shown = 0
    stats = {"total": 0, "no_hammer": 0, "no_artist": 0, "anon": 0}
    for record_id, text, _meta in iter_records(duran.SITE_NAME, ext="html"):
        if record_id == duran.INDEX_RECORD_ID:
            dates = duran.parse_index(text)
            print(f"[샘플] 경매일자 표 {len(dates)}건, 예: "
                  f"{dict(list(sorted(dates.items(), reverse=True))[:3])}")
            continue
        p = duran.parse_lot(text)
        stats["total"] += 1
        if p["hammer_price"] is None:
            stats["no_hammer"] += 1
        if not p["artist_name"]:
            stats["no_artist"] += 1
            if p["artist_raw"]:
                stats["anon"] += 1
        if shown < n:
            shown += 1
            print("-" * 70)
            print(f"  record_id   : {record_id}")
            for k in ("artist_raw", "artist_name", "birth_year", "death_year", "title",
                      "medium", "dimensions", "lot_number", "estimate_low", "hammer_price"):
                print(f"  {k:<12}: {p[k]!r}")
            print(f"  description : {(p['description'] or '')[:220]!r}")
    print("\n[샘플] 집계:", stats)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 DB 적재")
    ap.add_argument("--dry-run", action="store_true", help="파싱만 검증")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--samples", type=int, default=5)
    args = ap.parse_args()

    if not args.apply:
        sample_parse(args.samples)
        if not args.dry_run:
            print("\n(--apply 없이는 적재하지 않는다. DryRunStore로 전체 파싱도 돌려본다)")
        store = DryRunStore()
        duran.load(store, limit=args.limit)
        print("[dry-run] counts:", store.counts)
        return

    conn = connect_with_retry()
    store = PgStore(conn)
    try:
        n = duran.load(store, limit=args.limit)
        print(f"[load_duran] 적재 완료: {n}건")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
