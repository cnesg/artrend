"""정규화 적재 대상 저장소.

PgStore: 실제 Supabase Postgres에 적재. artworks/museum_holdings/artists는
개별 INSERT가 아니라 execute_values로 배치 처리한다 (NGA 28만 행을 원격 DB에
한 행씩 왕복하면 감당 못 할 정도로 느려서 — id는 클라이언트에서 uuid로 미리
생성해 FK 참조를 즉시 반환하고, 실제 INSERT는 버퍼가 차면 몰아서 실행).
DryRunStore: DB 연결 없이 파싱 결과만 집계 — Supabase 프로젝트 생성 전 검증용.
사이트별 로더(met.py 등)는 이 인터페이스만 보고 작성한다.
"""
from __future__ import annotations

import uuid
from typing import Any

from psycopg2.extras import execute_values

BATCH_SIZE = 500


class PgStore:
    def __init__(self, conn):
        self.conn = conn
        self.cur = conn.cursor()
        self._museum_cache: dict[str, str] = {}
        self._artist_cache: dict[str, str] | None = None  # lazy: name -> id
        self._pending_artists: list[tuple[str, str, dict]] = []
        self._pending_artworks: list[tuple[str, dict]] = []
        self._pending_holdings: list[tuple[str, dict]] = []

    def source_already_loaded(self, raw_path: str) -> bool:
        self.cur.execute("select id from sources where raw_path = %s limit 1", (raw_path,))
        return self.cur.fetchone() is not None

    def insert_source(self, meta: dict) -> str:
        self.cur.execute(
            """
            insert into sources (url, site_name, fetched_at, raw_path, license_note)
            values (%s, %s, %s, %s, %s)
            returning id
            """,
            (meta.get("url"), meta["site_name"], meta["fetched_at"], meta["raw_path"], meta.get("license_note")),
        )
        return str(self.cur.fetchone()[0])

    def get_or_create_museum(self, name: str, name_en: str | None = None) -> str:
        if name in self._museum_cache:
            return self._museum_cache[name]
        self.cur.execute("select id from museums where name = %s limit 1", (name,))
        row = self.cur.fetchone()
        if row is None:
            self.cur.execute(
                "insert into museums (name, name_en) values (%s, %s) returning id",
                (name, name_en),
            )
            row = self.cur.fetchone()
        museum_id = str(row[0])
        self._museum_cache[name] = museum_id
        return museum_id

    def _ensure_artist_cache(self) -> None:
        if self._artist_cache is not None:
            return
        self.cur.execute("select name, id from artists")
        self._artist_cache = {name: str(aid) for name, aid in self.cur.fetchall()}

    def get_or_create_artist(self, name: str | None, **fields: Any) -> str | None:
        if not name:
            return None
        self._ensure_artist_cache()
        if name in self._artist_cache:
            return self._artist_cache[name]
        new_id = str(uuid.uuid4())
        self._pending_artists.append((new_id, name, fields))
        self._artist_cache[name] = new_id
        return new_id

    def insert_artwork(self, **fields: Any) -> str:
        new_id = str(uuid.uuid4())
        self._pending_artworks.append((new_id, fields))
        if len(self._pending_artworks) >= BATCH_SIZE:
            self._flush_artworks()
        return new_id

    def insert_museum_holding(self, **fields: Any) -> None:
        new_id = str(uuid.uuid4())
        self._pending_holdings.append((new_id, fields))
        if len(self._pending_holdings) >= BATCH_SIZE:
            self._flush_holdings()
            # 배치마다 커밋 — 대량 로드를 하나의 트랜잭션으로 묶으면 pooler가
            # 중간에 끊었을 때 전부 롤백되고, 끝나기 전까지 진행 상황도 볼 수 없다.
            self.conn.commit()

    def _flush_artists(self) -> None:
        if not self._pending_artists:
            return
        cols = ["id", "name", "nationality", "birth_year", "death_year", "bio", "source_id"]
        rows = [
            (aid, name, f.get("nationality"), f.get("birth_year"), f.get("death_year"), f.get("bio"), f.get("source_id"))
            for aid, name, f in self._pending_artists
        ]
        execute_values(self.cur, f"insert into artists ({', '.join(cols)}) values %s", rows)
        self._pending_artists.clear()

    def _flush_artworks(self) -> None:
        self._flush_artists()
        if not self._pending_artworks:
            return
        cols = ["id", "artist_id", "title", "year_created", "medium", "dimensions", "description", "source_id"]
        rows = [
            (
                aid,
                f.get("artist_id"),
                f.get("title"),
                f.get("year_created"),
                f.get("medium"),
                f.get("dimensions"),
                f.get("description"),
                f.get("source_id"),
            )
            for aid, f in self._pending_artworks
        ]
        execute_values(self.cur, f"insert into artworks ({', '.join(cols)}) values %s", rows)
        self._pending_artworks.clear()

    def _flush_holdings(self) -> None:
        self._flush_artworks()
        if not self._pending_holdings:
            return
        cols = ["id", "museum_id", "artwork_id", "accession_number", "acquisition_date", "source_id"]
        rows = [
            (
                hid,
                f.get("museum_id"),
                f.get("artwork_id"),
                f.get("accession_number"),
                f.get("acquisition_date"),
                f.get("source_id"),
            )
            for hid, f in self._pending_holdings
        ]
        execute_values(self.cur, f"insert into museum_holdings ({', '.join(cols)}) values %s", rows)
        self._pending_holdings.clear()

    def commit(self) -> None:
        self._flush_holdings()
        self.conn.commit()


class DryRunStore:
    """실제 DB 없이 파싱/매핑 로직만 검증. 카운트만 집계하고 항상 새로 적재한다고 가정."""

    def __init__(self) -> None:
        self.counts = {"sources": 0, "artists": 0, "artworks": 0, "museum_holdings": 0, "museums": 0}
        self._museum_cache: dict[str, str] = {}
        self._artist_cache: dict[str, str] = {}
        self._next_id = 1
        self.samples: list[dict] = []

    def _fresh_id(self) -> str:
        self._next_id += 1
        return f"dry-{self._next_id}"

    def source_already_loaded(self, raw_path: str) -> bool:
        return False

    def insert_source(self, meta: dict) -> str:
        self.counts["sources"] += 1
        return self._fresh_id()

    def get_or_create_museum(self, name: str, name_en: str | None = None) -> str:
        if name not in self._museum_cache:
            self.counts["museums"] += 1
            self._museum_cache[name] = self._fresh_id()
        return self._museum_cache[name]

    def get_or_create_artist(self, name: str | None, **fields: Any) -> str | None:
        if not name:
            return None
        if name not in self._artist_cache:
            self.counts["artists"] += 1
            self._artist_cache[name] = self._fresh_id()
        return self._artist_cache[name]

    def insert_artwork(self, **fields: Any) -> str:
        self.counts["artworks"] += 1
        if len(self.samples) < 5:
            self.samples.append(fields)
        return self._fresh_id()

    def insert_museum_holding(self, **fields: Any) -> None:
        self.counts["museum_holdings"] += 1

    def commit(self) -> None:
        pass
