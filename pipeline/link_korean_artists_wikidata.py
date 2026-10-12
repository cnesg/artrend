"""한국 작가(한글 이름) ↔ Wikidata QID/ULAN 연결 (2026-09-15 작업분담 M6-c).

M6 authority 병합은 Met/Getty/Wikidata 미술관 raw에 ID가 있는 작가만 묶는다. 국립현대·서울시립·부산시립·리움 등
국내 소스의 작가 4,221명은 한글 이름뿐이고 생년·ID가 없어 "이우환"(mmca)과 "Lee, Ufan"(Tate, Q399775)이 따로 남는다.
여기서는 Wikidata의 한국어 라벨로 후보를 찾고, 다음 조건을 전부 만족할 때만 연결한다(추정·LLM 없음):
  1) P31 사람, 직업(P106)이 미술가 계열(OCCUPATIONS) 중 하나
  2) 같은 한글 라벨의 후보가 정확히 1명이거나, 여러 명이면 MMCA raw의 영문 이름(artistnmEng, 예 "LEE Ufan")의
     성(첫 토큰)이 영문 라벨에 포함되는 후보가 정확히 1명
  3) 국적(P27)이 대한민국/조선/북한이거나 비어 있음
--fetch : crawlers/raw/wikidata_korean_artists/<batch>.json 저장(save_raw, 이미 있으면 스킵)
기본    : 리포트(연결 예정/모호/미발견)
--apply : artists.wikidata_qid/ulan_id/name_en/birth_year/death_year(비어 있을 때만) 갱신. 이후 merge_by_authority.py 로 병합.
"""
from __future__ import annotations

import argparse
import glob
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
ROOT = Path(__file__).resolve().parent.parent
SITE_NAME = "wikidata_korean_artists"
RAW = ROOT / "crawlers" / "raw" / SITE_NAME
SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"}
LICENSE_NOTE = "Wikidata CC0 1.0 (https://www.wikidata.org/wiki/Wikidata:Licensing)"
BATCH = 100
OCCUPATIONS = ["Q483501", "Q1028181", "Q1281618", "Q33231", "Q3391743", "Q3055126", "Q11569986", "Q7541856",
               "Q3303330", "Q644687", "Q15296811", "Q10774753", "Q12341577", "Q1925963", "Q5322166", "Q2865523"]
KOREA = {"Q884", "Q423", "Q28179", "Q18097"}  # 대한민국, 북한, 조선, 대한제국
DB_ENG: dict[str, str] = {}  # 한글 이름 → DB name_en

QUERY = """
SELECT ?ko ?item ?en ?ulan ?born ?died (GROUP_CONCAT(DISTINCT ?c; separator=",") AS ?countries) WHERE {{
  VALUES ?ko {{ {values} }}
  ?item rdfs:label ?ko . FILTER(LANG(?ko) = "ko")
  ?item wdt:P31 wd:Q5 .
  ?item wdt:P106 ?occ . VALUES ?occ {{ {occs} }}
  OPTIONAL {{ ?item rdfs:label ?en FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item wdt:P245 ?ulan }}
  OPTIONAL {{ ?item wdt:P569 ?born }}
  OPTIONAL {{ ?item wdt:P570 ?died }}
  OPTIONAL {{ ?item wdt:P27 ?c }}
}} GROUP BY ?ko ?item ?en ?ulan ?born ?died
"""


def sparql(q: str) -> list[dict]:
    def _do():
        r = requests.get(SPARQL_URL, params={"query": q, "format": "json"}, headers=HEADERS, timeout=120)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", "10")))
            raise RuntimeError("429")
        r.raise_for_status()
        return [{k: v.get("value") for k, v in b.items()} for b in r.json()["results"]["bindings"]]
    return with_retry(_do)


def hangul_name(n: str) -> str | None:
    """'김정숙 a' 같은 접미 제거, 한글만 남긴 순수 이름. 한글이 없으면 None."""
    m = re.match(r"^([가-힣]{2,6})(?:\s|$|\()", n.strip())
    if not m or re.match(r"^[가-힣]+\s+[가-힣]", n.strip()):  # '미나미 소코'·'파블로 피카소'처럼 띄어쓴 다중 토큰 이름은 첫 토큰만 보면 오탐 → 제외
        return None
    return m.group(1)


def mmca_english() -> dict[str, str]:
    d: dict[str, Counter] = defaultdict(Counter)
    for fp in glob.glob(str(ROOT / "crawlers" / "raw" / "mmca" / "*.json")):
        if fp.endswith(".meta.json"):
            continue
        try:
            r = json.load(open(fp, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        k, e = hangul_name(r.get("artistnm") or ""), (r.get("artistnmEng") or "").strip()
        if k and e:
            d[k][e] += 1
    return {k: c.most_common(1)[0][0] for k, c in d.items()}


def load_targets(cur) -> dict[str, list[tuple[str, str]]]:
    cur.execute("select id::text, name, name_en from artists where entity_kind = 'person' and wikidata_qid is null and name ~ '[가-힣]'")
    by_ko: dict[str, list] = defaultdict(list)
    for aid, name, name_en in cur.fetchall():
        k = hangul_name(name)
        if k:
            by_ko[k].append((aid, name))
            if name_en and re.match(r"^[A-Za-z]", name_en):
                DB_ENG.setdefault(k, name_en.strip())  # 2026-09-16: DB name_en(mmca artistnmEng 적재분)도 성 대조에 사용
    return by_ko


def fetch(kos: list[str], limit: int | None) -> None:
    batches = [kos[i:i + BATCH] for i in range(0, len(kos), BATCH)]
    print(f"[{SITE_NAME}] 한글 이름 {len(kos)} → 배치 {len(batches)}")
    done = 0
    for bi, b in enumerate(batches[:limit] if limit else batches):
        key = f"b{bi:04d}_" + hashlib.md5("|".join(b).encode()).hexdigest()[:8]
        if already_fetched(SITE_NAME, key):
            continue
        values = " ".join('"' + k.replace('"', '') + '"@ko' for k in b)
        rows = sparql(QUERY.format(values=values, occs=" ".join(f"wd:{q}" for q in OCCUPATIONS)))
        save_raw(SITE_NAME, key, json.dumps({"names": b, "rows": rows}, ensure_ascii=False), url=SPARQL_URL, license_note=LICENSE_NOTE)
        done += 1
        time.sleep(1.2)
    print(f"저장 {done}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = get_conn()
    cur = conn.cursor()
    targets = load_targets(cur)
    if args.fetch:
        fetch(sorted(targets), args.limit)
        return

    eng = mmca_english()
    cands: dict[str, list[dict]] = defaultdict(list)
    for fp in glob.glob(str(RAW / "*.json")):
        if fp.endswith(".meta.json"):
            continue
        for r in json.load(open(fp, encoding="utf-8"))["rows"]:
            cands[r["ko"]].append(r)
    plan, stats, ambiguous, skipped = [], Counter(), [], []
    for ko, members in targets.items():
        rows = [r for r in cands.get(ko, []) if not (r.get("countries") and not set(r["countries"].replace("http://www.wikidata.org/entity/", "").split(",")) & KOREA)]
        rows = list({r["item"]: r for r in rows}.values())
        if not rows:
            stats["not-found" if ko not in cands else "filtered-by-country"] += 1
            continue
        if len(rows) > 1:
            surname = ((DB_ENG.get(ko) or eng.get(ko) or "").split(" ") or [""])[0].lower()
            if surname:
                rows2 = [r for r in rows if surname in (r.get("en") or "").lower().replace("-", " ").split()]
                if len(rows2) == 1:
                    rows = rows2
        if len(rows) != 1:
            stats["ambiguous"] += 1
            ambiguous.append((ko, [r.get("en") for r in rows][:4]))
            continue
        r = rows[0]
        qid = r["item"].rsplit("/", 1)[-1]
        by = int(r["born"][:4]) if r.get("born") and r["born"][:4].isdigit() else None
        dy = int(r["died"][:4]) if r.get("died") and r["died"][:4].isdigit() else None
        for aid, name in members:
            # 안전장치: "김원(1982)"처럼 이름에 연도가 붙어 있는데 Wikidata 생년과 다르면 동명이인 → 제외.
            # "김기창 a, 안동오"처럼 콤마로 여러 작가가 묶인 행은 단일 작가로 연결하지 않음.
            yrs = [int(y) for y in re.findall(r"\((?:b\.?\s*)?(1[89]\d\d|20\d\d)", name)]
            if re.search(r",|\s외(\s|$|\()", name) or (yrs and (by is None or yrs[0] != by)):
                stats["skipped-year/multi"] += 1
                skipped.append((name, qid, by))
                continue
            plan.append((qid, r.get("ulan"), r.get("en") or eng.get(ko), by, dy, aid, name))
        stats["linked-names"] += 1
    print(f"대상 한글 이름 {len(targets)} / 후보 있음 {len(cands)} → {dict(stats)} · artists 갱신 예정 {len(plan)}")
    for x in plan[:12] + [x for x in plan if x[6].split("(")[0].strip() in ("이우환", "김환기", "박서보", "백남준", "천경자", "이중섭")]:
        print("  ", x[6], "→", x[0], x[1], x[2], x[3], x[4])
    print("  모호 샘플:", ambiguous[:8])
    print("  제외(연도불일치/다중):", skipped[:15])
    if not args.apply:
        print("--apply 없음: 리포트만")
        return
    cur.executemany(
        """update artists set wikidata_qid = coalesce(wikidata_qid, %s), ulan_id = coalesce(ulan_id, %s), name_en = coalesce(name_en, %s),
                  birth_year = coalesce(birth_year, %s), death_year = coalesce(death_year, %s),
                  authority_source = coalesce(authority_source, 'wikidata_korean_label'), updated_at = now()
           where id = %s""",
        [(q, u, e, b, d, aid) for q, u, e, b, d, aid, _ in plan],
    )
    conn.commit()
    print(f"완료: {len(plan)}행 갱신 → 이제 merge_by_authority.py 실행")


if __name__ == "__main__":
    main()
