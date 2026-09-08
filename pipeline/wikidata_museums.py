"""Wikidata 보완 소스(raw/wikidata_<museum>/*.json) -> DB 적재.

공식 API가 없는 미술관(프라도, 빈미술사박물관 등)을 위한 보완 데이터.
"""
from __future__ import annotations

import re

from raw_iter import iter_records

# SPARQL label 서비스가 라벨 없는(익명 blank node 등) 엔티티에 대해
# 사람이 읽을 이름 대신 엔티티 URI를 그대로 돌려주는 경우가 있음 —
# creatorLabel이 URL이면 "작가 미상"으로 취급해야 함.
_NOT_A_NAME_RE = re.compile(r"^https?://")


def _is_real_name(value: str | None) -> bool:
    return bool(value) and not _NOT_A_NAME_RE.match(value.strip())

# site suffix -> 미술관 표시명
WIKIDATA_MUSEUMS: dict[str, str] = {
    "prado": "Museo del Prado",
    "khm_wien": "Kunsthistorisches Museum Wien",
    "orsay": "Musée d'Orsay",
    "uffizi": "Galleria degli Uffizi",
    "national_gallery_london": "National Gallery, London",
    "alte_pinakothek": "Alte Pinakothek",
    "belvedere": "Belvedere",
    "national_museum_korea": "국립중앙박물관",
    "reina_sofia": "Museo Reina Sofía",
    "van_gogh_museum": "Van Gogh Museum",
    "pompidou": "Centre Pompidou",
    "stadel": "Städel Museum",
    "hermitage": "Hermitage Museum",
    "vatican_museums": "Vatican Museums",
    "gemaldegalerie_berlin": "Gemäldegalerie Berlin",
    "albertina": "Albertina",
    "wallace_collection": "Wallace Collection",
    "musee_rodin": "Musée Rodin",
    "boijmans": "Museum Boijmans Van Beuningen",
    "momat_tokyo": "東京国立近代美術館 (MOMAT)",
    "leeum": "리움미술관 (Leeum, Samsung Museum of Art)",
    "sema": "서울시립미술관 (Seoul Museum of Art)",
    "ilmin": "일민미술관 (Ilmin Museum of Art)",
    "kyoto_national_museum": "京都国立博物館 (Kyoto National Museum)",
    "nara_national_museum": "奈良国立博物館 (Nara National Museum)",
    "pinault_collection": "Pinault Collection",
    "rubell_museum": "Rubell Museum",
    "louis_vuitton_foundation": "Fondation Louis Vuitton",
    "yvon_lambert_collection": "Yvon Lambert 컬렉션",
    "guggenheim_nyc": "Solomon R. Guggenheim Museum",
    "whitney": "Whitney Museum of American Art",
    "brooklyn_museum": "Brooklyn Museum",
    "israel_museum": "Israel Museum",
    "ashmolean": "Ashmolean Museum",
    "fitzwilliam": "Fitzwilliam Museum",
    "gardner_museum": "Isabella Stewart Gardner Museum",
    "national_palace_museum": "國立故宮博物院 (National Palace Museum)",
    "lacma": "Los Angeles County Museum of Art",
    "mfa_boston": "Museum of Fine Arts, Boston",
    "detroit_institute": "Detroit Institute of Arts",
    "philadelphia_museum": "Philadelphia Museum of Art",
    "frick_collection": "The Frick Collection",
    "yale_art_gallery": "Yale University Art Gallery",
    "princeton_art_museum": "Princeton Art Museum",
    "dallas_museum": "Dallas Museum of Art",
    "denver_art_museum": "Denver Art Museum",
    "seattle_art_museum": "Seattle Art Museum",
    "nmwa_tokyo": "国立西洋美術館 (National Museum of Western Art)",
    "nezu_museum": "根津美術館 (Nezu Museum)",
    "suntory_museum": "サントリー美術館 (Suntory Museum of Art)",
    "yokohama_museum": "横浜美術館 (Yokohama Museum of Art)",
    "stedelijk": "Stedelijk Museum Amsterdam",
    "kunstmuseum_basel": "Kunstmuseum Basel",
    "tretyakov": "Tretyakov Gallery",
    "cincinnati_art_museum": "Cincinnati Art Museum",
    "indianapolis_museum": "Indianapolis Museum of Art",
    "portland_art_museum": "Portland Art Museum",
    "norton_simon_museum": "Norton Simon Museum",
    "mfa_houston": "Museum of Fine Arts, Houston",
    "baltimore_museum": "Baltimore Museum of Art",
    "saint_louis_art_museum": "Saint Louis Art Museum",
    "wadsworth_atheneum": "Wadsworth Atheneum Museum of Art",
    "toledo_museum": "Toledo Museum of Art",
    "kimbell_art_museum": "Kimbell Art Museum",
    "nasjonalmuseet": "Nasjonalmuseet (Norway)",
    "ateneum": "Ateneum (Finland)",
    "national_gallery_prague": "National Gallery Prague",
    "national_museum_warsaw": "National Museum in Warsaw",
    "museu_arte_antiga": "National Museum of Ancient Art (Portugal)",
    "royal_museums_belgium": "Royal Museums of Fine Arts of Belgium",
    "kunsthaus_zurich": "Kunsthaus Zürich",
    "moderna_museet": "Moderna Museet (Sweden)",
    "ago_toronto": "Art Gallery of Ontario",
    "national_gallery_canada": "National Gallery of Canada",
    "national_gallery_australia": "National Gallery of Australia",
    "agnsw": "Art Gallery of New South Wales",
    "masp": "São Paulo Museum of Art",
    "shanghai_museum": "Shanghai Museum",
    "national_museum_singapore": "National Museum of Singapore",
    "singapore_art_museum": "Singapore Art Museum",
    "hoam_art_museum": "호암미술관 (Ho-Am Art Museum)",
    "art_sonje_center": "아트선재센터 (Art Sonje Center)",
    "busan_museum_of_art": "부산시립미술관 (Busan Museum of Art)",
    "daejeon_museum_of_art": "대전시립미술관 (Daejeon Museum of Art)",
    "gwangju_museum_of_art": "광주시립미술관 (Gwangju Museum of Art)",
    "artizon_museum": "アーティゾン美術館 (Artizon Museum)",
    "mori_art_museum": "森美術館 (Mori Art Museum)",
    "pola_museum": "ポーラ美術館 (Pola Museum of Art)",
    "yamatane_museum": "山種美術館 (Yamatane Museum of Art)",
    "idemitsu_museum": "出光美術館 (Idemitsu Museum of Arts)",
    "ohara_museum": "大原美術館 (Ohara Museum of Art)",
    "nelson_atkins": "The Nelson-Atkins Museum of Art",
    "crystal_bridges": "Crystal Bridges Museum of American Art",
    "south_african_national_gallery": "South African National Gallery",
    "mca_chicago": "Museum of Contemporary Art, Chicago",
    "milwaukee_art_museum": "Milwaukee Art Museum",
    "high_museum": "High Museum of Art",
    "auckland_art_gallery": "Auckland Art Gallery",
    "te_papa": "Museum of New Zealand Te Papa Tongarewa",
    "ngv_melbourne": "National Gallery of Victoria",
    "queensland_art_gallery": "Queensland Art Gallery",
    "freer_gallery": "Freer Gallery of Art",
    "currier_museum": "Currier Museum of Art",
    "wexner_center": "Wexner Center for the Arts",
    "menil_collection": "Menil Collection",
    "museum_ludwig": "Museum Ludwig",
    "van_abbemuseum": "Van Abbemuseum",
    "hamburger_kunsthalle": "Hamburger Kunsthalle",
    "mumok": "mumok (Museum Moderner Kunst Wien)",
    "smak": "S.M.A.K.",
    "louisiana_museum": "Louisiana Museum of Modern Art",
    "astrup_fearnley": "Astrup Fearnley Museum of Modern Art",
    "malba": "Museum of Latin American Art of Buenos Aires (MALBA)",
    "zeitz_mocaa": "Zeitz Museum of Contemporary Art Africa",
    "serralves": "Serralves Museum of Contemporary Art",
    "ludwig_budapest": "Ludwig Museum Budapest",
    "ivam": "Institut Valencià d'Art Modern (IVAM)",
    "palais_de_tokyo": "Palais de Tokyo",
    "fondazione_prada": "Fondazione Prada",
    "capc_bordeaux": "CAPC musée d'art contemporain de Bordeaux",
    "kiasma": "Kiasma",
    "mot_tokyo": "東京都現代美術館 (Museum of Contemporary Art Tokyo)",
    "hara_museum": "原美術館 (Hara Museum of Contemporary Art)",
    "fondation_beyeler": "Fondation Beyeler",
    "kunstmuseum_bern": "Kunstmuseum Bern",
    "mdbk_leipzig": "Museum der bildenden Künste Leipzig",
    "neue_nationalgalerie": "Neue Nationalgalerie",
    "kunsthalle_bielefeld": "Kunsthalle Bielefeld",
    "sprengel_museum": "Sprengel Museum",
    "kroller_muller": "Kröller-Müller Museum",
    "groninger_museum": "Groninger Museum",
    "museum_arnhem": "Museum Arnhem",
    "gulbenkian_modern": "Centro de Arte Moderna Gulbenkian",
    "turner_contemporary": "Turner Contemporary",
    "baltic_centre": "Baltic Centre for Contemporary Art",
    "bildmuseet": "Bildmuseet",
    "malmo_konsthall": "Malmö Konsthall",
    "kunsthal_rotterdam": "Kunsthal Rotterdam",
    "vasarely_museum": "Victor Vasarely Museum",
}


def _load_one(store, site_suffix: str, museum_name: str) -> int:
    site_name = f"wikidata_{site_suffix}"
    museum_id = store.get_or_create_museum(museum_name, museum_name)
    loaded = 0

    for record_id, data, meta in iter_records(site_name):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        source_id = store.insert_source(meta)

        artist_name = data.get("creatorLabel")
        if not _is_real_name(artist_name):
            artist_name = None
        title = data.get("itemLabel") or "(제목 없음)"
        year = None
        inception = data.get("inception")
        if inception:
            year = inception[:4]

        artist_id = store.get_or_create_artist(artist_name, source_id=source_id)

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=title,
            year_created=year,
            medium=data.get("materialLabel"),
            dimensions=None,
            description=None,
            source_id=source_id,
        )

        store.insert_museum_holding(
            museum_id=museum_id,
            artwork_id=artwork_id,
            accession_number=data.get("invNumber"),
            source_id=source_id,
        )
        loaded += 1

    print(f"[pipeline:wikidata_{site_suffix}] {loaded}건 적재")
    return loaded


def load(store) -> int:
    total = 0
    for suffix, name in WIKIDATA_MUSEUMS.items():
        total += _load_one(store, suffix, name)
    store.commit()
    return total
