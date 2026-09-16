"""raw/ 원본에서 이미 추출 가능한 nationality/birth_year/death_year를 artists에 백필.

**근본 원인**: `store.py`의 `get_or_create_artist()`는 이름(소문자) 기준으로
처음 만난 값만 쓰고 끝난다 — 나중에 같은 이름을 더 풍부한 메타데이터와 함께
가진 소스가 로드돼도 이미 존재하는 행은 절대 갱신되지 않는다. met/cleveland/
nga/smk/moma/tate 로더는 각자 raw 파일에서 nationality/birth_year/death_year를
이미 파싱하고 있으므로(코드 확인 완료), 이 스크립트는 **같은 파싱 로직을
재사용해서** 로더가 놓친(= 이미 다른 소스가 먼저 만들어 둔) 값을 뒤늦게
채워 넣는다. **새 크롤링이나 스키마 변경이 필요 없다** — artists.nationality/
birth_year/death_year 컬럼은 이미 존재.

기본은 dry-run(추정치만 출력). --apply를 줘야 실제 UPDATE 수행.
매칭은 get_or_create_artist와 동일하게 name의 소문자 기준(대소문자 dedup으로
이미 병합된 canonical name과의 불일치를 피하기 위함).
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

import psycopg2
from psycopg2.extras import execute_values

from raw_iter import RAW_ROOT, iter_records, to_int

sys.stdout.reconfigure(encoding="utf-8")


def collect_met() -> dict[str, dict]:
    out: dict[str, dict] = {}
    path = RAW_ROOT / "met" / "MetObjects.csv"
    if not path.exists():
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("Artist Display Name") or "").split("|")[0].strip()
            if not name:
                continue
            key = name.lower()
            if key in out:
                continue
            nationality = (row.get("Artist Nationality") or "").split("|")[0].strip() or None
            begin_date = (row.get("Artist Begin Date") or "").split("|")[0].strip()
            end_date = (row.get("Artist End Date") or "").split("|")[0].strip()
            out[key] = {
                "nationality": nationality,
                "birth_year": to_int(begin_date),
                "death_year": to_int(end_date),
            }
    return out


def collect_cleveland() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for _rid, data, _meta in iter_records("cleveland"):
        creators = data.get("creators") or []
        artists = [c for c in creators if (c.get("role") or "").lower() == "artist"] or creators
        creator = artists[0] if artists else None
        if not creator:
            continue
        description = (creator.get("description") or "").strip()
        name = description.split(" (")[0].strip() if description else None
        if not name:
            continue
        key = name.lower()
        if key in out:
            continue
        out[key] = {
            "nationality": None,
            "birth_year": to_int(creator.get("birth_year")),
            "death_year": to_int(creator.get("death_year")),
        }
    return out


def collect_nga() -> dict[str, dict]:
    out: dict[str, dict] = {}
    path = RAW_ROOT / "nga" / "constituents.csv"
    if not path.exists():
        return out
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("preferreddisplayname") or "").strip()
            if not name:
                continue
            key = name.lower()
            if key in out:
                continue
            out[key] = {
                "nationality": row.get("nationality") or None,
                "birth_year": to_int(row.get("beginyear")),
                "death_year": to_int(row.get("endyear")),
            }
    return out


def collect_smk() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for _rid, data, _meta in iter_records("smk"):
        production = (data.get("production") or [{}])[0]
        name = production.get("creator") or (data.get("artist") or [None])[0]
        if not name:
            continue
        key = name.lower()
        if key in out:
            continue
        out[key] = {
            "nationality": production.get("creator_nationality"),
            "birth_year": to_int((production.get("creator_date_of_birth") or "")[:4] or None),
            "death_year": to_int((production.get("creator_date_of_death") or "")[:4] or None),
        }
    return out


def collect_moma() -> dict[str, dict]:
    out: dict[str, dict] = {}
    path = RAW_ROOT / "moma" / "Artworks.csv"
    if not path.exists():
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("Artist") or "").strip()
            if not name:
                continue
            key = name.lower()
            if key in out:
                continue
            out[key] = {
                "nationality": (row.get("Nationality") or "").strip("() ") or None,
                "birth_year": to_int((row.get("BeginDate") or "").strip("() ")),
                "death_year": to_int((row.get("EndDate") or "").strip("() ")),
            }
    return out


def collect_tate() -> dict[str, dict]:
    out: dict[str, dict] = {}
    path = RAW_ROOT / "tate" / "artist_data.csv"
    if not path.exists():
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            key = name.lower()
            if key in out:
                continue
            out[key] = {
                "nationality": row.get("placeOfBirth") or None,
                "birth_year": to_int(row.get("yearOfBirth")),
                "death_year": to_int(row.get("yearOfDeath")),
            }
    return out


COLLECTORS = {
    "met": collect_met,
    "cleveland": collect_cleveland,
    "nga": collect_nga,
    "smk": collect_smk,
    "moma": collect_moma,
    "tate": collect_tate,
}


def merge_maps(maps: dict[str, dict[str, dict]]) -> dict[str, dict]:
    """소스별 name->metadata를 하나로 합친다. 필드별로 먼저 non-null인 값을 채택
    (소스 우선순위를 굳이 두지 않고 met/nga/cleveland/... 처리 순서대로 first-fill)."""
    merged: dict[str, dict] = {}
    for site, m in maps.items():
        for key, info in m.items():
            slot = merged.setdefault(key, {"nationality": None, "birth_year": None, "death_year": None, "sources": set()})
            for field in ("nationality", "birth_year", "death_year"):
                if slot[field] is None and info.get(field) is not None:
                    slot[field] = info[field]
                    slot["sources"].add(site)
    return merged


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 UPDATE 수행 (기본은 dry-run 추정치만 출력)")
    ap.add_argument("--sites", nargs="*", default=list(COLLECTORS.keys()), help="대상 소스 제한(기본: 전체)")
    args = ap.parse_args()

    maps = {}
    for site in args.sites:
        print(f"[backfill] {site} raw 파싱 중...")
        maps[site] = COLLECTORS[site]()
        print(f"[backfill] {site}: 고유 작가명 {len(maps[site])}명 파싱 완료")

    merged = merge_maps(maps)
    print(f"[backfill] 전체 소스 합산 고유 작가명: {len(merged)}명")

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("select id, name, nationality, birth_year, death_year from artists")
    db_rows = cur.fetchall()
    print(f"[backfill] DB artists 전체 {len(db_rows)}건 로드")

    to_update = []  # (id, nationality, birth_year, death_year)
    filled_nationality = filled_birth = filled_death = 0
    for aid, name, nationality, birth_year, death_year in db_rows:
        info = merged.get(name.lower())
        if not info:
            continue
        new_nat = nationality if nationality is not None else info["nationality"]
        new_birth = birth_year if birth_year is not None else info["birth_year"]
        new_death = death_year if death_year is not None else info["death_year"]
        if new_nat == nationality and new_birth == birth_year and new_death == death_year:
            continue
        if nationality is None and new_nat is not None:
            filled_nationality += 1
        if birth_year is None and new_birth is not None:
            filled_birth += 1
        if death_year is None and new_death is not None:
            filled_death += 1
        to_update.append((str(aid), new_nat, new_birth, new_death))

    print(f"[backfill] 백필 가능 추정: nationality {filled_nationality}건, birth_year {filled_birth}건, death_year {filled_death}건")
    print(f"[backfill] UPDATE 대상 artists 행: {len(to_update)}건")

    if not args.apply:
        print("[backfill] dry-run — DB 변경 없음. --apply로 실행하면 실제 반영됩니다.")
        cur.close()
        conn.close()
        return

    BATCH = 1000
    for i in range(0, len(to_update), BATCH):
        batch = to_update[i : i + BATCH]
        execute_values(
            cur,
            """
            update artists as a set
                nationality = coalesce(a.nationality, v.nationality),
                birth_year = coalesce(a.birth_year, v.birth_year),
                death_year = coalesce(a.death_year, v.death_year)
            from (values %s) as v(id, nationality, birth_year, death_year)
            where a.id = v.id::uuid
            """,
            batch,
            template="(%s::uuid, %s, %s::int, %s::int)",
        )
        conn.commit()
        print(f"[backfill] {min(i + BATCH, len(to_update))}/{len(to_update)}건 반영...")

    print(f"[backfill] 완료 — {len(to_update)}건 UPDATE")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
