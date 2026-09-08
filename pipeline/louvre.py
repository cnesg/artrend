"""루브르 원본(raw/louvre/*.json) -> museums/artists/artworks/museum_holdings 적재."""
from __future__ import annotations

from raw_iter import iter_records

MUSEUM_NAME = "Musée du Louvre"


def _accession(obj_numbers) -> str | None:
    if isinstance(obj_numbers, list) and obj_numbers:
        n0 = obj_numbers[0]
        return n0.get("value") if isinstance(n0, dict) else str(n0)
    return None


def _dimension_text(dims) -> str | None:
    if not isinstance(dims, list) or not dims:
        return None
    parts = [d.get("displayDimension") for d in dims if isinstance(d, dict) and d.get("displayDimension")]
    return "; ".join(parts) if parts else None


def load(store) -> int:
    museum_id = store.get_or_create_museum(MUSEUM_NAME, MUSEUM_NAME)
    loaded = 0

    for record_id, data, meta in iter_records("louvre"):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        source_id = store.insert_source(meta)

        creators = data.get("creator") or []
        artist_name = None
        if isinstance(creators, list) and creators:
            c0 = creators[0]
            artist_name = c0.get("label") if isinstance(c0, dict) else str(c0)

        title = data.get("title") or "(제목 없음)"
        materials = data.get("materialsAndTechniques")

        artist_id = store.get_or_create_artist(artist_name, source_id=source_id)
        accession = _accession(data.get("objectNumber"))

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=title,
            year_created=data.get("displayDateCreated"),
            medium=materials,
            dimensions=_dimension_text(data.get("dimension")),
            description=data.get("description") or data.get("provenance"),
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
    print(f"[pipeline:louvre] {loaded}건 적재")
    return loaded
