"""갤러리 작가 로스터(raw/gallery_<key>/) -> galleries/artists/gallery_representations 적재.

미술관 로더와 달리 artworks/museum_holdings를 채우지 않는다 — 갤러리 크롤러가
작가 로스터만 수집했기 때문에(관계 데이터), 여기서도 galleries 테이블과
gallery_representations 연결만 만든다.
"""
from __future__ import annotations

from raw_iter import iter_records

# site key -> (표시명, 도시, 국가)
GALLERY_INFO: dict[str, tuple[str, str, str]] = {
    "kukje": ("국제갤러리 (Kukje Gallery)", "서울", "대한민국"),
    "gallery_hyundai": ("갤러리현대 (Gallery Hyundai)", "서울", "대한민국"),
    "pkm": ("PKM갤러리", "서울", "대한민국"),
    "arario": ("아라리오갤러리 (Arario Gallery)", "서울", "대한민국"),
    "ropac": ("타데우스로팍 서울 (Thaddaeus Ropac)", "서울", "대한민국"),
    "wooson": ("우손갤러리 (Wooson Gallery)", "대구", "대한민국"),
    "gallery_baton": ("갤러리바톤 (Gallery Baton)", "서울", "대한민국"),
    "johyun": ("조현화랑 (Johyun Gallery)", "부산", "대한민국"),
    "pace": ("페이스갤러리 (Pace Gallery)", "뉴욕", "미국"),
}


def load(store) -> int:
    loaded = 0
    for key, (display_name, city, country) in GALLERY_INFO.items():
        site_name = f"gallery_{key}"
        gallery_id = None

        for _record_id, data, meta in iter_records(site_name):
            if store.source_already_loaded(meta["raw_path"]):
                continue

            if gallery_id is None:
                gallery_id = store.get_or_create_gallery(display_name, city=city, country=country, website=data.get("url"))

            source_id = store.insert_source(meta)
            artist_name = (data.get("name") or "").strip()
            artist_id = store.get_or_create_artist(artist_name, source_id=source_id)
            if artist_id is None:
                continue

            store.insert_gallery_representation(
                gallery_id=gallery_id,
                artist_id=artist_id,
                source_id=source_id,
            )
            loaded += 1

    store.commit()
    print(f"[pipeline:galleries] {loaded}건 적재")
    return loaded
