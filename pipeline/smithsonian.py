"""Smithsonian 원본(JSON) -> museums/artists/artworks/museum_holdings 적재.

유닛 코드(SAAM/HMSG/NPG/CHNDM/FSG/NMAfA)별로 별도 museums 행을 만든다
— 크롤러 단계에서 이미 미술 소장 부서만 필터링해서 받았기 때문에
NGA처럼 유물 걱정 없이 그대로 적재하면 된다.
"""
from __future__ import annotations

from raw_iter import iter_records

UNIT_NAMES = {
    "SAAM": "Smithsonian American Art Museum",
    "HMSG": "Hirshhorn Museum and Sculpture Garden",
    "NPG": "National Portrait Gallery",
    "CHNDM": "Cooper Hewitt, Smithsonian Design Museum",
    "FSG": "National Museum of Asian Art (Freer)",
    "NMAfA": "National Museum of African Art",
}


def _field(freetext: dict, key: str, *labels: str) -> str | None:
    for entry in freetext.get(key, []):
        if entry.get("label") in labels:
            return entry.get("content")
    return None


def load(store) -> int:
    museum_ids: dict[str, str] = {}
    loaded = 0

    for _record_id, data, meta in iter_records("smithsonian"):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        unit_code = data.get("unitCode") or "SI"
        museum_name = UNIT_NAMES.get(unit_code, f"Smithsonian ({unit_code})")
        if unit_code not in museum_ids:
            museum_ids[unit_code] = store.get_or_create_museum(museum_name, museum_name)
        museum_id = museum_ids[unit_code]

        source_id = store.insert_source(meta)

        freetext = (data.get("content") or {}).get("freetext") or {}
        non_repeating = (data.get("content") or {}).get("descriptiveNonRepeating") or {}

        artist_name = _field(freetext, "name", "Artist", "Attributed to")
        artist_id = store.get_or_create_artist(artist_name, source_id=source_id)

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=data.get("title") or "(제목 없음)",
            year_created=_field(freetext, "date", "Date"),
            medium=_field(freetext, "physicalDescription", "Medium"),
            dimensions=_field(freetext, "physicalDescription", "Dimensions"),
            description=_field(freetext, "creditLine", "Credit Line"),
            source_id=source_id,
        )

        store.insert_museum_holding(
            museum_id=museum_id,
            artwork_id=artwork_id,
            accession_number=(non_repeating.get("record_ID") or _field(freetext, "identifier", "Object number")),
            source_id=source_id,
        )
        loaded += 1

    store.commit()
    print(f"[pipeline:smithsonian] {loaded}건 적재")
    return loaded
