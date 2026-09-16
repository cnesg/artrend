"""GMoMA(경기도미술관) 원본(JSON) -> museums/artists/artworks/museum_holdings 적재.

crawlers/gmoma.py가 상세페이지까지 다 받아둬서 medium/dimensions/
description까지 채울 수 있다.
"""
from __future__ import annotations

from raw_iter import iter_records

MUSEUM_NAME = "경기도미술관 (GMoMA)"
MUSEUM_NAME_EN = "Gyeonggi Museum of Modern Art"


def load(store) -> int:
    museum_id = store.get_or_create_museum(MUSEUM_NAME, MUSEUM_NAME_EN)
    loaded = 0

    for _record_id, data, meta in iter_records("gmoma"):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        source_id = store.insert_source(meta)

        artist_name = (data.get("wriName") or "").strip() or None
        artist_id = store.get_or_create_artist(artist_name, source_id=source_id)

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=data.get("artKname") or "(제목 없음)",
            year_created=(data.get("year") or None),
            medium=(data.get("medium") or None),
            dimensions=(data.get("dimensions") or None),
            description=(data.get("description") or None),
            source_id=source_id,
        )

        store.insert_museum_holding(
            museum_id=museum_id,
            artwork_id=artwork_id,
            source_id=source_id,
        )
        loaded += 1

    store.commit()
    print(f"[pipeline:gmoma] {loaded}건 적재")
    return loaded
