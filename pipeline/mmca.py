"""MMCA 원본(JSON) -> museums/artists/artworks/museum_holdings 적재.

크롤러가 받은 건 소장품 검색 목록 API 응답이라 재료/크기(medium/dimensions)는
없다 — 상세 페이지를 따로 받아야 채울 수 있는 필드라 지금은 비워둔다.
"""
from __future__ import annotations

from raw_iter import iter_records

MUSEUM_NAME = "국립현대미술관 (MMCA)"


def load(store) -> int:
    museum_id = store.get_or_create_museum(MUSEUM_NAME, "National Museum of Modern and Contemporary Art, Korea")
    loaded = 0

    for _record_id, data, meta in iter_records("mmca"):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        source_id = store.insert_source(meta)

        artist_name = (data.get("artistnm") or "").strip() or None
        artist_id = store.get_or_create_artist(
            artist_name,
            name_en=(data.get("artistnmEng") or None),
            source_id=source_id,
        )

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=data.get("wrkNm") or "(제목 없음)",
            title_en=(data.get("wrkNmEng") or None),
            year_created=(data.get("wrkProdTermRangeTextKor") or data.get("wrkProdTerm") or None),
            source_id=source_id,
        )

        store.insert_museum_holding(
            museum_id=museum_id,
            artwork_id=artwork_id,
            accession_number=(data.get("wrkMngNo") or None),
            source_id=source_id,
        )
        loaded += 1

    store.commit()
    print(f"[pipeline:mmca] {loaded}건 적재")
    return loaded
