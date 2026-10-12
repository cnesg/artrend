"""게티박물관(Linked Art JSON, raw/getty/*.json) -> museums/artists/artworks/museum_holdings 적재."""
from __future__ import annotations

from raw_iter import iter_records

MUSEUM_NAME = "The J. Paul Getty Museum"


def _find_label(items, *labels) -> str | None:
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("_label") in labels:
            content = item.get("content")
            if content:
                return content
    return None


def _artist_name(data) -> str | None:
    production = data.get("produced_by")
    if not isinstance(production, dict):
        return None
    name = _find_label(production.get("referred_to_by"), "Artist/Maker (Producer) Name")
    if name:
        return name
    parts = production.get("part") or []
    for p in parts:
        name = _find_label(p.get("referred_to_by"), "Artist/Maker (Producer) Name")
        if name:
            return name
    return None


def load(store) -> int:
    museum_id = store.get_or_create_museum(MUSEUM_NAME, "로스앤젤레스, 미국")
    loaded = 0

    for record_id, data, meta in iter_records("getty"):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        source_id = store.insert_source(meta)

        identifiers = data.get("identified_by") or []
        title = _find_label(identifiers, "Preferred Title", "Primary Title") or data.get("_label") or "(제목 없음)"
        accession = _find_label(identifiers, "Accession Number")

        refs = data.get("referred_to_by") or []
        medium = _find_label(refs, "Materials Description")
        dimensions = _find_label(refs, "Dimensions Statement", "Dimensions Measurement (Formatted)")
        description = _find_label(refs, "Culture Statement")

        artist_name = _artist_name(data)
        artist_id = store.get_or_create_artist(artist_name, source_id=source_id)

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=title,
            year_created=None,
            medium=medium,
            dimensions=dimensions,
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
    print(f"[pipeline:getty] {loaded}건 적재")
    return loaded
