"""SMK 원본(JSON) -> museums/artists/artworks/museum_holdings 적재."""
from __future__ import annotations

from raw_iter import iter_records, to_int

MUSEUM_NAME = "Statens Museum for Kunst (SMK)"


def _dim_text(dimensions: list[dict]) -> str | None:
    if not dimensions:
        return None
    parts = [f"{d.get('type')} {d.get('value')}{d.get('unit', '')}" for d in dimensions if d.get("value")]
    return "; ".join(parts) or None


def load(store) -> int:
    museum_id = store.get_or_create_museum(MUSEUM_NAME, MUSEUM_NAME)
    loaded = 0

    for _record_id, data, meta in iter_records("smk"):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        source_id = store.insert_source(meta)

        production = (data.get("production") or [{}])[0]
        artist_name = production.get("creator") or (data.get("artist") or [None])[0]
        artist_id = store.get_or_create_artist(
            artist_name,
            nationality=production.get("creator_nationality"),
            birth_year=to_int((production.get("creator_date_of_birth") or "")[:4] or None),
            death_year=to_int((production.get("creator_date_of_death") or "")[:4] or None),
            source_id=source_id,
        )

        titles = data.get("titles") or [{}]
        production_date = (data.get("production_date") or [{}])[0]

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=titles[0].get("title") or "(제목 없음)",
            year_created=(production_date.get("period") or None),
            medium=", ".join(data.get("techniques") or []) or None,
            dimensions=_dim_text(data.get("dimensions") or []),
            description=", ".join(data.get("credit_line") or []) or None,
            source_id=source_id,
        )

        store.insert_museum_holding(
            museum_id=museum_id,
            artwork_id=artwork_id,
            accession_number=(data.get("object_number") or None),
            source_id=source_id,
        )
        loaded += 1

    store.commit()
    print(f"[pipeline:smk] {loaded}건 적재")
    return loaded
