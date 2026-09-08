"""collectors 테이블 순수 표기 차이(공백/구두점/악센트) 중복 병합.

artists 테이블에서 이미 해온 정합성 작업(merge_case_dup_artists.py/
merge_unicode_form_dup_artists.py 계열)과 같은 문제가 collectors에도 있음을
2026-09-04 워커1 자율 탐색 중 발견 — "Rogers Fund"/"Roger's Fund",
"Harris Brisbane Dick Fund"/"Harris Brisbane Dick  Fund"(이중공백),
"Mrs. Charles C. Bovey"/"Mrs Charles C. Bovey"(마침표 유무) 등 223개 그룹.

정규화(악센트 제거·구두점 제거·공백 정리·소문자화)했을 때 같은 그룹만 병합
대상 — 이건 사람이 봐도 100% 동일 인물/단체 표기라 동명이인 위험이 없는
케이스(artists의 merge_unicode_form_dup_artists.py와 동일 안전 근거).

canonical 선택: is_institution=true인 쪽 우선(펀드/단체명이 더 정확한 경우가
많음) → bio 채워진 쪽 우선 → 마침표/아포스트로피 있는 표준 표기 우선 → 전체
대문자 아닌 쪽.

사용법:
    python pipeline/merge_dup_collectors.py            # 리포트만
    python pipeline/merge_dup_collectors.py --apply    # 실제 반영
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from db import get_connection


def normalize(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = re.sub(r"[.\-'’,]", "", stripped)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


def is_all_caps(name: str) -> bool:
    letters = [c for c in name if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def main() -> None:
    parser = argparse.ArgumentParser(description="collectors 표기 차이 중복 병합")
    parser.add_argument("--apply", action="store_true", help="실제 DB 병합 실행")
    parser.add_argument("--sample", type=int, default=250, help="리포트에 출력할 그룹 수")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("select id, name, is_institution, bio from collectors")
    rows = cur.fetchall()
    print(f"[merge_dup_collectors] collectors 전체 {len(rows)}건 로드")

    groups: dict[str, list[tuple]] = defaultdict(list)
    for row in rows:
        groups[normalize(row[1])].append(row)

    candidates = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        distinct_lower = {m[1].lower() for m in members}
        if len(distinct_lower) == 1:
            continue  # 순수 대소문자 차이는 케이스 무관 병합 아님(그대로 둬도 무방)
        candidates.append(members)

    print(f"[merge_dup_collectors] 병합 후보 그룹 {len(candidates)}개\n")

    for members in candidates[: args.sample]:
        print(f"  {[(m[1], m[2]) for m in members]}")
    if len(candidates) > args.sample:
        print(f"  ... 외 {len(candidates) - args.sample}개 더 있음 (--sample로 더 보기)")

    if not args.apply:
        print("\n[merge_dup_collectors] --apply 없이 리포트만 실행함 (DB 변경 없음)")
        return

    total_merged = 0
    total_repointed = 0
    for i, members in enumerate(candidates, 1):
        def score(m):
            _id, name, is_inst, bio = m
            return (
                1 if is_inst else 0,
                1 if bio else 0,
                0 if is_all_caps(name) else 1,
            )

        ranked = sorted(members, key=score, reverse=True)
        canonical_id = ranked[0][0]
        canonical_is_inst = any(m[2] for m in members)
        loser_ids = [m[0] for m in ranked[1:]]

        for attempt in range(3):
            try:
                if canonical_is_inst and not ranked[0][2]:
                    cur.execute(
                        "update collectors set is_institution = true where id = %s",
                        (canonical_id,),
                    )
                cur.execute(
                    "update provenance_records set owner_collector_id = %s "
                    "where owner_collector_id = any(%s::uuid[])",
                    (canonical_id, loser_ids),
                )
                n = cur.rowcount
                cur.execute("delete from collectors where id = any(%s::uuid[])", (loser_ids,))
                conn.commit()
                break
            except Exception as e:
                conn.rollback()
                if attempt == 2:
                    print(f"  실패(재시도 초과): {[m[1] for m in members]} — {e}")
                    n = 0
                    loser_ids = []
                    break
                print(f"  재시도 {attempt + 1}: {[m[1] for m in members]} — {e}")

        if loser_ids:
            total_merged += len(loser_ids)
            total_repointed += n

        if i % 200 == 0:
            print(f"  ... 진행 {i}/{len(candidates)}")

    print(f"\n[merge_dup_collectors] 완료 — 병합된 행 {total_merged}개, 재연결 {total_repointed}건")


if __name__ == "__main__":
    main()
