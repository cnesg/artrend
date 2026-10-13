"""artgraph_v2 DB -> 목록 내보내기 (v2/exports/).

    python v2/export.py

  참가기록_2016-2026.csv   참가 1건 = 1행 (비엔날레·페어 공통, 페어는 갤러리·부스 포함)
  작가별집계_2016-2026.csv  작가 1명 = 1행 (비엔날레 회차 수, 페어 회차 수, 이력)
  갤러리별집계_2016-2026.csv 갤러리 1곳 = 1행 (페어 회차 수, 출품작가 수, 이력)
  요약_2016-2026.md         회차별 확보율 + 다회 참가 작가 + 비엔날레·페어 교차 작가
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import V2_ROOT, get_conn  # noqa: E402

OUT = V2_ROOT / "exports"

PARTICIPATIONS_SQL = """
select s.kind, s.name as series, s.name_ko as series_ko, e.id as edition_id, e.label, e.year, e.start_date,
       a.id as artist_id, a.name, a.name_ko, a.name_en, a.kind as artist_kind, a.birth_year,
       a.birth_year_source, a.death_year,
       p.section, g.name as gallery, fb.booth, p.name_as_listed, p.country_as_listed,
       src.url as source_url, src.source_tier
from participations p
join editions e on e.id = p.edition_id
join series s on s.id = e.series_id
join artists a on a.id = p.artist_id
left join fair_booths fb on fb.id = p.booth_id
left join galleries g on g.id = fb.gallery_id
left join sources src on src.id = p.source_id
order by s.kind, s.name, e.year, a.name, g.name nulls first
"""

EDITION_SQL = """
select s.kind, s.name, s.name_ko, e.id, e.label, e.year, e.announced_count, e.coverage, e.coverage_note,
       count(distinct p.artist_id) as artists, count(distinct fb.id) as booths,
       string_agg(distinct src.source_tier, ',') as tiers
from editions e join series s on s.id = e.series_id
left join participations p on p.edition_id = e.id
left join fair_booths fb on fb.edition_id = e.id
left join sources src on src.id = p.source_id
group by 1,2,3,4,5,6,7,8,9 order by 1, 2, 6
"""


GALLERY_SQL = """
select g.id, g.name, g.name_ko, g.name_en, g.city, count(distinct fb.edition_id) as n_editions,
       count(distinct p.artist_id) as n_artists,
       string_agg(distinct coalesce(s.name_ko, s.name) || ' ' || e.year, '; ') as hist
from galleries g
join fair_booths fb on fb.gallery_id = g.id
join editions e on e.id = fb.edition_id
join series s on s.id = e.series_id
left join participations p on p.booth_id = fb.id
group by g.id order by n_editions desc, n_artists desc, g.name
"""


def display(r: dict) -> str:
    return r["name"] + (f" ({r['name_ko']})" if r.get("name_ko") and r["name_ko"] != r["name"] else "")


def history(a: dict) -> str:
    return ", ".join(sorted(a["hist"], key=lambda h: (h[-4:], h)))


def main():
    OUT.mkdir(exist_ok=True)
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(PARTICIPATIONS_SQL)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    with (OUT / "참가기록_2016-2026.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["구분", "시리즈", "회차", "연도", "작가", "한글명", "영문명", "작가유형", "출생연도",
                    "섹션", "갤러리", "부스", "명단표기", "명단국가", "출처URL", "출처등급", "artist_id"])
        for r in rows:
            w.writerow(["비엔날레" if r["kind"] == "biennale" else "아트페어", r["series"], r["label"], r["year"],
                        r["name"], r["name_ko"] or "", r["name_en"] or "", r["artist_kind"], r["birth_year"] or "",
                        r["section"], r["gallery"] or "", r["booth"] or "", r["name_as_listed"],
                        r["country_as_listed"] or "", r["source_url"] or "", r["source_tier"] or "", r["artist_id"]])

    by_artist: dict[str, dict] = {}
    for r in rows:
        a = by_artist.setdefault(r["artist_id"], {"r": r, "bi": set(), "fair": set(), "hist": set()})
        key = (r["series"], r["year"])
        (a["bi"] if r["kind"] == "biennale" else a["fair"]).add(key)
        a["hist"].add(f"{r['series_ko'] or r['series']} {r['year']}")
    artists = sorted(by_artist.values(), key=lambda a: (-len(a["bi"]), -len(a["fair"]), a["r"]["name"]))
    with (OUT / "작가별집계_2016-2026.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["작가", "한글명", "영문명", "작가유형", "출생연도", "사망연도", "출생연도_출처", "비엔날레_회차수",
                    "아트페어_회차수", "첫참가연도", "최근참가연도", "이력", "artist_id"])
        for a in artists:
            r = a["r"]
            years = [y for _, y in a["bi"] | a["fair"]]
            w.writerow([r["name"], r["name_ko"] or "", r["name_en"] or "", r["artist_kind"], r["birth_year"] or "",
                        r["death_year"] or "", r["birth_year_source"] or "", len(a["bi"]), len(a["fair"]), min(years), max(years),
                        "; ".join(sorted(a["hist"], key=lambda h: (h[-4:], h))), r["artist_id"]])

    cur.execute(GALLERY_SQL)
    with (OUT / "갤러리별집계_2016-2026.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["갤러리", "한글명", "영문명", "도시", "페어_회차수", "출품작가수", "이력", "gallery_id"])
        for r in cur.fetchall():
            w.writerow([r[1], r[2] or "", r[3] or "", r[4] or "", r[5], r[6], r[7], r[0]])

    cur.execute(EDITION_SQL)
    eds = cur.fetchall()
    has_frieze = any(e[3].startswith("frieze_") for e in eds)
    lines = ["# 비엔날레·아트페어 참가작가 2016–2026 (아트그래프 v2)", "",
             f"생성 {datetime.now():%Y-%m-%d %H:%M} · `python v2/export.py` · DB `artgraph_v2`", "",
             f"- 참가 기록 {len(rows):,}건, 고유 작가 {len(by_artist):,}명",
             f"- 비엔날레 2회차 이상 참가 {sum(1 for a in artists if len(a['bi']) >= 2):,}명, "
             f"3회차 이상 {sum(1 for a in artists if len(a['bi']) >= 3):,}명", "",
             "범위: 비엔날레는 본전시만(베니스 국가관·병행전 제외), 아트페어는 갤러리 부스별 출품작가. "
             "확보율 `partial`은 공식 명단 자체가 공표 인원보다 적은 회차, 페어는 부스별 출품작가가 공개되지 "
             "않은 회차(갤러리 목록·특별전만) — 아래 메모 참고.", "",
             *(["> **프리즈 데이터는 내부 연구용**: frieze.com 이용약관이 서면 허가 없는 수집을 금지한다. "
                "웨이백 사본·공식 보도자료 PDF로 받았으며 외부 공개·상업 이용 시 프리즈 분을 빼거나 허가를 먼저 받을 것.", ""]
               if has_frieze else []),
             "## 회차별", "", "| 구분 | 시리즈 | 회차 | 연도 | 작가 | 부스 | 공표 | 확보 | 출처 |",
             "|---|---|---|---|---:|---:|---:|---|---|"]
    for kind, name, name_ko, eid, label, year, ann, cov, note, n_art, n_booth, tiers in eds:
        lines.append(f"| {'비엔날레' if kind == 'biennale' else '페어'} | {name_ko or name} | {label} | {year} | "
                     f"{n_art} | {n_booth or ''} | {ann or '—'} | {cov or '—'} | {tiers or '—'} |")
    partial = [(label, note) for kind, name, name_ko, eid, label, year, ann, cov, note, *_ in eds if cov != "complete"]
    if partial:
        lines += ["", "### 확보율 메모 (complete 아닌 회차)", ""]
        lines += [f"- **{label}** — {(note or '').strip()[:300]}" for label, note in partial]
    top = [a for a in artists if len(a["bi"]) >= 3]
    lines += ["", f"## 비엔날레 3회차 이상 참가 작가 ({len(top)}명)", "", "| 작가 | 출생 | 비엔날레 | 페어 | 이력 |",
              "|---|---|---:|---:|---|"]
    for a in top:
        r = a["r"]
        lines.append(f"| {display(r)} | {r['birth_year'] or ''} | {len(a['bi'])} | {len(a['fair'])} | {history(a)} |")
    young = [a for a in artists if len(a["bi"]) >= 2 and (a["r"]["birth_year"] or 0) >= 1980]
    n_birth = sum(1 for a in artists if a["r"]["birth_year"])
    lines += ["", f"## 1980년 이후 출생 · 비엔날레 2회차 이상 ({len(young)}명)", "",
              f"출생연도는 {n_birth:,}/{len(artists):,}명({n_birth / len(artists):.0%})만 확인됨 — 명단 원문 > Wikidata(QID) > "
              "Wikidata(이름 정확일치·작가 직업·동명인 2명 이하) > v1 순, 출처는 작가별집계 CSV `출생연도_출처`.", "",
              "| 작가 | 출생 | 비엔날레 | 페어 | 이력 |", "|---|---|---:|---:|---|"]
    for a in young:
        r = a["r"]
        lines.append(f"| {display(r)} | {r['birth_year']} | {len(a['bi'])} | {len(a['fair'])} | {history(a)} |")
    cross = [a for a in artists if a["bi"] and a["fair"]]
    cross2 = [a for a in cross if len(a["bi"]) >= 2]
    lines += ["", f"## 비엔날레와 아트페어 모두 등장한 작가 ({len(cross)}명 중 비엔날레 2회차 이상 {len(cross2)}명)", "",
              "제도권(비엔날레)과 시장(페어 부스) 양쪽에 잡힌 작가. 페어는 부스 작가가 공개된 회차만 반영돼 과소집계다.", "",
              "| 작가 | 출생 | 비엔날레 | 페어 | 이력 |", "|---|---|---:|---:|---|"]
    for a in cross2:
        r = a["r"]
        lines.append(f"| {display(r)} | {r['birth_year'] or ''} | {len(a['bi'])} | {len(a['fair'])} | {history(a)} |")
    (OUT / "요약_2016-2026.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"rows={len(rows)} artists={len(by_artist)} -> {OUT}")


if __name__ == "__main__":
    main()
