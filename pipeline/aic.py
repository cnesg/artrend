"""Art Institute of Chicago 원본(JSON) -> museums/artists/artworks/museum_holdings 적재."""
from __future__ import annotations

from raw_iter import iter_records

MUSEUM_NAME = "Art Institute of Chicago"


def load(store) -> int:
    museum_id = store.get_or_create_museum(MUSEUM_NAME, MUSEUM_NAME)
    loaded = 0

    for record_id, data, meta in iter_records("aic"):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        source_id = store.insert_source(meta)

        artist_name = (data.get("artist_title") or "").strip() or None
        artist_id = store.get_or_create_artist(
            artist_name,
            bio=(data.get("artist_display") or None),
            source_id=source_id,
        )

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=data.get("title") or "(제목 없음)",
            year_created=(data.get("date_display") or None),
            medium=(data.get("medium_display") or None),
            dimensions=(data.get("dimensions") or None),
            description=(data.get("provenance_text") or data.get("credit_line") or None),
            source_id=source_id,
        )

        store.insert_museum_holding(
            museum_id=museum_id,
            artwork_id=artwork_id,
            accession_number=record_id,
            source_id=source_id,
        )
        loaded += 1

    store.commit()
    print(f"[pipeline:aic] {loaded}건 적재")
    return loaded
