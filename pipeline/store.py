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
        self._collector_cache: dict[str, str] = {}
        self._pending_provenance: list[tuple[str, dict]] = []
        self._pending_auction_lots: list[dict] = []

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

    def get_or_create_gallery(self, name: str, city: str | None = None, country: str | None = None, website: str | None = None) -> str:
        cache_key = f"gallery:{name}"
        if cache_key in self._museum_cache:
            return self._museum_cache[cache_key]
        self.cur.execute("select id from galleries where name = %s limit 1", (name,))
        row = self.cur.fetchone()
        if row is None:
            self.cur.execute(
                "insert into galleries (name, city, country, website) values (%s, %s, %s, %s) returning id",
                (name, city, country, website),
            )
            row = self.cur.fetchone()
        gallery_id = str(row[0])
        self._museum_cache[cache_key] = gallery_id
        return gallery_id

    def insert_gallery_representation(self, **fields: Any) -> None:
        self._flush_artists()
        cols = list(fields.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        self.cur.execute(
            f"insert into gallery_representations ({', '.join(cols)}) values ({placeholders})",
            list(fields.values()),
        )

    def _ensure_artist_cache(self) -> None:
        if self._artist_cache is not None:
            return
        self.cur.execute("select name, id from artists")
        self._artist_cache = {name.lower(): str(aid) for name, aid in self.cur.fetchall()}

    def get_or_create_artist(self, name: str | None, **fields: Any) -> str | None:
        if not name:
            return None
        self._ensure_artist_cache()
        key = name.lower()
        if key in self._artist_cache:
            return self._artist_cache[key]
        new_id = str(uuid.uuid4())
        self._pending_artists.append((new_id, name, fields))
        self._artist_cache[key] = new_id
        return new_id

    def get_or_create_artist_safe(self, name: str | None, **fields: Any) -> str | None:
        """get_or_create_artist의 즉시-확정 버전.

        기존 get_or_create_artist는 클라이언트 UUID를 먼저 캐싱하고 실제 INSERT는
        나중에 배치로 미루는데, 그 사이에 동시에 돌고 있는 다른 세션이 같은 이름을
        먼저 커밋해버리면 내 INSERT는 `on conflict (name) do nothing`으로 조용히
        스킵되고, 이미 그 UUID를 참조해버린 artwork가 존재하지 않는 FK를 갖게 되는
        레이스가 있다(getty_provenance_sales.py 대량 적재 중 ForeignKeyViolation으로
        실제 발생, 2026-09-03). 로트 수가 많아 동시성 충돌 확률이 높은 로더는 이 메서드로
        이름마다 즉시 upsert하고 실제 DB id를 받아 레이스를 원천 차단한다.
        """
        if not name:
            return None
        self._ensure_artist_cache()
        key = name.lower()
        if key in self._artist_cache:
            return self._artist_cache[key]
        self.cur.execute(
            """
            insert into artists (name, name_en, nationality, birth_year, death_year, bio, source_id)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (name) do update set name = excluded.name
            returning id
            """,
            (
                name,
                fields.get("name_en"),
                fields.get("nationality"),
                fields.get("birth_year"),
                fields.get("death_year"),
                fields.get("bio"),
                fields.get("source_id"),
            ),
        )
        artist_id = str(self.cur.fetchone()[0])
        self._artist_cache[key] = artist_id
        return artist_id

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
        cols = ["id", "name", "name_en", "nationality", "birth_year", "death_year", "bio", "source_id"]
        rows = [
            (
                aid,
                name,
                f.get("name_en"),
                f.get("nationality"),
                f.get("birth_year"),
                f.get("death_year"),
                f.get("bio"),
                f.get("source_id"),
            )
            for aid, name, f in self._pending_artists
        ]
        execute_values(
            self.cur,
            f"insert into artists ({', '.join(cols)}) values %s on conflict (name) do nothing",
            rows,
        )
        # 다른 프로세스가 동시에 같은 이름을 먼저 커밋했으면 위 insert가 스킵되므로,
        # 방금 flush한 이름들의 실제 DB id로 캐시를 다시 맞춘다(안 그러면 artworks가
        # 존재하지 않는 클라이언트 생성 UUID를 참조해 FK 위반이 남).
        names = [name for _, name, _ in self._pending_artists]
        self.cur.execute("select name, id from artists where name = any(%s)", (names,))
        for name, aid in self.cur.fetchall():
            self._artist_cache[name.lower()] = str(aid)
        self._pending_artists.clear()

    def _flush_artworks(self) -> None:
        self._flush_artists()
        if not self._pending_artworks:
            return
        cols = ["id", "artist_id", "title", "title_en", "year_created", "medium", "dimensions", "description", "source_id"]
        rows = [
            (
                aid,
                f.get("artist_id"),
                f.get("title"),
                f.get("title_en"),
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
        execute_values(
            self.cur,
            f"insert into museum_holdings ({', '.join(cols)}) values %s "
            "on conflict (museum_id, accession_number) where accession_number is not null do nothing",
            rows,
        )
        self._pending_holdings.clear()

    def get_or_create_auction_house(self, name: str, country: str | None = None) -> str:
        cache_key = f"auction_house:{name}"
        if cache_key in self._museum_cache:
            return self._museum_cache[cache_key]
        self.cur.execute("select id from auction_houses where name = %s limit 1", (name,))
        row = self.cur.fetchone()
        if row is None:
            self.cur.execute(
                "insert into auction_houses (name, country) values (%s, %s) returning id",
                (name, country),
            )
            row = self.cur.fetchone()
        house_id = str(row[0])
        self._museum_cache[cache_key] = house_id
        return house_id

    def get_or_create_auction(self, auction_house_id: str, auction_date: str | None, source_id: str | None = None) -> str:
        cache_key = f"auction:{auction_house_id}:{auction_date}"
        if cache_key in self._museum_cache:
            return self._museum_cache[cache_key]
        self.cur.execute(
            "insert into auctions (auction_house_id, auction_date, source_id) values (%s, %s, %s) returning id",
            (auction_house_id, auction_date, source_id),
        )
        auction_id = str(self.cur.fetchone()[0])
        self._museum_cache[cache_key] = auction_id
        return auction_id

    def insert_auction_lot(self, **fields: Any) -> None:
        self._flush_artworks()
        cols = list(fields.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        self.cur.execute(
            f"insert into auction_lots ({', '.join(cols)}) values ({placeholders})",
            list(fields.values()),
        )

    def insert_auction_lot_batch(self, **fields: Any) -> None:
        """insert_auction_lot과 동일한 스키마지만 execute_values로 배치 처리 —
        Getty Provenance Index Sales Catalogs처럼 로트가 수십만 건 규모일 때
        건별 INSERT 왕복을 감당 못 해 추가함(NGA에서 이미 겪은 것과 동일한 이유,
        museum_holdings/provenance_records과 같은 패턴)."""
        self._pending_auction_lots.append(fields)
        if len(self._pending_auction_lots) >= BATCH_SIZE:
            self._flush_auction_lots()
            self.conn.commit()

    def _flush_auction_lots(self) -> None:
        self._flush_artworks()
        if not self._pending_auction_lots:
            return
        cols = ["auction_id", "artwork_id", "lot_number", "estimate_low", "estimate_high", "currency", "hammer_price", "sold", "source_id"]
        rows = [tuple(f.get(c) for c in cols) for f in self._pending_auction_lots]
        execute_values(self.cur, f"insert into auction_lots ({', '.join(cols)}) values %s", rows)
        self._pending_auction_lots.clear()

    def get_or_create_collector(self, name: str, is_institution: bool = False) -> str:
        cache_key = f"collector:{name.lower()}"
        if cache_key in self._collector_cache:
            return self._collector_cache[cache_key]
        self.cur.execute("select id from collectors where lower(name) = %s limit 1", (name.lower(),))
        row = self.cur.fetchone()
        if row is None:
            self.cur.execute(
                "insert into collectors (name, is_institution) values (%s, %s) returning id",
                (name, is_institution),
            )
            row = self.cur.fetchone()
        collector_id = str(row[0])
        self._collector_cache[cache_key] = collector_id
        return collector_id

    def insert_provenance_record(self, **fields: Any) -> None:
        new_id = str(uuid.uuid4())
        self._pending_provenance.append((new_id, fields))
        if len(self._pending_provenance) >= BATCH_SIZE:
            self._flush_provenance()
            self.conn.commit()

    def _flush_provenance(self) -> None:
        if not self._pending_provenance:
            return
        cols = [
            "id", "artwork_id", "owner_type", "owner_collector_id", "owner_museum_id",
            "owner_gallery_id", "owner_auction_house_id", "acquired_date", "acquired_method",
            "note", "source_id",
        ]
        rows = [
            (
                pid,
                f.get("artwork_id"),
                f["owner_type"],
                f.get("owner_collector_id"),
                f.get("owner_museum_id"),
                f.get("owner_gallery_id"),
                f.get("owner_auction_house_id"),
                f.get("acquired_date"),
                f.get("acquired_method"),
                f.get("note"),
                f.get("source_id"),
            )
            for pid, f in self._pending_provenance
        ]
        execute_values(self.cur, f"insert into provenance_records ({', '.join(cols)}) values %s", rows)
        self._pending_provenance.clear()

    def commit(self) -> None:
        self._flush_holdings()
        self._flush_provenance()
        self._flush_auction_lots()
        self.conn.commit()


class DryRunStore:
    """실제 DB 없이 파싱/매핑 로직만 검증. 카운트만 집계하고 항상 새로 적재한다고 가정."""

    def __init__(self) -> None:
        self.counts = {
            "sources": 0,
            "artists": 0,
            "artworks": 0,
            "museum_holdings": 0,
            "museums": 0,
            "galleries": 0,
            "gallery_representations": 0,
        }
        self._museum_cache: dict[str, str] = {}
        self._gallery_cache: dict[str, str] = {}
        self._artist_cache: dict[str, str] = {}
        self._auction_house_cache: dict[str, str] = {}
        self._auction_cache: dict[str, str] = {}
        self._collector_cache: dict[str, str] = {}
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
        key = name.lower()
        if key not in self._artist_cache:
            self.counts["artists"] += 1
            self._artist_cache[key] = self._fresh_id()
        return self._artist_cache[key]

    def get_or_create_artist_safe(self, name: str | None, **fields: Any) -> str | None:
        return self.get_or_create_artist(name, **fields)

    def get_or_create_gallery(self, name: str, city: str | None = None, country: str | None = None, website: str | None = None) -> str:
        if name not in self._gallery_cache:
            self.counts["galleries"] += 1
            self._gallery_cache[name] = self._fresh_id()
        return self._gallery_cache[name]

    def insert_gallery_representation(self, **fields: Any) -> None:
        self.counts["gallery_representations"] += 1

    def insert_artwork(self, **fields: Any) -> str:
        self.counts["artworks"] += 1
        if len(self.samples) < 5:
            self.samples.append(fields)
        return self._fresh_id()

    def insert_museum_holding(self, **fields: Any) -> None:
        self.counts["museum_holdings"] += 1

    def get_or_create_auction_house(self, name: str, country: str | None = None) -> str:
        if name not in self._auction_house_cache:
            self.counts.setdefault("auction_houses", 0)
            self.counts["auction_houses"] += 1
            self._auction_house_cache[name] = self._fresh_id()
        return self._auction_house_cache[name]

    def get_or_create_auction(self, auction_house_id: str, auction_date: str | None, source_id: str | None = None) -> str:
        cache_key = f"{auction_house_id}:{auction_date}"
        if cache_key not in self._auction_cache:
            self.counts.setdefault("auctions", 0)
            self.counts["auctions"] += 1
            self._auction_cache[cache_key] = self._fresh_id()
        return self._auction_cache[cache_key]

    def insert_auction_lot(self, **fields: Any) -> None:
        self.counts.setdefault("auction_lots", 0)
        self.counts["auction_lots"] += 1

    def insert_auction_lot_batch(self, **fields: Any) -> None:
        self.insert_auction_lot(**fields)
        if len(self.samples) < 5:
            self.samples.append(fields)

    def get_or_create_collector(self, name: str, is_institution: bool = False) -> str:
        key = name.lower()
        if key not in self._collector_cache:
            self.counts.setdefault("collectors", 0)
            self.counts["collectors"] += 1
            self._collector_cache[key] = self._fresh_id()
        return self._collector_cache[key]

    def insert_provenance_record(self, **fields: Any) -> None:
        self.counts.setdefault("provenance_records", 0)
        self.counts["provenance_records"] += 1
        if len(self.samples) < 5:
            self.samples.append(fields)

    def commit(self) -> None:
        pass
