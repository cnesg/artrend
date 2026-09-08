"""V&A(Victoria and Albert Museum) 원본(raw/vam/*.json) -> DB 적재.

crawlers/vam.py가 objectType별로 검색 API 결과를 저장한 레코드를 정규화한다.
검색 결과 레벨 필드만 쓰고(상세 조회는 하지 않음 — 대량 수집 속도 우선) 있음.
"""
from __future__ import annotations

from raw_iter import iter_records

SITE_NAME = "vam"
MUSEUM_NAME = "Victoria and Albert Museum"


def load(store) -> int:
    museum_id = store.get_or_create_museum(MUSEUM_NAME, "런던, 영국")
    loaded = 0

    for _record_id, data, meta in iter_records(SITE_NAME):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        source_id = store.insert_source(meta)

        maker = data.get("_primaryMaker") or {}
        artist_name = (maker.get("name") or "").strip() or None
        if artist_name and artist_name.lower() == "unknown":
            artist_name = None
        artist_id = store.get_or_create_artist(artist_name, source_id=source_id) if artist_name else None

        title = data.get("_primaryTitle") or "(제목 없음)"

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=title,
            year_created=data.get("_primaryDate"),
            medium=data.get("_object_type_query"),
            dimensions=None,
            description=data.get("_primaryPlace"),
            source_id=source_id,
        )

        store.insert_museum_holding(
            museum_id=museum_id,
            artwork_id=artwork_id,
            accession_number=data.get("accessionNumber"),
            source_id=source_id,
        )
        loaded += 1
        if loaded % 10000 == 0:
            print(f"[pipeline:vam] {loaded}건 진행 중...")

    store.commit()
    print(f"[pipeline:vam] {loaded}건 적재")
    return loaded
