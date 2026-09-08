"""작가 이름 대소문자 표기 차이 중복 병합(예: "Jeppe Hein" vs "JEPPE HEIN").

주로 갤러리 크롤러가 사이트마다 다른 대소문자 표기를 그대로 가져오면서 생긴
표기 중복 — 언어가 다른 게 아니라 같은 로마자 이름의 대소문자 변형이다.
canonical 선택 기준: 전체 대문자(ALL CAPS)가 아닌 쪽을 우선, 그런 쪽이
여럿/없으면 메타데이터(국적/생몰년)가 채워진 쪽, 그래도 동률이면 첫 번째.
"""
from __future__ import annotations

import os

import psycopg2


def is_all_caps(name: str) -> bool:
    letters = [c for c in name if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def main() -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    cur.execute(
        """
        select lower(name) as ln
        from artists
        group by lower(name)
        having count(*) > 1
        """
    )
    groups = [r[0] for r in cur.fetchall()]
    print(f"대상 그룹 {len(groups)}개")

    total_merged = 0
    total_repointed = 0
    for ln in groups:
        cur.execute(
            "select id, name, nationality, birth_year, death_year from artists where lower(name) = %s",
            (ln,),
        )
        rows = cur.fetchall()
        if len(rows) < 2:
            continue

        def score(r):
            _, name, nat, by, dy = r
            meta = sum(1 for v in (nat, by, dy) if v)
            return (0 if is_all_caps(name) else 1, meta)

        rows.sort(key=score, reverse=True)
        canonical_id = rows[0][0]
        loser_ids = [r[0] for r in rows[1:]]

        cur.execute("update artworks set artist_id = %s where artist_id = any(%s::uuid[])", (canonical_id, loser_ids))
        n1 = cur.rowcount
        cur.execute(
            "update gallery_representations set artist_id = %s where artist_id = any(%s::uuid[])",
            (canonical_id, loser_ids),
        )
        n2 = cur.rowcount
        cur.execute("delete from artists where id = any(%s::uuid[])", (loser_ids,))

        total_merged += len(loser_ids)
        total_repointed += n1 + n2

    conn.commit()
    print(f"병합된 행 {total_merged}개, 재연결 {total_repointed}건")


if __name__ == "__main__":
    main()
