"""Met 원본(JSON) -> museums/artists/artworks/museum_holdings 적재."""
from __future__ import annotations

from raw_iter import iter_records, to_int, year_to_date

MUSEUM_NAME = "The Metropolitan Museum of Art"


def load(store) -> int:
    museum_id = store.get_or_create_museum(MUSEUM_NAME, MUSEUM_NAME)
    loaded = 0

    for _record_id, data, meta in iter_records("met"):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        source_id = store.insert_source(meta)

        artist_name = (data.get("artistDisplayName") or "").strip() or None
        artist_id = store.get_or_create_artist(
            artist_name,
            nationality=(data.get("artistNationality") or None),
            bio=(data.get("artistDisplayBio") or None),
            birth_year=to_int(data.get("artistBeginDate")),
            death_year=to_int(data.get("artistEndDate")),
            source_id=source_id,
        )

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=data.get("title") or data.get("objectName") or "(제목 없음)",
            year_created=(data.get("objectDate") or None),
            medium=(data.get("medium") or None),
            dimensions=(data.get("dimensions") or None),
            description=(data.get("creditLine") or None),
            source_id=source_id,
        )

        store.insert_museum_holding(
            museum_id=museum_id,
            artwork_id=artwork_id,
            accession_number=(data.get("accessionNumber") or None),
            acquisition_date=year_to_date(data.get("accessionYear")),
            source_id=source_id,
        )
        loaded += 1

    store.commit()
    print(f"[pipeline:met] {loaded}건 적재")
    return loaded
