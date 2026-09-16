"""artists.ulan_id / wikidata_qid 백필 (2026-09-15 작업분담 §M6, 진단 §3-3 / 계획 P2-12).

문자열 병합으로는 못 잇는 변형(Rembrandt/Rembrandt van Rijn, Teniers/D. Teniers/David Teniers,
이우환/Lee, Ufan)을 authority ID로 묶기 위한 1단계. 재적재 없이 raw를 다시 읽어 "이름 → ID" 사전을
만들고, DB artists 행에 이름 매칭(정확 → 느슨, 유일할 때만)으로 ID를 채운다. 2단계 병합은
merge_by_authority.py.

이름 → ID 사전의 출처(모두 raw에 이미 있는 값, LLM·추정 없음):
  met            MetObjects.csv  "Artist Display Name" | "Artist ULAN URL" | "Artist Wikidata URL" (| 정렬 분할)
  getty_sales    sales_contents_N.csv  artist_name_k / artist_ulan_k (k=1..5)
  auctions_wd    crawlers/raw/auctions_wikidata/*.json  creatorLabel / creator(QID URI)
  wikidata_creators  crawlers/raw/wikidata_creators/*.json (워커 W9 산출물, 있으면 사용)
  + Met 행에서 (ULAN, QID)가 같이 나오는 쌍으로 ULAN→QID 교차 사전을 만들어 QID를 보강한다.

안전 규칙:
  - 같은 이름이 서로 다른 ID를 가리키면(동명이인) 사전에서 제외. 단 지배 ID가 DOMINANCE 이상이고
    행 수가 MIN_ROWS 이상이면 지배 ID 채택(Getty의 "Teniers"류 축약 표기 대응).
  - "(not assigned)", 대괄호 익명([Anonymous]), entity_kind <> 'person' 행은 대상 아님.
  - 이미 값이 있는 컬럼은 덮어쓰지 않고 충돌만 리포트.
기본 리포트, --apply 시 UPDATE. idempotent.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from artist_merge_util import get_conn, norm_exact, norm_loose

sys.stdout.reconfigure(encoding="utf-8")
csv.field_size_limit(10**9)
RAW = Path(__file__).resolve().parent.parent / "crawlers" / "raw"
DOMINANCE = 0.98
MIN_ROWS = 5
ANON_RE = re.compile(
    r"^\[|^(unknown|unidentified|anonymous|anoniem|anonyme|anonym|unbekannt\w*|inconnu|onbekend|ignoto|various|monogrammist)\b"
    r"|^\d{1,2}\. Jahrh",
    re.I,
)
# 귀속 표기(본체 ULAN이 붙어 있어도 본체와 합치면 안 됨) → ID는 주되 entity_kind='attribution'으로 표시
ATTR_RE = re.compile(
    r"(attribu|attributed|mani[èe]re?\b|manner\b|\bstyle\b|\bgo[uû]t\b|\bgusto\b|[ée]cole\b|\bschool\b|\bschule\b|sch[üu]ler\b|"
    r"\bd'?apr[èe]s\b|\bapr[èe]s\b|\bafter\b|\bnach\b|\bcopie\b|\bcopy\b|\bkopie\b|\bpastiche\b|\bimitation\b|\bsuiveur\b|\bfollower\b|\bcircle\b|"
    r"\bumkreis\b|\bnachfolger\b|\bentourage\b|\batelier\b|\bworkshop\b|\bwerkstatt\b|[ée]l[èe]ves?\b|\bpupils?\b|\bgenre de\b|\bsuite de\b|"
    r"\bart of\b|\bart de\b|\bnachahmer\b|\bnachahmung\b|\bfa[çc]on de\b|\bou sa\b|\bof his\b|\bor his\b|\bwie\b|\bso gut wie\b|\bin de manier\b|\bin zijn manier\b)",
    re.I,
)


def _id_tail(url: str) -> str | None:
    t = url.strip().rstrip("/").rsplit("/", 1)[-1]
    if not t or t == "(not assigned)":
        return None
    return t


def _resolve(counter: Counter) -> str | None:
    if not counter:
        return None
    if len(counter) == 1:
        return next(iter(counter))
    top, n = counter.most_common(1)[0]
    total = sum(counter.values())
    return top if n >= MIN_ROWS and n / total >= DOMINANCE else None


def collect() -> tuple[dict, dict, dict, Counter]:
    """이름 → Counter(ulan), 이름 → Counter(qid), ulan → Counter(qid), 출처 통계."""
    name_ulan: dict[str, Counter] = defaultdict(Counter)
    name_qid: dict[str, Counter] = defaultdict(Counter)
    ulan_qid: dict[str, Counter] = defaultdict(Counter)
    src: dict[str, dict[str, str]] = {}  # name -> {'ulan': source, 'qid': source}
    stats = Counter()

    def add(name: str, ulan: str | None, qid: str | None, source: str) -> None:
        name = " ".join(name.split())
        if not name or ANON_RE.match(name):
            return
        if ulan:
            name_ulan[name][ulan] += 1
            src.setdefault(name, {}).setdefault("ulan", source)
        if qid:
            name_qid[name][qid] += 1
            src.setdefault(name, {}).setdefault("qid", source)
        if ulan and qid:
            ulan_qid[ulan][qid] += 1

    met = RAW / "met" / "MetObjects.csv"
    if met.exists():
        with open(met, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                names = [x.strip() for x in row["Artist Display Name"].split("|")]
                ul = [x.strip() for x in row["Artist ULAN URL"].split("|")]
                wd = [x.strip() for x in row["Artist Wikidata URL"].split("|")]
                for i, n in enumerate(names):
                    u = _id_tail(ul[i]) if len(ul) == len(names) else None
                    q = _id_tail(wd[i]) if len(wd) == len(names) else None
                    if n and (u or q):
                        add(n, u, q, "met"); stats["met"] += 1

    for fp in sorted(glob.glob(str(RAW / "getty_provenance_sales" / "sales_contents_*.csv"))):
        with open(fp, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                for k in range(1, 6):
                    n = (row.get(f"artist_name_{k}") or "").strip()
                    u = (row.get(f"artist_ulan_{k}") or "").strip()
                    if n and u and u.isdigit() and u != "0":  # Getty는 미등록을 "0"/"not in ULAN"으로 적음
                        add(n, u, None, "getty_sales"); stats["getty_sales"] += 1

    for fp in glob.glob(str(RAW / "auctions_wikidata" / "*.json")):
        if fp.endswith(".meta.json"):
            continue
        try:
            d = json.load(open(fp, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        n = (d.get("creatorLabel") or "").strip()
        q = _id_tail(d.get("creator") or "")
        if n and q and q.startswith("Q") and not n.startswith("Q"):
            add(n, None, q, "auctions_wikidata"); stats["auctions_wikidata"] += 1

    for fp in glob.glob(str(RAW / "wikidata_creators" / "*.json")):
        if fp.endswith(".meta.json"):
            continue
        try:
            d = json.load(open(fp, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        recs = d if isinstance(d, list) else d.get("mappings") or d.get("records") or d.get("results") or []
        for r in recs:
            n = (r.get("creator_label") or r.get("creatorLabel") or "").strip()
            q = (r.get("creator_qid") or "").strip() or _id_tail(r.get("creator") or "")
            u = (r.get("ulan_id") or r.get("ulan") or "").strip() or None
            if n and (q or u) and not n.startswith("Q"):
                add(n, u, q if q and q.startswith("Q") else None, "wikidata_creators"); stats["wikidata_creators"] += 1

    return {n: (_resolve(c), src[n].get("ulan")) for n, c in name_ulan.items()}, \
           {n: (_resolve(c), src[n].get("qid")) for n, c in name_qid.items()}, \
           {u: _resolve(c) for u, c in ulan_qid.items()}, stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    name_ulan, name_qid, ulan_qid, stats = collect()
    n_ulan_ok = sum(1 for v, _ in name_ulan.values() if v)
    n_qid_ok = sum(1 for v, _ in name_qid.values() if v)
    print(f"raw 스캔: {dict(stats)}")
    print(f"이름→ULAN 사전 {len(name_ulan)} (유일/지배 {n_ulan_ok}) · 이름→QID 사전 {len(name_qid)} (유일/지배 {n_qid_ok}) · ULAN→QID {sum(1 for v in ulan_qid.values() if v)}")

    # 정확/느슨 키 사전 (느슨 키는 유일할 때만)
    def keyed(d: dict) -> tuple[dict, dict]:
        exact, loose_c = {}, defaultdict(set)
        for n, (v, s) in d.items():
            if not v:
                continue
            exact.setdefault(norm_exact(n), (v, s))
            loose_c[norm_loose(n)].add((v, s))
        loose = {k: next(iter(vs)) for k, vs in loose_c.items() if len({v for v, _ in vs}) == 1}
        return exact, loose

    ulan_exact, ulan_loose = keyed(name_ulan)
    qid_exact, qid_loose = keyed(name_qid)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("select id::text, name, ulan_id, wikidata_qid from artists where entity_kind = 'person'")
    rows = cur.fetchall()
    id2name_all = {aid: name for aid, name, _, _ in rows}
    plan_u, plan_q, conflicts = [], [], Counter()
    plan_attr = []  # (qualifier, aid) — 귀속 표기 이름
    how = Counter()
    for aid, name, cur_u, cur_q in rows:
        m_attr = ATTR_RE.search(name)
        if m_attr:
            how["attribution-flagged"] += 1
        ke, kl = norm_exact(name), norm_loose(name)
        hit_u = ulan_exact.get(ke) or ulan_loose.get(kl)
        hit_q = qid_exact.get(ke) or qid_loose.get(kl)
        new_u = hit_u[0] if hit_u else None
        new_q = hit_q[0] if hit_q else None
        src_u = hit_u[1] if hit_u else None
        src_q = hit_q[1] if hit_q else None
        if not new_q and (new_u or cur_u):
            new_q = ulan_qid.get(new_u or cur_u)
            src_q = "ulan_cross" if new_q else None
        if new_u:
            if cur_u and cur_u != new_u:
                conflicts["ulan"] += 1
            elif not cur_u:
                plan_u.append((new_u, src_u, aid)); how[f"ulan:{src_u}:{'exact' if ke in ulan_exact else 'loose'}"] += 1
                if m_attr:
                    plan_attr.append((m_attr.group(0).strip(), aid))
        if new_q:
            if cur_q and cur_q != new_q:
                conflicts["qid"] += 1
            elif not cur_q:
                plan_q.append((new_q, src_q, aid)); how[f"qid:{src_q}"] += 1

    print(f"person 작가 {len(rows)}: ULAN 부여 예정 {len(plan_u)} · QID 부여 예정 {len(plan_q)} · 기존값 충돌 {dict(conflicts)} · 귀속표기→attribution 전환 {len(plan_attr)}")
    for qv, aid in plan_attr[:8]:
        print(f"   attribution: {id2name_all.get(aid, aid)!r} ({qv})")
    for k, v in sorted(how.items()):
        print(f"   {k:40} {v}")
    # 같은 ID를 받게 되는 행 수(=병합 후보) 미리보기
    dup_u = Counter(u for u, _, _ in plan_u)
    dup_q = Counter(q for q, _, _ in plan_q)
    print(f"병합 후보: ULAN 그룹(2행 이상) {sum(1 for c in dup_u.values() if c > 1)} / 행 {sum(c for c in dup_u.values() if c > 1)} · QID 그룹 {sum(1 for c in dup_q.values() if c > 1)} / 행 {sum(c for c in dup_q.values() if c > 1)}")
    id2name = {aid: name for aid, name, _, _ in rows}
    by_u = defaultdict(list)
    for u, _, aid in plan_u:
        by_u[u].append(id2name[aid])
    for u, names in sorted(by_u.items(), key=lambda x: -len(x[1]))[:12]:
        print(f"   ULAN {u}: {names[:8]}")
    if not args.apply:
        print("--apply 없음: 리포트만")
        return
    cur.executemany("update artists set ulan_id = %s, authority_source = coalesce(authority_source, %s), updated_at = now() where id = %s and ulan_id is null", plan_u)
    cur.executemany("update artists set wikidata_qid = %s, authority_source = coalesce(authority_source, %s), updated_at = now() where id = %s and wikidata_qid is null", plan_q)
    cur.executemany(
        """update artists set entity_kind = 'attribution', attribution_qualifier = coalesce(attribution_qualifier, %s),
                  entity_kind_note = coalesce(entity_kind_note, 'authority-backfill: 귀속 표기'), updated_at = now()
           where id = %s and entity_kind = 'person'""",
        plan_attr,
    )
    conn.commit()
    cur.execute("select count(ulan_id), count(wikidata_qid) from artists")
    print("완료: artists ulan_id/wikidata_qid 보유 수 =", cur.fetchone())


if __name__ == "__main__":
    main()
