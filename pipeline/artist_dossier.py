"""작가 완결도(dossier) + 결손 진단 — 2026-09-17 '쓸만해지는 길: 깊이 한 축' 착수.

한 작가를 기준으로 5개 축(소장·경매·전시·사건·갤러리 전속)과 정체성(생몰·국적·약력·authority)을
한 번에 모아, 근거 인용 Q&A가 실제로 완결되는지 / 어디가 비었는지 보여준다. 읽기 전용.

사용:
    python pipeline/artist_dossier.py "이우환"          # 한 작가 완결 리포트 + 결손 스코어카드
    python pipeline/artist_dossier.py --coverage-kr      # 한국 작가 전체 축별 커버리지 통계
    python pipeline/artist_dossier.py --coverage-kr --top 30   # 완결도 상위 30명(깊이 확장 후보)
    python pipeline/artist_dossier.py "이우환" --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import get_connection  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# 완결도 = 채워진 축 수(정체성 3 + 관계 5). Q&A가 근거를 댈 수 있는 필드 기준.
AXES = ["birth", "nationality", "bio", "authority", "holdings", "auctions", "exhibitions", "events", "gallery"]


def resolve_artist(cur, q: str) -> tuple[str, str] | None:
    """이름/영문명 정확일치(person)로 작가 1명 해석. 여럿이면 소장+경매 많은 쪽."""
    cur.execute(
        """select id::text, name from artists
           where entity_kind='person' and (lower(name)=lower(%s) or lower(name_en)=lower(%s))
           order by (select count(*) from artworks aw
                     left join museum_holdings mh on mh.artwork_id=aw.id
                     left join auction_lots al on al.artwork_id=aw.id
                     where aw.artist_id=artists.id) desc
           limit 1""",
        (q, q),
    )
    return cur.fetchone()


def dossier(cur, aid: str) -> dict:
    cur.execute(
        "select name, name_en, birth_year, death_year, nationality, bio, ulan_id, wikidata_qid, authority_source "
        "from artists where id=%s",
        (aid,),
    )
    name, name_en, by, dy, nat, bio, ulan, qid, asrc = cur.fetchone()
    d: dict = {
        "id": aid, "name": name, "name_en": name_en, "birth_year": by, "death_year": dy,
        "nationality": nat, "bio_len": len(bio) if bio else 0,
        "ulan_id": ulan, "wikidata_qid": qid, "authority_source": asrc,
    }
    cur.execute("select count(*) from artist_bio_generated where artist_id=%s", (aid,))
    d["bio_generated"] = cur.fetchone()[0]

    # 소장 (artworks.artist_id -> museum_holdings -> museums)
    cur.execute(
        """select m.name, count(*) from artworks aw
           join museum_holdings mh on mh.artwork_id=aw.id
           join museums m on m.id=mh.museum_id
           where aw.artist_id=%s group by m.name order by count(*) desc""",
        (aid,),
    )
    hold = cur.fetchall()
    d["holdings_total"] = sum(c for _, c in hold)
    d["holdings_by_museum"] = [(n, c) for n, c in hold]

    # 경매 (artworks.artist_id -> auction_lots -> auctions -> auction_houses)
    cur.execute(
        """select ah.name, count(*), max(al.hammer_price) from artworks aw
           join auction_lots al on al.artwork_id=aw.id
           join auctions au on au.id=al.auction_id
           join auction_houses ah on ah.id=au.auction_house_id
           where aw.artist_id=%s group by ah.name order by count(*) desc""",
        (aid,),
    )
    au = cur.fetchall()
    d["auctions_total"] = sum(c for _, c, _ in au)
    d["auctions_by_house"] = [(n, c) for n, c, _ in au]

    # 전시
    cur.execute(
        """select e.title, e.venue_name, e.start_date from exhibition_artists ea
           join exhibitions e on e.id=ea.exhibition_id
           where ea.artist_id=%s order by e.start_date desc nulls last limit 200""",
        (aid,),
    )
    exh = cur.fetchall()
    d["exhibitions_total"] = len(exh)
    d["exhibitions_recent"] = [(t, v, str(s) if s else None) for t, v, s in exh[:5]]

    # 사건 (수상/사망 등)
    cur.execute("select event_kind, count(*) from artist_events where artist_id=%s group by event_kind", (aid,))
    ev = cur.fetchall()
    d["events_total"] = sum(c for _, c in ev)
    d["events_by_kind"] = dict(ev)

    # 갤러리 전속
    cur.execute(
        """select g.name from gallery_representations gr
           join galleries g on g.id=gr.gallery_id where gr.artist_id=%s""",
        (aid,),
    )
    d["galleries"] = [r[0] for r in cur.fetchall()]

    # 완결도 스코어카드
    present = {
        "birth": by is not None,
        "nationality": bool(nat),
        "bio": d["bio_len"] > 0,
        "authority": bool(ulan or qid),
        "holdings": d["holdings_total"] > 0,
        "auctions": d["auctions_total"] > 0,
        "exhibitions": d["exhibitions_total"] > 0,
        "events": d["events_total"] > 0,
        "gallery": len(d["galleries"]) > 0,
    }
    d["axes_present"] = present
    d["completeness"] = sum(present.values())
    d["missing"] = [k for k, v in present.items() if not v]
    return d


def print_dossier(d: dict) -> None:
    print(f"\n=== {d['name']} ({d.get('name_en') or '-'}) — 완결도 {d['completeness']}/9 ===")
    print(f"생몰 {d['birth_year']}~{d['death_year']} · 국적 {d['nationality'] or '(없음)'} · "
          f"ULAN {d['ulan_id'] or '-'} · QID {d['wikidata_qid'] or '-'}")
    print(f"약력 원본 {d['bio_len']}자 · 생성약력 {d['bio_generated']}건(격리)")
    print(f"소장 {d['holdings_total']}건" + (f" → {', '.join(f'{n} {c}' for n, c in d['holdings_by_museum'][:5])}" if d['holdings_by_museum'] else ""))
    print(f"경매 {d['auctions_total']}건" + (f" → {', '.join(f'{n} {c}' for n, c in d['auctions_by_house'][:5])}" if d['auctions_by_house'] else ""))
    print(f"전시 {d['exhibitions_total']}건" + (f" → 최근: {d['exhibitions_recent'][0][0]}" if d['exhibitions_recent'] else ""))
    print(f"사건 {d['events_total']}건 {d['events_by_kind'] or ''}")
    print(f"갤러리 전속 {len(d['galleries'])}곳 {d['galleries'] or ''}")
    print(f"결손 축: {', '.join(d['missing']) if d['missing'] else '없음 (완결)'}")


def coverage_kr(cur, top: int | None) -> dict:
    """한국 작가(국적 Korean 또는 한글 이름) person 전체의 축별 커버리지."""
    cur.execute(
        r"""select id::text, name from artists
            where entity_kind='person'
              and (nationality ilike '%%korea%%' or nationality='한국' or name ~ '[가-힣]')
        """
    )
    rows = cur.fetchall()
    tally = {a: 0 for a in AXES}
    scored = []
    for aid, name in rows:
        d = dossier(cur, aid)
        for a, v in d["axes_present"].items():
            tally[a] += 1 if v else 0
        scored.append((d["completeness"], name, d["holdings_total"], d["auctions_total"],
                       d["exhibitions_total"], d["events_total"], len(d["galleries"])))
    n = len(rows)
    scored.sort(reverse=True)
    print(f"\n=== 한국 작가 커버리지 (n={n}) ===")
    for a in AXES:
        print(f"  {a:12} {tally[a]:6}  ({100*tally[a]//n if n else 0}%)")
    print(f"\n=== 완결도 상위 {top or 20} (깊이 확장 후보) ===")
    print(f"  {'완결':>2} {'소장':>5} {'경매':>4} {'전시':>4} {'사건':>4} {'전속':>4}  작가")
    for c, name, h, au, ex, ev, g in scored[: (top or 20)]:
        print(f"  {c:>2}/9 {h:>5} {au:>4} {ex:>4} {ev:>4} {g:>4}  {name}")
    return {"n": n, "tally": tally, "top": scored[: (top or 20)]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", help="작가 이름")
    ap.add_argument("--coverage-kr", action="store_true", help="한국 작가 전체 축별 커버리지")
    ap.add_argument("--top", type=int, default=None)
    ap.add_argument("--json", help="결과 JSON 저장")
    args = ap.parse_args()
    conn = get_connection()
    cur = conn.cursor()

    if args.coverage_kr:
        res = coverage_kr(cur, args.top)
        if args.json:
            Path(args.json).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    if not args.query:
        ap.error("작가 이름 또는 --coverage-kr 필요")
    r = resolve_artist(cur, args.query)
    if not r:
        print(f"'{args.query}' person 작가를 정확일치로 못 찾음")
        return
    d = dossier(cur, r[0])
    print_dossier(d)
    if args.json:
        Path(args.json).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
