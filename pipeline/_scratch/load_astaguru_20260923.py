"""AstaGuru 1회성 적재 스크립트 (2026-09-23).

`pipeline/run.py`는 다른 세션이 동시에 고치고 있어 건드리지 않기로 해서, 로더 모듈
(`pipeline/astaguru.py`)을 직접 import해 돌리는 1회성 실행기다. run.py의
DryRunStore/PgStore 분기와 동일한 동작을 하고, 추가로 pgportable이 오늘 두 번 죽었던
이력이 있어 **DB 연결에 넉넉한 재시도**를 건다.

    python pipeline/_scratch/load_astaguru_20260923.py --dry-run   # 파싱만 검증
    python pipeline/_scratch/load_astaguru_20260923.py             # 실제 적재
    python pipeline/_scratch/load_astaguru_20260923.py --max-sales 3   # 파일럿(오래된 세일부터 N개)

적재 자체는 `sources.raw_path` 기준으로 idempotent라 재실행해도 중복되지 않는다
(로더가 `store.source_already_loaded`로 이미 적재된 raw 파일을 건너뛴다).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE_DIR))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

import astaguru  # noqa: E402
import raw_iter  # noqa: E402
from db import get_connection  # noqa: E402
from store import DryRunStore, PgStore  # noqa: E402


def connect_with_retry(attempts: int = 8, base_delay: float = 3.0):
    """pgportable이 불안정해 한두 번 끊기는 일이 잦아 넉넉히 재시도한다."""
    last = None
    for attempt in range(1, attempts + 1):
        try:
            return get_connection()
        except Exception as exc:  # psycopg2.OperationalError 등
            last = exc
            wait = min(base_delay * attempt, 30)
            print(f"[load_astaguru] DB 연결 실패({exc}) — {wait:.0f}초 후 재시도 ({attempt}/{attempts})")
            time.sleep(wait)
    raise SystemExit(f"[load_astaguru] DB 연결 최종 실패: {last}")


def limit_sales(max_sales: int) -> None:
    """iter_records가 도는 raw 파일을 오래된 세일 N개로 제한한다(파일럿용).

    raw_iter.iter_records를 감싸서 lots_<id>_pNNN 중 id가 작은 순으로 N개 세일만 통과시킨다.
    """
    original = raw_iter.iter_records
    astaguru_iter = astaguru.iter_records

    def wrapped(site_name: str, ext: str = "json"):
        records = list(original(site_name, ext))
        sale_ids = sorted(
            {r[0].split("_")[1] for r in records if r[0].startswith("lots_")},
            key=lambda s: int(s) if s.isdigit() else 0,
        )[:max_sales]
        allowed = set(sale_ids)
        print(f"[load_astaguru] 파일럿 — 세일 {sorted(allowed, key=int)}만 적재")
        for record_id, data, meta in records:
            if record_id.startswith("lots_") and record_id.split("_")[1] not in allowed:
                continue
            yield record_id, data, meta

    astaguru.iter_records = wrapped
    assert astaguru_iter is original


def main() -> None:
    parser = argparse.ArgumentParser(description="AstaGuru 1회성 적재")
    parser.add_argument("--dry-run", action="store_true", help="DB에 쓰지 않고 파싱 결과만 집계")
    parser.add_argument("--max-sales", type=int, default=None, help="세일 N개만 적재(파일럿)")
    args = parser.parse_args()

    if args.max_sales:
        limit_sales(args.max_sales)

    dry_run = args.dry_run or not os.environ.get("DATABASE_URL")
    if dry_run:
        print("[load_astaguru] DRY-RUN — DB에 쓰지 않고 집계만 합니다"
              + ("" if args.dry_run else " (DATABASE_URL 미설정)"))
        store = DryRunStore()
        astaguru.load(store)
        print("\n[load_astaguru] dry-run 집계:", store.counts)
        for sample in store.samples:
            print("  샘플:", sample)
        return

    conn = connect_with_retry()
    store = PgStore(conn)
    try:
        astaguru.load(store)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
