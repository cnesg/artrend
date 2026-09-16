"""'Park Seo-Bo 박서보'처럼 로마자+한글이 한 이름에 든 갤러리 로스터 작가 행을 기존 한글 이름 행과 Wikidata QID로 묶기 (2026-09-16).

문자열이 같다는 이유로 합치지 않는다. M6-c(link_korean_artists_wikidata)와 같은 규칙: 한글 라벨로 Wikidata 후보를 찾아
미술가 직업·한국 국적·유일 후보일 때만 QID를 (기존 한글 행, 혼합 행) 양쪽에 부여(기존 QID가 있으면 같을 때만),
로마자 부분의 성(첫 토큰 또는 마지막 토큰)이 영문 라벨에 있어야 한다. 그 뒤 merge_by_authority.py --apply 로 병합한다.
기본: 리포트   --apply: QID 부여 + merge_by_authority 실행.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from artist_merge_util import get_conn  # noqa: E402
from link_korean_artists_wikidata import KOREA, OCCUPATIONS, QUERY, SITE_NAME, sparql  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "crawlers"))
from common import already_fetched, save_raw  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
RAW = Path(__file__).resolve().parent.parent / "crawlers" / "raw" / SITE_NAME
MIXED_RE = re.compile(r"^([A-Za-z][A-Za-z .,'-]+?)\s+([가-힣]+)$")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("select id::text, name, wikidata_qid from artists where entity_kind = 'person' and name ~ '^[A-Za-z][A-Za-z .,''-]+ [가-힣]+$'")
    pairs = []
    for aid, name, qid in cur.fetchall():
        m = MIXED_RE.match(name)
        if not m or re.search(r"\b[A-Z]\.\s*$", m.group(1)):  # 'H. A. 카루나라트네' 같은 이니셜 표기는 제외
            continue
        latin, hang = m.group(1).strip(" ,"), m.group(2)
        cur.execute("select id::text, wikidata_qid from artists where name = %s and entity_kind = 'person'", (hang,))
        other = cur.fetchone()
        if other:
            pairs.append((aid, name, qid, latin, hang, other[0], other[1]))
    names = sorted({p[4] for p in pairs})
    key = "mixed_" + "_".join(str(len(names)) for _ in [0])
    if not already_fetched(SITE_NAME, key):
        values = " ".join('"' + k + '"@ko' for k in names)
        rows = sparql(QUERY.format(values=values, occs=" ".join(f"wd:{q}" for q in OCCUPATIONS)))
        save_raw(SITE_NAME, key, json.dumps({"names": names, "rows": rows}, ensure_ascii=False), url="https://query.wikidata.org/sparql",
                 license_note="Wikidata CC0 1.0")
    rows = json.load(open(RAW / f"{key}.json", encoding="utf-8"))["rows"]
    cands: dict[str, dict] = {}
    for r in rows:
        cs = set(r["countries"].replace("http://www.wikidata.org/entity/", "").split(",")) if r.get("countries") else set()
        if cs and not cs & KOREA:
            continue
        cands.setdefault(r["ko"], {})[r["item"].rsplit("/", 1)[-1]] = r
    plan, skipped = [], []
    for aid, name, qid, latin, hang, oid, oqid in pairs:
        c = cands.get(hang, {})
        toks = [t.lower() for t in re.split(r"[\s,-]+", latin) if len(t) > 1]
        if len(c) > 1:
            c = {q: r for q, r in c.items() if any(t in (r.get("en") or "").lower().replace("-", " ").split() for t in toks)}
        if len(c) != 1:
            skipped.append((name, "후보 %d" % len(c)))
            continue
        (wq, r), = c.items()
        en = (r.get("en") or "").lower().replace("-", " ").split()
        if not any(t in en for t in toks):
            skipped.append((name, f"성 불일치 {r.get('en')}"))
            continue
        if (qid and qid != wq) or (oqid and oqid != wq):
            skipped.append((name, f"기존 QID 상이 {qid}/{oqid} vs {wq}"))
            continue
        plan.append((wq, aid, oid, name, hang, r.get("en")))
    print(f"혼합 이름 {len(pairs)} → 연결 {len(plan)} / 보류 {len(skipped)}")
    for p in plan:
        print("  ", p[3], "+", p[4], "→", p[0], p[5])
    print("  보류:", skipped)
    if not args.apply:
        print("--apply 없음: 리포트만")
        return
    for wq, aid, oid, name, hang, en in plan:
        cur.execute("update artists set wikidata_qid = coalesce(wikidata_qid, %s), authority_source = coalesce(authority_source, 'wikidata_korean_label'), updated_at = now() where id in (%s, %s)", (wq, aid, oid))
    conn.commit()
    print("QID 부여 완료 → merge_by_authority.py --apply 실행")
    subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "merge_by_authority.py"), "--apply"], check=True)


if __name__ == "__main__":
    main()
