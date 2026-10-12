"""artists.bio 컬럼(met/cleveland/aic 등에서 이미 채워둔 자유텍스트)에서
nationality/birth_year/death_year 파싱 정확도 샘플 검증(DB 변경 없음)."""
from __future__ import annotations

import os
import sys

import psycopg2

from freetext_metadata import parse_bio_text

sys.stdout.reconfigure(encoding="utf-8")


def main(n: int) -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute(
        "select name, bio from artists where bio is not null and length(bio) > 0 "
        "and (nationality is null or birth_year is null) order by random() limit %s",
        (n,),
    )
    rows = cur.fetchall()
    print(f"=== bio 샘플 {len(rows)}건 ===")
    for name, bio in rows:
        nat, birth, death = parse_bio_text(name, bio)
        print(f"  name={name!r} bio={bio!r}\n    -> nationality={nat!r} birth={birth!r} death={death!r}")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 80)
