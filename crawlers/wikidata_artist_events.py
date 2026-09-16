"""Wikidata 작가 사건 수집 — 수상·사망·전시 참여 (2026-09-15 최신성보강안 R4).

artists.wikidata_qid(M6 backfill)가 붙은 작가를 200개씩 묶어 SPARQL로 다음을 받는다(CC0):
  award       P166 (+ P585 시점, P1027 수여자 라벨)
  death       P570
  exhibition  ?exh wdt:P710 ?artist (참가자) + P31/P279* 전시(Q464980) 또는 P1344(참가한 행사) 역참조,
              P580/P582 기간, P276 장소 라벨, P17 국가 라벨
저장: crawlers/raw/wikidata_artist_events/<batch_key>.json (save_raw, 이미 있으면 스킵). DB 적재는
pipeline/wikidata_artist_events.py. 요청 간 1초 이상, User-Agent 명시, 실패 시 with_retry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from common import already_fetched, save_raw, with_retry  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
SITE_NAME = "wikidata_artist_events"
SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"}
LICENSE_NOTE = "Wikidata CC0 1.0 (https://www.wikidata.org/wiki/Wikidata:Licensing)"
BATCH = 200

Q_EVENTS = """
SELECT ?artist ?kind ?date ?label ?extra ?url WHERE {{
  VALUES ?artist {{ {values} }}
  {{
    ?artist p:P166 ?st . ?st ps:P166 ?award .
    OPTIONAL {{ ?st pq:P585 ?date . }}
    OPTIONAL {{ ?st pq:P1027 ?by . ?by rdfs:label ?extra FILTER(LANG(?extra) IN ("en","ko")) }}
    ?award rdfs:label ?label FILTER(LANG(?label) IN ("en","ko"))
    BIND("award" AS ?kind) BIND(?award AS ?url)
  }} UNION {{
    ?artist wdt:P570 ?date . BIND("death" AS ?kind) BIND("" AS ?label) BIND("" AS ?extra) BIND(?artist AS ?url)
  }}
}}
"""

Q_EXH = """
SELECT ?artist ?exh ?exhLabel ?start ?end ?placeLabel ?countryLabel WHERE {{
  VALUES ?artist {{ {values} }}
  {{ ?exh wdt:P710 ?artist . }} UNION {{ ?artist wdt:P1344 ?exh . }}
  ?exh wdt:P31/wdt:P279* wd:Q464980 .
  OPTIONAL {{ ?exh wdt:P580 ?start . }}
  OPTIONAL {{ ?exh wdt:P582 ?end . }}
  OPTIONAL {{ ?exh wdt:P276 ?place . }}
  OPTIONAL {{ ?exh wdt:P17 ?country . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ko,en". }}
}}
"""


def sparql(query: str) -> list[dict]:
    def _do():
        r = requests.get(SPARQL_URL, params={"query": query, "format": "json"}, headers=HEADERS, timeout=120)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", "10")))
            raise RuntimeError("429")
        r.raise_for_status()
        return [{k: v.get("value") for k, v in b.items()} for b in r.json()["results"]["bindings"]]
    return with_retry(_do)


def load_qids() -> list[str]:
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / "pipeline" / ".env")
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("select distinct wikidata_qid from artists where entity_kind = 'person' and wikidata_qid ~ '^Q[0-9]+$' order by 1")
    return [r[0] for r in cur.fetchall()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="배치 수 제한(테스트)")
    args = ap.parse_args()
    qids = load_qids()
    batches = [qids[i:i + BATCH] for i in range(0, len(qids), BATCH)]
    print(f"[{SITE_NAME}] QID {len(qids)}개 → 배치 {len(batches)}")
    done = skipped = 0
    for bi, b in enumerate(batches[: args.limit] if args.limit else batches):
        key = f"b{bi:04d}_" + hashlib.md5(",".join(b).encode()).hexdigest()[:8]
        if already_fetched(SITE_NAME, key):
            skipped += 1
            continue
        values = " ".join(f"wd:{q}" for q in b)
        events = sparql(Q_EVENTS.format(values=values))
        time.sleep(1.2)
        exhs = sparql(Q_EXH.format(values=values))
        time.sleep(1.2)
        save_raw(SITE_NAME, key, json.dumps({"qids": b, "events": events, "exhibitions": exhs}, ensure_ascii=False),
                 url=SPARQL_URL, license_note=LICENSE_NOTE)
        done += 1
        if done % 10 == 0:
            print(f"  배치 {bi + 1}/{len(batches)} 저장 (events {len(events)}, exh {len(exhs)})")
    print(f"완료: 저장 {done}, 스킵 {skipped}")


if __name__ == "__main__":
    main()
