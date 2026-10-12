"""월터스 미술관 원본(CSV, CC0) -> museums/artists/artworks/museum_holdings 적재.

raw/walters/art.csv(작품) + creators.csv(작가 id -> 이름)를 함께 읽는다.
art.csv의 Creators 필드는 작가 id를 '|'로 join한 문자열이라 첫 번째 id만 사용한다.
"""
from __future__ import annotations

import csv
import json

from raw_iter import RAW_ROOT, to_int

MUSEUM_NAME = "Walters Art Museum"
WALTERS_DIR = RAW_ROOT / "walters"


def _read_meta() -> dict:
    return json.loads((WALTERS_DIR / "art.meta.json").read_text(encoding="utf-8"))


def _load_creators() -> dict[str, str]:
    creators: dict[str, str] = {}
    with open(WALTERS_DIR / "creators.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            cid = row.get("id")
            name = (row.get("name") or "").strip()
            if cid and name:
                creators[cid] = name
    return creators


def load(store) -> int:
    meta = _read_meta()
    if store.source_already_loaded(meta["raw_path"]):
        print("[pipeline:walters] 이미 적재됨 — 건너뜀")
        return 0

    museum_id = store.get_or_create_museum(MUSEUM_NAME, "볼티모어, 미국")
    source_id = store.insert_source(meta)
    creators = _load_creators()

    loaded = 0
    with open(WALTERS_DIR / "art.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            creator_ids = (row.get("Creators") or "").split("|")
            artist_name = creators.get(creator_ids[0]) if creator_ids and creator_ids[0] else None

            artist_id = store.get_or_create_artist(artist_name, source_id=source_id)

            artwork_id = store.insert_artwork(
                artist_id=artist_id,
                title=row.get("Title") or "(제목 없음)",
                year_created=row.get("DateText") or None,
                medium=row.get("Medium") or None,
                dimensions=row.get("Dimensions") or None,
                description=row.get("CreditLine") or row.get("Provenance") or None,
                source_id=source_id,
            )

            store.insert_museum_holding(
                museum_id=museum_id,
                artwork_id=artwork_id,
                accession_number=row.get("ObjectNumber") or None,
                source_id=source_id,
            )
            loaded += 1
            if loaded % 10000 == 0:
                print(f"[pipeline:walters] {loaded}건 진행 중...")

    store.commit()
    print(f"[pipeline:walters] {loaded}건 적재")
    return loaded
