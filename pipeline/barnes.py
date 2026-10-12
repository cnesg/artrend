"""반스 파운데이션 원본(raw/barnes/*.json) -> museums/artists/artworks/museum_holdings 적재."""
from __future__ import annotations

from raw_iter import iter_records

MUSEUM_NAME = "Barnes Foundation"


def load(store) -> int:
    museum_id = store.get_or_create_museum(MUSEUM_NAME, "필라델피아, 미국")
    loaded = 0

    for record_id, data, meta in iter_records("barnes"):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        source_id = store.insert_source(meta)

        # Barnes API의 "people" 필드는 공저자가 있으면 "; "로 이어붙여 반환한다
        # (예: "Acoma Mary ; Unidentified Maker") — Met "|"/mia ";" 케이스와 동일한
        # 다중 작가 오염 위험이라 첫 번째만 주 작가로 취한다.
        artist_name = (data.get("people") or "").split(";")[0].strip() or None
        title = data.get("title") or "(제목 없음)"

        artist_id = store.get_or_create_artist(artist_name, source_id=source_id)

        description = data.get("longDescription") or data.get("shortDescription") or data.get("publishedProvenance")

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=title,
            year_created=data.get("displayDate"),
            medium=data.get("medium"),
            dimensions=data.get("dimensions"),
            description=description,
            source_id=source_id,
        )

        store.insert_museum_holding(
            museum_id=museum_id,
            artwork_id=artwork_id,
            accession_number=data.get("invno") or None,
            source_id=source_id,
        )
        loaded += 1

    store.commit()
    print(f"[pipeline:barnes] {loaded}건 적재")
    return loaded
