"""v2 작가 출생·사망연도 보강 (2026-10-13). 기본은 리포트만, --apply로 반영.

    python v2/enrich_birth.py            # 후보 수집 + 리포트 (DB 쓰기 없음, Wikidata 조회는 함)
    python v2/enrich_birth.py --apply

우선순위 (위에서 정해지면 아래는 안 봄):
  1. list               참가 명단 원문에 출생연도 — 이미 채워져 있음, 건드리지 않음
  2. wikidata:Q..       artists.wikidata_qid(v1 링크로 얻은 QID)의 P569/P570
  3. wikidata_name:Q..  이름 정확일치(label/alias, en·mul·ko) + 사람(Q5) + 시각예술·영상 계열 직업
                        (P106 ⊂* 시각예술가 Q3391743, 또는 artist·painter·sculptor·photographer·performance artist·
                        film director 직접) + Wikidata 전체에서 그 이름의 사람이 1명뿐일 때만.
                        2026-10-13 1차 실행은 직업 필터를 artist(Q483501) 하위 전체로 잡아 가수·배우까지 걸렸고
                        동명인 2명을 허용해 'Tony Garnier'(리옹 2022, 건축가) 같은 오매칭이 나와 되돌리고 재실행.
                        단체(collective)는 이름 검색 안 함
  4. v1:<id>            v1 소프트 링크 작가의 출생연도
3과 4가 둘 다 있는데 2년 넘게 다르면 둘 다 버리고 리포트(conflict)로 남긴다.
타당성 검사: 출생연도 <= 첫 참가연도 - 12 (아니면 동명이인 의심으로 버림).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import psycopg2

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA_ROOT, PoliteSession, get_conn  # noqa: E402

V1_DSN = os.environ.get("V1_DATABASE_URL") or "postgresql://postgres@127.0.0.1:5433/artrend"
SPARQL = "https://query.wikidata.org/sparql"
HANGUL = re.compile(r"[가-힣]")
BATCH = 120

Q_BY_QID = """SELECT ?item ?birth ?death WHERE {{
  VALUES ?item {{ {values} }}
  OPTIONAL {{ ?item wdt:P569 ?birth }} OPTIONAL {{ ?item wdt:P570 ?death }} }}"""

# 작가 직업 필터를 걸지 않고 같은 이름의 사람 전체를 받아, 흔한 이름(동명인 3명 이상)은 거른다
Q_BY_NAME = """SELECT ?name ?item ?birth ?death ?artist WHERE {{
  VALUES ?name {{ {values} }}
  ?item rdfs:label|skos:altLabel ?name .
  ?item wdt:P31 wd:Q5 .
  BIND(EXISTS {{ ?item wdt:P106 ?occ .
                {{ ?occ wdt:P279* wd:Q3391743 }} UNION
                {{ VALUES ?occ {{ wd:Q483501 wd:Q1028181 wd:Q1281618 wd:Q33231 wd:Q1709010 wd:Q2526255 }} }} }} AS ?artist)
  OPTIONAL {{ ?item wdt:P569 ?birth }} OPTIONAL {{ ?item wdt:P570 ?death }} }}"""
MAX_NAMESAKES = 1


def year(v: str | None) -> int | None:
    m = re.match(r"^-?(\d{1,4})-", v or "")
    return int(m.group(1)) if m and not (v or "").startswith("-") else None


def lit(s: str, lang: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + f'"@{lang}'


def name_variants(n: str) -> set[str]:
    """원 표기 + 대문자 성 정리('Dineo Seshee BOPAPE' -> 'Dineo Seshee Bopape')."""
    out = {n}
    toks = n.split()
    if len(toks) >= 2 and any(t.isupper() and len(t) >= 2 and t.isalpha() for t in toks) \
            and any(not t.isupper() for t in toks):
        out.add(" ".join(t.capitalize() if t.isupper() and t.isalpha() else t for t in toks))
    return out


def sparql(sess: PoliteSession, q: str) -> list[dict]:
    r = sess.get(SPARQL, params={"query": q, "format": "json"}, delay=1.5)
    return r.json()["results"]["bindings"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, help="시험용: 보강 대상 앞 N명만")
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""select a.id, a.name, a.name_en, a.name_ko, a.kind, a.wikidata_qid, a.v1_artist_id, a.birth_year,
                          min(e.year), array_agg(distinct p.name_as_listed)
                   from artists a join participations p on p.artist_id = a.id join editions e on e.id = p.edition_id
                   group by a.id""")
    rows = cur.fetchall()
    todo = [r for r in rows if r[7] is None][: args.limit or None]
    print(f"artists={len(rows)} already_list={len(rows) - len(todo)} todo={len(todo)}", flush=True)

    sess = PoliteSession()
    cand: dict[str, dict[str, tuple]] = defaultdict(dict)  # artist_id -> {stage: (birth, death, ref)}

    # 2. QID 직접
    with_qid = [r for r in todo if r[5]]
    qid_owner = defaultdict(list)
    for r in with_qid:
        qid_owner[r[5]].append(str(r[0]))
    qids = list(qid_owner)
    for i in range(0, len(qids), BATCH):
        for b in sparql(sess, Q_BY_QID.format(values=" ".join(f"wd:{q}" for q in qids[i:i + BATCH]))):
            q = b["item"]["value"].rsplit("/", 1)[1]
            by, dy = year(b.get("birth", {}).get("value")), year(b.get("death", {}).get("value"))
            for aid in qid_owner[q]:
                prev = cand[aid].get("qid")
                if by and (not prev or not prev[0]):
                    cand[aid]["qid"] = (by, dy, f"wikidata:{q}")
    print("stage qid:", sum(1 for a in cand.values() if "qid" in a), "/", len(with_qid), flush=True)

    # 3. 이름 검색 (QID로 못 정한 개인 작가만)
    need = [r for r in todo if "qid" not in cand[str(r[0])] and r[4] == "person"]
    lit_owner = defaultdict(set)
    for r in need:
        names = {r[1], r[2], r[3], *(r[9] or [])} - {None}
        for n in names:
            for v in name_variants(n.strip()):
                langs = ("ko",) if HANGUL.search(v) else ("en", "mul")
                for lg in langs:
                    lit_owner[lit(v, lg)].add(str(r[0]))
    lits = list(lit_owner)
    hits: dict[str, dict[str, tuple]] = defaultdict(dict)  # artist_id -> {qid: (birth, death)}
    t0 = time.time()
    for i in range(0, len(lits), BATCH):
        chunk = lits[i:i + BATCH]
        try:
            res = sparql(sess, Q_BY_NAME.format(values=" ".join(chunk)))
        except Exception as exc:  # 한 배치 실패가 전체를 멈추지 않게 — 리포트에 남김
            print(f"[warn] batch {i // BATCH} 실패: {type(exc).__name__} — 재실행하면 남은 작가만 다시 조회", flush=True)
            continue
        for b in res:
            key = lit(b["name"]["value"], b["name"]["xml:lang"])
            q = b["item"]["value"].rsplit("/", 1)[1]
            by, dy = year(b.get("birth", {}).get("value")), year(b.get("death", {}).get("value"))
            is_artist = b.get("artist", {}).get("value") == "true"
            for aid in lit_owner.get(key, ()):
                old = hits[aid].get(q)
                if not old or (by and not old[0]):
                    hits[aid][q] = (by, dy, is_artist)
        if (i // BATCH) % 10 == 0:
            print(f"  name batches {i // BATCH + 1}/{(len(lits) + BATCH - 1) // BATCH} ({time.time() - t0:.0f}s)", flush=True)
    st = Counter()
    for aid, items in hits.items():
        artists_ = {q: v for q, v in items.items() if v[2]}
        if not artists_:
            st["name_no_artist"] += 1
        elif len(artists_) > 1:
            st["name_ambiguous"] += 1
        elif len(items) > MAX_NAMESAKES:
            st["name_common"] += 1
        else:
            q, (by, dy, _) = next(iter(artists_.items()))
            if by:
                cand[aid]["name"] = (by, dy, f"wikidata_name:{q}")
            else:
                st["name_unique_no_birth"] += 1

    # 4. v1 출생연도
    v1_ids = {str(r[6]): str(r[0]) for r in todo if r[6]}
    if v1_ids:
        v1 = psycopg2.connect(V1_DSN, connect_timeout=10)
        v1.set_session(readonly=True)
        c1 = v1.cursor()
        # v1은 MoMA 등 원천 관례로 0을 '미상'으로 쓴 행이 있다 — 0은 값 없음으로 본다
        c1.execute("select id, birth_year, nullif(death_year, 0) from artists where id = any(%s::uuid[]) and birth_year > 0",
                   (list(v1_ids),))
        for vid, by, dy in c1.fetchall():
            cand[v1_ids[str(vid)]]["v1"] = (by, dy, f"v1:{vid}")
        v1.close()

    first_year = {str(r[0]): r[8] for r in rows}
    decided, conflicts, implausible = {}, [], []
    for aid, c in cand.items():
        pick = c.get("qid")
        if not pick:
            n, v = c.get("name"), c.get("v1")
            if n and v and abs(n[0] - v[0]) > 2:
                conflicts.append({"artist_id": aid, "wikidata_name": n, "v1": v})
                continue
            pick = n or v
        if not pick:
            continue
        if pick[0] > first_year[aid] - 12:
            implausible.append({"artist_id": aid, "pick": pick, "first_year": first_year[aid]})
            continue
        decided[aid] = pick
        st["by_" + pick[2].split(":")[0]] += 1

    print(dict(st), "conflicts", len(conflicts), "implausible", len(implausible), "decided", len(decided), flush=True)
    if args.apply:
        for aid, (by, dy, ref) in decided.items():
            qid = ref.split(":", 1)[1] if ref.startswith("wikidata_name:") else None
            cur.execute("""update artists set birth_year = %s, birth_year_source = %s,
                             death_year = coalesce(death_year, %s), wikidata_qid = coalesce(wikidata_qid, %s)
                           where id = %s and birth_year is null""", (by, ref, dy, qid, aid))
        conn.commit()
        print("applied", len(decided))
    names = {str(r[0]): r[1] for r in rows}
    out = DATA_ROOT / "logs" / f"enrich_birth_{'apply' if args.apply else 'report'}_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({
        "stats": st, "decided": len(decided),
        "conflicts": [{**c, "name": names[c["artist_id"]]} for c in conflicts],
        "implausible": [{**c, "name": names[c["artist_id"]]} for c in implausible],
        "sample_wikidata_name": [[names[a], *p] for a, p in decided.items() if p[2].startswith("wikidata_name")][:80],
        "sample_v1": [[names[a], *p] for a, p in decided.items() if p[2].startswith("v1")][:80],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("report ->", out)


if __name__ == "__main__":
    main()
