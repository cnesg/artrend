"""대형 미술관 중 라벨 정확 일치로 못 붙은 곳의 Wikidata QID 수동 지정 + Wikidata 조회로 검증 후 백필 (2026-09-15).

backfill_institutions_wikidata.py 는 'The Metropolitan Museum of Art (Met)' 처럼 접두 관사·약칭 때문에 라벨이 안 맞거나
같은 이름의 항목이 여럿(모호)이라 대형 미술관 상당수를 못 붙였다. 여기서는 QID를 사람이 지정하되, **Wikidata에서 그 QID의
영문 라벨·설명·국가를 실제로 조회해 기대 키워드가 라벨/설명에 있을 때만** 적용한다(지정 오류 방지). 소장 수가 많은 곳 위주.
기본: 리포트   --apply: museums UPDATE(coalesce). idempotent.
"""
from __future__ import annotations

import argparse
import sys
import time

import requests

from artist_merge_util import get_conn

sys.stdout.reconfigure(encoding="utf-8")
SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"}

# museums.name → (QID, 라벨/설명에 있어야 하는 키워드)
MANUAL = {
    "The Metropolitan Museum of Art (Met)": ("Q160236", "Metropolitan Museum of Art"),
    "National Gallery of Art": ("Q214867", "national art museum in Washington"),
    "The Museum of Modern Art (MoMA)": ("Q188740", "Museum of Modern Art"),
    "Cleveland Museum of Art": ("Q657415", "Cleveland Museum of Art"),
    "Victoria and Albert Museum": ("Q213322", "Victoria and Albert Museum"),
    "Belvedere": ("Q303139", "Belvedere"),
    "Austrian Gallery Belvedere": ("Q303139", "Belvedere"),
    "The Albertina Museum": ("Q371908", "Albertina"),
    "The J. Paul Getty Museum": ("Q731126", "Getty"),
    "Smithsonian American Art Museum": ("Q1192305", "Smithsonian American Art Museum"),
    "National Gallery of Denmark": ("Q671384", "Statens Museum for Kunst"),
    "Nationalmuseum Sweden": ("Q842858", "Nationalmuseum"),
    "National Gallery, London": ("Q180788", "National Gallery"),
    "Museum of Fine Arts, Boston": ("Q49133", "Museum of Fine Arts"),
    "Indianapolis Museum of Art": ("Q1117704", "art museum in Indianapolis"),
    "Neue Nationalgalerie": ("Q32659772", "Neue Nationalgalerie"),
    "S.M.A.K.": ("Q1540707", "Actuele Kunst"),
    "Slovak national gallery": ("Q1744024", "Slovak National Gallery"),
}
QUERY = """
SELECT ?item ?en ?desc ?country ?city ?web WHERE {{
  VALUES ?item {{ {values} }}
  OPTIONAL {{ ?item rdfs:label ?en FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item schema:description ?desc FILTER(LANG(?desc) = "en") }}
  OPTIONAL {{ ?item wdt:P17 ?c . ?c rdfs:label ?country FILTER(LANG(?country) = "en") }}
  OPTIONAL {{ ?item wdt:P131 ?ci . ?ci rdfs:label ?city FILTER(LANG(?city) = "en") }}
  OPTIONAL {{ ?item wdt:P856 ?web }}
}}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = get_conn()
    cur = conn.cursor()
    qids = sorted({q for q, _ in MANUAL.values()})
    r = requests.post(SPARQL_URL, data={"query": QUERY.format(values=" ".join(f"wd:{q}" for q in qids)), "format": "json"}, headers=HEADERS, timeout=120)
    r.raise_for_status()
    info: dict[str, dict] = {}
    for b in r.json()["results"]["bindings"]:
        q = b["item"]["value"].rsplit("/", 1)[-1]
        d = info.setdefault(q, {"en": None, "desc": None, "country": None, "city": None, "web": None})
        for k in d:
            if b.get(k) and not d[k]:
                d[k] = b[k]["value"]
    plan = []
    for name, (qid, kw) in MANUAL.items():
        d = info.get(qid)
        ok = bool(d) and kw.lower() in ((d["en"] or "") + " " + (d["desc"] or "")).lower()
        print(f"  {'OK ' if ok else 'NG '} {name} → {qid} | {d and d['en']} | {d and d['desc']} | {d and d['country']} | {d and d['city']}")
        if ok:
            plan.append((qid, d["country"], d["city"], d["web"], name))
    print(f"검증 통과 {len(plan)}/{len(MANUAL)}")
    if not args.apply:
        print("--apply 없음: 리포트만")
        return
    cur.executemany("update museums set wikidata_qid = coalesce(wikidata_qid, %s), country = coalesce(country, %s), city = coalesce(city, %s), website = coalesce(website, %s) where name = %s", plan)
    conn.commit()
    cur.execute("select count(wikidata_qid), count(country) from museums")
    print("museums qid/country:", cur.fetchone())
    time.sleep(0)


if __name__ == "__main__":
    main()
