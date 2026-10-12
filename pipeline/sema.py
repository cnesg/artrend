"""SeMA(서울시립미술관) 원본(JSON) -> museums/artists/artworks/museum_holdings 적재.

crawlers/sema.py가 이미 상세페이지까지 받아둬서 medium/dimensions/description/
donor(기증자, credit line 성격)까지 채울 수 있다 — MMCA와 달리 상세 필드 공백 없음.
"""
from __future__ import annotations

from raw_iter import iter_records

MUSEUM_NAME = "서울시립미술관 (SeMA)"
MUSEUM_NAME_EN = "Seoul Museum of Art"


def load(store) -> int:
    museum_id = store.get_or_create_museum(MUSEUM_NAME, MUSEUM_NAME_EN)
    loaded = 0

    for _record_id, data, meta in iter_records("sema"):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        source_id = store.insert_source(meta)

        artist_name = (data.get("wriName") or "").strip() or None
        artist_id = store.get_or_create_artist(artist_name, source_id=source_id)

        description_parts = []
        if data.get("description"):
            description_parts.append(data["description"])
        if data.get("donor"):
            description_parts.append(f"기증자: {data['donor']}")
        description = " / ".join(description_parts) or None

        dimensions = data.get("dimensions")
        frame_dimensions = data.get("frameDimensions")
        if frame_dimensions and frame_dimensions.strip() not in ("", "-"):
            dimensions = f"{dimensions or ''} (액자: {frame_dimensions})".strip()

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=data.get("artKname") or "(제목 없음)",
            year_created=(data.get("year") or None),
            medium=(data.get("medium") or None),
            dimensions=(dimensions or None),
            description=description,
            source_id=source_id,
        )

        store.insert_museum_holding(
            museum_id=museum_id,
            artwork_id=artwork_id,
            accession_number=(data.get("accessionNumber") or None),
            source_id=source_id,
        )
        loaded += 1

    store.commit()
    print(f"[pipeline:sema] {loaded}건 적재")
    return loaded
