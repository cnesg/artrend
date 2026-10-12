"""galleries 테이블 순수 표기 차이(공백/구두점/악센트/대소문자) 중복 병합.

artists/collectors(§1·§6·§9 docs/정합성작업.md)에 이어 galleries에도 같은
문제 발견 — "Bernard Quaritch Ltd"/"Bernard Quaritch LTD",
"André Emmerich Gallery"/"Andre Emmerich Gallery" 등 18개 그룹(2026-09-04).

정규화(악센트 제거·구두점 제거·공백 정리·소문자화) 후 같은 그룹만 병합 —
동명이인 위험 없는 순수 표기 차이만 대상(merge_unicode_form_dup_artists.py와
동일 안전 근거).

canonical 선택: gallery_representations 연결 있는 쪽 우선 → city/country
채워진 쪽 우선 → 전체 대문자 아닌 쪽.

사용법:
    python pipeline/merge_dup_galleries.py            # 리포트만
    python pipeline/merge_dup_galleries.py --apply    # 실제 반영
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
    parser = argparse.ArgumentParser(description="galleries 표기 차이 중복 병합")
    parser.add_argument("--apply", action="store_true", help="실제 DB 병합 실행")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("select id, name, city, country from galleries")
    rows = cur.fetchall()
    print(f"[merge_dup_galleries] galleries 전체 {len(rows)}건 로드")

    cur.execute("select distinct gallery_id from gallery_representations")
    represented_ids = {str(r[0]) for r in cur.fetchall()}

    groups: dict[str, list[tuple]] = defaultdict(list)
    for row in rows:
        groups[normalize(row[1])].append(row)

    # artists와 달리 galleries엔 별도 case-only 병합 스크립트가 없으므로 대소문자만
    # 다른 중복도 이 스크립트에서 같이 처리한다(정규화 키가 같으면 전부 대상).
    candidates = [m for m in groups.values() if len(m) > 1]
    print(f"[merge_dup_galleries] 병합 후보 그룹 {len(candidates)}개\n")
    for members in candidates:
        print(f"  {[m[1] for m in members]}")

    if not args.apply:
        print("\n[merge_dup_galleries] --apply 없이 리포트만 실행함 (DB 변경 없음)")
        return

    total_merged = 0
    total_repointed = 0
    for members in candidates:
        def score(m):
            gid, name, city, country = m
            return (
                1 if str(gid) in represented_ids else 0,
                1 if city else 0,
                1 if country else 0,
                0 if is_all_caps(name) else 1,
            )

        ranked = sorted(members, key=score, reverse=True)
        canonical_id = ranked[0][0]
        loser_ids = [m[0] for m in ranked[1:]]

        for attempt in range(3):
            try:
                cur.execute(
                    "update gallery_representations set gallery_id = %s where gallery_id = any(%s::uuid[])",
                    (canonical_id, loser_ids),
                )
                n1 = cur.rowcount
                cur.execute(
                    "update provenance_records set owner_gallery_id = %s where owner_gallery_id = any(%s::uuid[])",
                    (canonical_id, loser_ids),
                )
                n2 = cur.rowcount
                cur.execute("delete from galleries where id = any(%s::uuid[])", (loser_ids,))
                conn.commit()
                total_merged += len(loser_ids)
                total_repointed += n1 + n2
                break
            except Exception as e:
                conn.rollback()
                if attempt == 2:
                    print(f"  실패(재시도 초과): {[m[1] for m in members]} — {e}")
                else:
                    print(f"  재시도 {attempt + 1}: {[m[1] for m in members]} — {e}")

    print(f"\n[merge_dup_galleries] 완료 — 병합된 행 {total_merged}개, 재연결 {total_repointed}건")


if __name__ == "__main__":
    main()
