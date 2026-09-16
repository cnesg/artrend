"""docs/철자변형_대형클러스터_잔여.json(여전히 대형(>10건)이라 자동 병합 보류한
10개 클러스터)를 백필된 nationality/birth_year로 재검토 — 읽기 전용, 병합 없음.

각 클러스터의 keep + candidates 전부에 대해 현재 DB의 nationality/birth_year/
death_year를 조회해서 출력한다. 메타데이터로 명확히 갈리는 서브그룹이 보이면
사람이 이어서 판단할 수 있게 그 부분만 표시하고, 애매하면(메타데이터 없음/
비슷함) 그대로 둔다는 걸 알 수 있게 전체를 보여준다.
"""
from __future__ import annotations

import json
import os
import sys

import psycopg2

sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
    with open(os.path.join(docs_dir, "철자변형_대형클러스터_잔여.json"), encoding="utf-8") as f:
        clusters = json.load(f)

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    for cluster in clusters:
        all_ids = [cluster["keep_id"]] + [c["id"] for c in cluster["candidates"]]
        cur.execute(
            "select id, name, nationality, birth_year, death_year from artists where id = any(%s::uuid[])",
            (all_ids,),
        )
        meta = {str(r[0]): r for r in cur.fetchall()}

        print(f"\n=== keep: {cluster['keep_name']!r} (id={cluster['keep_id']}) ===")
        keep_row = meta.get(cluster["keep_id"])
        if keep_row:
            _, name, nat, by, dy = keep_row
            print(f"  [keep] {name!r} nat={nat!r} birth={by} death={dy}")

        for c in sorted(cluster["candidates"], key=lambda x: -x["richness"]):
            row = meta.get(c["id"])
            if row:
                _, name, nat, by, dy = row
                print(f"    {name!r} (r={c['richness']}) nat={nat!r} birth={by} death={dy}")
            else:
                print(f"    {c['name']!r} (r={c['richness']}) [DB에서 못 찾음]")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
