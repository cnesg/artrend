"""authority(wikidata_qid 또는 ulan_id)가 있는 person 작가의 생년/몰년/국적/영문명 결손을 Wikidata로 채움 (계획 P2-13).

LLM 없음. QID가 있으면 QID로, ULAN만 있으면 P245(ULAN) 역조회로 QID를 먼저 얻는다(유일 매칭만).
국적은 P27 국가의 한국어 라벨(없으면 영어). 값은 비어 있을 때만 채움(coalesce). raw는 crawlers/raw/wikidata_artist_meta/.
--fetch : SPARQL 수집(배치 200, 이미 저장된 배치 스킵)   기본: 리포트   --apply: UPDATE. idempotent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "crawlers"))
from common import already_fetched, save_raw, with_retry  # noqa: E402
from artist_merge_util import get_conn  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
SITE = "wikidata_artist_meta"
RAW = Path(__file__).resolve().parent.parent / "crawlers" / "raw" / SITE
SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"}
LICENSE_NOTE = "Wikidata CC0 1.0 (https://www.wikidata.org/wiki/Wikidata:Licensing)"
BATCH = 200

# Wikidata P27 한국어 라벨(역사 국가 포함) → 기존 artists.nationality 관행(영문 demonym). 미매핑은 채우지 않음.
NAT_MAP = {
    "미국": "American", "프랑스": "French", "프랑스 왕국": "French", "독일": "German", "독일국": "German", "독일 제국": "German",
    "프로이센 왕국": "German", "바이에른 왕국": "German", "작센 왕국": "German", "바덴 대공국": "German", "뷔르템베르크 왕국": "German",
    "헤센 대공국": "German", "함부르크": "German", "동독": "German", "신성 로마 제국": "German",
    "영국": "British", "그레이트브리튼 아일랜드 연합왕국": "British", "그레이트브리튼 왕국": "British", "잉글랜드 왕국": "English",
    "잉글랜드": "English", "스코틀랜드": "Scottish", "아일랜드": "Irish", "아일랜드 왕국": "Irish",
    "네덜란드 왕국": "Dutch", "네덜란드 공화국": "Dutch", "네덜란드": "Dutch", "합스부르크 네덜란드": "Netherlandish",
    "스페인령 네덜란드": "Flemish", "플란데런 백국": "Flemish", "벨기에": "Belgian",
    "스페인": "Spanish", "아라곤 연합왕국": "Spanish", "포르투갈": "Portuguese", "포르투갈 왕국": "Portuguese",
    "이탈리아": "Italian", "이탈리아 왕국": "Italian", "베네치아 공화국": "Italian", "교황령": "Italian", "토스카나 대공국": "Italian",
    "피렌체 공화국": "Italian", "나폴리 왕국": "Italian", "밀라노 공국": "Italian", "제노바 공화국": "Italian",
    "오스트리아": "Austrian", "오스트리아 제국": "Austrian", "오스트리아-헝가리 제국": "Austrian", "시스라이타니아": "Austrian",
    "합스부르크 제국": "Austrian", "헝가리": "Hungarian", "체코": "Czech", "체코슬로바키아": "Czech",
    "스위스": "Swiss", "제네바 공화국": "Swiss", "폴란드": "Polish", "폴란드-리투아니아": "Polish", "폴란드 제2공화국": "Polish",
    "폴란드 입헌왕국": "Polish", "러시아": "Russian", "러시아 제국": "Russian", "소련": "Russian",
    "노르웨이": "Norwegian", "스웨덴": "Swedish", "덴마크 왕국": "Danish", "핀란드": "Finnish", "그리스": "Greek", "루마니아": "Romanian",
    "오스트레일리아": "Australian", "뉴질랜드": "New Zealander", "캐나다": "Canadian", "남아프리카 공화국": "South African",
    "일본": "Japanese", "에도 막부": "Japanese", "대한민국": "Korean", "조선": "Korean", "중화인민공화국": "Chinese", "중화민국": "Chinese",
    "청나라": "Chinese", "명나라": "Chinese", "송나라": "Chinese", "원나라": "Chinese", "인도": "Indian", "무굴 제국": "Indian",
    "이스라엘": "Israeli", "멕시코": "Mexican", "브라질": "Brazilian", "아르헨티나": "Argentine", "칠레": "Chilean", "베네수엘라": "Venezuelan",
    "쿠바": "Cuban", "콜롬비아": "Colombian", "우루과이": "Uruguayan", "아이티": "Haitian", "고대 아테네": "Greek",
}

Q_BY_QID = """
SELECT ?item ?ulan ?en ?born ?died (GROUP_CONCAT(DISTINCT ?cl; separator="|") AS ?nat) WHERE {{
  VALUES ?item {{ {values} }}
  OPTIONAL {{ ?item wdt:P245 ?ulan }}
  OPTIONAL {{ ?item rdfs:label ?en FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item wdt:P569 ?born }}
  OPTIONAL {{ ?item wdt:P570 ?died }}
  OPTIONAL {{ ?item wdt:P27 ?c . ?c rdfs:label ?cl FILTER(LANG(?cl) = "ko") }}
}} GROUP BY ?item ?ulan ?en ?born ?died
"""
Q_BY_ULAN = """
SELECT ?item ?ulan ?en ?born ?died (GROUP_CONCAT(DISTINCT ?cl; separator="|") AS ?nat) WHERE {{
  VALUES ?ulan {{ {values} }}
  ?item wdt:P245 ?ulan . ?item wdt:P31 wd:Q5 .
  OPTIONAL {{ ?item rdfs:label ?en FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item wdt:P569 ?born }}
  OPTIONAL {{ ?item wdt:P570 ?died }}
  OPTIONAL {{ ?item wdt:P27 ?c . ?c rdfs:label ?cl FILTER(LANG(?cl) = "ko") }}
}} GROUP BY ?item ?ulan ?en ?born ?died
"""


def sparql(q: str) -> list[dict]:
    def _do():
        r = requests.get(SPARQL_URL, params={"query": q, "format": "json"}, headers=HEADERS, timeout=180)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", "10")))
            raise RuntimeError("429")
        r.raise_for_status()
        return [{k: v.get("value") for k, v in b.items()} for b in r.json()["results"]["bindings"]]
    return with_retry(_do)


def targets(cur):
    cur.execute("""select id::text, wikidata_qid, ulan_id, birth_year, death_year, nationality, name_en from artists
                   where entity_kind = 'person' and (wikidata_qid is not null or ulan_id is not null)
                     and (birth_year is null or death_year is null or nationality is null or name_en is null)""")
    return cur.fetchall()


def fetch(rows, limit):
    qids = sorted({q for _, q, *_ in rows if q})
    ulans = sorted({u for _, q, u, *_ in rows if not q and u})
    jobs = [("qid", qids[i:i + BATCH]) for i in range(0, len(qids), BATCH)] + [("ulan", ulans[i:i + BATCH]) for i in range(0, len(ulans), BATCH)]
    print(f"[{SITE}] QID {len(qids)} / ULAN-only {len(ulans)} → 배치 {len(jobs)}")
    done = 0
    for kind, b in (jobs[:limit] if limit else jobs):
        key = f"{kind}_" + hashlib.md5("|".join(b).encode()).hexdigest()[:10]
        if already_fetched(SITE, key):
            continue
        if kind == "qid":
            q = Q_BY_QID.format(values=" ".join(f"wd:{x}" for x in b))
        else:
            q = Q_BY_ULAN.format(values=" ".join(f'"{x}"' for x in b))
        res = sparql(q)
        save_raw(SITE, key, json.dumps({"kind": kind, "keys": b, "rows": res}, ensure_ascii=False), url=SPARQL_URL, license_note=LICENSE_NOTE)
        done += 1
        time.sleep(1.0)
        if done % 10 == 0:
            print(f"  배치 {done} 저장", flush=True)
    print(f"저장 {done}")


def _year(v):
    return int(v[:4]) if v and v[:4].isdigit() and v[:4] != "0000" else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = get_conn()
    cur = conn.cursor()
    rows = targets(cur)
    if args.fetch:
        fetch(rows, args.limit)
        return
    by_qid, by_ulan = {}, {}
    ulan_hits = Counter()
    for fp in RAW.glob("*.json"):
        if fp.name.endswith(".meta.json"):
            continue
        d = json.loads(fp.read_text(encoding="utf-8"))
        for r in d["rows"]:
            qid = r["item"].rsplit("/", 1)[-1]
            rec = dict(qid=qid, ulan=r.get("ulan"), en=r.get("en"), born=_year(r.get("born")), died=_year(r.get("died")),
                       nat=NAT_MAP.get((r.get("nat") or "").split("|")[0]))
            if d["kind"] == "qid":
                by_qid.setdefault(qid, rec)
            else:
                ulan_hits[r["ulan"]] += 1
                by_ulan.setdefault(r["ulan"], rec)
    plan, stats = [], Counter()
    for aid, qid, ulan, by, dy, nat, en in rows:
        rec = by_qid.get(qid) if qid else (by_ulan.get(ulan) if ulan_hits.get(ulan) == 1 else None)
        if not rec:
            stats["no-data" if qid or ulan_hits.get(ulan, 0) == 0 else "ulan-ambiguous"] += 1
            continue
        upd = dict(birth_year=rec["born"] if by is None else None, death_year=rec["died"] if dy is None else None,
                   nationality=rec["nat"] if nat is None else None, name_en=rec["en"] if en is None else None,
                   wikidata_qid=rec["qid"] if not qid else None, ulan_id=rec["ulan"] if not ulan else None)
        if not any(upd.values()):
            stats["nothing-new"] += 1
            continue
        for k, v in upd.items():
            if v is not None:
                stats[k] += 1
        plan.append((upd["birth_year"], upd["death_year"], upd["nationality"], upd["name_en"], upd["wikidata_qid"], upd["ulan_id"], aid))
    print(f"대상 {len(rows)} → 갱신 {len(plan)} · {dict(stats)}")
    for p in plan[:8]:
        print("  ", p)
    if not args.apply:
        print("--apply 없음: 리포트만")
        return
    cur.executemany("""update artists set birth_year = coalesce(birth_year, %s), death_year = coalesce(death_year, %s),
                       nationality = coalesce(nullif(trim(nationality), ''), %s), name_en = coalesce(name_en, %s),
                       wikidata_qid = coalesce(wikidata_qid, %s), ulan_id = coalesce(ulan_id, %s),
                       authority_source = coalesce(authority_source, 'wikidata_meta'), updated_at = now() where id = %s""", plan)
    conn.commit()
    print("완료:", len(plan))


if __name__ == "__main__":
    main()
