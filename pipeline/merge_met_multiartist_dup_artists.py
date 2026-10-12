"""Met CSV "|" 다중작가 필드 오염 백필 (docs/자율운영기준.md §3 워커1 큐,
2026-09-04 메인 세션 지시).

Met 공식 CSV 벌크 덤프의 `Artist Display Name`(및 Nationality/Begin Date/
End Date/Bio) 필드는 작가가 여럿인 오브젝트(주로 판화)를 "|"로 구분한 병렬
배열로 담는 공식 컨벤션인데, `pipeline/met.py`(수정 전)가 이를 안 쪼개고
필드 전체를 `artists.name`에 그대로 저장해 같은 작가가 공저자 조합에 따라
수십 개의 서로 다른 artists 행으로 흩어지는 오염이 발생했다(예: Jonas
Suyderhoef 30개 이상). met.py는 이미 수정돼 재발은 안 하지만, 기존 적재분
36,618건은 소급 반영이 안 돼 이 스크립트로 백필한다.

Met 컨벤션: "|"로 구분된 각 필드(name/nationality/bio)는 같은 인덱스가 같은
작가를 가리키는 병렬 배열 — 첫 번째("|" 앞) 값이 주 작가(met.py 수정과 동일
파싱 로직).

처리 로직:
1. `artists.name`에 "|"가 있는 행을 대상으로 `name.split('|')[0].strip()`을
   "정식 이름"으로 추출.
2. 그 정식 이름과 대소문자 무시 일치하는 **오염 안 된**(name에 "|" 없는)
   기존 artists 행이 있으면 → 오염 행을 그 행으로 재연결(artworks +
   gallery_representations) 후 오염 행 삭제.
3. 없으면 → 오염 행 자체를 in-place 정정(name/nationality/bio는 "|" split의
   첫 값, birth_year/death_year는 원래 값 유지 — 컬럼 자체가 다중작가 행에서
   항상 null이라 정정할 값이 없음).

"; after "/": After " 패턴(1,697건, 별도 컨벤션 — 주 작가가 세미콜론 앞)은
이 스크립트 스코프 밖. 함께 섞으면 위험하므로 건드리지 않는다.

사용법:
    python pipeline/merge_met_multiartist_dup_artists.py            # 리포트만
    python pipeline/merge_met_multiartist_dup_artists.py --apply    # 실제 반영
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from db import get_connection


def split_first(value: str | None) -> str | None:
    if value is None:
        return None
    first = value.split("|")[0].strip()
    return first or None


def reconnect(cur, conn, pid: str, cid: str, label: str) -> tuple[bool, int]:
    for attempt in range(3):
        try:
            cur.execute("update artworks set artist_id = %s where artist_id = %s", (cid, pid))
            n1 = cur.rowcount
            cur.execute(
                "update gallery_representations set artist_id = %s where artist_id = %s",
                (cid, pid),
            )
            n2 = cur.rowcount
            cur.execute("delete from artists where id = %s", (pid,))
            conn.commit()
            return True, n1 + n2
        except Exception as e:
            conn.rollback()
            if attempt == 2:
                print(f"  실패(재시도 초과): {pid} ({label!r}) — {e}")
                return False, 0
            print(f"  재시도 {attempt + 1}: {pid} ({label!r}) — {e}")
    return False, 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Met '|' 다중작가 필드 오염 백필")
    parser.add_argument("--apply", action="store_true", help="실제 DB 반영")
    parser.add_argument("--sample", type=int, default=30, help="리포트에 출력할 그룹 수")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "select id, name, nationality, birth_year, death_year, bio "
        "from artists where name like '%|%'"
    )
    polluted = cur.fetchall()
    print(f"[merge_met_multiartist] '|' 오염 행 {len(polluted)}건 로드")

    cur.execute("select id, name from artists where name not like '%|%'")
    clean_by_lower: dict[str, str] = {}
    for aid, name in cur.fetchall():
        clean_by_lower.setdefault(name.lower(), aid)

    # 정식 이름(소문자) -> 오염 행 목록으로 그룹화 — 같은 정식 이름으로 귀결되는
    # 오염 행이 여럿이면 unique index(artists.name)를 건드리지 않도록 그룹당
    # 하나만 in-place 정정하고 나머지는 그 행으로 재연결한다.
    groups: dict[str, list[tuple]] = defaultdict(list)
    skipped = []
    for row in polluted:
        pid, name, nat, by, dy, bio = row
        primary_name = split_first(name)
        if not primary_name:
            skipped.append((pid, name))
            continue
        groups[primary_name.lower()].append((pid, primary_name, split_first(nat), split_first(bio)))

    reconnect_to_existing = []  # (pid, canonical_id, primary_name)
    inplace_then_reconnect = []  # (canonical_row, [dup rows...])

    for key, members in groups.items():
        canonical_id = clean_by_lower.get(key)
        if canonical_id:
            for pid, primary_name, _nat, _bio in members:
                reconnect_to_existing.append((pid, canonical_id, primary_name))
        else:
            canonical_row, *dup_rows = members
            inplace_then_reconnect.append((canonical_row, dup_rows))

    total_dup_in_groups = sum(len(d) for _, d in inplace_then_reconnect)
    print(f"[merge_met_multiartist] 기존 정상 행으로 재연결 {len(reconnect_to_existing)}건")
    print(
        f"[merge_met_multiartist] 정상 행 없어 in-place 정정 {len(inplace_then_reconnect)}건 "
        f"(그룹 내 동일 정식이름 중복 {total_dup_in_groups}건은 정정된 행으로 재연결)"
    )
    if skipped:
        print(f"[merge_met_multiartist] 스킵(빈 이름 등) {len(skipped)}건")

    print("\n  -- 재연결 샘플 --")
    for pid, cid, pname in reconnect_to_existing[: args.sample]:
        print(f"  {pid} -> {cid} (canonical name={pname!r})")

    print("\n  -- in-place 정정 샘플 --")
    for (pid, pname, nat, bio), dups in inplace_then_reconnect[: args.sample]:
        extra = f" (+ 그룹 내 중복 {len(dups)}건 재연결)" if dups else ""
        print(f"  {pid}: name -> {pname!r}, nationality -> {nat!r}{extra}")

    if not args.apply:
        print("\n[merge_met_multiartist] --apply 없이 리포트만 실행함 (DB 변경 없음)")
        return

    total_reconnected = 0
    total_repointed = 0
    total_fixed = 0

    for i, (pid, cid, pname) in enumerate(reconnect_to_existing, 1):
        ok, n = reconnect(cur, conn, pid, cid, pname)
        if ok:
            total_reconnected += 1
            total_repointed += n
        if i % 2000 == 0:
            print(f"  ... 재연결 진행 {i}/{len(reconnect_to_existing)}")

    for i, ((pid, pname, nat, bio), dups) in enumerate(inplace_then_reconnect, 1):
        fixed_ok = False
        for attempt in range(3):
            try:
                cur.execute(
                    "update artists set name = %s, nationality = %s, bio = %s, "
                    "updated_at = now() where id = %s",
                    (pname, nat, bio, pid),
                )
                conn.commit()
                fixed_ok = True
                break
            except Exception as e:
                conn.rollback()
                if attempt == 2:
                    print(f"  실패(재시도 초과): {pid} ({pname!r}) — {e}")
                else:
                    print(f"  재시도 {attempt + 1}: {pid} ({pname!r}) — {e}")
        if fixed_ok:
            total_fixed += 1
            for dup_pid, dup_pname, _nat, _bio in dups:
                ok, n = reconnect(cur, conn, dup_pid, pid, dup_pname)
                if ok:
                    total_reconnected += 1
                    total_repointed += n
        if i % 2000 == 0:
            print(f"  ... in-place 진행 {i}/{len(inplace_then_reconnect)}")

    print(
        f"\n[merge_met_multiartist] 완료 — in-place 정정 {total_fixed}건, "
        f"재연결(삭제) {total_reconnected}건 (재연결된 참조 {total_repointed}건)"
    )


if __name__ == "__main__":
    main()
