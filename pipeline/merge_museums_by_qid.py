"""같은 wikidata_qid 를 가진 museums 행 병합 (2026-09-15, 0011 백필 후속).

'Kunsthistorisches Museum Wien' / 'Kunsthistorisches Museum', '서울시립미술관 (SeMA)' / '서울시립미술관 (Seoul Museum of Art)' 처럼
소스마다 다른 표기로 생긴 중복을 authority ID 동일 조건으로만 합친다(문자열 유사도 없음).
정본 = 소장(museum_holdings) 최다 → 전시 최다 → 생성 오래된 행. FK(museum_holdings.museum_id, provenance_records.owner_museum_id,
exhibitions.museum_id)를 정본으로 옮기고 나머지 행 삭제. museum_holdings (museum_id, accession) 유니크 충돌 시 그 행은 삭제(같은 소장 중복).
기본: 리포트   --apply: 실행. idempotent.
"""
from __future__ import annotations

import argparse
import sys

from artist_merge_util import get_conn

sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """select m.wikidata_qid, m.id::text, m.name,
                  (select count(*) from museum_holdings h where h.museum_id = m.id) hold,
                  (select count(*) from exhibitions e where e.museum_id = m.id) exh,
                  (select count(*) from provenance_records p where p.owner_museum_id = m.id) prov,
                  m.created_at
           from museums m where m.wikidata_qid in (select wikidata_qid from museums where wikidata_qid is not null group by 1 having count(*) > 1)
           order by m.wikidata_qid, hold desc, exh desc, m.created_at"""
    )
    groups: dict[str, list] = {}
    for row in cur.fetchall():
        groups.setdefault(row[0], []).append(row)
    print(f"중복 QID 그룹 {len(groups)}")
    plan = []
    for qid, rows in groups.items():
        canon, dups = rows[0], rows[1:]
        print(f"  {qid}: 정본 '{canon[2]}' (소장 {canon[3]}/전시 {canon[4]}/프로버넌스 {canon[5]}) ← " + ", ".join(f"'{d[2]}'({d[3]}/{d[4]}/{d[5]})" for d in dups))
        plan += [(canon[1], d[1]) for d in dups]
    if not args.apply:
        print("--apply 없음: 리포트만")
        return
    for canon_id, dup_id in plan:
        cur.execute("delete from museum_holdings h using museum_holdings c where h.museum_id = %s and c.museum_id = %s and h.accession_number = c.accession_number", (dup_id, canon_id))
        cur.execute("update museum_holdings set museum_id = %s where museum_id = %s", (canon_id, dup_id))
        cur.execute("update provenance_records set owner_museum_id = %s where owner_museum_id = %s", (canon_id, dup_id))
        cur.execute("update exhibitions set museum_id = %s where museum_id = %s", (canon_id, dup_id))
        cur.execute("delete from museums where id = %s", (dup_id,))
    conn.commit()
    cur.execute("select count(*), count(wikidata_qid), count(distinct wikidata_qid) from museums")
    print("완료: museums 행/QID/고유QID =", cur.fetchone())


if __name__ == "__main__":
    main()
