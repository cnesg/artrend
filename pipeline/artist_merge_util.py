"""artists 행 병합/재연결 공용 유틸 (2026-09-15 작업분담 §M4).

기존 merge_*_dup_artists.py 들이 각자 반복하던 "참조 재연결 후 삭제" 로직을 한 곳에 모은다.
artists를 참조하는 컬럼: artworks.artist_id, gallery_representations.artist_id,
artists.attribution_of(0007), artist_bio_generated.artist_id(0006, on delete cascade).
"""
from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path


def get_conn():
    import psycopg2

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent / ".env")
        dsn = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(dsn)
    conn.set_client_encoding("UTF8")
    return conn


def norm_exact(name: str) -> str:
    return " ".join(name.strip().split()).lower()


def norm_loose(name: str) -> str:
    """악센트 제거 + 구두점 제거 + 소문자 (audit_gallery_artist_matches.py 규칙)."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.lower().split())


def relink_and_delete(cur, from_id: str, to_id: str) -> int:
    """from_id의 모든 참조를 to_id로 옮기고 from_id 행을 삭제. 재연결 건수 반환."""
    if from_id == to_id:
        return 0
    n = 0
    cur.execute("update artworks set artist_id = %s where artist_id = %s", (to_id, from_id))
    n += cur.rowcount
    cur.execute(
        """delete from gallery_representations g using gallery_representations h
           where g.artist_id = %s and h.artist_id = %s and g.gallery_id = h.gallery_id""",
        (from_id, to_id),
    )  # 같은 갤러리에 양쪽 다 있으면 중복 방지로 from 쪽 삭제
    cur.execute("update gallery_representations set artist_id = %s where artist_id = %s", (to_id, from_id))
    n += cur.rowcount
    cur.execute("update artists set attribution_of = %s where attribution_of = %s", (to_id, from_id))
    n += cur.rowcount
    cur.execute(
        """update artist_bio_generated b set artist_id = %s where artist_id = %s
           and not exists (select 1 from artist_bio_generated t where t.artist_id = %s)""",
        (to_id, from_id, to_id),
    )
    cur.execute("delete from artists where id = %s", (from_id,))
    return n


def fill_missing_meta(cur, to_id: str, from_id: str) -> None:
    """to 행에 비어 있는 nationality/birth/death/bio를 from 행 값으로 보충(덮어쓰지 않음)."""
    cur.execute(
        """update artists t set
             nationality = coalesce(t.nationality, f.nationality),
             birth_year = coalesce(t.birth_year, f.birth_year),
             death_year = coalesce(t.death_year, f.death_year),
             bio = coalesce(t.bio, f.bio),
             updated_at = now()
           from artists f where t.id = %s and f.id = %s""",
        (to_id, from_id),
    )
