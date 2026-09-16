"""R5-기관 — MMCA/부산시립미술관/경기도미술관 전시 raw -> exhibitions/exhibition_artists.

crawlers/mmca_exhibitions.py, busan_exhibitions.py, gmoma_exhibitions.py가
수집한 raw JSON을 정규화한다(리움/서울시립은 접근 실패로 보류 — 워커 로그
2026-09-15 참고).

메인 지시(2026-09-15 R5 규칙) 준수:
- venue_kind='museum', museum_id는 **기존 museums 행에만** 매칭(이름 정확
  일치). 없으면 museum_id=None + venue_name만 채우고 리포트에 보고 —
  신규 museums 생성 안 함.
- 작가는 **기존 artists의 entity_kind='person' 행과 이름 정확 일치**로만
  연결(한글 이름은 link_korean_artists_wikidata.py의 hangul_name 규칙과
  동일하게 " a"/" b" 같은 동명이인 접미 제거 후 비교). 신규 artists 생성 안 함.
- MMCA/GMoMA는 참여작가가 자유텍스트("이중섭, 김환기 등 100여명")라
  콤마/가운뎃점 분리 후 "등 N명" 꼬리를 잘라내고 개별 이름만 매칭 시도.
  부산은 목록 페이지에 작가 정보가 없어 exhibition_artists 링크 없이
  exhibitions만 채운다.
- report -> 표본 30건 검수 -> apply. 0009 유니크 인덱스로 idempotent.

사용법:
    python pipeline/institution_exhibitions_load.py            # 리포트만
    python pipeline/institution_exhibitions_load.py --apply     # 실제 반영
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from db import get_connection  # noqa: E402
from raw_iter import iter_records  # noqa: E402

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "logs"

MUSEUM_NAME_HINTS = {
    "mmca_exhibitions": "%MMCA%",
    "busan_exhibitions": "%Busan Museum%",
    "gmoma_exhibitions": "%GMoMA%",
}

TRAILING_COUNT_RE = re.compile(r"\s*등\s*\d+\s*(여)?\s*명\s*$")


def hangul_name(n: str) -> str | None:
    """link_korean_artists_wikidata.py의 규칙 재사용 — 동명이인 접미 제거."""
    m = re.match(r"^([가-힣]{2,6})(?:\s|$|\()", n.strip())
    return m.group(1) if m else None


def split_artist_names(raw: str | None) -> list[str]:
    if not raw:
        return []
    text = TRAILING_COUNT_RE.sub("", raw.strip())
    parts = re.split(r"[,·/]| 등$", text)
    names = []
    for p in parts:
        p = p.strip().strip(".")
        if not p or p in ("등",):
            continue
        names.append(p)
    return names


def build_museum_map(cur) -> dict[str, str | None]:
    result = {}
    for site, pattern in MUSEUM_NAME_HINTS.items():
        cur.execute("select id from museums where name ilike %s limit 1", (pattern,))
        row = cur.fetchone()
        result[site] = str(row[0]) if row else None
    return result


def build_person_artist_map(cur) -> dict[str, str]:
    cur.execute("select id, name from artists where entity_kind = 'person'")
    mapping: dict[str, str] = {}
    for aid, name in cur.fetchall():
        if not name:
            continue
        mapping.setdefault(name.strip(), str(aid))
        hn = hangul_name(name)
        if hn:
            mapping.setdefault(hn, str(aid))
    return mapping


def collect_records(site: str) -> list[dict]:
    out = []
    for record_id, data, meta in iter_records(site):
        out.append({"record_id": record_id, "data": data, "raw_path": meta["raw_path"]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    museum_map = build_museum_map(cur)
    artist_map = build_person_artist_map(cur)

    to_insert = []
    artist_match_miss: dict[str, int] = {}
    museum_miss_sites = [s for s, m in museum_map.items() if m is None]

    # MMCA
    for rec in collect_records("mmca_exhibitions"):
        d = rec["data"]
        title = (d.get("exhTitle") or "").strip()
        if not title:
            continue
        names = split_artist_names(d.get("exhArtist"))
        matched = [artist_map[n] for n in names if n in artist_map]
        miss = len(names) - len(matched)
        if miss > 0:
            artist_match_miss["mmca_exhibitions"] = artist_match_miss.get("mmca_exhibitions", 0) + miss
        to_insert.append(
            {
                "title": title,
                "venue_kind": "museum",
                "museum_id": museum_map["mmca_exhibitions"],
                "venue_name": None if museum_map["mmca_exhibitions"] else "국립현대미술관 (MMCA)",
                "city": None,
                "start_date": d.get("exhStDt"),
                "end_date": d.get("exhEdDt"),
                "artist_ids": matched,
            }
        )

    # Busan (작가 정보 없음)
    for rec in collect_records("busan_exhibitions"):
        d = rec["data"]
        title = (d.get("title") or "").strip()
        if not title:
            continue
        to_insert.append(
            {
                "title": title,
                "venue_kind": "museum",
                "museum_id": museum_map["busan_exhibitions"],
                "venue_name": None if museum_map["busan_exhibitions"] else "부산시립미술관 (Busan Museum of Art)",
                "city": None,
                "start_date": d.get("start_date"),
                "end_date": d.get("end_date"),
                "artist_ids": [],
            }
        )

    # GMoMA
    for rec in collect_records("gmoma_exhibitions"):
        d = rec["data"]
        title = (d.get("title") or "").strip()
        if not title:
            continue
        names = split_artist_names(d.get("artists_raw"))
        matched = [artist_map[n] for n in names if n in artist_map]
        miss = len(names) - len(matched)
        if miss > 0:
            artist_match_miss["gmoma_exhibitions"] = artist_match_miss.get("gmoma_exhibitions", 0) + miss
        to_insert.append(
            {
                "title": title,
                "venue_kind": "museum",
                "museum_id": museum_map["gmoma_exhibitions"],
                "venue_name": None if museum_map["gmoma_exhibitions"] else "경기도미술관 (GMoMA)",
                "city": None,
                "start_date": d.get("start_date"),
                "end_date": d.get("end_date"),
                "artist_ids": matched,
            }
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_candidates": len(to_insert),
        "museum_id_missing_sites": museum_miss_sites,
        "artist_name_miss_by_site": artist_match_miss,
        "samples": [
            {k: v for k, v in row.items() if k != "artist_ids"} | {"artist_id_count": len(row["artist_ids"])}
            for row in to_insert[:30]
        ],
    }
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DOCS_DIR / f"기관전시_리포트_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[institution_exhibitions] 삽입 후보 {len(to_insert)}건")
    print(f"[institution_exhibitions] museum_id 미매칭 사이트: {museum_miss_sites or '없음'}")
    print(f"[institution_exhibitions] 작가명 미매칭 건수: {artist_match_miss}")
    print(f"[institution_exhibitions] 리포트: {report_path}")

    if not args.apply:
        print("[institution_exhibitions] dry-run — --apply로 실제 반영")
        return

    exh_inserted = 0
    link_inserted = 0
    for row in to_insert:
        cur.execute(
            """
            insert into exhibitions (title, venue_kind, museum_id, venue_name, city, start_date, end_date)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (coalesce(url,''), title, coalesce(start_date, date '0001-01-01')) do nothing
            returning id
            """,
            (
                row["title"],
                row["venue_kind"],
                row["museum_id"],
                row["venue_name"],
                row["city"],
                row["start_date"],
                row["end_date"],
            ),
        )
        result = cur.fetchone()
        if result is None:
            cur.execute(
                "select id from exhibitions where title = %s and coalesce(start_date, date '0001-01-01') = coalesce(%s::date, date '0001-01-01') and coalesce(url,'') = ''",
                (row["title"], row["start_date"]),
            )
            existing = cur.fetchone()
            if existing is None:
                continue
            exh_id = str(existing[0])
        else:
            exh_id = str(result[0])
            exh_inserted += 1

        for artist_id in row["artist_ids"]:
            cur.execute(
                "insert into exhibition_artists (exhibition_id, artist_id, role) values (%s, %s, %s) on conflict do nothing",
                (exh_id, artist_id, "group"),
            )
            link_inserted += cur.rowcount

    conn.commit()
    print(f"[institution_exhibitions] 적용 완료 — exhibitions 신규 {exh_inserted}건, exhibition_artists 링크 {link_inserted}건")


if __name__ == "__main__":
    main()
