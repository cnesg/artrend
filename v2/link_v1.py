"""v2 작가 -> v1(artrend) 작가 소프트 링크. v1은 읽기만 한다.

    python v2/link_v1.py            # 리포트만
    python v2/link_v1.py --apply    # artists.v1_artist_id (+ 비어 있으면 wikidata_qid) 채움

매칭: v2 작가의 별칭 키(이름·한글명·영문명 정규화) 중 하나가 v1 artists.name / name_en 의 정규화 값과
정확일치, v1 entity_kind in (person, organization). 유사도 매칭 없음.
동명이인 방어: 후보가 여럿이면 wikidata_qid 있는 쪽 > person > 먼저 생긴 쪽. 양쪽에 출생연도가 있는데
2년 넘게 다르면 버리고, v2 출생연도가 없을 때 v1 후보가 1850년 이전 출생이면(고미술 동명이인 위험) 버린다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import psycopg2

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA_ROOT, alias_key, get_conn  # noqa: E402

V1_DSN = os.environ.get("V1_DATABASE_URL") or "postgresql://postgres@127.0.0.1:5433/artrend"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    v1 = psycopg2.connect(V1_DSN, connect_timeout=10)
    v1.set_session(readonly=True)
    c1 = v1.cursor()
    # birth_year 0은 원천(MoMA 등) 관례상 '미상' — None으로 봐야 고미술 동명이인 필터에 잘못 걸리지 않는다
    c1.execute("select id, name, name_en, entity_kind, wikidata_qid, nullif(birth_year, 0), created_at from artists "
               "where entity_kind in ('person','organization')")
    idx = defaultdict(list)
    for row in c1.fetchall():
        for n in {row[1], row[2]}:
            k = alias_key(n)
            if k:
                idx[k].append(row)
    v1.close()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("select a.id, a.birth_year, a.wikidata_qid, array_agg(al.alias_key) from artists a "
                "join artist_aliases al on al.artist_id = a.id group by a.id")
    st = Counter()
    samples = defaultdict(list)
    updates = []
    for aid, by, qid, keys in cur.fetchall():
        cands = {}
        for k in keys:
            for row in idx.get(k, []):
                cands[str(row[0])] = row
        if not cands:
            st["no_match"] += 1
            continue
        rows = [r for r in cands.values()
                if not (by and r[5] and abs(by - r[5]) > 2)
                and not (not by and r[5] and r[5] < 1850)]
        if not rows:
            st["rejected_birth_year"] += 1
            samples["rejected_birth_year"].append([keys[0], [(r[1], r[5]) for r in cands.values()][:3]])
            continue
        rows.sort(key=lambda r: (r[4] is None, r[3] != "person", r[6]))
        best = rows[0]
        st["linked_multi" if len(rows) > 1 else "linked"] += 1
        if len(rows) > 1:
            samples["linked_multi"].append([keys[0], [(r[1], r[4]) for r in rows][:4]])
        updates.append((str(best[0]), best[4] if not qid else None, str(aid)))

    print(dict(st))
    if args.apply:
        # 출생연도 보강 뒤엔 예전 링크가 동명이인으로 판정될 수 있어, 링크는 매번 처음부터 다시 정한다
        cur.execute("update artists set v1_artist_id = null where v1_artist_id is not null")
        for v1_id, new_qid, aid in updates:
            cur.execute("update artists set v1_artist_id = %s, wikidata_qid = coalesce(wikidata_qid, %s) where id = %s",
                        (v1_id, new_qid, aid))
        conn.commit()
        print("applied", len(updates))
    out = DATA_ROOT / "logs" / f"link_v1_{'apply' if args.apply else 'report'}_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({"stats": st, "samples": {k: v[:50] for k, v in samples.items()}},
                              ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("report ->", out)


if __name__ == "__main__":
    main()
