"""작가 약력 결손을 위키백과/Wikidata 설명으로 백필 (2026-09-17 깊이 보강, 메인 소유 artists).

LLM 생성이 아니라 **출처가 명확한 외부 인용**이다: Wikidata QID → 위키백과(ko 우선, 없으면 en) 개요
문단(REST summary API의 extract), 없으면 Wikidata 설명(ko/en). 저장 시 artists.bio + artists.bio_source
(출처 URL)에 남겨 artgraph_chat이 근거를 인용하게 한다. CC-BY-SA(위키백과)·CC0(Wikidata)를 note로 기록.

대상(기본): entity_kind='person' + wikidata_qid 보유 + bio 결손 + 한국 작가(국적 Korean 또는 한글 이름).
  --all-person : 한국 한정 없이 QID 보유·약력 결손 person 전체
  --limit N    : 상위 N명만(소장 많은 순)
기본 리포트(표본), --apply로 반영. idempotent: 약력 있는 행은 건드리지 않고, 응답은 already_fetched 캐시.
규칙: 결손 채움은 authority(QID) 매칭으로만 — 문자열 추측·LLM 생성 금지([[project_rediagnosis_20260915]]).

성능(2026-09-21): 원래는 (1) Wikidata를 QID 1개씩 조회 (2) 완전 순차 실행이라 21,620명에 8~12시간이
걸렸다. wbgetentities는 QID를 파이프(|)로 최대 50개까지 한 번에 받으므로 Wikidata 조회는 배치로 묶고,
위키백과 REST summary(배치 불가)는 스레드풀로 동시 조회해 수십 분대로 단축했다.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import threading
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import get_connection  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "crawlers"))
from common import already_fetched, save_raw, with_retry  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

SITE = "wikipedia_artist_bio"
UA = {"User-Agent": "ArtrendBot/1.0 (artgraph bio backfill; contact artgraph@artrend.com)"}
WD_ENTITY = "https://www.wikidata.org/w/api.php"
MIN_BIO_LEN = 40  # 이보다 짧으면(한 줄 설명 수준) 약력으로 안 침, bio_source만으로도 부실
WD_BATCH_SIZE = 50  # wbgetentities가 허용하는 ids 최대 개수
EXTRACT_WORKERS = 6  # 위키백과 REST summary 동시 요청 수(예의상 과하지 않게)
RAW_DIR = Path(__file__).resolve().parent.parent / "crawlers" / "raw" / SITE


def prefetch_wikidata_batch(qids: list[str]) -> None:
    """QID들을 50개씩 묶어 wbgetentities 한 번으로 조회, 개별 QID 캐시 파일로 쪼개 저장.

    fetch_qid()의 캐시 포맷({"entities": {qid: {...}}})과 동일하게 저장해서, 이후 fetch_qid() 호출은
    전부 로컬 캐시 히트가 되고 네트워크 호출이 없어진다.
    """
    missing = [q for q in dict.fromkeys(qids) if not already_fetched(SITE, f"wd_{q}")]
    if not missing:
        print("Wikidata: 전부 캐시됨, 배치 조회 스킵")
        return
    print(f"Wikidata 배치 조회: 신규 {len(missing)}건 (배치당 {WD_BATCH_SIZE}개)")
    for i in range(0, len(missing), WD_BATCH_SIZE):
        batch = missing[i:i + WD_BATCH_SIZE]
        ids_param = "|".join(batch)

        def _go():
            r = requests.get(WD_ENTITY, params={
                "action": "wbgetentities", "ids": ids_param,
                "props": "sitelinks|descriptions", "format": "json",
            }, headers=UA, timeout=30)
            r.raise_for_status()
            return r.json()

        data = with_retry(_go)
        entities = data.get("entities", {})
        for q in batch:
            ent = entities.get(q, {})
            save_raw(SITE, f"wd_{q}", json.dumps({"entities": {q: ent}}, ensure_ascii=False),
                     url=f"{WD_ENTITY}?action=wbgetentities&ids={ids_param}", license_note="Wikidata CC0 1.0")
        time.sleep(0.3)
        done = i + len(batch)
        if (i // WD_BATCH_SIZE) % 10 == 0 or done >= len(missing):
            print(f"  ...Wikidata {done}/{len(missing)} 배치 완료")


def fetch_qid(qid: str) -> dict:
    """Wikidata sitelinks+descriptions — prefetch_wikidata_batch()가 이미 캐시를 채워둔 걸 읽기만 한다.

    (배치 프리페치 전에 단독으로 불리는 경로도 남겨둠: 캐시 미스면 그때만 개별 조회로 폴백.)
    """
    if not already_fetched(SITE, f"wd_{qid}"):
        def _go():
            r = requests.get(WD_ENTITY, params={
                "action": "wbgetentities", "ids": qid,
                "props": "sitelinks|descriptions", "format": "json",
            }, headers=UA, timeout=30)
            r.raise_for_status()
            return r.json()
        data = with_retry(_go)
        save_raw(SITE, f"wd_{qid}", json.dumps(data, ensure_ascii=False),
                 url=f"{WD_ENTITY}?action=wbgetentities&ids={qid}", license_note="Wikidata CC0 1.0")
        time.sleep(0.4)
    return json.load(open(RAW_DIR / f"wd_{qid}.json", encoding="utf-8"))


def fetch_extract(lang: str, title: str, qid: str) -> str | None:
    """위키백과 REST summary의 개요 문단, raw 캐시. 스레드풀에서 동시 호출됨."""
    key = f"wp_{qid}_{lang}"
    if not already_fetched(SITE, key):
        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/" + requests.utils.quote(title.replace(" ", "_"), safe="")
        def _go():
            r = requests.get(url, headers=UA, timeout=30)
            if r.status_code == 404:
                return {"extract": None}
            r.raise_for_status()
            return r.json()
        data = with_retry(_go)
        save_raw(SITE, key, json.dumps(data, ensure_ascii=False), url=url,
                 license_note="Wikipedia CC-BY-SA 4.0")
        time.sleep(0.4)
    data = json.load(open(RAW_DIR / f"{key}.json", encoding="utf-8"))
    return data.get("extract")


def resolve_bio(qid: str) -> tuple[str, str] | None:
    """(bio, source_url) 반환. ko 위키백과 → en 위키백과 → Wikidata 설명 순."""
    wd = fetch_qid(qid)
    ent = wd.get("entities", {}).get(qid, {})
    sitelinks = ent.get("sitelinks", {})
    for lang in ("ko", "en"):
        sl = sitelinks.get(f"{lang}wiki")
        if sl:
            title = sl["title"]
            ext = fetch_extract(lang, title, qid)
            if ext and len(ext) >= MIN_BIO_LEN:
                return ext.strip(), f"https://{lang}.wikipedia.org/wiki/" + title.replace(" ", "_")
    # 폴백: Wikidata 설명(짧음)
    descs = ent.get("descriptions", {})
    for lang in ("ko", "en"):
        d = descs.get(lang, {}).get("value")
        if d:
            return d.strip(), f"https://www.wikidata.org/wiki/{qid}"
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--all-person", action="store_true", help="한국 한정 해제")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sample", type=int, default=8)
    ap.add_argument("--workers", type=int, default=EXTRACT_WORKERS, help="위키백과 조회 동시 스레드 수")
    args = ap.parse_args()
    conn = get_connection()
    cur = conn.cursor()

    where = ["entity_kind='person'", "wikidata_qid is not null", "(bio is null or bio='')"]
    if not args.all_person:
        where.append(r"(nationality ilike '%%korea%%' or nationality='한국' or name ~ '[가-힣]')")
    sql = ("select a.id::text, a.name, a.wikidata_qid, coalesce(h.cnt, 0) as h "
           "from artists a "
           "left join (select aw.artist_id, count(*) cnt from artworks aw "
           "join museum_holdings mh on mh.artwork_id=aw.id group by aw.artist_id) h on h.artist_id=a.id "
           "where " + " and ".join(where) + " order by h desc")
    if args.limit:
        sql += f" limit {args.limit}"
    cur.execute(sql)
    targets = cur.fetchall()
    print(f"대상 {len(targets)}명 (약력 결손·QID 보유{'' if args.all_person else '·한국'})")

    prefetch_wikidata_batch([qid for _, _, qid, _ in targets])

    print(f"위키백과 개요 조회 중 (동시 {args.workers}개)...")
    counter_lock = threading.Lock()
    done = 0

    def worker(t):
        nonlocal done
        aid, name, qid, h = t
        r = resolve_bio(qid)
        with counter_lock:
            done += 1
            if done % 500 == 0:
                print(f"  ...{done}/{len(targets)} 조회")
        return aid, name, qid, r

    resolved = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        resolved = list(ex.map(worker, targets))

    plan, filled, empty = [], [], 0
    for aid, name, qid, r in resolved:
        if r:
            plan.append((aid, name, qid, r[0], r[1]))
            filled.append((name, len(r[0]), r[1]))
        else:
            empty += 1
    print(f"약력 확보 {len(plan)} / 위키 없음 {empty}")
    import random
    random.seed(1)
    for name, blen, src in random.sample(filled, min(args.sample, len(filled))):
        print(f"  {name} ({blen}자) ← {src}")

    if not args.apply:
        print("--apply 없음: 리포트만")
        return
    for i in range(0, len(plan), 500):
        cur.executemany(
            "update artists set bio=%s, bio_source=%s, updated_at=now() where id=%s and (bio is null or bio='')",
            [(b, s, aid) for aid, _, _, b, s in plan[i:i + 500]],
        )
        conn.commit()
    print(f"완료: 약력 백필 {len(plan)}건 (bio_source 기록)")


if __name__ == "__main__":
    main()
