"""작가 허브 — 한 작가를 소장·경매·갤러리·전시·사건 축으로 묶고, 각 줄마다 근거 URL을 붙여 보여 준다.

읽기 전용(DB 변경 없음). 질의 응답의 "경로 답변"(작가→작품→소장처/경매→출처)용 원형이며,
build_curated_vault/artgraph_chat에 붙이기 전에 형태를 검증하는 용도다.

    python pipeline/artist_hub.py --name "Rembrandt" [--max-evidence 3]
    python pipeline/artist_hub.py --id <uuid>
    python pipeline/artist_hub.py --top 20          # 4축(소장·경매·갤러리·전시) 연결 수 상위 작가 후보

규칙: 이름 검색이 여러 명이면 병합하지 않고 후보만 나열한다. 생성 약력은 [AI 생성, 미검증]으로 구분.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import get_connection  # noqa: E402


def find(cur, name):
    cur.execute("""select id, name, name_en, birth_year, death_year, entity_kind,
                          (select count(*) from artworks w where w.artist_id = a.id) n
                   from artists a
                   where lower(name_en) = lower(%s) or lower(name) = lower(%s)
                   order by n desc limit 8""", (name, name))
    rows = cur.fetchall()
    if not rows:
        cur.execute("""select id, name, name_en, birth_year, death_year, entity_kind,
                              (select count(*) from artworks w where w.artist_id = a.id) n
                       from artists a where name_en ilike %s or name ilike %s
                       order by n desc limit 8""", (f"%{name}%", f"%{name}%"))
        rows = cur.fetchall()
    return rows


def hub(cur, aid, k=3):
    out = {}
    cur.execute("""select name, name_en, birth_year, death_year, nationality, entity_kind,
                          ulan_id, wikidata_qid, bio_source, left(bio, 300)
                   from artists where id = %s""", (aid,))
    out["id"] = cur.fetchone()
    cur.execute("select left(bio, 300) from artist_bio_generated where artist_id = %s", (aid,))
    g = cur.fetchone()
    out["gen_bio"] = g[0] if g else None

    cur.execute("""select m.name, m.country, count(*) from artworks w
                   join museum_holdings h on h.artwork_id = w.id
                   join museums m on m.id = h.museum_id
                   where w.artist_id = %s group by 1, 2 order by 3 desc limit 10""", (aid,))
    out["museums"] = cur.fetchall()
    cur.execute("""select w.title, w.year_created, m.name, h.accession_number, s.site_name, s.url
                   from artworks w join museum_holdings h on h.artwork_id = w.id
                   join museums m on m.id = h.museum_id
                   left join sources s on s.id = h.source_id
                   where w.artist_id = %s order by w.year_created nulls last limit %s""", (aid, k))
    out["hold_ev"] = cur.fetchall()

    cur.execute("""select count(*), count(l.hammer_price), min(a.auction_date), max(a.auction_date),
                          count(distinct a.id) from auction_lots l
                   join artworks w on w.id = l.artwork_id join auctions a on a.id = l.auction_id
                   where w.artist_id = %s""", (aid,))
    out["lots"] = cur.fetchone()
    cur.execute("""select l.currency, count(*), min(l.hammer_price), max(l.hammer_price),
                          percentile_cont(0.5) within group (order by l.hammer_price)
                   from auction_lots l join artworks w on w.id = l.artwork_id
                   where w.artist_id = %s and l.hammer_price > 0 group by 1 order by 2 desc limit 4""",
                (aid,))
    out["prices"] = cur.fetchall()
    cur.execute("""select h.name, count(*) from auction_lots l join artworks w on w.id = l.artwork_id
                   join auctions a on a.id = l.auction_id join auction_houses h on h.id = a.auction_house_id
                   where w.artist_id = %s group by 1 order by 2 desc limit 5""", (aid,))
    out["houses"] = cur.fetchall()
    cur.execute("""select w.title, a.auction_date, h.name, l.lot_number, l.hammer_price, l.currency,
                          s.url, s.fetched_at
                   from auction_lots l join artworks w on w.id = l.artwork_id
                   join auctions a on a.id = l.auction_id join auction_houses h on h.id = a.auction_house_id
                   left join sources s on s.id = l.source_id
                   where w.artist_id = %s and l.hammer_price > 0
                   order by l.price_usd desc nulls last, l.hammer_price desc limit %s""", (aid, k))
    out["lot_ev"] = cur.fetchall()

    cur.execute("""select g.name, g.city, gr.start_date, gr.end_date from gallery_representations gr
                   join galleries g on g.id = gr.gallery_id where gr.artist_id = %s limit 8""", (aid,))
    out["galleries"] = cur.fetchall()
    cur.execute("""select e.title, e.venue_name, e.start_date, e.url from exhibition_artists ea
                   join exhibitions e on e.id = ea.exhibition_id where ea.artist_id = %s
                   order by e.start_date desc nulls last limit 6""", (aid,))
    out["exhibitions"] = cur.fetchall()
    cur.execute("""select event_kind, event_date, left(detail, 90), url from artist_events
                   where artist_id = %s order by event_date desc nulls last limit 6""", (aid,))
    out["events"] = cur.fetchall()
    return out


def render(h):
    n, ne, by, dy, nat, kind, ulan, qid, bsrc, bio = h["id"]
    L = [f"# {n}" + (f" / {ne}" if ne and ne != n else ""),
         f"{by or '?'}–{dy or ''} · {nat or '국적 미상'} · {kind}"
         f" · ULAN {ulan or '-'} · Wikidata {qid or '-'}"]
    if bio:
        L.append(f"약력(원본 — AI 생성 아님{', 출처 ' + bsrc if bsrc else ''}): {bio}")
    elif h["gen_bio"]:
        L.append(f"약력 [AI 생성, 미검증]: {h['gen_bio']}")
    L.append("\n## 소장 (미술관 → 작품 수)")
    L += [f"- {m} ({c or '-'}): {k}점" for m, c, k in h["museums"]] or ["- 없음"]
    for t, y, m, acc, site, url in h["hold_ev"]:
        L.append(f"  · 근거: 《{t}》{y or ''} · {m} {acc or ''} — {site} {url or ''}")
    cnt, priced, d0, d1, nauc = h["lots"]
    L.append(f"\n## 경매 (로트 {cnt:,}건 · 경매 {nauc:,}회 · 낙찰가 있는 {priced:,}건 · {d0}~{d1})")
    L += [f"- {cur}: {c:,}건, 중앙값 {med:,.0f} (최저 {lo:,.0f} ~ 최고 {hi:,.0f}) [원 통화 그대로]"
          for cur, c, lo, hi, med in h["prices"]]
    L += [f"- 주요 경매사: {', '.join(f'{n} {c:,}' for n, c in h['houses'])}"] if h["houses"] else []
    for t, d, hn, lot, hp, cu, url, fa in h["lot_ev"]:
        L.append(f"  · 근거: 《{t}》 {hn} {d} lot {lot} {hp:,.0f} {cu} — {url or ''} (수집 {str(fa)[:10]})")
    L.append("\n## 갤러리 전속")
    # start_date는 로스터 수집일이라 실제 전속 시작일이 아니다 → 표기하지 않고 "수집 기준 현재 로스터"로만 쓴다
    L += [f"- {g} ({c or '-'}) [수집 시점 로스터]" for g, c, s, e in h["galleries"]] or ["- 없음"]
    L.append("\n## 전시")
    L += [f"- {t} @ {v or '-'} {s or ''} {u or ''}" for t, v, s, u in h["exhibitions"]] or ["- 없음"]
    L.append("\n## 사건")
    L += [f"- {k} {d or ''}: {dt} {u or ''}" for k, d, dt, u in h["events"]] or ["- 없음"]
    return "\n".join(L)


def top(cur, n):
    cur.execute("""with ax as (
      select a.id, a.name,
        exists(select 1 from artworks w join museum_holdings h on h.artwork_id = w.id where w.artist_id = a.id) hd,
        exists(select 1 from artworks w join auction_lots l on l.artwork_id = w.id where w.artist_id = a.id) au,
        exists(select 1 from gallery_representations g where g.artist_id = a.id) ga,
        exists(select 1 from exhibition_artists e where e.artist_id = a.id) ex
      from artists a where a.entity_kind = 'person' and (a.ulan_id is not null or a.wikidata_qid is not null))
      select id, name, hd::int + au::int + ga::int + ex::int s from ax
      where hd::int + au::int + ga::int + ex::int >= 4 limit %s""", (n,))
    return cur.fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name")
    ap.add_argument("--id")
    ap.add_argument("--top", type=int)
    ap.add_argument("--max-evidence", type=int, default=3)
    a = ap.parse_args()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("set statement_timeout='300s'")
    if a.top:
        for i, nm, s in top(cur, a.top):
            print(i, nm, s)
        return
    aid = a.id
    if a.name:
        rows = find(cur, a.name)
        if not rows:
            print("후보 없음")
            return
        if len(rows) > 1:
            print("후보(병합하지 않음, 작품 수 순):")
            for r in rows:
                print("  ", *r)
        aid = rows[0][0]
    print(render(hub(cur, aid, a.max_evidence)))
    conn.close()


if __name__ == "__main__":
    main()
