"""Tate 원본(CSV) -> museums/artists/artworks/museum_holdings 적재."""
from __future__ import annotations

import csv
import json

from raw_iter import RAW_ROOT, to_int

MUSEUM_NAME = "Tate"
TATE_DIR = RAW_ROOT / "tate"


def _read_meta(name: str) -> dict:
    return json.loads((TATE_DIR / f"{name}.meta.json").read_text(encoding="utf-8"))


def _load_artists() -> dict[str, dict]:
    artists: dict[str, dict] = {}
    with open(TATE_DIR / "artist_data.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            artists[row["id"]] = {
                "name": (row.get("name") or "").strip() or None,
                "birth_year": to_int(row.get("yearOfBirth")),
                "death_year": to_int(row.get("yearOfDeath")),
                "nationality": (row.get("placeOfBirth") or None),
            }
    return artists


def load(store) -> int:
    artwork_meta = _read_meta("artwork_data")
    if store.source_already_loaded(artwork_meta["raw_path"]):
        print("[pipeline:tate] 이미 적재됨 — 건너뜀")
        return 0

    artists = _load_artists()
    museum_id = store.get_or_create_museum(MUSEUM_NAME, MUSEUM_NAME)
    source_id = store.insert_source(artwork_meta)

    loaded = 0
    with open(TATE_DIR / "artwork_data.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            info = artists.get(row.get("artistId") or "")
            artist_name = info["name"] if info else (row.get("artist") or None)
            artist_id = store.get_or_create_artist(
                artist_name,
                birth_year=(info["birth_year"] if info else None),
                death_year=(info["death_year"] if info else None),
                nationality=(info["nationality"] if info else None),
                source_id=source_id,
            )

            dims = row.get("dimensions") or None
            artwork_id = store.insert_artwork(
                artist_id=artist_id,
                title=row.get("title") or "(제목 없음)",
                year_created=(row.get("dateText") or row.get("year") or None),
                medium=(row.get("medium") or None),
                dimensions=dims,
                description=(row.get("creditLine") or None),
                source_id=source_id,
            )

            store.insert_museum_holding(
                museum_id=museum_id,
                artwork_id=artwork_id,
                accession_number=(row.get("accession_number") or None),
                source_id=source_id,
            )
            loaded += 1

    store.commit()
    print(f"[pipeline:tate] {loaded}건 적재")
    return loaded
