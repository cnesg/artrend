"""Mia(Minneapolis Institute of Art) "; after "/"After X" 오염 백필.

pipeline/mia.py의 구 파싱 로직(artist: 접두어 제거 후 단순 split(';')[0], 또는
접두어 없으면 원문 그대로 저장)이 "Sculptor: After François du Quesnoy",
"After Raphael (Raffaello Sanzio)"처럼 **원작자 참조("After X")를 실제 활동
작가명으로 잘못 저장**하거나, "Engraver: X; Designer: After Y" 같은 다중 역할
크레딧 라인을 안 쪼갠 채 통째로 저장하는 오염을 냈다(docs/정합성작업.md §6
후속 참고). `pipeline/mia.py`는 이미 `parse_artist_name()`으로 수정 완료 —
이 스크립트는 이미 적재된 mia 소스 artists 행을 같은 로직으로 재평가해
백필한다.

방침(Europeana/Wikidata 오염 정리와 동일 원칙 — 틀린 이름보다 모르는 게 낫다):
- `parse_artist_name(현재 name)` 결과가 **None**이면 → 작가 미상 처리:
  해당 artist_id를 참조하는 artworks/gallery_representations를 artist_id
  NULL로 돌리고, 오염된 artists 행 삭제.
- 결과가 **원래 name과 다른 문자열**이면(다중 세그먼트를 첫 세그먼트로
  축약) → 그 이름의 기존 정상 행이 있으면 재연결 후 삭제, 없으면 그룹당
  하나만 in-place 정정(그룹 내 나머지는 정정된 행으로 재연결 — unique
  index 충돌 방지, merge_met_multiartist_dup_artists.py와 동일 패턴).
- 결과가 원래 name과 같으면 → 이미 올바름, 손대지 않음.

mia 소스로 한정(source_id 스코프) — 같은 "After X" 패턴이 aic/getty_
provenance_sales/moma에도 소수 있으나, 그건 각 소스 자체 API가 원래 그렇게
제공하는 값이라 로더 버그가 아님(별도 판단 필요 — 이 스크립트 스코프 아님).

사용법:
    python pipeline/fix_mia_after_artist_names.py            # 리포트만
    python pipeline/fix_mia_after_artist_names.py --apply    # 실제 반영
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from db import get_connection
from mia import parse_artist_name


def nullify_and_delete(cur, conn, pid: str, label: str) -> tuple[bool, int]:
    for attempt in range(3):
        try:
            cur.execute("update artworks set artist_id = null where artist_id = %s", (pid,))
            n1 = cur.rowcount
            cur.execute(
                "delete from gallery_representations where artist_id = %s", (pid,)
            )
            n2 = cur.rowcount
            cur.execute("delete from artists where id = %s", (pid,))
            conn.commit()
            return True, n1 + n2
        except Exception as e:
            conn.rollback()
            if attempt == 2:
                print(f"  실패(재시도 초과, null화): {pid} ({label!r}) — {e}")
                return False, 0
            print(f"  재시도 {attempt + 1}(null화): {pid} ({label!r}) — {e}")
    return False, 0


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
                print(f"  실패(재시도 초과, 재연결): {pid} ({label!r}) — {e}")
                return False, 0
            print(f"  재시도 {attempt + 1}(재연결): {pid} ({label!r}) — {e}")
    return False, 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Mia after-패턴 작가명 오염 백필")
    parser.add_argument("--apply", action="store_true", help="실제 DB 반영")
    parser.add_argument("--sample", type=int, default=30, help="리포트에 출력할 그룹 수")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("select id from sources where site_name = 'mia'")
    row = cur.fetchone()
    if not row:
        print("[fix_mia_after] mia source_id를 찾을 수 없음 — 종료")
        return
    mia_source_id = row[0]

    cur.execute("select id, name from artists where source_id = %s", (mia_source_id,))
    rows = cur.fetchall()
    print(f"[fix_mia_after] mia 소스 artists {len(rows)}건 로드")

    cur.execute(
        "select id, name from artists where source_id is distinct from %s", (mia_source_id,)
    )
    other_by_lower: dict[str, str] = {}
    for aid, name in cur.fetchall():
        other_by_lower.setdefault(name.lower(), aid)
    cur.execute("select id, name from artists where source_id = %s", (mia_source_id,))
    mia_by_lower: dict[str, str] = {}
    for aid, name in rows:
        mia_by_lower.setdefault(name.lower(), aid)

    to_nullify = []  # (pid, name)
    to_reconnect_existing = []  # (pid, canonical_id, name, new_name)
    groups_for_inplace: dict[str, list[tuple]] = defaultdict(list)  # new_name.lower() -> [(pid, name, new_name)]
    unchanged = 0

    for pid, name in rows:
        new_name = parse_artist_name(name)
        if new_name == name:
            unchanged += 1
            continue
        if new_name is None:
            to_nullify.append((pid, name))
            continue
        canonical_id = other_by_lower.get(new_name.lower()) or (
            mia_by_lower.get(new_name.lower()) if mia_by_lower.get(new_name.lower()) != pid else None
        )
        if canonical_id:
            to_reconnect_existing.append((pid, canonical_id, name, new_name))
        else:
            groups_for_inplace[new_name.lower()].append((pid, name, new_name))

    inplace_then_reconnect = []
    for key, members in groups_for_inplace.items():
        canonical, *dups = members
        inplace_then_reconnect.append((canonical, dups))

    print(f"[fix_mia_after] 변경 없음(이미 올바름) {unchanged}건")
    print(f"[fix_mia_after] 작가 미상 처리(NULL화+삭제) {len(to_nullify)}건")
    print(f"[fix_mia_after] 기존 정상 행으로 재연결 {len(to_reconnect_existing)}건")
    total_dup = sum(len(d) for _, d in inplace_then_reconnect)
    print(
        f"[fix_mia_after] 정상 행 없어 in-place 축약 {len(inplace_then_reconnect)}건 "
        f"(그룹 내 중복 {total_dup}건은 정정된 행으로 재연결)"
    )

    print("\n  -- 작가 미상 처리 샘플 --")
    for pid, name in to_nullify[: args.sample]:
        print(f"  {pid}: {name!r} -> None")

    print("\n  -- 재연결 샘플 --")
    for pid, cid, name, new_name in to_reconnect_existing[: args.sample]:
        print(f"  {pid} ({name!r}) -> {cid} (existing={new_name!r})")

    print("\n  -- in-place 축약 샘플 --")
    for (pid, name, new_name), dups in inplace_then_reconnect[: args.sample]:
        extra = f" (+ 그룹 내 중복 {len(dups)}건)" if dups else ""
        print(f"  {pid}: {name!r} -> {new_name!r}{extra}")

    if not args.apply:
        print("\n[fix_mia_after] --apply 없이 리포트만 실행함 (DB 변경 없음)")
        return

    total_nullified = 0
    total_nullified_refs = 0
    for i, (pid, name) in enumerate(to_nullify, 1):
        ok, n = nullify_and_delete(cur, conn, pid, name)
        if ok:
            total_nullified += 1
            total_nullified_refs += n
        if i % 500 == 0:
            print(f"  ... null화 진행 {i}/{len(to_nullify)}")

    total_reconnected = 0
    total_repointed = 0
    for i, (pid, cid, name, new_name) in enumerate(to_reconnect_existing, 1):
        ok, n = reconnect(cur, conn, pid, cid, name)
        if ok:
            total_reconnected += 1
            total_repointed += n
        if i % 500 == 0:
            print(f"  ... 재연결 진행 {i}/{len(to_reconnect_existing)}")

    total_fixed = 0
    for i, ((pid, name, new_name), dups) in enumerate(inplace_then_reconnect, 1):
        fixed_ok = False
        for attempt in range(3):
            try:
                cur.execute(
                    "update artists set name = %s, updated_at = now() where id = %s",
                    (new_name, pid),
                )
                conn.commit()
                fixed_ok = True
                break
            except Exception as e:
                conn.rollback()
                if attempt == 2:
                    print(f"  실패(재시도 초과, in-place): {pid} ({new_name!r}) — {e}")
                else:
                    print(f"  재시도 {attempt + 1}(in-place): {pid} ({new_name!r}) — {e}")
        if fixed_ok:
            total_fixed += 1
            for dup_pid, dup_name, _new in dups:
                ok, n = reconnect(cur, conn, dup_pid, pid, dup_name)
                if ok:
                    total_reconnected += 1
                    total_repointed += n
        if i % 500 == 0:
            print(f"  ... in-place 진행 {i}/{len(inplace_then_reconnect)}")

    print(
        f"\n[fix_mia_after] 완료 — 작가미상 처리 {total_nullified}건"
        f"(참조 NULL화/삭제 {total_nullified_refs}건), "
        f"in-place 축약 {total_fixed}건, 재연결(삭제) {total_reconnected}건"
        f"(재연결된 참조 {total_repointed}건)"
    )


if __name__ == "__main__":
    main()
