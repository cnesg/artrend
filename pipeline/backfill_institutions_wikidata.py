"""museums / auction_houses 에 Wikidata QID·국가·도시·웹사이트 백필 (2026-09-15, 계획 P2-13 후반).

LLM·추정 없음. 기관 이름(name, name_en, 괄호 약칭 제거형)을 Wikidata rdfs:label 과 **정확 일치**시키고,
P31/P279* 가 기관 계열(미술관·박물관·갤러리·경매회사·도서관·대학·재단)인 항목이 **정확히 1개**일 때만 연결한다.
같은 이름으로 2개 이상이면 '모호'로 보고 건너뜀. 국가는 P17 영어 라벨, 도시는 P131(행정구역) 영어 라벨, 웹은 P856.
raw: crawlers/raw/wikidata_institutions/<batch>.json (save_raw, 재실행 시 스킵)
--fetch : SPARQL 수집   기본: 리포트   --apply: UPDATE(비어 있을 때만 coalesce). idempotent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "crawlers"))
from common import already_fetched, save_raw, with_retry  # noqa: E402
from artist_merge_util import get_conn  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
SITE = "wikidata_institutions"
RAW = Path(__file__).resolve().parent.parent / "crawlers" / "raw" / SITE
SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"}
LICENSE_NOTE = "Wikidata CC0 1.0 (https://www.wikidata.org/wiki/Wikidata:Licensing)"
BATCH = 30
LANGS = ["en", "ko", "de", "fr", "nl", "da", "sv", "nb", "fi", "it", "es", "pl", "ja", "zh", "ro", "el", "ru", "pt"]
# 기관 계열 클래스: museum, art museum, art gallery, auction house, library, university, foundation, archive, organization, cultural institution, museum institution
CLASSES = ["Q33506", "Q207694", "Q1030034", "Q194166", "Q7075", "Q3918", "Q157031", "Q166118", "Q5341295", "Q2668072", "Q4830453"]
# 표별 허용 클래스: 경매회사는 auction house(Q194166)만(기업 Q4830453·조직 일반은 'Ford'·'Ansell' 같은 오탐을 만들었음),
# 미술관은 museum/art museum/gallery/library/university/foundation/archive/cultural institution/museum institution.
# Wikidata가 경매회사를 P31=business(Q4830453)로만 적는 경우가 많아(Bonhams·Dorotheum), 기업 클래스는 영문 설명(schema:description)에
# auction/auktion 이 있을 때만 경매회사로 인정. 미술관도 기업 클래스는 설명에 museum/gallery 가 있을 때만.
ALLOW = {"auction_houses": {"Q194166"}, "museums": {"Q33506", "Q207694", "Q1030034", "Q7075", "Q3918", "Q157031", "Q166118", "Q5341295", "Q2668072"}}
DESC_RE = {"auction_houses": re.compile(r"auction|auktion|veiling", re.I), "museums": re.compile(r"museum|gallery|galerie|art collection", re.I)}

QUERY = """
SELECT ?l ?item ?country ?city ?web ?en ?desc (GROUP_CONCAT(DISTINCT ?cls; separator=",") AS ?classes) WHERE {{
  VALUES ?l {{ {values} }}
  ?item rdfs:label ?l .
  ?item wdt:P31/wdt:P279* ?cls . VALUES ?cls {{ {classes} }}
  OPTIONAL {{ ?item wdt:P17 ?c . ?c rdfs:label ?country FILTER(LANG(?country) = "en") }}
  OPTIONAL {{ ?item wdt:P131 ?ci . ?ci rdfs:label ?city FILTER(LANG(?city) = "en") }}
  OPTIONAL {{ ?item wdt:P856 ?web }}
  OPTIONAL {{ ?item rdfs:label ?en FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item schema:description ?desc FILTER(LANG(?desc) = "en") }}
}} GROUP BY ?l ?item ?country ?city ?web ?en ?desc
"""


def sparql(q: str) -> list[dict]:
    def _do():
        r = requests.post(SPARQL_URL, data={"query": q, "format": "json"}, headers=HEADERS, timeout=180)  # 라벨×언어 VALUES가 길어 GET은 414
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", "10")))
            raise RuntimeError("429")
        r.raise_for_status()
        return [{k: v.get("value") for k, v in b.items()} for b in r.json()["results"]["bindings"]]
    return with_retry(_do)


def variants(name: str | None, name_en: str | None) -> list[str]:
    """정확 일치 후보: 원명, 괄호 제거형, name_en. 'X, 도시' 형태의 name_en(한글 도시 설명)은 제외."""
    out = []
    for n in (name, name_en):
        if not n:
            continue
        n = n.strip()
        if re.search(r"[가-힣]+,\s*[가-힣]+$", n):  # '미니애폴리스, 미국' 같은 설명문
            continue
        out.append(n)
        stripped = re.sub(r"\s*\([^)]*\)\s*$", "", n).strip()
        if stripped and stripped != n:
            out.append(stripped)
        m = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", n)
        if m and re.search(r"[A-Za-z]{3,}", m.group(2)) and " " in m.group(2):  # 긴 영문 병기명은 후보, 'MMCA' 같은 약칭은 제외
            out.append(m.group(2).strip())
    seen, uniq = set(), []
    for v in out:
        if v.lower() not in seen:
            seen.add(v.lower())
            uniq.append(v)
    return uniq


def load_targets(cur) -> dict[str, list[tuple[str, str, str]]]:
    """label -> [(table, id, name)]"""
    by_label: dict[str, list] = defaultdict(list)
    cur.execute("select id::text, name, name_en from museums where wikidata_qid is null")
    for i, n, ne in cur.fetchall():
        for v in variants(n, ne):
            by_label[v].append(("museums", i, n))
    cur.execute("select id::text, name from auction_houses where wikidata_qid is null")
    for i, n in cur.fetchall():
        if re.search(r"\([A-Z][a-z]+", n) or "," in n:  # 'Foster (Edward)', 'Paillet, Alexandre Joseph' — Getty식 개인 경매인, 기관 아님
            continue
        for v in variants(n, None):
            by_label[v].append(("auction_houses", i, n))
    return by_label


def fetch(labels: list[str]) -> None:
    batches = [labels[i:i + BATCH] for i in range(0, len(labels), BATCH)]
    print(f"[{SITE}] 라벨 {len(labels)} → 배치 {len(batches)}")
    done = 0
    for bi, b in enumerate(batches):
        key = f"b{bi:04d}_" + hashlib.md5("|".join(b).encode()).hexdigest()[:8]
        if already_fetched(SITE, key):
            continue
        values = " ".join('"' + lab.replace('"', "").replace("\\", "") + '"@' + lg for lab in b for lg in LANGS)
        rows = sparql(QUERY.format(values=values, classes=" ".join(f"wd:{q}" for q in CLASSES)))
        save_raw(SITE, key, json.dumps({"labels": b, "rows": rows}, ensure_ascii=False), url=SPARQL_URL, license_note=LICENSE_NOTE)
        done += 1
        print(f"  배치 {bi + 1}/{len(batches)} 저장 (rows {len(rows)})", flush=True)
        time.sleep(1.0)
    print(f"저장 {done}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = get_conn()
    cur = conn.cursor()
    targets = load_targets(cur)
    if args.fetch:
        fetch(sorted(targets))
        return

    cands: dict[str, dict[str, dict]] = defaultdict(dict)  # label(lower) -> qid -> row
    for fp in RAW.glob("*.json"):
        if fp.name.endswith(".meta.json"):
            continue
        for r in json.load(open(fp, encoding="utf-8"))["rows"]:
            qid = r["item"].rsplit("/", 1)[-1]
            cls = {c.rsplit("/", 1)[-1] for c in (r.get("classes") or "").split(",") if c}
            d = cands[r["l"].lower()].setdefault(qid, {"qid": qid, "country": set(), "city": set(), "web": set(), "en": r.get("en"), "cls": set(), "desc": r.get("desc") or ""})
            d["cls"] |= cls
            for k in ("country", "city", "web"):
                if r.get(k):
                    d[k].add(r[k])
    per_entity: dict[tuple, dict[str, dict]] = defaultdict(dict)  # 여러 변형 라벨이 같은 QID면 1개로
    for label, ents in targets.items():
        for qid, d in cands.get(label.lower(), {}).items():
            for ent in ents:
                if d["cls"] & ALLOW[ent[0]] or ("Q4830453" in d["cls"] and DESC_RE[ent[0]].search(d["desc"])):
                    per_entity[ent][qid] = d
    stats, plan, ambiguous = Counter(), [], []
    all_entities = {e for ents in targets.values() for e in ents}

    def pick(s: set) -> str | None:
        return sorted(s)[0] if s else None

    for ent in all_entities:
        c = per_entity.get(ent, {})
        if not c:
            stats[f"{ent[0]}:not-found"] += 1
            continue
        if len(c) > 1:
            stats[f"{ent[0]}:ambiguous"] += 1
            ambiguous.append((ent[2], sorted(c)))
            continue
        (qid, d), = c.items()
        plan.append((ent[0], ent[1], ent[2], qid, pick(d["country"]), pick(d["city"]), pick(d["web"]), d["desc"]))
        stats[f"{ent[0]}:linked"] += 1
    print(f"대상 기관 {len(all_entities)} / 라벨 {len(targets)} → {dict(sorted(stats.items()))}")
    for p in sorted(plan):
        print("  ", p[0], p[2], "→", p[3], p[4], p[5], (p[6] or "")[:40], "|", p[7][:50])
    print("  모호:", ambiguous)
    if not args.apply:
        print("--apply 없음: 리포트만")
        return
    mus = [(q, co, ci, w, i) for t, i, _, q, co, ci, w, _d in plan if t == "museums"]
    ah = [(q, co, w, i) for t, i, _, q, co, ci, w, _d in plan if t == "auction_houses"]
    cur.executemany("update museums set wikidata_qid = coalesce(wikidata_qid, %s), country = coalesce(country, %s), city = coalesce(city, %s), website = coalesce(website, %s) where id = %s", mus)
    cur.executemany("update auction_houses set wikidata_qid = coalesce(wikidata_qid, %s), country = coalesce(country, %s), website = coalesce(website, %s) where id = %s", ah)
    conn.commit()
    cur.execute("select count(wikidata_qid), count(country), count(city), count(website) from museums")
    print("museums qid/country/city/web:", cur.fetchone())
    cur.execute("select count(wikidata_qid), count(country), count(website) from auction_houses")
    print("auction_houses qid/country/web:", cur.fetchone())


if __name__ == "__main__":
    main()
