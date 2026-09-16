"""상시 건강지표 스크립트 — 2026-09-15 작업분담 §W7 (계획 P3-17)

C:\\Users\\CNCITY\\.claude\\plans\\jiggly-mixing-summit.md §6 표의 지표를 한 번에 출력한다.
읽기 전용(SELECT만) — DB를 변경하지 않는다. 각 쿼리에 statement_timeout을 걸고
쿼리별 소요시간을 출력해, 이후 이 스크립트를 정기 실행할 때 회귀(느려짐/수치
급변)를 바로 눈치챌 수 있게 한다.

사용법:
    python pipeline/audit_health.py                # 전체 지표 출력
    python pipeline/audit_health.py --json report.json   # JSON으로도 저장
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path(__file__).parent / ".env")

from db import get_connection  # noqa: E402

STATEMENT_TIMEOUT_MS = 90_000

# 2026-09-15 메인 지시: "정확중복"이 source_id+title+year+dimensions만으로는
# 너무 느슨해서(Getty NULL스텁 제네릭타이틀, 터너 스케치북 낱장 등 실제로는
# 서로 다른 실물이 걸림) artist_id까지 포함한 전부-non-null 일치로 좁히고,
# 아래 제네릭 제목은 애초에 제외한다. 표본 조사(2026-09-15)에서 확인된 것들.
GENERIC_TITLES = {
    "untitled", "no title", "title not known", "date not known",
    "landscape", "a landscape", "landscape and figures", "a landscape and figures",
    "blank", "piece", "ribbon", "watch cock", "souvenir spoon", "fragment",
    "study", "sketch", "portrait", "still life", "figure", "flowers",
    "sans titre", "ohne titel", "senza titolo", "무제",
}


def run(cur, label: str, sql: str, params=None):
    start = time.time()
    cur.execute(sql, params)
    rows = cur.fetchall()
    elapsed = time.time() - start
    print(f"[{elapsed:6.2f}s] {label}")
    return rows, elapsed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="결과를 이 경로에 JSON으로도 저장")
    args = ap.parse_args()

    conn = get_connection()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"set statement_timeout = {STATEMENT_TIMEOUT_MS}")

    metrics: dict = {"generated_at": datetime.now(timezone.utc).isoformat()}

    print("=" * 70)
    print("  아트그래프 건강지표 (읽기 전용)")
    print("=" * 70)

    # 1. 강한 정확중복(참고용) — source_id+artist_id+title+year+dimensions 전부
    # non-null 일치 + 제네릭 제목 제외. 2026-09-15 이전 버전(느슨한 정의,
    # source_id+title+year+dimensions만)은 Getty NULL스텁·터너 스케치북 낱장 등
    # 실제로 다른 실물을 대량으로 오탐해서 폐기 — 그 판단 근거는
    # docs/logs/에 남긴 중복 분해 리포트 참고.
    generic_list = sorted(GENERIC_TITLES)
    rows, _ = run(
        cur,
        "강한 정확중복(참고용) artworks (source_id+artist_id+title+year+dimensions 전부 non-null 일치, 제네릭 제목 제외)",
        """
        select count(*) - count(distinct (source_id, artist_id, title, year_created, dimensions))
        from artworks
        where artist_id is not null
          and title is not null and length(trim(title)) > 0
          and year_created is not null and length(trim(year_created)) > 0
          and dimensions is not null and length(trim(dimensions)) > 0
          and lower(trim(regexp_replace(title, '[][()."]', '', 'g'))) != all(%s)
        """,
        (generic_list,),
    )
    metrics["strong_exact_duplicate_artworks_reference_only"] = rows[0][0]
    print(f"  -> {rows[0][0]:,}건 (source_id+artist_id+title+year+dimensions 전부 일치, 제네릭 제목 제외 — 참고용, 자동삭제 대상 아님)")

    # 2. 소스별 artist NULL 비율 (상위 15개 소스)
    rows, _ = run(
        cur,
        "소스별 artist_id NULL 비율 (상위 15)",
        """
        select s.site_name,
               count(*) as total,
               count(*) filter (where w.artist_id is null) as no_artist,
               round(100.0 * count(*) filter (where w.artist_id is null) / count(*), 1) as pct_null
        from artworks w
        join sources s on s.id = w.source_id
        group by s.site_name
        having count(*) >= 500
        order by pct_null desc
        limit 15
        """,
    )
    metrics["artist_null_pct_by_source_top15"] = [
        {"site_name": r[0], "total": r[1], "no_artist": r[2], "pct_null": float(r[3])} for r in rows
    ]
    for r in rows:
        print(f"  -> {r[0]:30s} 전체 {r[1]:>8,} / artist없음 {r[2]:>8,} ({r[3]}%)")

    # 3. entity_kind별 작가 수 + 작품 수 (익명/국가/기업/귀속 등 "작가 아닌 작가")
    rows, _ = run(
        cur,
        "entity_kind별 작가 수 + 연결 작품 수",
        """
        select a.entity_kind, count(distinct a.id) as artists, count(w.id) as artworks
        from artists a
        left join artworks w on w.artist_id = a.id
        group by a.entity_kind
        order by artworks desc
        """,
    )
    metrics["entity_kind_breakdown"] = [
        {"entity_kind": r[0], "artists": r[1], "artworks": r[2]} for r in rows
    ]
    for r in rows:
        print(f"  -> {r[0]:15s} 작가 {r[1]:>8,}명 / 작품 {r[2]:>10,}건")

    # 4. 소장(museum_holdings)∧경매(auction_lots) 둘 다 가진 작가 교집합
    rows, _ = run(
        cur,
        "소장∧경매 작가 교집합",
        """
        with holding_artists as (
            select distinct w.artist_id from artworks w
            join museum_holdings mh on mh.artwork_id = w.id
            where w.artist_id is not null
        ),
        auction_artists as (
            select distinct w.artist_id from artworks w
            join auction_lots al on al.artwork_id = w.id
            where w.artist_id is not null
        )
        select
            (select count(*) from holding_artists) as holding_count,
            (select count(*) from auction_artists) as auction_count,
            (select count(*) from holding_artists h join auction_artists au on au.artist_id = h.artist_id) as both_count
        """,
    )
    h, au, both = rows[0]
    metrics["holding_auction_artist_overlap"] = {"holding": h, "auction": au, "both": both}
    print(f"  -> 소장 작가 {h:,} / 경매 작가 {au:,} / 교집합 {both:,}")

    # 5. 유령 1급 엔티티 (museums/auction_houses/galleries 중 실데이터 0건)
    # 2026-09-16 메인 지시로 museums/galleries 정의 갱신: 전시만 있고 소장/로스터가
    # 없는 기관(예: Museum Ludwig — R5/R4 전시만 연결됨)을 유령으로 오판정하던
    # 문제 수정. exhibitions·provenance_records(museums만)도 실데이터로 인정.
    rows, _ = run(
        cur,
        "유령 museums (소장 0건 AND exhibitions 0건 AND provenance owner 0건)",
        """
        select count(*) from museums m
        where not exists (select 1 from museum_holdings mh where mh.museum_id = m.id)
          and not exists (select 1 from exhibitions e where e.museum_id = m.id)
          and not exists (select 1 from provenance_records pr where pr.owner_museum_id = m.id)
        """,
    )
    metrics["ghost_museums"] = rows[0][0]
    print(f"  -> 유령 museums(소장·전시·provenance 전부 0건): {rows[0][0]:,}건")

    rows, _ = run(
        cur,
        "유령 auction_houses (경매 0건)",
        "select count(*) from auction_houses ah where not exists (select 1 from auctions au where au.auction_house_id = ah.id)",
    )
    metrics["ghost_auction_houses"] = rows[0][0]
    print(f"  -> 유령 auction_houses(경매 0건): {rows[0][0]:,}건")

    rows, _ = run(
        cur,
        "유령 galleries (로스터 0건 AND exhibitions 0건)",
        """
        select count(*) from galleries g
        where not exists (select 1 from gallery_representations gr where gr.gallery_id = g.id)
          and not exists (select 1 from exhibitions e where e.gallery_id = g.id)
        """,
    )
    metrics["ghost_galleries"] = rows[0][0]
    print(f"  -> 유령 galleries(로스터·전시 전부 0건): {rows[0][0]:,}건")

    # 6. price_usd 통화 분포 (값 있는 로트 기준)
    rows, _ = run(
        cur,
        "price_usd 보유 로트의 currency 분포 (상위 10)",
        """
        select coalesce(currency, '(NULL)'), count(*)
        from auction_lots
        where price_usd is not null
        group by currency
        order by count(*) desc
        limit 10
        """,
    )
    metrics["price_usd_currency_top10"] = [{"currency": r[0], "count": r[1]} for r in rows]
    for r in rows:
        print(f"  -> {r[0]:10s} {r[1]:>8,}건")

    # 7. bio 원본/생성 비율
    rows, _ = run(
        cur,
        "artists.bio 원본 보유 수",
        "select count(*) from artists where bio is not null and length(trim(bio)) > 0",
    )
    original_bio = rows[0][0]
    try:
        rows, _ = run(cur, "artist_bio_generated 행 수", "select count(*) from artist_bio_generated")
        generated_bio = rows[0][0]
    except Exception:
        conn.rollback()
        generated_bio = None
    metrics["bio_original_count"] = original_bio
    metrics["bio_generated_count"] = generated_bio
    print(f"  -> 원본 bio {original_bio:,}건 / 생성(격리된) bio {generated_bio if generated_bio is not None else 'N/A(테이블 없음)'}")

    # 8. 마이그레이션 파일 vs 라이브 스키마 차이 (요약 — 컬럼/인덱스 개수만)
    rows, _ = run(
        cur,
        "라이브 스키마 컬럼/인덱스 개수",
        """
        select
            (select count(*) from information_schema.columns where table_schema='public') as col_count,
            (select count(*) from pg_indexes where schemaname='public') as idx_count,
            (select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE') as table_count
        """,
    )
    col_count, idx_count, table_count = rows[0]
    metrics["live_schema_summary"] = {"tables": table_count, "columns": col_count, "indexes": idx_count}
    print(f"  -> 라이브 테이블 {table_count} / 컬럼 {col_count} / 인덱스 {idx_count}")
    migration_files = sorted((Path(__file__).resolve().parent.parent / "db" / "migrations").glob("*.sql"))
    metrics["migration_files"] = [p.name for p in migration_files]
    print(f"  -> 마이그레이션 파일 {len(migration_files)}개: {', '.join(p.name for p in migration_files)}")

    # 9. 최신성(freshness) 지표 — docs/최신성보강안_20260915.md §1 재측정
    print("-" * 70)
    print("  최신성(freshness)")
    print("-" * 70)

    rows, _ = run(
        cur,
        "제작연도 2020년 이후 작품 수",
        r"""
        select count(*) from artworks
        where year_created ~ '\d{4}' and substring(year_created from '\d{4}')::int >= 2020
        """,
    )
    metrics["artworks_since_2020"] = rows[0][0]
    print(f"  -> 2020년 이후 작품(year_created 기준): {rows[0][0]:,}건")

    rows, _ = run(
        cur,
        "2020년 이후 auction_lots 수 + 경매사별 분해",
        """
        select ah.name, count(*)
        from auction_lots al
        join auctions au on au.id = al.auction_id
        join auction_houses ah on ah.id = au.auction_house_id
        where au.auction_date >= '2020-01-01'
        group by ah.name
        order by count(*) desc
        limit 10
        """,
    )
    metrics["auction_lots_since_2020_by_house"] = [{"auction_house": r[0], "count": r[1]} for r in rows]
    total_lots_2020 = sum(r[1] for r in rows)
    print(f"  -> 2020년 이후 auction_lots 합계(상위10 경매사 기준): {total_lots_2020:,}건")
    for r in rows:
        print(f"     {r[0]:20s} {r[1]:>8,}건")

    for table in ("exhibitions", "exhibition_artists", "artist_events"):
        try:
            rows, _ = run(cur, f"{table} 행 수", f"select count(*) from {table}")
            metrics[f"{table}_count"] = rows[0][0]
            print(f"  -> {table}: {rows[0][0]:,}건")
        except Exception:
            conn.rollback()
            metrics[f"{table}_count"] = None
            print(f"  -> {table}: 테이블 없음")

    try:
        rows, _ = run(
            cur,
            "생존추정 작가(1950년 이후 출생, 사망일 없음, person) 중 2020년 이후 로트/전시 보유 비율",
            """
            with survivors as (
                select id from artists
                where entity_kind = 'person' and birth_year >= 1950 and death_year is null
            ),
            with_recent_lot as (
                select distinct w.artist_id from artworks w
                join auction_lots al on al.artwork_id = w.id
                join auctions au on au.id = al.auction_id
                where au.auction_date >= '2020-01-01' and w.artist_id in (select id from survivors)
            ),
            with_exhibition as (
                select distinct ea.artist_id from exhibition_artists ea
                where ea.artist_id in (select id from survivors)
            )
            select
                (select count(*) from survivors) as survivor_count,
                (select count(*) from with_recent_lot) as with_lot,
                (select count(*) from with_exhibition) as with_exhibition
            """,
        )
        s, wl, we = rows[0]
        metrics["survivor_artists"] = {"total": s, "with_recent_lot": wl, "with_exhibition": we}
        pct_lot = round(100.0 * wl / s, 1) if s else 0.0
        pct_ex = round(100.0 * we / s, 1) if s else 0.0
        print(
            f"  -> 생존추정 작가 {s:,}명 중 2020년 이후 로트보유 {wl:,}명({pct_lot}%) / "
            f"전시보유 {we:,}명({pct_ex}%)"
        )
    except Exception as e:
        conn.rollback()
        metrics["survivor_artists"] = None
        print(f"  -> 생존추정 작가 지표 계산 실패(exhibition_artists 테이블 없음 등): {e}")

    print("=" * 70)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2, default=str)
        print(f"JSON 저장: {args.json}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
