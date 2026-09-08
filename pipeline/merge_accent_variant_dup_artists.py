"""악센트/마크론/하이픈 등 순수 표기 차이 중복 병합 — 메타데이터 대조로 안전 확장.

audit_gallery_artist_matches.py 감사에서 원인 2·4(악센트/발음부호 유무,
하이픈·공백 변형)로 분류된 그룹은 표기 순서 차이(merge_name_order_dup_artists.py)
와 달리 "실제로 표기가 바뀌었다"는 구조적 증거가 약해 동명이인 오병합 위험이
있다는 이유로 지금까지 사람 검토로만 남겨뒀다(docs/정합성작업.md §1 참고).

이 스크립트는 그 위험을 낮추는 별도 안전장치를 추가한다: 정규화 이름이 같은
것만으로 묶지 않고, **그룹 내 채워진 메타데이터(생몰년/국적)가 전부 서로
일치할 때만** 병합 후보로 인정한다.
  - birth_year: 그룹 내 값이 있는 행이 2개 이상이면 전부 같아야 함
  - death_year: 위와 동일
  - nationality: 위와 동일(대소문자/공백 정규화 후 비교)
  - 메타데이터가 하나도 없는 행만 있는 그룹(전부 null)은 대조 근거가 없으므로
    후보에서 제외 — 여전히 사람 검토로 남김
  - 채워진 필드가 하나라도 서로 다르면(동명이인 의심) 그룹 전체를 스킵

canonical 선택: merge_name_order_dup_artists.py와 동일한 기준(메타데이터
채워진 쪽 우선 -> 전체 대문자 아닌 쪽).

사용법:
    python pipeline/merge_accent_variant_dup_artists.py            # 리포트만
    python pipeline/merge_accent_variant_dup_artists.py --apply    # 실제 병합
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


def norm_nationality(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip().lower()
    return v or None


def is_all_caps(name: str) -> bool:
    letters = [c for c in name if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def corroborated(members: list[tuple]) -> bool:
    """채워진 메타데이터가 그룹 내에서 전부 일치하는지, 대조 근거가 있는지 확인."""
    any_field_filled_by_2plus = False
    for idx in (2, 3, 4):  # nationality, birth_year, death_year
        vals = [m[idx] for m in members if m[idx] not in (None, "")]
        if len(vals) >= 2:
            any_field_filled_by_2plus = True
            if len(set(vals)) > 1:
                return False
    return any_field_filled_by_2plus


def main() -> None:
    parser = argparse.ArgumentParser(description="악센트/표기 변형 중복 — 메타데이터 대조 병합")
    parser.add_argument("--apply", action="store_true", help="실제 DB 병합 실행")
    parser.add_argument("--sample", type=int, default=200, help="리포트에 출력할 그룹 수")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("select id, name, nationality, birth_year, death_year from artists")
    rows = cur.fetchall()
    print(f"[merge_accent_variant] artists 전체 {len(rows)}건 로드")

    groups: dict[str, list[tuple]] = defaultdict(list)
    for row in rows:
        _id, name, nat, by, dy = row
        key = normalize(name)
        groups[key].append((row[0], name, norm_nationality(nat), by, dy))

    candidates = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        distinct_lower = {m[1].lower() for m in members}
        if len(distinct_lower) == 1:
            continue  # 순수 대소문자 차이는 merge_case_dup_artists.py 몫
        if not corroborated(members):
            continue
        candidates.append(members)

    print(f"[merge_accent_variant] 메타데이터 대조로 검증된 병합 후보 그룹 {len(candidates)}개\n")

    for members in candidates[: args.sample]:
        print(f"  {[(m[1], m[2], m[3], m[4]) for m in members]}")

    if len(candidates) > args.sample:
        print(f"  ... 외 {len(candidates) - args.sample}개 더 있음 (--sample로 더 보기)")

    if not args.apply:
        print("\n[merge_accent_variant] --apply 없이 리포트만 실행함 (DB 변경 없음)")
        return

    total_merged = 0
    total_repointed = 0
    for i, members in enumerate(candidates, 1):
        ranked = sorted(members, key=lambda m: (
            sum(1 for v in (m[2], m[3], m[4]) if v),
            0 if not is_all_caps(m[1]) else -1,
        ), reverse=True)
        canonical_id = ranked[0][0]
        loser_ids = [m[0] for m in ranked[1:]]

        for attempt in range(3):
            try:
                cur.execute(
                    "update artworks set artist_id = %s where artist_id = any(%s::uuid[])",
                    (canonical_id, loser_ids),
                )
                n1 = cur.rowcount
                cur.execute(
                    "update gallery_representations set artist_id = %s where artist_id = any(%s::uuid[])",
                    (canonical_id, loser_ids),
                )
                n2 = cur.rowcount
                cur.execute("delete from artists where id = any(%s::uuid[])", (loser_ids,))
                conn.commit()
                break
            except Exception as e:
                conn.rollback()
                if attempt == 2:
                    print(f"  실패(재시도 초과): {[m[1] for m in members]} — {e}")
                    n1 = n2 = 0
                    loser_ids = []
                    break
                print(f"  재시도 {attempt + 1}: {[m[1] for m in members]} — {e}")

        if loser_ids:
            print(f"  병합: {[m[1] for m in members]} -> canonical={ranked[0][1]!r}")
            total_merged += len(loser_ids)
            total_repointed += n1 + n2

        if i % 500 == 0:
            print(f"  ... 진행 {i}/{len(candidates)}")

    print(f"\n[merge_accent_variant] 완료 — 병합된 행 {total_merged}개, 재연결 {total_repointed}건")


if __name__ == "__main__":
    main()
