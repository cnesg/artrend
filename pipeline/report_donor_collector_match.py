"""기증·유증 크레딧라인(artworks.description) → collectors 이름 정확일치 수확 리포트 (읽기 전용).

museum_holdings.donor_name은 전부 NULL이라, 기증자 정보는 artworks.description의
"Gift of X" / "Bequest of X" 크레딧라인과 provenance_records(기증 449k건)에만 있다.
여기서는 크레딧라인의 X를 정규화(대소문자·공백·구두점만)한 뒤 collectors.name과
**정확히 같을 때만** 매칭으로 센다. 유사도/부분일치는 쓰지 않는다(동명이인 위험).
같은 작품의 provenance에 그 컬렉터가 이미 있으면 'already_linked', 없으면 'new_link'.
DB는 바꾸지 않는다.

    python pipeline/report_donor_collector_match.py [--json docs/logs/xxx.json]
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import get_connection  # noqa: E402

RE_CREDIT = re.compile(
    r"^\s*(?:gift|bequest|bequeathed|donated|promised gift)\s+(?:of|by)\s+(.+)", re.I)
RE_TAIL = re.compile(
    r"\s+(?:in\s+(?:memory|honor|celebration|recognition|tribute|appreciation)\b|"
    r"on\s+behalf\b|through\b|by\s+exchange\b|\().*$|[;].*$|,\s*(?:\d{4}|by\b).*$", re.I)


def norm(s):
    s = re.sub(r"[^\w\s&]", " ", (s or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def donor_of(desc):
    first = (desc or "").strip().splitlines()[0] if desc else ""
    m = RE_CREDIT.match(first)
    if not m:
        return None, None
    kind = "bequest" if re.match(r"\s*(bequest|bequeathed)", first, re.I) else "gift"
    x = RE_TAIL.sub("", m.group(1)).strip(" .,")
    return (x, kind) if 3 <= len(x) <= 120 else (None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("set statement_timeout='500s'")

    cur.execute("select id, name from collectors")
    by_name = defaultdict(list)
    for cid, name in cur.fetchall():
        by_name[norm(name)].append(cid)

    cur.execute("select artwork_id, owner_collector_id from provenance_records "
                "where owner_collector_id is not null")
    linked = set(cur.fetchall())

    cur.execute("""select w.id, w.description, m.id
                   from artworks w
                   join museum_holdings h on h.artwork_id = w.id
                   join museums m on m.id = h.museum_id
                   where w.description ~* '^\\s*(gift|bequest|bequeathed|donated|promised gift)\\s+(of|by)'""")
    stat = Counter()
    donors = defaultdict(lambda: {"museums": set(), "works": 0})
    ambiguous = set()
    for awid, desc, mid in cur.fetchall():
        stat["credit_rows"] += 1
        x, kind = donor_of(desc)
        if not x:
            stat["unparsed"] += 1
            continue
        stat["parsed"] += 1
        ids = by_name.get(norm(x))
        if not ids:
            stat["no_collector_match"] += 1
            continue
        if len(ids) > 1:
            stat["ambiguous_name_skipped"] += 1
            ambiguous.add(norm(x))
            continue
        cid = ids[0]
        stat["matched"] += 1
        if (awid, cid) in linked:
            stat["already_linked"] += 1
        else:
            stat["new_link"] += 1
        d = donors[cid]
        d["museums"].add(mid)
        d["works"] += 1

    multi = sum(1 for d in donors.values() if len(d["museums"]) >= 2)
    print("== 크레딧라인 기증자 → collectors 정확일치 (읽기 전용) ==")
    for k in ["credit_rows", "unparsed", "parsed", "no_collector_match",
              "ambiguous_name_skipped", "matched", "already_linked", "new_link"]:
        print(f"{k:24s} {stat[k]:>9,}")
    print(f"{'distinct_donors_matched':24s} {len(donors):>9,}")
    print(f"{'donors_in_2plus_museums':24s} {multi:>9,}")
    top = sorted(donors.items(), key=lambda kv: -kv[1]["works"])[:8]
    cur.execute("select id, name from collectors where id = any(%s::uuid[])", ([k for k, _ in top],))
    nm = dict(cur.fetchall())
    print("-- 작품 수 상위 기증자(매칭) --")
    for cid, d in top:
        print(f"{nm.get(cid)}  works={d['works']} museums={len(d['museums'])}")
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"stat": dict(stat), "distinct_donors": len(donors), "multi_museum": multi},
            ensure_ascii=False, indent=1), encoding="utf-8")
    conn.close()


if __name__ == "__main__":
    main()
