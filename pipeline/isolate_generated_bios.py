"""LLM(Gemini) 생성 약력을 artists.bio에서 분리해 artist_bio_generated로 옮기고 원본을 복원한다.

2026-09-15 작업분담 §M1 (진단 §3-2-7). enrich_artist_bios.py가 핵심 작가 2,499명의
artists.bio를 "한국어 개요\\n\\n- **주요 사조**: X\\n- **국적 및 활동시기**: Y" 형식의 생성문으로
덮어썼다. 이 스크립트는
  1. 그 형식의 bio를 전부 찾아 artist_bio_generated(0006 마이그레이션)에 저장하고,
  2. artists.bio는 원본(수집 소스가 제공한 텍스트)으로 되돌린다.
     원본 후보 우선순위: (a) 2026-09-02 Supabase 덤프(C:/pgportable/supabase_dump.sql,
     met/aic/cleveland/nga 적재 직후) → (b) raw 재파싱(met MetObjects.csv / moma Artworks.csv /
     aic *.json artist_display / cleveland *.json creators[].biography — 각 로더와 동일 규칙).
     둘 다 없으면 NULL(원래 bio를 쓰지 않는 소스거나 애초에 비어 있던 작가).
기본은 리포트만, --apply 시 실제 반영. idempotent(재실행 시 대상 0건).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from raw_iter import RAW_ROOT  # noqa: E402

DUMP_PATH = Path("C:/pgportable/supabase_dump.sql")
MIGRATION = Path(__file__).resolve().parent.parent / "db" / "migrations" / "0006_artist_bio_generated.sql"
GEN_MARK_SQL = r"\*\*주요 사조\*\*"
GEN_MARK_RE = re.compile(r"\*\*주요 사조\*\*")
PARSE_RE = re.compile(
    r"^(?P<overview>.*?)\s*\n\s*\n-\s*\*\*주요 사조\*\*:\s*(?P<movement>.*?)\s*\n-\s*\*\*국적 및 활동시기\*\*:\s*(?P<natper>.*?)\s*$",
    re.S,
)


def get_conn():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent / ".env")
        dsn = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(dsn)
    conn.set_client_encoding("UTF8")
    return conn


def parse_generated(bio: str) -> tuple[str, str | None, str | None]:
    m = PARSE_RE.match(bio.strip())
    if not m:
        return bio.strip(), None, None
    return m.group("overview").strip(), m.group("movement").strip() or None, m.group("natper").strip() or None


# ---------------------------------------------------------------- 원본 인덱스
def _unescape_copy(v: str) -> str | None:
    if v == "\\N":
        return None
    return v.replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")


def index_from_dump(wanted: set[str]) -> dict[str, str]:
    """덤프의 COPY public.artists 블록에서 name.lower() -> bio (bio 있는 것만)."""
    out: dict[str, str] = {}
    if not DUMP_PATH.exists():
        return out
    in_block = False
    with open(DUMP_PATH, encoding="utf-8", errors="replace") as f:
        for line in f:
            if not in_block:
                if line.startswith("COPY public.artists ("):
                    in_block = True
                continue
            if line.startswith("\\."):
                break
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 7:
                continue
            name, bio = cols[1], _unescape_copy(cols[6])
            key = name.lower()
            if bio and key in wanted and key not in out:
                out[key] = bio
    return out


def index_from_met(wanted: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    p = RAW_ROOT / "met" / "MetObjects.csv"
    if not p.exists():
        return out
    with open(p, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("Artist Display Name") or "").split("|")[0].strip()
            if not name:
                continue
            key = name.lower()
            if key in wanted and key not in out:
                bio = (row.get("Artist Display Bio") or "").split("|")[0].strip()
                if bio:
                    out[key] = bio
    return out


def index_from_moma(wanted: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    p = RAW_ROOT / "moma" / "Artworks.csv"
    if not p.exists():
        return out
    with open(p, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("Artist") or "").strip()
            key = name.lower()
            if key in wanted and key not in out:
                bio = (row.get("ArtistBio") or "").strip()
                if bio:
                    out[key] = bio
    return out


def index_from_json_site(site: str, wanted: set[str], extract) -> dict[str, str]:
    out: dict[str, str] = {}
    site_dir = RAW_ROOT / site
    if not site_dir.exists():
        return out
    remaining = set(wanted)
    for p in site_dir.glob("*.json"):
        if p.name.endswith(".meta.json"):
            continue
        if not remaining:
            break
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for name, bio in extract(data):
            key = (name or "").lower()
            if key in remaining and bio:
                out[key] = bio
                remaining.discard(key)
    return out


def _aic_extract(data):
    yield (data.get("artist_title") or "").strip(), (data.get("artist_display") or "").strip()


def _cleveland_extract(data):
    for c in data.get("creators") or []:
        desc = (c.get("description") or "").strip()
        if desc:
            yield desc.split(" (")[0].strip(), (c.get("biography") or "").strip()


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--skip-raw", action="store_true", help="raw 재파싱 생략(덤프만 사용, 빠른 테스트용)")
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """select a.id::text, a.name, a.bio, coalesce(s.site_name, '')
           from artists a left join sources s on s.id = a.source_id
           where a.bio ~ %s""",
        (GEN_MARK_SQL,),
    )
    rows = cur.fetchall()
    print(f"생성 약력 감지: {len(rows)}건")
    if not rows:
        print("대상 없음 (idempotent) — 종료")
        return

    wanted = {r[1].lower() for r in rows}
    by_site: dict[str, int] = {}
    for r in rows:
        by_site[r[3]] = by_site.get(r[3], 0) + 1
    print("소스별:", sorted(by_site.items(), key=lambda x: -x[1])[:12])

    print("원본 인덱스 구축 중 (덤프)...")
    dump_idx = index_from_dump(wanted)
    print(f"  덤프 매칭 {len(dump_idx)}")
    raw_idx: dict[str, str] = {}
    if not args.skip_raw:
        print("원본 인덱스 구축 중 (raw: met/moma/aic/cleveland)...")
        for label, fn in (
            ("met", lambda: index_from_met(wanted)),
            ("moma", lambda: index_from_moma(wanted)),
            ("aic", lambda: index_from_json_site("aic", wanted, _aic_extract)),
            ("cleveland", lambda: index_from_json_site("cleveland", wanted, _cleveland_extract)),
        ):
            got = fn()
            print(f"  {label} 매칭 {len(got)}")
            for k, v in got.items():
                raw_idx.setdefault(k, v)

    restored = 0
    nulled = 0
    inserts = []
    updates = []
    samples = []
    for aid, name, bio, site in rows:
        overview, movement, natper = parse_generated(bio)
        inserts.append(
            (
                aid, overview, movement, natper,
                "gemini-flash-lite (계열, 정확 모델명 로그 부재)",
                "2026-09-15", "pipeline/enrich_artist_bios.py",
                "원본을 덮어쓴 생성문. 사실 검증 안 됨.",
            )
        )
        key = name.lower()
        original = dump_idx.get(key) or raw_idx.get(key)
        if original and not GEN_MARK_RE.search(original):
            restored += 1
            updates.append((aid, original))
        else:
            nulled += 1
            updates.append((aid, None))
        if len(samples) < 8:
            samples.append((name, site, (original or "")[:80], movement))

    print(f"\n복원 가능(원본 있음): {restored} / NULL 처리: {nulled}")
    print("샘플:")
    for s in samples:
        print("  ", s)

    if not args.apply:
        print("\n--apply 없음: 리포트만. 종료")
        return

    cur.execute(MIGRATION.read_text(encoding="utf-8"))
    execute_values(
        cur,
        """insert into artist_bio_generated
           (artist_id, bio, movement, nationality_period, model, generated_at, source_script, note)
           values %s on conflict (artist_id) do nothing""",
        inserts,
        page_size=500,
    )
    execute_values(
        cur,
        """update artists a set bio = v.bio, updated_at = now()
           from (values %s) as v(id, bio) where a.id = v.id::uuid""",
        updates,
        page_size=500,
    )
    conn.commit()
    cur.execute("select count(*) from artist_bio_generated")
    print("artist_bio_generated 총:", cur.fetchone()[0])
    cur.execute("select count(*) from artists where bio ~ %s", (GEN_MARK_SQL,))
    print("artists.bio 잔여 생성문:", cur.fetchone()[0])


if __name__ == "__main__":
    main()
