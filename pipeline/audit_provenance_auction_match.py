"""제목 유사도 매칭(audit_auction_artwork_matches.py, 0.73%로 사실상 무의미하다고
판명)의 대안: provenance_records 중 owner_type='auction_house'인 행의
note 텍스트("(Sotheby, London, sale July 8, 1942, no. 112)" 같은 형식)에서
(경매사명, 날짜, 로트번호)를 정규식으로 뽑아 auction_lots(lot_number)/
auctions(auction_house_id, auction_date)와 구조화된 키로 매칭한다.

이게 왜 더 나은가: 제목은 "Portrait of a Woman"처럼 우연히 겹치는 경우가
흔하지만, (경매사+날짜+로트번호) 3중 일치는 우연일 확률이 극히 낮다 —
같은 경매의 같은 로트라는 뜻이라 사실상 동일 거래를 가리킨다.

리포트 전용, DB에 쓰지 않는다.
"""
from __future__ import annotations

import os
import re

import psycopg2

# "(Sotheby, London, sale July 8, 1942, no. 112)"
# "(sale, Christie's, Paris, 12 November 2015, lot 45)"
# "(Christie's, New York, September 25, 2002, sale 1111, lot 228)"
LOT_RE = re.compile(r"\b(?:no\.?|lot)\s*(\d+)", re.IGNORECASE)
DATE_RE = re.compile(
    r"\b(\d{1,2}\s+)?(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2},?\s+)?(\d{4})\b",
    re.IGNORECASE,
)
HOUSE_NAMES = ["sotheby", "christie", "phillips", "bonhams", "dorotheum", "swann"]


def extract_house(note: str) -> str | None:
    low = note.lower()
    for h in HOUSE_NAMES:
        if h in low:
            return h
    return None


def extract_lot(note: str) -> str | None:
    m = LOT_RE.search(note)
    return m.group(1) if m else None


def extract_year(note: str) -> int | None:
    m = DATE_RE.search(note)
    if m:
        return int(m.group(4))
    # 연도만 있는 케이스 fallback
    m2 = re.search(r"\b(1[5-9]\d{2}|20[0-2]\d)\b", note)
    return int(m2.group(1)) if m2 else None


def main() -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    cur.execute("select id, note, artwork_id from provenance_records where owner_type='auction_house' and note is not null")
    rows = cur.fetchall()
    print(f"[audit] provenance_records(auction_house) 전체: {len(rows)}건")

    parsed = []
    for pid, note, artwork_id in rows:
        house = extract_house(note)
        lot = extract_lot(note)
        year = extract_year(note)
        if house and lot:
            parsed.append((pid, artwork_id, house, lot, year))
    print(f"[audit] 경매사+로트번호 둘 다 파싱된 건: {len(parsed)}건 (연도까지 있는 건 {sum(1 for p in parsed if p[4])}건)")

    # auction_lots 쪽 (house_name_lower, lot_number, year) -> auction_lot_id 인덱스 구성
    cur.execute(
        """
        select al.id, ah.name, al.lot_number, extract(year from a.auction_date)
        from auction_lots al
        join auctions a on a.id = al.auction_id
        join auction_houses ah on ah.id = a.auction_house_id
        """
    )
    index: dict[tuple, list] = {}
    for lot_id, house_name, lot_number, year in cur.fetchall():
        if not house_name or not lot_number:
            continue
        key_house = house_name.lower()
        matched_alias = next((h for h in HOUSE_NAMES if h in key_house), None)
        if not matched_alias:
            continue
        index.setdefault((matched_alias, lot_number.strip()), []).append((lot_id, year))
    print(f"[audit] auction_lots 쪽 인덱스 키 수: {len(index)}")

    exact_house_lot = 0
    exact_house_lot_year = 0
    examples = []
    for pid, artwork_id, house, lot, year in parsed:
        candidates = index.get((house, lot))
        if not candidates:
            continue
        exact_house_lot += 1
        year_match = [c for c in candidates if year and c[1] and int(c[1]) == year]
        if year_match:
            exact_house_lot_year += 1
            if len(examples) < 10:
                examples.append((pid, artwork_id, house, lot, year, year_match[0]))

    print(f"[audit] (경매사+로트번호) 일치: {exact_house_lot}건")
    print(f"[audit] (경매사+로트번호+연도) 일치: {exact_house_lot_year}건")
    print("[audit] 샘플:")
    for ex in examples:
        print(" ", ex)


if __name__ == "__main__":
    main()
