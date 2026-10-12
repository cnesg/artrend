"""auction_lots(사실상 전부 Getty Provenance Index — 1650~1945년 유럽 경매)가
기존 museum_holdings 소장 artworks와 동일 작품일 가능성이 있는지 감사하는
리포트 전용 스크립트. DB에 아무것도 쓰지 않는다.

배경: 2026-09-03 저녁 진단에서 auction_lots 437,672건이 museum_holdings와
0% 연결(전부 신규 고립 artwork 행)이라는 게 드러남. 다만 매칭 방식 자체가
스키마 변경(중복/동일작품 표시용 컬럼·테이블)을 요구할 수 있어, 먼저 이
스크립트로 "같은 작가 + 제목 유사도"만으로 실제 몇 건이나 매칭 후보가
나오는지부터 측정한다 — 스키마를 건드리기 전에 이 작업이 실제로 가치가
있는 규모인지 확인하는 게 먼저(자율운영기준.md의 "스키마 변경은 사용자
승인 필요" 원칙과도 맞물림).

예상: Getty 데이터는 옥션 카탈로그 서술형 제목("Wynants. Een Landschap,
zeer warm...")이라 미술관 소장 제목("Landscape")과 문자열이 크게 달라
매칭률이 낮을 가능성이 높음 — 실측으로 확인한다.
"""
from __future__ import annotations

import difflib
import os
import random

import psycopg2


def normalize(title: str) -> str:
    return " ".join(title.lower().split())


def main(sample_size: int = 3000) -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    # museum_holdings가 있는 작가별 제목 목록을 미리 메모리에 올림 (반복 조회 방지)
    cur.execute(
        """
        select aw.artist_id, aw.title
        from artworks aw
        join museum_holdings mh on mh.artwork_id = aw.id
        where aw.artist_id is not null
        """
    )
    museum_titles_by_artist: dict[str, list[str]] = {}
    for artist_id, title in cur.fetchall():
        museum_titles_by_artist.setdefault(str(artist_id), []).append(title or "")
    print(f"[audit] museum_holdings 작가 수: {len(museum_titles_by_artist)}")

    # auction_lots 중 artist_id가 museum 쪽과 겹치는 것만 표본 추출
    cur.execute(
        """
        select al.id, aw.artist_id, aw.title
        from auction_lots al
        join artworks aw on aw.id = al.artwork_id
        where aw.artist_id is not null
          and aw.artist_id = any(%s::uuid[])
        """,
        (list(museum_titles_by_artist.keys()),),
    )
    all_candidates = cur.fetchall()
    print(f"[audit] 작가 겹치는 auction_lot 후보 총: {len(all_candidates)}")

    random.seed(42)
    sample = random.sample(all_candidates, min(sample_size, len(all_candidates)))

    buckets = {"high(>=0.85)": 0, "mid(0.6~0.85)": 0, "low(<0.6)": 0}
    high_examples = []
    for lot_id, artist_id, auction_title in sample:
        candidates = museum_titles_by_artist.get(str(artist_id), [])
        if not candidates or not auction_title:
            buckets["low(<0.6)"] += 1
            continue
        norm_auction = normalize(auction_title)
        best_ratio = 0.0
        best_title = None
        for cand in candidates:
            ratio = difflib.SequenceMatcher(None, norm_auction, normalize(cand)).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_title = cand
        if best_ratio >= 0.85:
            buckets["high(>=0.85)"] += 1
            if len(high_examples) < 15:
                high_examples.append((auction_title, best_title, round(best_ratio, 3)))
        elif best_ratio >= 0.6:
            buckets["mid(0.6~0.85)"] += 1
        else:
            buckets["low(<0.6)"] += 1

    print(f"[audit] 표본 {len(sample)}건 매칭 결과: {buckets}")
    print(f"[audit] high(>=0.85) 매칭 비율: {buckets['high(>=0.85)'] / len(sample):.2%}")
    print("[audit] high 샘플:")
    for a, m, r in high_examples:
        print(f"  auction={a!r}\n  museum ={m!r}\n  ratio={r}\n")


if __name__ == "__main__":
    main()
