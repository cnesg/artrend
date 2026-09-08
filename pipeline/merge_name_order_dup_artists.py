"""작가 이름 "성, 이름" ↔ "이름 성" 표기 순서 차이 중복 병합.

audit_gallery_artist_matches.py 감사에서 발견한 원인 1번(표기 순서 차이) —
미술관 소스는 "Kusama, Yayoi"처럼 도서관 목록 관행(성 먼저, 쉼표)을 쓰고
갤러리 사이트는 "Kusama Yayoi"처럼 자연스러운 순서를 쓴다.

안전 조건(동명이인 오병합 위험을 낮추기 위해 전부 만족해야 병합 대상):
1. 그룹 내 이름들을 정규화(악센트 제거, 구두점 제거, 소문자화)한 뒤 토큰으로
   쪼갰을 때 토큰 멀티셋이 완전히 동일해야 한다(순서만 다르고 토큰 추가/누락 없음).
2. 그룹 안에 쉼표 형태("성, 이름")인 이름이 최소 1개, 쉼표 없는 형태가 최소
   1개 있어야 한다 — 즉 실제로 "표기 순서가 바뀌었다"는 증거가 있어야 병합.
   (단순 우연한 토큰 애너그램이 아니라 comma-reorder 패턴이 확인된 경우만.)
3. 토큰 수가 2개 이상이어야 한다(단일 토큰은 애초에 이 패턴에 해당 안 됨).

canonical 선택: 메타데이터(국적/생몰년) 채워진 쪽 우선 → 쉼표 없는 자연스러운
순서 표기 우선(다른 소스 다수가 이 형태라 표준에 가까움) → 전체 대문자 아닌 쪽.
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


def norm_token(tok: str) -> str:
    decomposed = unicodedata.normalize("NFKD", tok)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", stripped.lower())


def tokenize(name: str) -> tuple[str, ...]:
    # 쉼표를 공백으로 바꿔서 "Kusama, Yayoi" -> ["Kusama", "Yayoi"]처럼 토큰화
    raw = name.replace(",", " ")
    tokens = [norm_token(t) for t in raw.split()]
    return tuple(sorted(t for t in tokens if t))


def is_comma_form(name: str) -> bool:
    return bool(re.match(r"^\s*[^,]+,\s*\S", name))


def is_all_caps(name: str) -> bool:
    letters = [c for c in name if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def main() -> None:
    parser = argparse.ArgumentParser(description="작가명 성/이름 순서 차이 중복 병합")
    parser.add_argument("--apply", action="store_true", help="실제 DB 병합 실행")
    parser.add_argument("--sample", type=int, default=200, help="리포트에 출력할 그룹 수")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("select id, name, nationality, birth_year, death_year from artists")
    rows = cur.fetchall()
    print(f"[merge_name_order] artists 전체 {len(rows)}건 로드")

    groups: dict[tuple[str, ...], list[tuple]] = defaultdict(list)
    for row in rows:
        key = tokenize(row[1])
        if len(key) >= 2:
            groups[key].append(row)

    candidates = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        # 정규화 토큰이 같아도 동일 문자열(대소문자 차이만)이면 merge_case_dup_artists.py 몫이니 스킵
        distinct_lower = {m[1].lower() for m in members}
        if len(distinct_lower) == 1:
            continue
        has_comma = any(is_comma_form(m[1]) for m in members)
        has_non_comma = any(not is_comma_form(m[1]) for m in members)
        if not (has_comma and has_non_comma):
            continue
        candidates.append(members)

    print(f"[merge_name_order] 병합 후보 그룹 {len(candidates)}개\n")

    for members in candidates[: args.sample]:
        print(f"  {[m[1] for m in members]}")

    if len(candidates) > args.sample:
        print(f"  ... 외 {len(candidates) - args.sample}개 더 있음 (--sample로 더 보기)")

    if not args.apply:
        print("\n[merge_name_order] --apply 없이 리포트만 실행함 (DB 변경 없음)")
        return

    total_merged = 0
    total_repointed = 0
    for i, members in enumerate(candidates, 1):
        def score(r):
            _, name, nat, by, dy = r
            meta = sum(1 for v in (nat, by, dy) if v)
            return (meta, 0 if is_comma_form(name) else 1, 0 if is_all_caps(name) else 1)

        members = sorted(members, key=score, reverse=True)
        canonical_id = members[0][0]
        loser_ids = [m[0] for m in members[1:]]

        # 다른 세션이 동시에 artists를 쓰고 있어(크롤링/provenance_extract 진행 중)
        # 그룹 단위로 커밋해야 트랜잭션이 오래 열려있다 데드락에 걸리지 않는다.
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
            print(f"  병합: {[m[1] for m in members]} -> canonical={members[0][1]!r}")
            total_merged += len(loser_ids)
            total_repointed += n1 + n2

        if i % 500 == 0:
            print(f"  ... 진행 {i}/{len(candidates)}")

    print(f"\n[merge_name_order] 완료 — 병합된 행 {total_merged}개, 재연결 {total_repointed}건")


if __name__ == "__main__":
    main()
