"""정규화 적재 대상 저장소.

PgStore: 실제 Supabase Postgres에 적재.
DryRunStore: DB 연결 없이 파싱 결과만 집계 — Supabase 프로젝트 생성 전 검증용.
사이트별 로더(met.py 등)는 이 인터페이스만 보고 작성한다.
"""
from __future__ import annotations

from typing import Any


class PgStore:
    def __init__(self, conn):
        self.conn = conn
        self.cur = conn.cursor()
        self._museum_cache: dict[str, str] = {}
        self._artist_cache: dict[str, str] = {}

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

    def get_or_create_artist(self, name: str | None, **fields: Any) -> str | None:
        if not name:
            return None
        if name in self._artist_cache:
            return self._artist_cache[name]
        self.cur.execute("select id from artists where name = %s limit 1", (name,))
        row = self.cur.fetchone()
        if row is None:
            cols = ["name", *fields.keys()]
            vals = [name, *fields.values()]
            placeholders = ", ".join(["%s"] * len(vals))
            self.cur.execute(
                f"insert into artists ({', '.join(cols)}) values ({placeholders}) returning id",
                vals,
            )
            row = self.cur.fetchone()
        artist_id = str(row[0])
        self._artist_cache[name] = artist_id
        return artist_id

    def insert_artwork(self, **fields: Any) -> str:
        cols = list(fields.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        self.cur.execute(
            f"insert into artworks ({', '.join(cols)}) values ({placeholders}) returning id",
            list(fields.values()),
        )
        return str(self.cur.fetchone()[0])

    def insert_museum_holding(self, **fields: Any) -> None:
        cols = list(fields.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        self.cur.execute(
            f"insert into museum_holdings ({', '.join(cols)}) values ({placeholders})",
            list(fields.values()),
        )

    def commit(self) -> None:
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
