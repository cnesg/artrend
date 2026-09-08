"""릭스뮤지엄 원본(raw/rijksmuseum/*.json, oai_dc 필드) -> DB 적재."""
from __future__ import annotations

from raw_iter import iter_records

MUSEUM_NAME = "Rijksmuseum"


def _first(field) -> str | None:
    if isinstance(field, list) and field:
        return field[0]
    return field or None


def load(store) -> int:
    museum_id = store.get_or_create_museum(MUSEUM_NAME, MUSEUM_NAME)
    loaded = 0

    for record_id, data, meta in iter_records("rijksmuseum"):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        source_id = store.insert_source(meta)

        artist_name = _first(data.get("creator"))
        title = _first(data.get("title")) or "(제목 없음)"
        date_created = _first(data.get("date"))
        medium = _first(data.get("format"))
        description = _first(data.get("description"))
        accession = _first(data.get("identifier"))

        artist_id = store.get_or_create_artist(artist_name, source_id=source_id)

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=title,
            year_created=date_created,
            medium=medium,
            dimensions=None,
            description=description,
            source_id=source_id,
        )

        store.insert_museum_holding(
            museum_id=museum_id,
            artwork_id=artwork_id,
            accession_number=accession,
            source_id=source_id,
        )
        loaded += 1

    store.commit()
    print(f"[pipeline:rijksmuseum] {loaded}건 적재")
    return loaded
