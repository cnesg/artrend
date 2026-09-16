"""exhibitions.title이 QID 그대로인 행(R4 적재 시 ko/en 라벨이 없던 전시)의 제목을 다른 언어 라벨로 보강.

우선순위: ko > en > de > fr > nl > it > es > ja > 나머지(알파벳순 첫 언어). 라벨이 전혀 없으면 그대로 둔다.
raw는 crawlers/raw/wikidata_exhibition_labels/ 에 배치 단위 저장. 기본 리포트, --apply 시 UPDATE. idempotent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "crawlers"))
from common import already_fetched, save_raw, with_retry  # noqa: E402
from artist_merge_util import get_conn  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
SITE = "wikidata_exhibition_labels"
RAW = Path(__file__).resolve().parent.parent / "crawlers" / "raw" / SITE
SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"}
PREF = ["ko", "en", "de", "fr", "nl", "it", "es", "ja"]
BATCH = 200


def sparql(q: str) -> list[dict]:
    def _do():
        r = requests.get(SPARQL_URL, params={"query": q, "format": "json"}, headers=HEADERS, timeout=120)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", "10")))
            raise RuntimeError("429")
        r.raise_for_status()
        return [{k: v.get("value") for k, v in b.items()} | {"lang": b["l"].get("xml:lang")} for b in r.json()["results"]["bindings"]]
    return with_retry(_do)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("select id, title from exhibitions where title ~ '^Q[0-9]+$'")
    rows = cur.fetchall()
    qids = sorted({t for _, t in rows})
    print(f"QID 제목 전시 {len(rows)}행 / QID {len(qids)}")
    labels: dict[str, dict[str, str]] = defaultdict(dict)
    for i in range(0, len(qids), BATCH):
        b = qids[i:i + BATCH]
        key = f"b{i // BATCH:04d}_" + hashlib.md5("|".join(b).encode()).hexdigest()[:8]
        if not already_fetched(SITE, key):
            q = "SELECT ?e ?l WHERE { VALUES ?e { " + " ".join(f"wd:{x}" for x in b) + " } ?e rdfs:label ?l . }"
            res = sparql(q)
            save_raw(SITE, key, json.dumps(res, ensure_ascii=False), url=SPARQL_URL, license_note="Wikidata CC0 1.0")
            time.sleep(1.0)
        fp = RAW / f"{key}.json"
        for r in json.loads(fp.read_text(encoding="utf-8")):
            labels[r["e"].rsplit("/", 1)[-1]][r["lang"]] = r["l"]
    plan = []
    for eid, q in rows:
        ls = labels.get(q)
        if not ls:
            continue
        lang = next((p for p in PREF if p in ls), sorted(ls)[0])
        plan.append((ls[lang][:500], eid, q, lang))
    print(f"보강 가능 {len(plan)} / 라벨 없음 {len(rows) - len(plan)}")
    for t, _, q, lang in plan[:8]:
        print("  ", q, lang, t[:60])
    if not args.apply:
        print("--apply 없음: 리포트만")
        return
    cur.executemany("update exhibitions set title = %s where id = %s and title = %s", [(t, e, q) for t, e, q, _ in plan])
    conn.commit()
    print("완료:", len(plan))


if __name__ == "__main__":
    main()
