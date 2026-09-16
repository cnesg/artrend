"""artists.bio 컬럼에서 nationality/birth_year/death_year 백필.

2026-09-08 1차 시도(가드 없이)에서 여러 오탐 발견 후 중단, 이후 가드 설계:
- bio 길이 <= MAX_BIO_LEN (짧은 bio만 — 긴 서술형 산문은 exhibition 연도 등
  무관한 숫자를 생몰년으로 오인하는 사례 확인)
- bio 괄호 0~1개만 (다수 괄호는 복수인물 합성/각주 구조일 위험)
- name에 콤마 없음 (콤마 있는 이름은 "Various Artists, X, Y, Z" 같은
  복수인물 합성 행일 위험)
- name에 회사/공방 표지어 없음 (창업/폐업 연도를 생몰년으로 오인 방지)
- name에 귀속표기(School of/Attributed to 등) 없음 (원작가와 다른 개체로
  취급하는 기존 정책과 충돌 방지)
- "active YYYY-YYYY"(활동시기)는 생몰년으로 취급 안 함
- 국적 후보는 bio에 연도가 하나라도 있을 때만 채택("City, Country"류 오탐 방지)

전부 pipeline/freetext_metadata.py의 parse_bio_text에 구현됨. 샘플 300여건
검증 결과 추출률 ~7%, 오탐 0건(2026-09-08). 기본은 dry-run.
"""
from __future__ import annotations

import argparse
import os
import sys

import psycopg2
from psycopg2.extras import execute_values

from freetext_metadata import parse_bio_text

sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    cur.execute(
        "select id, name, bio, nationality, birth_year, death_year from artists "
        "where bio is not null and length(bio) > 0 "
        "and (nationality is null or birth_year is null or death_year is null)"
    )
    rows = cur.fetchall()
    print(f"[backfill_bio] bio 있고 메타데이터 비어있는 artists {len(rows)}건 로드")

    to_update = []
    filled_nat = filled_birth = filled_death = 0

    for aid, name, bio, nationality, birth_year, death_year in rows:
        nat, birth, death = parse_bio_text(name, bio)
        if not (nat or birth or death):
            continue

        new_nat = nationality if nationality is not None else nat
        new_birth = birth_year if birth_year is not None else birth
        new_death = death_year if death_year is not None else death
        if new_nat == nationality and new_birth == birth_year and new_death == death_year:
            continue

        if nationality is None and new_nat is not None:
            filled_nat += 1
        if birth_year is None and new_birth is not None:
            filled_birth += 1
        if death_year is None and new_death is not None:
            filled_death += 1
        to_update.append((str(aid), new_nat, new_birth, new_death))

    print(f"[backfill_bio] 백필 가능 추정: nationality {filled_nat}건, birth_year {filled_birth}건, death_year {filled_death}건")
    print(f"[backfill_bio] UPDATE 대상 artists 행: {len(to_update)}건")

    if not args.apply:
        print("[backfill_bio] dry-run — DB 변경 없음. --apply로 실행하면 실제 반영됩니다.")
        cur.close()
        conn.close()
        return

    BATCH = 1000
    for i in range(0, len(to_update), BATCH):
        batch = to_update[i : i + BATCH]
        execute_values(
            cur,
            """
            update artists as a set
                nationality = coalesce(a.nationality, v.nationality),
                birth_year = coalesce(a.birth_year, v.birth_year),
                death_year = coalesce(a.death_year, v.death_year)
            from (values %s) as v(id, nationality, birth_year, death_year)
            where a.id = v.id::uuid
            """,
            batch,
            template="(%s::uuid, %s, %s::int, %s::int)",
        )
        conn.commit()
        print(f"[backfill_bio] {min(i + BATCH, len(to_update))}/{len(to_update)}건 반영...")

    print(f"[backfill_bio] 완료 — {len(to_update)}건 UPDATE")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
