"""museum_holdings 중복 (museum_id, accession_number) 병합 + 유니크 제약 추가.

원인: Wikidata 보완 소스에서 동일 실물 작품에 대해 병합되지 않은 중복 Q-item이
존재해(Wikidata 자체의 데이터 품질 문제) 같은 accession_number로 서로 다른
artwork 행이 생성됨. 제목이 비어 Q-id 그대로 들어간(저품질) 쪽을 버리고,
제목이 채워진 쪽을 남긴다 — 둘 다 제목이 있으면 먼저 생성된 쪽을 남긴다.
"""
from __future__ import annotations

import os
import re

import psycopg2

Q_ID_RE = re.compile(r"^Q\d+$")


def main() -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    cur.execute("""
        select mh.museum_id, mh.accession_number, mh.id, mh.artwork_id, a.title, mh.created_at
        from museum_holdings mh
        join artworks a on a.id = mh.artwork_id
        where mh.accession_number is not null
        order by mh.museum_id, mh.accession_number, mh.created_at
    """)
    from collections import defaultdict

    groups: dict[tuple, list[tuple]] = defaultdict(list)
    for museum_id, accession, holding_id, artwork_id, title, created_at in cur.fetchall():
        groups[(museum_id, accession)].append((holding_id, artwork_id, title, created_at))

    dupe_groups = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"[dedup] {len(dupe_groups)}개 중복 (museum, accession) 그룹 발견")

    removed_holdings = 0
    removed_artworks = 0
    for key, rows in dupe_groups.items():
        # Q-id를 제목 그대로 쓴(비어있던) 저품질 행을 뒤로 보내고, 나머지는 생성순
        rows.sort(key=lambda r: (bool(Q_ID_RE.match(r[2] or "")), r[3]))
        keep = rows[0]
        drop = rows[1:]
        drop_holding_ids = [r[0] for r in drop]
        drop_artwork_ids = [r[1] for r in drop]

        cur.execute("delete from museum_holdings where id = any(%s::uuid[])", (drop_holding_ids,))
        cur.execute("delete from artworks where id = any(%s::uuid[])", (drop_artwork_ids,))
        removed_holdings += len(drop_holding_ids)
        removed_artworks += len(drop_artwork_ids)

    conn.commit()
    print(f"[dedup] holdings {removed_holdings}건, artworks {removed_artworks}건 제거")

    cur.execute("""
        create unique index if not exists idx_museum_holdings_museum_accession_unique
        on museum_holdings(museum_id, accession_number)
        where accession_number is not null
    """)
    conn.commit()
    print("[dedup] museum_holdings(museum_id, accession_number) 유니크 인덱스 생성 완료")

    cur.execute("create unique index if not exists idx_museums_name_unique on museums(name)")
    cur.execute("create unique index if not exists idx_galleries_name_unique on galleries(name)")
    cur.execute("create unique index if not exists idx_sources_raw_path_unique on sources(raw_path)")
    conn.commit()
    print("[dedup] museums/galleries(name), sources(raw_path) 유니크 인덱스 생성 완료")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
