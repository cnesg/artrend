"""Enrich and Standardize Auction Data in PostgreSQL.

1. Add price_usd, estimate_low_usd, estimate_high_usd columns to auction_lots.
2. Standardize currencies and compute USD equivalent prices.
3. Create and populate artist_market_metrics table (all-time record, turnover, sell-through rate, avg price).
4. Create B-Tree indexes for ultra-fast query execution.

2026-09-15 작업분담 §W2 정정: 역사 통화(livres/francs/Reichsmark/Dutch guilders/
pounds 등 18~19세기 유럽 경매 통화) USD 환산 금지. CURRENCY_RATES_TO_USD는
ISO 4217 코드 20종(현대 통화)만 남겼고, 매핑에 없는 통화를 "rate=1.0(USD로 간주)"
처리하던 폴백도 제거했다 — 예전 폴백이 바로 오늘(2026-09-15) 발견된 가짜
시장지표(auction_lots.price_usd)의 원인이었다(파이프라인/nullify_historical_price_usd.py
참고). artist_market_metrics 테이블은 db/migrations/0004_drop_artist_market_metrics.sql로
DROP됐다 — 이 스크립트를 재실행하면 테이블이 다시 생성/적재되므로, 재실행 전
0004 마이그레이션을 다시 적용하거나 뷰로 대체할지 먼저 확인할 것.
"""
from __future__ import annotations

import sys
import time
import psycopg2

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

DB_URL = "postgresql://postgres@127.0.0.1:5433/artrend"

# Currency conversion rates to USD (approximate reference standard).
# ISO 4217 코드 현대 통화만 — 2026-09-15 작업분담 §W2: 역사 통화(18~19세기 유럽
# 경매 통화) 항목 전부 제거. 이 딕셔너리에 없는 통화는 더 이상 환산하지 않는다
# (아래 "default 1.0 rate" 폴백도 제거됨 — 매핑 없는 통화를 USD로 간주하지 않음).
CURRENCY_RATES_TO_USD = {
    "USD": 1.0,
    "GBP": 1.30,
    "EUR": 1.08,
    "CHF": 1.15,
    "HKD": 0.128,
    "KRW": 0.00075,
    "JPY": 0.0067,
    "CNY": 0.14,
    "AUD": 0.65,
    "CAD": 0.73,
    "SEK": 0.095,
    "NOK": 0.093,
    "DKK": 0.145,
    "SGD": 0.77,
    "TWD": 0.031,
    "CZK": 0.043,
    "PLN": 0.25,
    "HUF": 0.0028,
    "ILS": 0.27,
    "NZD": 0.60,
}


def main():
    start_time = time.time()
    print("==================================================")
    print("  Artrend 경매 DB 정규화 & 시장 지표 테이블 구축")
    print("==================================================")

    conn = psycopg2.connect(DB_URL)
    conn.set_client_encoding("UTF8")
    conn.autocommit = True
    cur = conn.cursor()

    # 1. Add columns to auction_lots if not exist
    print("\n[1/4] auction_lots 테이블에 USD 환산 컬럼 추가 중...")
    cur.execute("""
        ALTER TABLE auction_lots 
        ADD COLUMN IF NOT EXISTS price_usd NUMERIC,
        ADD COLUMN IF NOT EXISTS estimate_low_usd NUMERIC,
        ADD COLUMN IF NOT EXISTS estimate_high_usd NUMERIC;
    """)
    print("  -> 컬럼 확인/추가 완료.")

    # 2. Populate price_usd based on currency mapping
    print("\n[2/4] 통화 정규화 및 price_usd 계산 중...")
    
    # Create temporary conversion table for ultra-fast bulk update
    cur.execute("DROP TABLE IF EXISTS _temp_currency_rates;")
    cur.execute("""
        CREATE TEMP TABLE _temp_currency_rates (
            raw_curr TEXT PRIMARY KEY,
            rate NUMERIC
        );
    """)
    
    for curr_name, rate in CURRENCY_RATES_TO_USD.items():
        cur.execute(
            "INSERT INTO _temp_currency_rates (raw_curr, rate) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
            (curr_name, rate)
        )

    # Bulk update price_usd — ISO 통화 매핑 + auction_date >= 1970 (현대 시장)인
    # 로트만 대상 (2026-09-15 §W2 정책: db/migrations/0004 + nullify_historical_price_usd.py)
    cur.execute("""
        UPDATE auction_lots al
        SET price_usd = ROUND(al.hammer_price * r.rate, 2),
            estimate_low_usd = ROUND(al.estimate_low * r.rate, 2),
            estimate_high_usd = ROUND(al.estimate_high * r.rate, 2)
        FROM _temp_currency_rates r, auctions au
        WHERE au.id = al.auction_id
          AND (al.currency = r.raw_curr OR LOWER(al.currency) = LOWER(r.raw_curr))
          AND al.hammer_price IS NOT NULL
          AND au.auction_date >= '1970-01-01';
    """)
    print("  -> 통화 매핑 기반 price_usd 산출 완료.")

    # 2026-09-15 §W2: "매핑 없는 통화 = USD로 간주(rate 1.0)" 폴백 제거.
    # 이 폴백이 역사 통화(livres/francs/Reichsmark 등)와 NULL 통화 로트에
    # 실제 가치와 무관한 price_usd를 채워 넣은 원인이었다 — ISO 통화 매핑에
    # 없는 로트는 price_usd를 NULL로 남긴다.

    # Create Indexes for fast ranking
    print("  -> auction_lots price_usd 인덱스 생성 중...")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_auction_lots_price_usd 
        ON auction_lots (price_usd DESC NULLS LAST);
        
        CREATE INDEX IF NOT EXISTS idx_auction_lots_artwork_price 
        ON auction_lots (artwork_id, price_usd DESC NULLS LAST);
    """)
    print("  -> 인덱스 생성 완료.")

    # 3. Create artist_market_metrics table
    print("\n[3/4] artist_market_metrics 분석 지표 테이블 생성 중...")
    cur.execute("""
        DROP TABLE IF EXISTS artist_market_metrics CASCADE;
        CREATE TABLE artist_market_metrics (
            artist_id UUID PRIMARY KEY REFERENCES artists(id) ON DELETE CASCADE,
            total_lots_offered INT DEFAULT 0,
            total_lots_sold INT DEFAULT 0,
            sold_rate_pct NUMERIC(5, 2) DEFAULT 0,
            total_turnover_usd NUMERIC(15, 2) DEFAULT 0,
            avg_price_usd NUMERIC(15, 2) DEFAULT 0,
            record_price_usd NUMERIC(15, 2) DEFAULT 0,
            record_price_original NUMERIC(15, 2),
            record_currency TEXT,
            record_artwork_id UUID REFERENCES artworks(id) ON DELETE SET NULL,
            record_artwork_title TEXT,
            record_auction_house_id UUID REFERENCES auction_houses(id) ON DELETE SET NULL,
            record_auction_house_name TEXT,
            record_sale_date DATE,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );

        CREATE INDEX idx_artist_market_record_price ON artist_market_metrics (record_price_usd DESC NULLS LAST);
        CREATE INDEX idx_artist_market_turnover ON artist_market_metrics (total_turnover_usd DESC NULLS LAST);
        CREATE INDEX idx_artist_market_lots_sold ON artist_market_metrics (total_lots_sold DESC NULLS LAST);
    """)
    print("  -> artist_market_metrics 테이블 구조 생성 완료.")

    # 4. Populate artist_market_metrics
    print("\n[4/4] 작가별 경매 통계 및 역대 최고가 집계 데이터 적재 중...")
    cur.execute("""
        WITH artist_lots_agg AS (
            SELECT 
                a.artist_id,
                COUNT(al.id) AS total_offered,
                COUNT(CASE WHEN al.sold = TRUE OR (al.sold IS NULL AND al.hammer_price > 0) THEN 1 END) AS total_sold,
                COALESCE(SUM(CASE WHEN al.sold = TRUE OR (al.sold IS NULL AND al.hammer_price > 0) THEN al.price_usd ELSE 0 END), 0) AS turnover_usd,
                COALESCE(AVG(CASE WHEN al.sold = TRUE OR (al.sold IS NULL AND al.hammer_price > 0) THEN al.price_usd END), 0) AS avg_price_usd,
                MAX(CASE WHEN al.sold = TRUE OR (al.sold IS NULL AND al.hammer_price > 0) THEN al.price_usd END) AS max_price_usd
            FROM artworks a
            JOIN auction_lots al ON al.artwork_id = a.id
            WHERE a.artist_id IS NOT NULL
            GROUP BY a.artist_id
        ),
        ranked_records AS (
            SELECT 
                a.artist_id,
                a.id AS artwork_id,
                a.title AS artwork_title,
                al.hammer_price AS record_price_orig,
                al.currency AS record_curr,
                al.price_usd AS record_price_usd,
                ah.id AS house_id,
                ah.name AS house_name,
                au.auction_date AS sale_date,
                ROW_NUMBER() OVER (
                    PARTITION BY a.artist_id 
                    ORDER BY al.price_usd DESC NULLS LAST, au.auction_date DESC NULLS LAST
                ) AS rn
            FROM artworks a
            JOIN auction_lots al ON al.artwork_id = a.id
            JOIN auctions au ON au.id = al.auction_id
            JOIN auction_houses ah ON ah.id = au.auction_house_id
            WHERE a.artist_id IS NOT NULL 
              AND al.price_usd IS NOT NULL 
              AND al.price_usd > 0
              AND (al.sold = TRUE OR al.sold IS NULL)
        )
        INSERT INTO artist_market_metrics (
            artist_id,
            total_lots_offered,
            total_lots_sold,
            sold_rate_pct,
            total_turnover_usd,
            avg_price_usd,
            record_price_usd,
            record_price_original,
            record_currency,
            record_artwork_id,
            record_artwork_title,
            record_auction_house_id,
            record_auction_house_name,
            record_sale_date
        )
        SELECT 
            agg.artist_id,
            agg.total_offered,
            agg.total_sold,
            ROUND(CASE WHEN agg.total_offered > 0 THEN (agg.total_sold::numeric / agg.total_offered::numeric) * 100.0 ELSE 0 END, 2),
            ROUND(agg.turnover_usd, 2),
            ROUND(agg.avg_price_usd, 2),
            ROUND(COALESCE(rec.record_price_usd, 0), 2),
            rec.record_price_orig,
            rec.record_curr,
            rec.artwork_id,
            rec.artwork_title,
            rec.house_id,
            rec.house_name,
            rec.sale_date
        FROM artist_lots_agg agg
        LEFT JOIN ranked_records rec ON rec.artist_id = agg.artist_id AND rec.rn = 1;
    """)

    cur.execute("SELECT COUNT(*) FROM artist_market_metrics;")
    metric_cnt = cur.fetchone()[0]
    print(f"  -> 작가 경매 지표 {metric_cnt:,}명 적재 완료!")

    elapsed = time.time() - start_time
    print(f"\n==================================================")
    print(f"  경매 DB 정규화 완료 (소요 시간: {elapsed:.2f}초)")
    print(f"==================================================")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
