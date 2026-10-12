"""부산시립미술관 원본(JSON) -> museums/artists/artworks/museum_holdings 적재.

crawlers/busan_art_museum.py는 목록 페이지만 수집(상세페이지가 세션토큰
요구로 이번 스코프 제외) — MMCA와 동일하게 medium/dimensions는 비워둔다.
"""
from __future__ import annotations

from raw_iter import iter_records

MUSEUM_NAME = "부산시립미술관 (Busan Museum of Art)"
MUSEUM_NAME_EN = "Busan Museum of Art"


def load(store) -> int:
    museum_id = store.get_or_create_museum(MUSEUM_NAME, MUSEUM_NAME_EN)
    loaded = 0

    for _record_id, data, meta in iter_records("busan_art_museum"):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        source_id = store.insert_source(meta)

        artist_name = (data.get("wriName") or "").strip() or None
        artist_id = store.get_or_create_artist(artist_name, source_id=source_id)

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=data.get("artKname") or "(제목 없음)",
            year_created=(data.get("year") or None),
            source_id=source_id,
        )

        store.insert_museum_holding(
            museum_id=museum_id,
            artwork_id=artwork_id,
            accession_number=(data.get("manageNo") or None),
            source_id=source_id,
        )
        loaded += 1

    store.commit()
    print(f"[pipeline:busan_art_museum] {loaded}건 적재")
    return loaded
