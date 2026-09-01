"""NGA(National Gallery of Art) CSV 덤프 -> museums/artists/artworks/museum_holdings 적재.

objects.csv(28만 행)가 핵심 소스. constituents.csv에서 작가명을 찾고,
objects_constituents.csv에서 각 작품의 주 작가(roletype=artist, displayorder 최소)를 연결한다.
provenancetext는 구조화된 provenance_records 매칭 없이 artworks.description에 원문 그대로 보존한다
— 소유자 개체(컬렉터/미술관 등) 인식·매칭은 별도 작업으로 남겨둠.
"""
from __future__ import annotations

import csv
import json

from raw_iter import RAW_ROOT, to_int

MUSEUM_NAME = "National Gallery of Art"
NGA_DIR = RAW_ROOT / "nga"


def _read_meta(name: str) -> dict:
    return json.loads((NGA_DIR / f"{name}.meta.json").read_text(encoding="utf-8"))


def _load_constituents() -> dict[str, dict]:
    constituents: dict[str, dict] = {}
    with open(NGA_DIR / "constituents.csv", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            constituents[row["constituentid"]] = {
                "name": (row.get("preferreddisplayname") or "").strip() or None,
                "nationality": (row.get("nationality") or None),
                "birth_year": to_int(row.get("beginyear")),
                "death_year": to_int(row.get("endyear")),
            }
    return constituents


def _load_primary_artists() -> dict[str, str]:
    """objectid -> constituentid (roletype=artist 중 displayorder 최소값)."""
    best: dict[str, tuple[int, str]] = {}
    with open(NGA_DIR / "objects_constituents.csv", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("roletype") != "artist":
                continue
            object_id = row["objectid"]
            order = to_int(row.get("displayorder")) or 0
            current = best.get(object_id)
            if current is None or order < current[0]:
                best[object_id] = (order, row["constituentid"])
    return {oid: cid for oid, (_order, cid) in best.items()}


def load(store, limit: int | None = None) -> int:
    objects_meta = _read_meta("objects")
    if store.source_already_loaded(objects_meta["raw_path"]):
        print("[pipeline:nga] 이미 적재됨 — 건너뜀")
        return 0

    print("[pipeline:nga] constituents.csv 로딩 중...")
    constituents = _load_constituents()
    print(f"[pipeline:nga] 작가 후보 {len(constituents)}명")

    print("[pipeline:nga] objects_constituents.csv에서 주 작가 매핑 구성 중...")
    primary_artist = _load_primary_artists()

    museum_id = store.get_or_create_museum(MUSEUM_NAME, MUSEUM_NAME)
    objects_source_id = store.insert_source(objects_meta)

    loaded = 0
    with open(NGA_DIR / "objects.csv", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if limit is not None and loaded >= limit:
                break

            constituent_id = primary_artist.get(row["objectid"])
            artist_id = None
            if constituent_id and constituent_id in constituents:
                info = constituents[constituent_id]
                artist_id = store.get_or_create_artist(
                    info["name"],
                    nationality=info["nationality"],
                    birth_year=info["birth_year"],
                    death_year=info["death_year"],
                    source_id=objects_source_id,
                )

            artwork_id = store.insert_artwork(
                artist_id=artist_id,
                title=row.get("title") or "(제목 없음)",
                year_created=(row.get("displaydate") or None),
                medium=(row.get("medium") or None),
                dimensions=(row.get("dimensions") or None),
                description=(row.get("provenancetext") or row.get("creditline") or None),
                source_id=objects_source_id,
            )

            store.insert_museum_holding(
                museum_id=museum_id,
                artwork_id=artwork_id,
                accession_number=(row.get("accessionnum") or None),
                source_id=objects_source_id,
            )
            loaded += 1

    store.commit()
    print(f"[pipeline:nga] {loaded}건 적재")
    return loaded
