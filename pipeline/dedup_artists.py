"""동일 이름(완전 일치) 작가 중복 병합 + name 유니크 제약 추가.

여러 크롤러 프로세스가 각자 인메모리 캐시를 가진 채 동시에 돌면서
동일한 이름의 artists 행이 중복 생성된 경우를 정리한다. 다국어 표기
차이(Lee Ufan vs 이우환)는 여기서 다루지 않음 — 완전 문자열 일치만 병합.
"""
from __future__ import annotations

import os

import psycopg2


def main() -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    cur.execute("select name, id from artists order by name, created_at")
    from collections import defaultdict

    by_name: dict[str, list[str]] = defaultdict(list)
    for name, aid in cur.fetchall():
        by_name[name].append(str(aid))
    groups = [(name, ids) for name, ids in by_name.items() if len(ids) > 1]
    print(f"[dedup] {len(groups)}개 중복 이름 그룹 발견")

    merged = 0
    for name, ids in groups:
        keep_id = ids[0]
        dupe_ids = ids[1:]
        cur.execute("update artworks set artist_id = %s where artist_id = any(%s::uuid[])", (keep_id, dupe_ids))
        cur.execute("update gallery_representations set artist_id = %s where artist_id = any(%s::uuid[])", (keep_id, dupe_ids))
        cur.execute("delete from artists where id = any(%s::uuid[])", (dupe_ids,))
        merged += len(dupe_ids)

    conn.commit()
    print(f"[dedup] {merged}건 병합 완료")

    cur.execute("create unique index if not exists idx_artists_name_unique on artists(name)")
    conn.commit()
    print("[dedup] artists(name) 유니크 인덱스 생성 완료")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
