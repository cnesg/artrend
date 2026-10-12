"""같은 authority ID(ULAN / Wikidata QID)를 가진 artists 행 병합 (2026-09-15 작업분담 §M6, 계획 P2-12).

backfill_artist_authority.py가 채운 artists.ulan_id / wikidata_qid 기준으로, 같은 ID를 가진 person 행이
2개 이상이면 하나로 합친다. 문자열 유사도는 전혀 쓰지 않는다(단일연결 체이닝 재발 방지 — 그룹 키는
ID 하나뿐이고 전이 병합 없음).

정본(canonical) 선택: 생년 보유 → 작품 수 최다 → 원본 bio 길이 → 이름이 긴 쪽(축약 표기 배제).
병합 후 entity_kind='attribution' 행의 attribution_of를 같은 ULAN/QID의 person 정본으로 채운다.
병합: artist_merge_util.relink_and_delete(작품·로스터·attribution_of·생성약력 재연결 후 삭제) +
fill_missing_meta. 정본의 ulan/qid가 비어 있으면 그룹 값으로 채움. entity_kind_note에 흡수된 이름을 남긴다.
ULAN 그룹 먼저, 그 다음 QID 그룹. 기본 리포트, --apply 시 반영. idempotent.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from artist_merge_util import fill_missing_meta, get_conn, relink_and_delete

sys.stdout.reconfigure(encoding="utf-8")


def load_groups(cur, col: str) -> dict[str, list[tuple]]:
    cur.execute(
        f"""select a.{col}, a.id::text, a.name, a.birth_year, coalesce(length(a.bio),0),
                   (select count(*) from artworks w where w.artist_id = a.id) as n_art,
                   a.ulan_id, a.wikidata_qid
            from artists a
            where a.entity_kind = 'person' and a.{col} is not null
              and a.{col} in (select {col} from artists where entity_kind = 'person' group by {col} having count(*) > 1)
            order by a.{col}"""
    )
    groups: dict[str, list[tuple]] = defaultdict(list)
    for row in cur.fetchall():
        groups[row[0]].append(row[1:])
    return groups


def pick_canonical(members: list[tuple]) -> tuple:
    # 생년 있는 행(미술관 소스 메타) → 작품 수 → bio 길이 → 이름 길이. Getty 축약 스텁("Teniers")이 작품이 많아도 정본이 되지 않게.
    return max(members, key=lambda m: (m[2] is not None, m[4], m[3], len(m[1])))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sample", type=int, default=15)
    args = ap.parse_args()
    conn = get_conn()
    cur = conn.cursor()
    total_groups = total_rows = total_relinked = 0
    for col in ("ulan_id", "wikidata_qid"):
        groups = load_groups(cur, col)
        n_rows = sum(len(v) for v in groups.values())
        print(f"[{col}] 그룹 {len(groups)} / 행 {n_rows} → 삭제 예정 {n_rows - len(groups)}")
        shown = 0
        for key, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            can = pick_canonical(members)
            if shown < args.sample:
                print(f"   {key}: 정본 '{can[1]}'({can[4]}) ← {[m[1] for m in members if m[0] != can[0]][:8]}")
                shown += 1
            if not args.apply:
                continue
            for m in members:
                if m[0] == can[0]:
                    continue
                fill_missing_meta(cur, can[0], m[0])
                total_relinked += relink_and_delete(cur, m[0], can[0])
                cur.execute(
                    """update artists set ulan_id = coalesce(ulan_id, %s), wikidata_qid = coalesce(wikidata_qid, %s),
                              entity_kind_note = left(concat_ws(' | ', entity_kind_note, %s), 2000), updated_at = now()
                       where id = %s""",
                    (m[5], m[6], f"merged:{m[1]}", can[0]),
                )
            conn.commit()
            total_groups += 1
            total_rows += len(members) - 1
    if not args.apply:
        print("--apply 없음: 리포트만")
        return
    for col in ("ulan_id", "wikidata_qid"):
        cur.execute(
            f"""update artists a set attribution_of = p.id, updated_at = now()
                from artists p
                where a.entity_kind = 'attribution' and a.attribution_of is null and a.{col} is not null
                  and p.{col} = a.{col} and p.entity_kind = 'person' and p.id <> a.id"""
        )
        print(f"attribution_of 채움({col}): {cur.rowcount}")
    conn.commit()
    print(f"완료: 그룹 {total_groups}, 삭제 {total_rows}행, 재연결 {total_relinked}건")


if __name__ == "__main__":
    main()
