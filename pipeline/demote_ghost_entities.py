"""유령 1급 엔티티 강등 — museums/auction_houses/galleries (2026-09-15 작업분담 §M5, 진단 §3-2-4).

`provenance_extract.py`가 크레딧라인 문자열을 museums/galleries/auction_houses 행으로 승격시킨
결과, 소장(museum_holdings)·경매(auctions)·로스터(gallery_representations) 실데이터가 전혀 없는
행이 museums 197 / auction_houses 343 / galleries 1,680개 있다. 전부 지우면 안 된다 —
"British Museum"·"Galerie Louise Leiris"·"Koller Auktionen AG"처럼 프로버넌스 체인에 등장하는
실존 기관은 실데이터가 없어도 1급 엔티티가 맞다. 따라서 이름 형태로 3분류한다:

  keep     — 기관명으로 성립(기관 키워드 포함, 서술 구문 없음) → 그대로 둠
  unknown  — 문장 조각("Commissioned by the Museum", "Chance and is now in the Fitzwilliam Museum",
             "Hèle sale", "Dealer", "Florentine dealer or private") → provenance_records.owner_type='unknown'
             (+ note 앞에 "[원문 owner] …" 보존) 후 행 삭제
  collector — 기관 키워드는 없지만 이름으로는 성립(회사 "Industrial Petro-Chemicals Inc",
             개인 "Mrs. F. C. Phillips") → collectors(is_institution=회사 여부)로 재연결 후 행 삭제

기본 리포트(분류별 건수·샘플), --apply 시 반영 + docs/logs/에 삭제 로그 JSON. idempotent.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from artist_merge_util import get_conn

sys.stdout.reconfigure(encoding="utf-8")
LOG_DIR = Path(__file__).resolve().parent.parent / "docs" / "logs"

FRAGMENT_RE = re.compile(
    r"\b(?:to the|to|and is|is now|was|were|purchase[d]?|purchasing|commissioned|gift of|through|via|"
    r"inaugurates|acquired|presented|bequest|donated|sold|bought|lent|on loan|on behalf of|with funds|out of funds|"
    r"to celebrate|by direction|by exchange|in memory of|in honor of|in honour of|matching funds)\b"
    r"|\bsale\b|^(?:dealer|dealers|private|anonymous|unknown)\b|\bor private\b|[:;]",
    re.I,
)
LOWER_START_RE = re.compile(r"^[a-z]")  # 대소문자 구분 — 소문자로 시작하면 문장 조각
INSTITUTION_NOUN_RE = re.compile(
    r"\b(?:funds?|council|friends|society|committee|associates|foundation|trust|endowment|staff|program|proceeds|"
    r"association|department|institute|corporation|"
    r"patrons|members|guild|club|league|circle of friends|acquisition fund|purchase fund)\b",
    re.I,
)
KEEP_WHITELIST = {"albertina", "kiasma", "국립중앙박물관"}
MUSEUM_KW = re.compile(
    r"\b(?:museum|museo|musée|musee|museu|museet|muzeum|muzej|museum of|gallery of art|national gallery|kunsthalle|"
    r"kunstmuseum|kunsthaus|rijksmuseum|pinakothek|galleria|galerie nationale|art institute|institute of arts?|"
    r"collection|foundation|fondation|fondazione|stiftung|palace|palais|castle|schloss|library|bibliothèque|"
    r"archive|academy|university|college|cathedral|church|abbey|temple|shrine|center|centre)\b"
    r"|미술관|박물관|컬렉션|美術館|博物館",
    re.I,
)
GALLERY_KW = re.compile(
    r"\b(?:gallery|galleries|galerie|galeria|galleria|kunsthandel|kunsthandlung|fine arts?|art dealers?|dealers?|"
    r"antiquaire|antiques?|rare books|booksellers?|editions?|éditions|art|arts|kunst|works of art|old masters?|"
    r"& (?:co|cie|fils|sons?)\b|and (?:co|sons?)\b|ltd|inc|gmbh|associates|partners)\b",
    re.I,
)
HOUSE_KW = re.compile(
    r"(?:\bauction\w*|\bauktion\w*|\bauctioneers?\b|\benchères\b|\bencheres\b|\bveiling\w*|\bsalerooms?\b|\bsale room\b|"
    r"\bchristie[’']?s?\b|\bsotheby[’']?s?\b|\bbonhams?\b|\bphillips de pury\b|\bdorotheum\b|\blempertz\b|\bkoller\b|"
    r"\bhindman\b|\bswann\b|\bheritage auctions\b|\bdrouot\b|\btajan\b|\bartcurial\b|\bpiasa\b|\bketterer\b|"
    r"\bgrisebach\b|\bvan ham\b|\bneumeister\b|\bbukowskis\b|\bbruun rasmussen\b|\blyon & turnbull\b|\bdreweatts?\b|"
    r"\btennants\b|\bcheffins\b|\bsworders\b|\bhampel\b|\bhargesheimer\b|\bim kinsky\b|\baguttes\b|\bbinoche\b|"
    r"\bcornette\b|\bparke-?bernet\b|\bamerican art association\b|\banderson galleries\b|\bbutterfields?\b|"
    r"\bweschler\b|\bsloans?\b|\bleslie hindman\b|\bbarridoff\b|\bseoul auction\b|\bk-?auction\b|\bmainichi\b|"
    r"\bshinwa\b|\bchina guardian\b|\bkunstauktionen\b|\bgallery auction\b|\bauction galleries\b)",
    re.I,
)
PERSON_RE = re.compile(r"^(?:mr|mrs|ms|miss|dr|sir|lady|lord|madame|mme|mlle|monsieur|herr|frau)\.?\s", re.I)
COMPANY_RE = re.compile(r"\b(?:inc|ltd|llc|gmbh|corp|corporation|company|co\.|& co|and co|bros|brothers|& sons|and sons|fund|trust|foundation|society|association|committee|council|institute|department|ministry|bank|press|publishers?|verlag)\b\.?", re.I)


def bucket(kind: str, name: str) -> tuple[str, str]:
    n = " ".join(name.split())
    words = n.split()
    if n.lower() in KEEP_WHITELIST:
        return "keep", "whitelist"
    if FRAGMENT_RE.search(n) or LOWER_START_RE.match(n) or len(words) > 9 or len(n) < 3:
        return "unknown", "fragment"
    if INSTITUTION_NOUN_RE.search(n):
        return "collector_inst", "inst-noun"
    kw = {"museum": MUSEUM_KW, "gallery": GALLERY_KW, "house": HOUSE_KW}[kind]
    if kw.search(n):
        return "keep", "kw"
    if PERSON_RE.match(n):
        return "collector_person", "honorific"
    if COMPANY_RE.search(n):
        return "collector_inst", "company"
    # "John Goldsmith Phillips"처럼 2~4단어 고유명이면 개인으로 본다
    if 2 <= len(words) <= 4 and not re.search(r"[\d&/]", n):
        return "collector_person", "plain-name"
    return "collector_inst", "plain-name"


def load_targets(cur):
    cur.execute(
        """select 'museum', m.id::text, m.name from museums m
           where not exists (select 1 from museum_holdings h where h.museum_id = m.id)
           union all
           select 'house', h.id::text, h.name from auction_houses h
           where not exists (select 1 from auctions a where a.auction_house_id = h.id)
           union all
           select 'gallery', g.id::text, g.name from galleries g
           where not exists (select 1 from gallery_representations r where r.gallery_id = g.id)"""
    )
    return cur.fetchall()


OWNER_COL = {"museum": "owner_museum_id", "house": "owner_auction_house_id", "gallery": "owner_gallery_id"}
TABLE = {"museum": "museums", "house": "auction_houses", "gallery": "galleries"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sample", type=int, default=10)
    args = ap.parse_args()
    conn = get_conn()
    cur = conn.cursor()
    targets = load_targets(cur)
    counts = Counter()
    samples = defaultdict(list)
    plan = []
    for kind, eid, name in targets:
        b, why = bucket(kind, name)
        counts[(kind, b, why)] += 1
        if len(samples[(kind, b)]) < args.sample:
            samples[(kind, b)].append(name)
        if b != "keep":
            plan.append((kind, eid, name, b))
    print(f"대상 {len(targets)}건")
    for (kind, b, why), c in sorted(counts.items()):
        print(f"  {kind:8} {b:16} {why:12} {c:5}")
    for key, ss in samples.items():
        print(f"\n[{key[0]} / {key[1]}]")
        for s in ss:
            print("   ", s[:100])
    if not args.apply:
        print("\n--apply 없음: 리포트만")
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"ghost_entities_demoted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    log_path.write_text(json.dumps([dict(kind=k, id=i, name=n, bucket=b) for k, i, n, b in plan], ensure_ascii=False, indent=1), encoding="utf-8")
    done = Counter()
    for kind, eid, name, b in plan:
        col = OWNER_COL[kind]
        try:
            if b == "unknown":
                cur.execute(
                    f"""update provenance_records set owner_type = 'unknown', {col} = null,
                           note = concat('[원문 owner] ', %s, coalesce(' | ' || note, ''))
                        where {col} = %s""",
                    (name, eid),
                )
            else:
                is_inst = b == "collector_inst"
                cur.execute("select id from collectors where lower(name) = %s limit 1", (name.lower(),))
                row = cur.fetchone()
                if row:
                    cid = row[0]
                else:
                    cur.execute("insert into collectors (name, is_institution) values (%s, %s) returning id", (name, is_inst))
                    cid = cur.fetchone()[0]
                cur.execute(
                    f"""update provenance_records set owner_type = 'collector', owner_collector_id = %s, {col} = null
                        where {col} = %s""",
                    (cid, eid),
                )
            done[f"{kind}:{b}:records"] += cur.rowcount
            cur.execute(f"delete from {TABLE[kind]} where id = %s", (eid,))
            done[f"{kind}:{b}:deleted"] += cur.rowcount
            conn.commit()
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            print(f"  실패 {kind} {name!r}: {e}")
    print("완료:", dict(done), "로그:", log_path)


if __name__ == "__main__":
    main()
