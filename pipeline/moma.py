"""MoMA 원본(CSV) -> museums/artists/artworks/museum_holdings 적재.

MoMA 소장품엔 Design/Architecture/Mies van der Rohe Archive 등 건축·디자인
아카이브가 섞여 있다 — 유물은 아니지만 프로젝트 스코프(미술품)와는 다른
범주라 ART_CLASSIFICATIONS로 순수 미술 분류만 필터링한다.
"""
from __future__ import annotations

import csv

from raw_iter import RAW_ROOT, to_int

MUSEUM_NAME = "The Museum of Modern Art (MoMA)"
MOMA_DIR = RAW_ROOT / "moma"

ART_CLASSIFICATIONS = {
    "Photograph",
    "Print",
    "Drawing",
    "Painting",
    "Sculpture",
    "Video",
    "Installation",
    "Multiple",
    "Film",
    "Collage",
    "Work on Paper",
    "Illustrated Book",
    "Portfolio",
    "Performance",
}


def _read_meta() -> dict:
    import json

    return json.loads((MOMA_DIR / "Artworks.meta.json").read_text(encoding="utf-8"))


def load(store) -> int:
    meta = _read_meta()
    if store.source_already_loaded(meta["raw_path"]):
        print("[pipeline:moma] 이미 적재됨 — 건너뜀")
        return 0

    museum_id = store.get_or_create_museum(MUSEUM_NAME, MUSEUM_NAME)
    source_id = store.insert_source(meta)

    loaded = 0
    with open(MOMA_DIR / "Artworks.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("Classification") not in ART_CLASSIFICATIONS:
                continue

            # MoMA CSV는 작가가 여럿이면 Artist를 ", "로, ConstituentID를 ", "로,
            # Nationality/BeginDate/EndDate를 "(A) (B)"로 병렬 나열한다. Met "|"와 같은
            # 구조라 첫 번째(주작가)만 취한다(2026-09-15, 진단 §3-2-3 — 이전엔 통째로
            # 저장해 "Pablo Picasso, Ilia Zdanevich" 같은 행이 1,126건 생겼음).
            multi = ", " in (row.get("ConstituentID") or "")
            artist_name = (row.get("Artist") or "").strip() or None
            nationality = (row.get("Nationality") or "").strip()
            begin_date = (row.get("BeginDate") or "").strip()
            end_date = (row.get("EndDate") or "").strip()
            bio = (row.get("ArtistBio") or "").strip()
            if multi and artist_name:
                artist_name = artist_name.split(", ")[0].strip() or None
                nationality = nationality.split(") (")[0]
                begin_date = begin_date.split(") (")[0]
                end_date = end_date.split(") (")[0]
                bio = bio.split(") (")[0]
            artist_id = store.get_or_create_artist(
                artist_name,
                nationality=nationality.strip("() ") or None,
                birth_year=to_int(begin_date.strip("() ")) or None,
                death_year=to_int(end_date.strip("() ")) or None,
                bio=(bio.strip("() ") or None),
                source_id=source_id,
            )

            artwork_id = store.insert_artwork(
                artist_id=artist_id,
                title=row.get("Title") or "(제목 없음)",
                year_created=(row.get("Date") or None),
                medium=(row.get("Medium") or None),
                dimensions=(row.get("Dimensions") or None),
                description=(row.get("CreditLine") or None),
                source_id=source_id,
            )

            store.insert_museum_holding(
                museum_id=museum_id,
                artwork_id=artwork_id,
                accession_number=(row.get("AccessionNumber") or None),
                source_id=source_id,
            )
            loaded += 1

    store.commit()
    print(f"[pipeline:moma] {loaded}건 적재 (미술 분류만 필터링)")
    return loaded
