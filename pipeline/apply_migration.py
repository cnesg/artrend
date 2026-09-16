"""db/migrations/<file>.sql 을 현재 DATABASE_URL에 적용한다 (idempotent SQL만 넣을 것).

사용: python pipeline/apply_migration.py 0007_artists_entity_kind.sql
"""
from __future__ import annotations

import sys
from pathlib import Path

from artist_merge_util import get_conn

sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    name = sys.argv[1]
    path = Path(__file__).resolve().parent.parent / "db" / "migrations" / name
    sql = path.read_text(encoding="utf-8")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql)
    conn.commit()
    print("applied:", path.name)


if __name__ == "__main__":
    main()
