"""Cleveland Museum of Art 원본(JSON) -> museums/artists/artworks/museum_holdings 적재."""
from __future__ import annotations

from raw_iter import iter_records, to_int

MUSEUM_NAME = "Cleveland Museum of Art"


def _primary_creator(data: dict) -> dict | None:
    creators = data.get("creators") or []
    artists = [c for c in creators if (c.get("role") or "").lower() == "artist"] or creators
    return artists[0] if artists else None


def _creator_name(creator: dict) -> str | None:
    description = (creator.get("description") or "").strip()
    if not description:
        return None
    return description.split(" (")[0].strip() or None


def load(store) -> int:
    museum_id = store.get_or_create_museum(MUSEUM_NAME, MUSEUM_NAME)
    loaded = 0

    for _record_id, data, meta in iter_records("cleveland"):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        source_id = store.insert_source(meta)

        creator = _primary_creator(data)
        artist_name = _creator_name(creator) if creator else None
        artist_id = None
        if creator:
            artist_id = store.get_or_create_artist(
                artist_name,
                birth_year=to_int(creator.get("birth_year")),
                death_year=to_int(creator.get("death_year")),
                bio=(creator.get("biography") or None),
                source_id=source_id,
            )

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=data.get("title") or "(제목 없음)",
            year_created=(data.get("creation_date") or None),
            medium=(data.get("technique") or None),
            dimensions=(data.get("measurements") or None),
            description=(data.get("tombstone") or None),
            source_id=source_id,
        )

        store.insert_museum_holding(
            museum_id=museum_id,
            artwork_id=artwork_id,
            accession_number=(data.get("accession_number") or None),
            source_id=source_id,
        )
        loaded += 1

    store.commit()
    print(f"[pipeline:cleveland] {loaded}건 적재")
    return loaded
