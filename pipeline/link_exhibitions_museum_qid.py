"""Wikidata 전시(exhibitions.url = wikidata entity) 의 장소(P276) QID를 museums.wikidata_qid 와 맞춰 museum_id 연결 (2026-09-15, R4 후속).

R4 적재 시 장소는 라벨(ko/en)만 저장해 미술관 이름 매칭이 거의 안 됐다. 0011로 museums에 QID가 붙었으므로
전시 QID → P276 장소 QID 를 다시 조회해(라벨 언어 무관) QID 동일할 때만 연결한다. 추정 없음.
장소가 미술관 QID의 일부(P361/P527, 예: 분관)인 경우는 다루지 않음.
raw: crawlers/raw/wikidata_exhibition_places/<batch>.json
--fetch : SPARQL   기본: 리포트   --apply: exhibitions.museum_id/venue_kind 갱신(museum_id NULL 인 행만). idempotent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "crawlers"))
from common import already_fetched, save_raw, with_retry  # noqa: E402
from artist_merge_util import get_conn  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
SITE = "wikidata_exhibition_places"
RAW = Path(__file__).resolve().parent.parent / "crawlers" / "raw" / SITE
SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"}
LICENSE_NOTE = "Wikidata CC0 1.0 (https://www.wikidata.org/wiki/Wikidata:Licensing)"
BATCH = 200
QUERY = """
SELECT ?exh ?place WHERE {{
  VALUES ?exh {{ {values} }}
  ?exh wdt:P276 ?place .
}}
"""


def sparql(q: str) -> list[dict]:
    def _do():
        r = requests.post(SPARQL_URL, data={"query": q, "format": "json"}, headers=HEADERS, timeout=180)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", "10")))
            raise RuntimeError("429")
        r.raise_for_status()
        return [{k: v.get("value") for k, v in b.items()} for b in r.json()["results"]["bindings"]]
    return with_retry(_do)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("select id::text, url, venue_name from exhibitions where museum_id is null and url like 'http://www.wikidata.org/entity/Q%'")
    rows = cur.fetchall()
    qids = sorted({u.rsplit("/", 1)[-1] for _, u, _ in rows})
    if args.fetch:
        batches = [qids[i:i + BATCH] for i in range(0, len(qids), BATCH)]
        print(f"[{SITE}] 전시 QID {len(qids)} → 배치 {len(batches)}")
        for bi, b in enumerate(batches):
            key = f"b{bi:04d}_" + hashlib.md5("|".join(b).encode()).hexdigest()[:8]
            if already_fetched(SITE, key):
                continue
            res = sparql(QUERY.format(values=" ".join(f"wd:{q}" for q in b)))
            save_raw(SITE, key, json.dumps({"qids": b, "rows": res}, ensure_ascii=False), url=SPARQL_URL, license_note=LICENSE_NOTE)
            print(f"  배치 {bi + 1}/{len(batches)} 저장 (rows {len(res)})", flush=True)
            time.sleep(1.0)
        return

    places: dict[str, set[str]] = defaultdict(set)
    for fp in RAW.glob("*.json"):
        if fp.name.endswith(".meta.json"):
            continue
        for r in json.load(open(fp, encoding="utf-8"))["rows"]:
            places[r["exh"].rsplit("/", 1)[-1]].add(r["place"].rsplit("/", 1)[-1])
    cur.execute("select wikidata_qid, id::text, name from museums where wikidata_qid is not null")
    mus = {q: (i, n) for q, i, n in cur.fetchall()}
    stats, plan = Counter(), []
    for eid, url, venue in rows:
        q = url.rsplit("/", 1)[-1]
        hits = [p for p in places.get(q, ()) if p in mus]
        if not places.get(q):
            stats["no-place"] += 1
        elif not hits:
            stats["place-not-in-museums"] += 1
        elif len(hits) > 1:
            stats["multi"] += 1
        else:
            plan.append((mus[hits[0]][0], eid))
            stats[f"linked:{mus[hits[0]][1]}"] += 1
    linked = sum(v for k, v in stats.items() if k.startswith("linked:"))
    print(f"대상 {len(rows)} → 연결 {linked} / 장소없음 {stats['no-place']} / 장소가 museums에 없음 {stats['place-not-in-museums']} / 다중 {stats['multi']}")
    print("  미술관별:", sorted(((k[7:], v) for k, v in stats.items() if k.startswith("linked:")), key=lambda x: -x[1])[:30])
    if not args.apply:
        print("--apply 없음: 리포트만")
        return
    cur.executemany("update exhibitions set museum_id = %s, venue_kind = 'museum' where id = %s and museum_id is null", plan)
    conn.commit()
    cur.execute("select venue_kind, count(*), count(museum_id) from exhibitions group by 1")
    print("완료:", cur.fetchall())


if __name__ == "__main__":
    main()
