"""Met 원본(CSV) -> museums/artists/artworks/museum_holdings 적재.

기존엔 오브젝트당 API 요청 방식(raw/met/<id>.json)이었으나 너무 느려서
MetObjects.csv 벌크 다운로드로 전환함(2026-09-02, crawlers/met.py 참고).
API 시절 부서 ID 9/11/12/15/19/21(Drawings and Prints, European Paintings,
European Sculpture and Decorative Arts, The Robert Lehman Collection,
Photographs, Modern Art)과 동일한 스코프를 CSV의 Department 텍스트 컬럼으로
유지한다 — 무기/의상/악기 등 유물성 부서 제외 방침 그대로.
"""
from __future__ import annotations

import csv
import json

from raw_iter import RAW_ROOT, to_int

MUSEUM_NAME = "The Metropolitan Museum of Art (Met)"
MET_DIR = RAW_ROOT / "met"

ART_DEPARTMENTS = {
    "Drawings and Prints",
    "European Paintings",
    "European Sculpture and Decorative Arts",
    "The Robert Lehman Collection",
    "Photographs",
    "Modern Art",
    "Modern and Contemporary Art",
}


def _read_meta() -> dict:
    return json.loads((MET_DIR / "MetObjects.meta.json").read_text(encoding="utf-8"))


def load(store) -> int:
    meta = _read_meta()
    if store.source_already_loaded(meta["raw_path"]):
        print("[pipeline:met] 이미 적재됨 — 건너뜀")
        return 0

    museum_id = store.get_or_create_museum(MUSEUM_NAME, MUSEUM_NAME)
    source_id = store.insert_source(meta)

    loaded = 0
    with open(MET_DIR / "MetObjects.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("Department") not in ART_DEPARTMENTS:
                continue

            # Met CSV는 작가가 여럿인 오브젝트(주로 판화)를 "|"로 구분해 병렬
            # 배열로 담는다(Artist Display Name/Nationality/Begin Date/...가
            # 전부 같은 순서로 "|" 분리됨) — 스키마가 artworks.artist_id 단일
            # FK라 전원을 다 못 담으므로, Met 컨벤션대로 첫 번째(주작가)만 취함.
            artist_name = (row.get("Artist Display Name") or "").split("|")[0].strip() or None
            nationality = (row.get("Artist Nationality") or "").split("|")[0].strip() or None
            begin_date = (row.get("Artist Begin Date") or "").split("|")[0].strip()
            end_date = (row.get("Artist End Date") or "").split("|")[0].strip()
            bio = (row.get("Artist Display Bio") or "").split("|")[0].strip() or None
            artist_id = store.get_or_create_artist(
                artist_name,
                nationality=nationality,
                birth_year=to_int(begin_date),
                death_year=to_int(end_date),
                bio=bio,
                source_id=source_id,
            )

            artwork_id = store.insert_artwork(
                artist_id=artist_id,
                title=row.get("Title") or "(제목 없음)",
                year_created=(row.get("Object Date") or None),
                medium=(row.get("Medium") or None),
                dimensions=(row.get("Dimensions") or None),
                description=(row.get("Credit Line") or None),
                source_id=source_id,
            )

            store.insert_museum_holding(
                museum_id=museum_id,
                artwork_id=artwork_id,
                accession_number=(row.get("Object Number") or None),
                source_id=source_id,
            )
            loaded += 1
            if loaded % 20000 == 0:
                print(f"[pipeline:met] {loaded}건 진행 중...")

    store.commit()
    print(f"[pipeline:met] {loaded}건 적재 (미술 관련 부서만 필터링)")
    return loaded
