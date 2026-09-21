"""Wikidata 작가 사건 수집 — 수상·사망·전시 참여 (2026-09-15 최신성보강안 R4).

artists.wikidata_qid(M6 backfill)가 붙은 작가를 200개씩 묶어 SPARQL로 조회한다(CC0):
  award       P166 (+ P585 시점, P1027 수여자 라벨)
  death       P570
  exhibition  ?exh wdt:P710 ?artist (참가자) + P31/P279* 전시(Q464980) 또는 P1344(참가한 행사) 역참조,
              P580/P582 기간, P276 장소 라벨, P17 국가 라벨

2026-09-17 재설계(docs/갱신잡_20260917.md 진단 후속, 메인 승인): 저장 단위를 **QID 1개당 파일 1개**로
바꿨다 — `crawlers/raw/wikidata_artist_events/<QID>.json`. 예전엔 200개 묶음을 위치 인덱스로 잘라
배치 해시를 already_fetched 키로 썼는데, artists.wikidata_qid가 계속 늘어나는 중이라 새 QID가 중간에
끼어들 때마다 그 뒤 배치 전체가 밀려 "새 배치"로 오인돼 재수집되는 결함이 있었다(재실행할 때마다 사실상
풀스캔). QID 자체를 키로 쓰면 다른 QID가 몇 개 늘어나도 기존 QID의 already_fetched 여부엔 영향이 없다.
SPARQL 쿼리는 여전히 200개씩 묶어 보내되(왕복 절약), 응답을 QID별로 쪼개 각각 저장한다 — 사건이 0건인
QID도 빈 결과로 저장해 재조회를 막는다. 저장 JSON 스키마(`{"qids":[...], "events":[...],
"exhibitions":[...]}`)는 예전 배치 파일과 동일하게 유지해 `pipeline/wikidata_artist_events.py`가 파일
단위 배치 크기와 무관하게 그대로 동작한다(로더는 glob으로 전체 파일을 읽어 이벤트를 모으므로 수정 불필요,
예전 배치 파일도 삭제하지 않고 같이 읽힘).

`--refresh-days N`: 이미 수집된 QID라도 meta.json의 fetched_at이 N일보다 오래됐으면 다시 대상에 넣는다
(사건은 시간이 지나며 새로 생기므로). 기본값(옵션 없음)은 신규 QID만 — 주간 잡으로 쓰기 적합하고, 월 1회는
`--refresh-days 90` 정도로 오래된 QID도 갱신 권장.

DB 적재는 pipeline/wikidata_artist_events.py. 요청 간 1초 이상, User-Agent 명시, 실패 시 with_retry.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from common import RAW_ROOT, save_raw, with_retry  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
SITE_NAME = "wikidata_artist_events"
SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"}
LICENSE_NOTE = "Wikidata CC0 1.0 (https://www.wikidata.org/wiki/Wikidata:Licensing)"
BATCH = 200


def _is_fresh(qid: str, refresh_days: int | None) -> bool:
    meta_path = RAW_ROOT / SITE_NAME / f"{qid}.meta.json"
    if not meta_path.exists():
        return False
    if refresh_days is None:
        return True
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(meta["fetched_at"])
    except (OSError, ValueError, KeyError):
        return False
    age_days = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 86400
    return age_days < refresh_days

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
    ap.add_argument("--refresh-days", type=int, default=None,
                     help="이미 수집된 QID라도 이 일수보다 오래됐으면 재조회(기본: 신규 QID만)")
    args = ap.parse_args()
    all_qids = load_qids()
    qids = [q for q in all_qids if not _is_fresh(q, args.refresh_days)]
    batches = [qids[i:i + BATCH] for i in range(0, len(qids), BATCH)]
    print(f"[{SITE_NAME}] 전체 QID {len(all_qids)}개 중 대상 {len(qids)}개 → SPARQL 배치 {len(batches)}(저장은 QID 단위)")
    saved = 0
    for bi, b in enumerate(batches[: args.limit] if args.limit else batches):
        values = " ".join(f"wd:{q}" for q in b)
        events = sparql(Q_EVENTS.format(values=values))
        time.sleep(1.2)
        exhs = sparql(Q_EXH.format(values=values))
        time.sleep(1.2)

        events_by_qid: dict[str, list] = {q: [] for q in b}
        exhs_by_qid: dict[str, list] = {q: [] for q in b}
        for e in events:
            q = (e.get("artist") or "").rsplit("/", 1)[-1]
            if q in events_by_qid:
                events_by_qid[q].append(e)
        for x in exhs:
            q = (x.get("artist") or "").rsplit("/", 1)[-1]
            if q in exhs_by_qid:
                exhs_by_qid[q].append(x)

        for q in b:
            save_raw(SITE_NAME, q,
                     json.dumps({"qids": [q], "events": events_by_qid[q], "exhibitions": exhs_by_qid[q]}, ensure_ascii=False),
                     url=SPARQL_URL, license_note=LICENSE_NOTE)
            saved += 1
        if (bi + 1) % 10 == 0:
            print(f"  배치 {bi + 1}/{len(batches)} 완료 (QID {saved}개 저장, events {len(events)}, exh {len(exhs)})")
    print(f"완료: QID {saved}개 저장(대상 {len(qids)}개 중), 스킵(이미 신선함) {len(all_qids) - len(qids)}개")


if __name__ == "__main__":
    main()
