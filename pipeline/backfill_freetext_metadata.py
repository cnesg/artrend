"""aic(raw artist_display) + smithsonian(DB name 컬럼 자체)에서 nationality/
birth_year/death_year 백필. 사전 샘플 검증(60+80건, 오탐 0건 확인, artrend-3a
승인 완료) 범위만 적용 — bio 컬럼 전체로의 확장은 별도(cleveland 등 장문 서술형
bio 섞여있어 오탐 위험 있음 확인, 이번엔 미포함, 보고만 함).

기본은 dry-run. --apply로 실제 반영, coalesce라 기존 값은 안 건드림.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import psycopg2
from psycopg2.extras import execute_values

from freetext_metadata import parse_aic_display, parse_smithsonian_name
from raw_iter import RAW_ROOT

sys.stdout.reconfigure(encoding="utf-8")


def collect_aic() -> dict[str, dict]:
    out: dict[str, dict] = {}
    aic_dir = RAW_ROOT / "aic"
    for path in aic_dir.glob("*.json"):
        if path.name.endswith(".meta.json"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        artist_name = (data.get("artist_title") or "").strip()
        if not artist_name:
            continue
        key = artist_name.lower()
        if key in out:
            continue
        nat, birth, death = parse_aic_display(data.get("artist_display") or "")
        if nat or birth or death:
            out[key] = {"nationality": nat, "birth_year": birth, "death_year": death}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    print("[backfill2] aic raw 파싱 중...")
    aic_map = collect_aic()
    print(f"[backfill2] aic: 메타데이터 있는 고유 작가명 {len(aic_map)}명")

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    cur.execute("select id, name, nationality, birth_year, death_year from artists")
    db_rows = cur.fetchall()
    print(f"[backfill2] DB artists 전체 {len(db_rows)}건 로드")

    to_update = []
    filled_nat = filled_birth = filled_death = 0
    smithsonian_hits = aic_hits = 0

    for aid, name, nationality, birth_year, death_year in db_rows:
        if nationality is not None and birth_year is not None and death_year is not None:
            continue

        info = None
        if "born" in name.lower():
            nat, birth, death = parse_smithsonian_name(name)
            if nat or birth or death:
                info = {"nationality": nat, "birth_year": birth, "death_year": death}
                smithsonian_hits += 1
        if info is None:
            aic_info = aic_map.get(name.lower())
            if aic_info:
                info = aic_info
                aic_hits += 1

        if not info:
            continue

        new_nat = nationality if nationality is not None else info["nationality"]
        new_birth = birth_year if birth_year is not None else info["birth_year"]
        new_death = death_year if death_year is not None else info["death_year"]
        if new_nat == nationality and new_birth == birth_year and new_death == death_year:
            continue

        if nationality is None and new_nat is not None:
            filled_nat += 1
        if birth_year is None and new_birth is not None:
            filled_birth += 1
        if death_year is None and new_death is not None:
            filled_death += 1
        to_update.append((str(aid), new_nat, new_birth, new_death))

    print(f"[backfill2] smithsonian 패턴 매치: {smithsonian_hits}건, aic 매치: {aic_hits}건")
    print(f"[backfill2] 백필 가능 추정: nationality {filled_nat}건, birth_year {filled_birth}건, death_year {filled_death}건")
    print(f"[backfill2] UPDATE 대상 artists 행: {len(to_update)}건")

    if not args.apply:
        print("[backfill2] dry-run — DB 변경 없음. --apply로 실행하면 실제 반영됩니다.")
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
        print(f"[backfill2] {min(i + BATCH, len(to_update))}/{len(to_update)}건 반영...")

    print(f"[backfill2] 완료 — {len(to_update)}건 UPDATE")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
