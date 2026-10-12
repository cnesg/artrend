"""Bonhams 경매 lot title에 뭉쳐 있는 작가명/생몰/국적을 분리해 artworks.artist_id를 채운다.

[문제] Bonhams raw JSON에는 구조화된 작가 필드가 없고(heading/styledDescription 공란), title에
  "Pablo Picasso (1881-1973) Le Peintre 45 x 38cm" 식으로 작가+생몰+제목+크기가 뭉쳐 있다.
  `pipeline/bonhams.py`가 이를 그대로 저장해 89,743건 전량 artist_id NULL(진단 2026-09-15 §3-2-2).

[처리] 2026-09-15 작업분담 §M3 (원안 09-15 11:34 작성분을 메인 세션이 검수·수정)
  1. Bonhams 작품 중 artist_id IS NULL 전체 로드
  2. 정규식으로 작가명·괄호 내용(국적/생몰) 파싱 — 괄호 없는 구형 카탈로그 제목은 건드리지 않음
  3. 제외 패턴(School / After / Circle of / Attributed to …)은 작가 NULL 유지 + 제목만 정제
  4. 기존 artists 매칭: (a) 소문자 정확 일치 → (b) 악센트 제거·구두점 제거 정규화 일치
     (`audit_gallery_artist_matches.py`와 같은 규칙) — 변형 신규 생성을 막기 위한 2단계
  5. 미매칭 → 신규 artist INSERT (괄호에서 뽑은 nationality/birth_year/death_year 함께 저장)
  6. 원래 title은 `artworks.description`이 비어 있을 때 `[Bonhams 원제] ...`로 보존(정보 손실 방지)

[실행] 기본은 리포트만, `--apply` 시 반영. idempotent(artist_id 채워진 행은 다시 안 봄).
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from typing import Optional, Tuple

import psycopg2.extras
from psycopg2.extras import execute_values

from db import get_connection

sys.stdout.reconfigure(encoding="utf-8")

BATCH_SIZE = 500

# ──────────────────────────────────────────────
# 제외 패턴: 이 패턴이 앞에 오면 개인 작가가 아님
# ──────────────────────────────────────────────
SKIP_PREFIXES = re.compile(
    r"^("
    r"After\b|Follower of\b|Circle of\b|Manner of\b|Attributed to\b|"
    r"Workshop of\b|Studio of\b|School of\b|Style of\b|In the manner of\b|"
    r"(?:English|French|Dutch|Flemish|Italian|German|Continental|"
    r"Spanish|Chinese|Japanese|Korean|Indian|Russian|American|"
    r"Australian|Scandinavian|Nordic|British|Irish|Scottish|Welsh|"
    r"Venetian|Florentine|Bolognese|Neapolitan|Provençal|European|Roman|Northern|Southern)\s+School|"
    r"\d{2}th\s+Century\s+School|"
    r"Anonymous|Unknown|After the manner|"
    r"Pr of|A collection|Various|Property of|A pair|A set|A group|Two |Three |Four "
    r")",
    re.IGNORECASE,
)

# 예: "Pablo Picasso (1881-1973) Title 45x38cm"
#     "George Lambert (Australian, 1873-1930) A Lady..."
#     "Thomas Webster (20th Century) ..."  ← 생년 없어 매칭 안 됨(의도)
ARTIST_PAREN_RE = re.compile(
    r"^"
    r"(?P<artist>[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ\.\-\' ]{1,60}?)"
    r"\s*"
    r"\("
    r"(?P<paren_content>"
    r"(?:[A-Za-z][A-Za-z /\-]*,\s*)?"      # 국적(선택)
    r"(?:b\.?\s*|born\s*)?"                 # "b." / "born" 접두어(선택)
    r"\d{4}"                                # 생년
    r"(?:\s*[-–]\s*\d{2,4})?"               # 사망년(선택)
    r"[^)]*"
    r")"
    r"\)"
    r"(?:\s*\([^)]+\))?"                    # 추가 별칭 괄호(선택)
    r"\s*[;,]?\s*"
    r"(?P<rest>.+?)?"
    r"$",
    re.DOTALL,
)

PAREN_META_RE = re.compile(
    r"^(?:(?P<nat>[A-Za-z][A-Za-z /\-]*?),\s*)?(?:b\.?\s*|born\s*)?(?P<birth>\d{4})(?:\s*[-–]\s*(?P<death>\d{2,4}))?"
)

# 끝에 붙은 크기 정보 제거 ("45 x 38cm", "31.5 x 26.7 in.", "(2)" 등)
DIMENSION_RE = re.compile(
    r"[\s,;]+\d+[\.,]?\d*(?:\s+\d+/\d+)?\s*[xX×]\s*\d+[\.,]?\d*(?:\s+\d+/\d+)?\s*(?:cms?|mm|in(?:ches)?)?\.?\s*(?:\([^)]*\))?\s*[,;.]?\s*$"
    r"|\s+\(\d+\)\s*$",
    re.IGNORECASE,
)


def parse_title(raw_title: str) -> Tuple[Optional[str], str, dict]:
    """(artist_name|None, cleaned_title, meta{nationality,birth_year,death_year})."""
    t = " ".join(raw_title.split())
    meta: dict = {}
    if SKIP_PREFIXES.match(t):
        return None, DIMENSION_RE.sub("", t).strip(), meta
    m = ARTIST_PAREN_RE.match(t)
    if not m:
        return None, DIMENSION_RE.sub("", t).strip(), meta

    artist = m.group("artist").strip().rstrip(",;")
    if len(artist) < 3 or SKIP_PREFIXES.match(artist) or " " not in artist:
        # 한 단어 이름(예: "Rubens")은 동명이인·약칭 위험 → 신규 생성하지 않음
        return None, DIMENSION_RE.sub("", t).strip(), meta

    pm = PAREN_META_RE.match(m.group("paren_content").strip())
    if pm:
        nat = (pm.group("nat") or "").strip() or None
        birth = int(pm.group("birth"))
        death_s = pm.group("death")
        death = None
        if death_s:
            death = int(death_s) if len(death_s) == 4 else int(str(birth)[:2] + death_s)
            if death < birth:
                death = None
        meta = {"nationality": nat, "birth_year": birth, "death_year": death}

    rest = DIMENSION_RE.sub("", (m.group("rest") or "").strip().rstrip(",;")).strip()
    cleaned_title = rest if rest else t
    return artist, cleaned_title, meta


def norm_exact(name: str) -> str:
    return " ".join(name.strip().split()).lower()


def norm_loose(name: str) -> str:
    """악센트 제거 + 구두점 제거 + 소문자 (audit_gallery_artist_matches.py 규칙과 동일)."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.lower().split())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 DB 반영 (없으면 리포트만)")
    ap.add_argument("--sample", type=int, default=30)
    args = ap.parse_args()

    conn = get_connection()
    conn.set_client_encoding("UTF8")
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    print("[1/3] Bonhams artist NULL 작품 로드...")
    cur.execute(
        """
        SELECT a.id::text AS artwork_id, a.title AS raw_title, (a.description IS NULL) AS desc_empty
        FROM artworks a
        JOIN sources s ON s.id = a.source_id
        WHERE s.site_name = 'bonhams' AND a.artist_id IS NULL
          AND a.title IS NOT NULL AND length(trim(a.title)) >= 5
        """
    )
    rows = cur.fetchall()
    print(f"  대상 {len(rows):,}건")

    print("[2/3] 기존 작가 캐시 로드...")
    cur.execute("SELECT id::text, name FROM artists")
    exact_cache: dict[str, str] = {}
    loose_cache: dict[str, str] = {}
    loose_ambiguous: set[str] = set()
    for r in cur.fetchall():
        exact_cache.setdefault(norm_exact(r["name"]), r["id"])
        k = norm_loose(r["name"])
        if k in loose_cache and loose_cache[k] != r["id"]:
            loose_ambiguous.add(k)
        loose_cache.setdefault(k, r["id"])
    print(f"  캐시 {len(exact_cache):,}명 (loose 충돌 {len(loose_ambiguous):,}키는 loose 매칭 제외)")

    print("[3/3] 파싱...")
    stats = dict(matched_exact=0, matched_loose=0, new_artist=0, skip_pattern=0, no_pattern=0, title_cleaned=0)
    new_artists: dict[str, tuple[str, dict]] = {}  # exact key -> (display name, meta)
    updates: list[dict] = []
    samples_new: list[tuple] = []
    samples_loose: list[tuple] = []

    for r in rows:
        raw = r["raw_title"]
        artist, cleaned, meta = parse_title(raw)
        if artist is None:
            if SKIP_PREFIXES.match(raw.strip()):
                stats["skip_pattern"] += 1
            else:
                stats["no_pattern"] += 1
            continue  # 작가 못 뽑으면 제목도 손대지 않음(원문 보존)

        key = norm_exact(artist)
        artist_id = exact_cache.get(key)
        how = "exact"
        if artist_id is None:
            lk = norm_loose(artist)
            if lk in loose_cache and lk not in loose_ambiguous:
                artist_id = loose_cache[lk]
                how = "loose"
                if len(samples_loose) < args.sample:
                    samples_loose.append((artist, artist_id[:8]))
            elif key in new_artists:
                how = "new"
            else:
                new_artists[key] = (artist, meta)
                how = "new"
                if len(samples_new) < args.sample:
                    samples_new.append((artist, meta, cleaned[:50]))
        stats[{"exact": "matched_exact", "loose": "matched_loose", "new": "new_artist"}[how]] += 1
        if cleaned != raw:
            stats["title_cleaned"] += 1
        updates.append(
            dict(artwork_id=r["artwork_id"], key=key, artist_id=artist_id, cleaned=cleaned,
                 raw=raw, desc_empty=r["desc_empty"])
        )

    print("\n결과:")
    for k, v in stats.items():
        print(f"  {k:>15}: {v:,}")
    print(f"  신규 작가(고유): {len(new_artists):,}")
    print("\n신규 작가 샘플:")
    for s in samples_new:
        print("  ", s)
    print("\nloose 매칭 샘플(악센트/구두점 차이로 기존 작가에 붙은 것):")
    for s in samples_loose:
        print("  ", s)

    if not args.apply:
        print("\n--apply 없음: 리포트만. 종료")
        return

    print("\n신규 작가 INSERT...")
    for key, (name, meta) in new_artists.items():
        cur.execute(
            """INSERT INTO artists (name, nationality, birth_year, death_year)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
               RETURNING id::text""",
            (name, meta.get("nationality"), meta.get("birth_year"), meta.get("death_year")),
        )
        exact_cache[key] = cur.fetchone()["id"]
    conn.commit()

    print("artworks UPDATE...")
    done = 0
    for i in range(0, len(updates), BATCH_SIZE):
        batch = updates[i : i + BATCH_SIZE]
        vals = []
        for u in batch:
            aid = u["artist_id"] or exact_cache.get(u["key"])
            if not aid:
                continue
            desc = f"[Bonhams 원제] {u['raw']}" if u["desc_empty"] else None
            vals.append((u["artwork_id"], aid, u["cleaned"], desc))
        execute_values(
            cur,
            """UPDATE artworks a SET artist_id = v.artist_id::uuid, title = v.title,
                   description = COALESCE(a.description, v.description), updated_at = now()
               FROM (VALUES %s) AS v(id, artist_id, title, description)
               WHERE a.id = v.id::uuid AND a.artist_id IS NULL""",
            vals, page_size=BATCH_SIZE,
        )
        conn.commit()
        done += len(vals)
        print(f"  {done:,}/{len(updates):,}", end="\r")
    print()
    cur.execute(
        "SELECT count(*) AS n FROM artworks a JOIN sources s ON s.id=a.source_id WHERE s.site_name='bonhams' AND a.artist_id IS NULL"
    )
    print("잔여 artist NULL:", cur.fetchone()["n"])


if __name__ == "__main__":
    main()
