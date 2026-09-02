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
    "lehmannmaupin": ("리만머핀 (Lehmann Maupin)", "뉴욕", "미국"),
    "perrotin": ("페로탕 (Perrotin)", "파리", "프랑스"),
    "davidzwirner": ("데이비드즈워너 (David Zwirner)", "뉴욕", "미국"),
    "whitecube": ("화이트큐브 (White Cube)", "런던", "영국"),
    "mariangoodman": ("마리안굿맨 (Marian Goodman Gallery)", "뉴욕", "미국"),
    "spruethmagers": ("스프루스마거스 (Sprüth Magers)", "베를린", "독일"),
    "victoriamiro": ("빅토리아미로 (Victoria Miro)", "런던", "영국"),
    "koeniggalerie": ("쾨니히갤러리 (König Galerie)", "베를린", "독일"),
    "gladstone": ("글래드스톤갤러리 (Gladstone Gallery)", "뉴욕", "미국"),
    "shugoarts": ("슈고아츠 (ShugoArts)", "도쿄", "일본"),
    "tomiokoyama": ("토미오코야마갤러리 (Tomio Koyama Gallery)", "도쿄", "일본"),
    "estherschipper": ("에스더쉬퍼 (Esther Schipper)", "베를린", "독일"),
    "maxhetzler": ("막스헤츨러갤러리 (Galerie Max Hetzler)", "베를린", "독일"),
    "otafinearts": ("오타파인아츠 (Ota Fine Arts)", "도쿄", "일본"),
    "leeahn": ("리안갤러리 (Leeahn Gallery)", "대구", "대한민국"),
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
