"""가짜 시장지표(price_usd) 무효화 — 2026-09-15 작업분담 §W2

원인: enrich_auction_db.py가 (1) 1675~1944년 유럽 경매의 역사 통화(livres/francs/
Reichsmark/Dutch guilders/pounds 등)를 임의 근사 환율로 USD 환산했고, (2) 통화가
NULL/미매핑인 로트는 "rate=1.0(=USD로 간주)"으로 price_usd를 그대로 채워 넣었다.
둘 다 실제 시장가치와 무관한 숫자라 "시장 지표"로 쓸 수 없다.

정책: auction_lots.price_usd / estimate_low_usd / estimate_high_usd는 다음 두 조건을
**모두** 만족하는 행만 유지하고, 나머지는 NULL로 되돌린다.
  (a) currency가 ISO 4217 코드 집합(현대 통화)에 속함:
      USD, GBP, EUR, HKD, AUD, CHF, JPY, KRW, CNY, CAD, SGD, SEK, NOK, DKK,
      PLN, CZK, HUF, ILS, NZD, TWD
  (b) 소속 auctions.auction_date >= 1970-01-01

'pounds','livres','francs','frs','Reichsmark','Mark','M','fl','fl.',
'Dutch guilders','florins','guineas','assignats','thaler','rigsdaler',
'Schilling','Kronen','Groschen','Kruezer','Rt','Sch' 및 NULL 통화는 전부 NULL 처리.

hammer_price / estimate_low / estimate_high(원본 통화 표시 금액)는 건드리지 않는다
— 역사 사료로서의 가격 정보 자체는 유효하고, 무효화 대상은 "USD 환산값"뿐.

**기본은 dry-run(통화별 유지/NULL 건수 리포트)이며, --apply 없이는 절대 UPDATE하지 않는다.**
idempotent — 재실행 시 "NULL 처리 대상"이 0건이어야 정상(이미 NULL인 행은 재실행 영향 없음).

사용법:
    python pipeline/nullify_historical_price_usd.py              # dry-run, 리포트 JSON 저장
    python pipeline/nullify_historical_price_usd.py --apply       # 실제 UPDATE
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path(__file__).parent / ".env")

from db import get_connection  # noqa: E402

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "logs"

ISO_CURRENCIES = [
    "USD", "GBP", "EUR", "HKD", "AUD", "CHF", "JPY", "KRW", "CNY",
    "CAD", "SGD", "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "ILS", "NZD", "TWD",
]

KEEP_CONDITION_SQL = """
    currency = any(%(iso)s)
    and auction_date_resolved >= '1970-01-01'
"""

# price_usd/estimate_*_usd 중 하나라도 not null인 행 기준으로 통계
BASE_CTE = """
    with lots as (
        select al.id, al.currency, au.auction_date as auction_date_resolved,
               al.price_usd, al.estimate_low_usd, al.estimate_high_usd
        from auction_lots al
        join auctions au on au.id = al.auction_id
        where al.price_usd is not null or al.estimate_low_usd is not null or al.estimate_high_usd is not null
    )
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 UPDATE한다 (주의)")
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    # 통화별 유지/NULL대상 건수 리포트
    cur.execute(
        BASE_CTE
        + f"""
        select coalesce(currency, '(NULL)') as currency,
               count(*) as total,
               count(*) filter (where {KEEP_CONDITION_SQL}) as keep_count
        from lots
        group by currency
        order by total desc
        """,
        {"iso": ISO_CURRENCIES},
    )
    rows = cur.fetchall()

    total_usd_rows = 0
    total_keep = 0
    total_nullify = 0
    per_currency = []
    for currency, total, keep_count in rows:
        nullify_count = total - keep_count
        total_usd_rows += total
        total_keep += keep_count
        total_nullify += nullify_count
        per_currency.append(
            {"currency": currency, "total": total, "keep": keep_count, "nullify": nullify_count}
        )
        print(f"[nullify_price] {currency:30s} 전체 {total:>8d} / 유지 {keep_count:>8d} / NULL처리 {nullify_count:>8d}")

    print(
        f"\n[nullify_price] USD값 보유 로트 합계 {total_usd_rows}건 — "
        f"유지 {total_keep}건 / NULL 처리 대상 {total_nullify}건"
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "iso_currencies": ISO_CURRENCIES,
        "total_usd_rows": total_usd_rows,
        "total_keep": total_keep,
        "total_nullify": total_nullify,
        "per_currency": per_currency,
    }
    out_path = DOCS_DIR / f"price_usd_무효화_리포트_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[nullify_price] 상세 리포트 저장: {out_path}")

    if not args.apply:
        print("\n[nullify_price] dry-run — UPDATE 없음. --apply로 실행하면 실제 반영됩니다.")
        cur.close()
        conn.close()
        return

    cur.execute(
        f"""
        update auction_lots al
        set price_usd = null, estimate_low_usd = null, estimate_high_usd = null
        from auctions au
        where au.id = al.auction_id
          and (al.price_usd is not null or al.estimate_low_usd is not null or al.estimate_high_usd is not null)
          and not (
              al.currency = any(%(iso)s)
              and au.auction_date >= '1970-01-01'
          )
        """,
        {"iso": ISO_CURRENCIES},
    )
    updated = cur.rowcount
    conn.commit()
    print(f"[nullify_price] {updated}건 NULL 처리 완료")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
