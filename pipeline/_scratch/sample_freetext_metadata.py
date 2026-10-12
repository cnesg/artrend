"""aic/smithsonian 자유텍스트 파싱 정확도 샘플 검증용(DB 변경 없음).

원본 텍스트와 파싱 결과를 나란히 출력 — 사람이 눈으로 오탐률을 추정하기 위함.
전체 적용 스크립트(backfill_freetext_metadata.py)는 이 샘플 검토 승인 후 실행.
"""
from __future__ import annotations

import os
import random
import sys

import psycopg2

from freetext_metadata import parse_aic_display, parse_smithsonian_name
from raw_iter import RAW_ROOT

sys.stdout.reconfigure(encoding="utf-8")


def sample_smithsonian(n: int) -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute(
        "select name from artists where name ~* 'born' and (birth_year is null or death_year is null) "
        "order by random() limit %s",
        (n,),
    )
    rows = cur.fetchall()
    print(f"\n=== Smithsonian 샘플 {len(rows)}건 ===")
    for (name,) in rows:
        nat, birth, death = parse_smithsonian_name(name)
        print(f"  name={name!r}\n    -> nationality={nat!r} birth={birth!r} death={death!r}")
    cur.close()
    conn.close()


def sample_aic(n: int) -> None:
    import json

    aic_dir = RAW_ROOT / "aic"
    files = [p for p in aic_dir.glob("*.json") if not p.name.endswith(".meta.json")]
    random.seed(42)
    sample = random.sample(files, min(n, len(files)))
    print(f"\n=== AIC 샘플 {len(sample)}건 ===")
    for path in sample:
        data = json.loads(path.read_text(encoding="utf-8"))
        display = data.get("artist_display")
        if not display:
            continue
        nat, birth, death = parse_aic_display(display)
        print(f"  artist_display={display!r}")
        print(f"    -> nationality={nat!r} birth={birth!r} death={death!r}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    sample_smithsonian(n)
    sample_aic(n)
