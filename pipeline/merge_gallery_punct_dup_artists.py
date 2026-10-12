"""갤러리 로스터 작가 중 구두점/공백 표기 차이로 남은 중복 병합.

audit_gallery_artist_matches.py가 찾은 "정규화 후 이름 같은데 id 다른" 그룹 중
갤러리 연결이 있는 5건 — 이니셜 마침표(J.R. vs JR), 존칭 마침표(MR vs Mr.),
악센트+대소문자(Ján Mančuška vs JÁN MANCUŠKA), 이니셜 마침표(T.J. Wilcox vs
TJ Wilcox), 중간이름 마침표(Michael E. Smith vs Michael E Smith) — 전부 동일
인물의 표기 차이로 수동 확인됨. canonical은 갤러리 연결이 있는 쪽(둘 다 연결된
경우 메타데이터가 더 채워진 쪽)을 우선한다.
"""
from __future__ import annotations

import os
import sys

import psycopg2

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# (canonical_id, loser_id) — 수동 확인된 쌍만, 자동 그룹핑 아님
PAIRS = [
    ("261f6b2b-12f2-4a8f-852f-8fad4c2753f3", "8ab11f14-045f-42a0-9d62-810520b100f6"),  # JR <- J.R.
    ("847ddca0-33ba-41b0-89a1-0b948fcdb2fb", "360e586c-50c6-41b8-b516-08baad5d915a"),  # Mr. <- MR (전부 대문자 표기 지양 관례)
    ("f37e91f5-5b0f-4d9e-9e8f-cc35aaab6272", "54d419ed-24a5-4dd1-99fe-a392a67c5b78"),  # Ján Mančuška <- JÁN MANCUŠKA
    ("571b597a-68ea-4198-891c-c96d0065f35b", "1f2fdeee-9cb1-4319-b4e3-b10aa177d695"),  # T.J. Wilcox <- TJ Wilcox
    ("01625596-5d5a-47e5-bfa0-520976a0ec6b", "3f6667b5-1f5e-4b00-99c0-3d6d9aa631a0"),  # Michael E. Smith <- Michael E Smith
]


def main() -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    total_repointed = 0
    merged = 0
    for canonical_id, loser_id in PAIRS:
        cur.execute("select name from artists where id = %s", (loser_id,))
        row = cur.fetchone()
        if row is None:
            print(f"[skip] loser {loser_id} 이미 없음 (재실행 시 정상)")
            continue
        cur.execute("select name from artists where id = %s", (canonical_id,))
        canon_row = cur.fetchone()
        print(f"병합: '{row[0]}' ({loser_id}) -> '{canon_row[0]}' ({canonical_id})")

        cur.execute("update artworks set artist_id = %s where artist_id = %s", (canonical_id, loser_id))
        n1 = cur.rowcount
        cur.execute(
            "update gallery_representations set artist_id = %s where artist_id = %s",
            (canonical_id, loser_id),
        )
        n2 = cur.rowcount
        cur.execute("delete from artists where id = %s", (loser_id,))

        total_repointed += n1 + n2
        merged += 1

    conn.commit()
    print(f"병합 {merged}건, 재연결 {total_repointed}건")


if __name__ == "__main__":
    main()
