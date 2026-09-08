"""Wikidata SPARQL을 통한 미술관 소장품 보완 수집.

공식 API/벌크덤프가 없는 미술관(프라도, 빈미술사박물관 등)을 위한 폴백.
"Sum of all Paintings" 등 위키프로젝트가 구조화해둔 collection(P195) 속성으로
특정 미술관 QID에 속한 작품만 필터링한다 — 위키데이터 전체를 긁지 않는다.

사용법:
    python wikidata_museums.py --museum prado
    python wikidata_museums.py --museum all
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time

import requests

from common import already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"}
LICENSE_NOTE = "Wikidata SPARQL (P195 collection 필터) — CC0, 공식 API 없는 미술관 보완용, 2026-09-02"

# site key -> (미술관명, Wikidata QID)
MUSEUMS: dict[str, tuple[str, str]] = {
    "prado": ("Museo del Prado", "Q160112"),
    "khm_wien": ("Kunsthistorisches Museum Wien", "Q95569"),
    "orsay": ("Musée d'Orsay", "Q23402"),
    "uffizi": ("Galleria degli Uffizi", "Q51252"),
    "national_gallery_london": ("National Gallery, London", "Q1471477"),
    "alte_pinakothek": ("Alte Pinakothek", "Q157918"),
    "belvedere": ("Belvedere", "Q812285"),
    "national_museum_korea": ("국립중앙박물관", "Q838439"),
    "reina_sofia": ("Museo Reina Sofía", "Q179467"),
    "van_gogh_museum": ("Van Gogh Museum", "Q1499958"),
    "pompidou": ("Centre Pompidou", "Q1075988"),
    "stadel": ("Städel Museum", "Q157825"),
    "hermitage": ("Hermitage Museum", "Q132783"),
    "vatican_museums": ("Vatican Museums", "Q182955"),
    "gemaldegalerie_berlin": ("Gemäldegalerie Berlin", "Q165631"),
    "albertina": ("Albertina", "Q12784143"),
    "wallace_collection": ("Wallace Collection", "Q1327919"),
    "musee_rodin": ("Musée Rodin", "Q650519"),
    "boijmans": ("Museum Boijmans Van Beuningen", "Q679527"),
    "momat_tokyo": ("東京国立近代美術館 (MOMAT)", "Q1359908"),
    "leeum": ("리움미술관 (Leeum, Samsung Museum of Art)", "Q487498"),
    "sema": ("서울시립미술관 (Seoul Museum of Art)", "Q7451676"),
    "ilmin": ("일민미술관 (Ilmin Museum of Art)", "Q6000822"),
    "kyoto_national_museum": ("京都国立博物館 (Kyoto National Museum)", "Q147286"),
    "nara_national_museum": ("奈良国立博物館 (Nara National Museum)", "Q147312"),
    # 컬렉터 티어 — 미술관은 아니지만 P195(collection) 필터가 그대로 적용됨
    "pinault_collection": ("Pinault Collection", "Q2278052"),
    "rubell_museum": ("Rubell Museum", "Q86757788"),
    "louis_vuitton_foundation": ("Fondation Louis Vuitton", "Q3075489"),
    "yvon_lambert_collection": ("Yvon Lambert 컬렉션", "Q3574124"),
    "guggenheim_nyc": ("Solomon R. Guggenheim Museum", "Q201469"),
    "whitney": ("Whitney Museum of American Art", "Q639791"),
    "brooklyn_museum": ("Brooklyn Museum", "Q632682"),
    "israel_museum": ("Israel Museum", "Q46815"),
    "ashmolean": ("Ashmolean Museum", "Q636400"),
    "fitzwilliam": ("Fitzwilliam Museum", "Q1421440"),
    "gardner_museum": ("Isabella Stewart Gardner Museum", "Q49135"),
    "national_palace_museum": ("國立故宮博物院 (National Palace Museum)", "Q540668"),
    "lacma": ("Los Angeles County Museum of Art", "Q1641836"),
    "mfa_boston": ("Museum of Fine Arts, Boston", "Q49133"),
    "detroit_institute": ("Detroit Institute of Arts", "Q1201549"),
    "philadelphia_museum": ("Philadelphia Museum of Art", "Q510324"),
    "frick_collection": ("The Frick Collection", "Q682827"),
    "yale_art_gallery": ("Yale University Art Gallery", "Q1568434"),
    "princeton_art_museum": ("Princeton Art Museum", "Q2603905"),
    "dallas_museum": ("Dallas Museum of Art", "Q745866"),
    "denver_art_museum": ("Denver Art Museum", "Q1189960"),
    "seattle_art_museum": ("Seattle Art Museum", "Q1816301"),
    "nmwa_tokyo": ("国立西洋美術館 (National Museum of Western Art)", "Q1362629"),
    "nezu_museum": ("根津美術館 (Nezu Museum)", "Q1047097"),
    "suntory_museum": ("サントリー美術館 (Suntory Museum of Art)", "Q11249110"),
    "yokohama_museum": ("横浜美術館 (Yokohama Museum of Art)", "Q861588"),
    "stedelijk": ("Stedelijk Museum Amsterdam", "Q924335"),
    "kunstmuseum_basel": ("Kunstmuseum Basel", "Q194626"),
    "tretyakov": ("Tretyakov Gallery", "Q183334"),
    "cincinnati_art_museum": ("Cincinnati Art Museum", "Q2970522"),
    "indianapolis_museum": ("Indianapolis Museum of Art", "Q1117704"),
    "portland_art_museum": ("Portland Art Museum", "Q279049"),
    "norton_simon_museum": ("Norton Simon Museum", "Q1752085"),
    "mfa_houston": ("Museum of Fine Arts, Houston", "Q1565911"),
    "baltimore_museum": ("Baltimore Museum of Art", "Q377579"),
    "saint_louis_art_museum": ("Saint Louis Art Museum", "Q1760539"),
    "wadsworth_atheneum": ("Wadsworth Atheneum Museum of Art", "Q403080"),
    "toledo_museum": ("Toledo Museum of Art", "Q1743116"),
    "kimbell_art_museum": ("Kimbell Art Museum", "Q1741629"),
    "nasjonalmuseet": ("Nasjonalmuseet (Norway)", "Q1132918"),
    "ateneum": ("Ateneum (Finland)", "Q754507"),
    "national_gallery_prague": ("National Gallery Prague", "Q1419555"),
    "national_museum_warsaw": ("National Museum in Warsaw", "Q153306"),
    "museu_arte_antiga": ("National Museum of Ancient Art (Portugal)", "Q212459"),
    "royal_museums_belgium": ("Royal Museums of Fine Arts of Belgium", "Q377500"),
    "kunsthaus_zurich": ("Kunsthaus Zürich", "Q685038"),
    "moderna_museet": ("Moderna Museet (Sweden)", "Q1274511"),
    "ago_toronto": ("Art Gallery of Ontario", "Q670250"),
    "national_gallery_canada": ("National Gallery of Canada", "Q1068063"),
    "national_gallery_australia": ("National Gallery of Australia", "Q795228"),
    "agnsw": ("Art Gallery of New South Wales", "Q705551"),
    "masp": ("São Paulo Museum of Art", "Q82941"),
    "shanghai_museum": ("Shanghai Museum", "Q1051293"),
    "national_museum_singapore": ("National Museum of Singapore", "Q632689"),
    "singapore_art_museum": ("Singapore Art Museum", "Q2032637"),
    "hoam_art_museum": ("호암미술관 (Ho-Am Art Museum)", "Q491279"),
    "art_sonje_center": ("아트선재센터 (Art Sonje Center)", "Q4801558"),
    "busan_museum_of_art": ("부산시립미술관 (Busan Museum of Art)", "Q16096732"),
    "daejeon_museum_of_art": ("대전시립미술관 (Daejeon Museum of Art)", "Q5208225"),
    "gwangju_museum_of_art": ("광주시립미술관 (Gwangju Museum of Art)", "Q12585149"),
    "artizon_museum": ("アーティゾン美術館 (Artizon Museum)", "Q913808"),
    "mori_art_museum": ("森美術館 (Mori Art Museum)", "Q4410434"),
    "pola_museum": ("ポーラ美術館 (Pola Museum of Art)", "Q1574475"),
    "yamatane_museum": ("山種美術館 (Yamatane Museum of Art)", "Q3329572"),
    "idemitsu_museum": ("出光美術館 (Idemitsu Museum of Arts)", "Q3076590"),
    "ohara_museum": ("大原美術館 (Ohara Museum of Art)", "Q2977589"),
    "nelson_atkins": ("The Nelson-Atkins Museum of Art", "Q1976985"),
    "crystal_bridges": ("Crystal Bridges Museum of American Art", "Q1142334"),
    "south_african_national_gallery": ("South African National Gallery", "Q1419469"),
    "mca_chicago": ("Museum of Contemporary Art, Chicago", "Q118142"),
    "milwaukee_art_museum": ("Milwaukee Art Museum", "Q325712"),
    "high_museum": ("High Museum of Art", "Q953345"),
    "auckland_art_gallery": ("Auckland Art Gallery", "Q4819492"),
    "te_papa": ("Museum of New Zealand Te Papa Tongarewa", "Q915603"),
    "ngv_melbourne": ("National Gallery of Victoria", "Q1464509"),
    "queensland_art_gallery": ("Queensland Art Gallery", "Q7270900"),
    "freer_gallery": ("Freer Gallery of Art", "Q1075126"),
    "currier_museum": ("Currier Museum of Art", "Q3007727"),
    "wexner_center": ("Wexner Center for the Arts", "Q2527311"),
    "menil_collection": ("Menil Collection", "Q1888308"),
    "museum_ludwig": ("Museum Ludwig", "Q703640"),
    "van_abbemuseum": ("Van Abbemuseum", "Q1782422"),
    "hamburger_kunsthalle": ("Hamburger Kunsthalle", "Q169542"),
    "mumok": ("mumok (Museum Moderner Kunst Wien)", "Q689951"),
    "smak": ("S.M.A.K.", "Q1540707"),
    "louisiana_museum": ("Louisiana Museum of Modern Art", "Q1410617"),
    "astrup_fearnley": ("Astrup Fearnley Museum of Modern Art", "Q761048"),
    "malba": ("Museum of Latin American Art of Buenos Aires (MALBA)", "Q1808336"),
    "zeitz_mocaa": ("Zeitz Museum of Contemporary Art Africa", "Q28003638"),
    "serralves": ("Serralves Museum of Contemporary Art", "Q1954380"),
    "ludwig_budapest": ("Ludwig Museum Budapest", "Q958750"),
    "ivam": ("Institut Valencià d'Art Modern (IVAM)", "Q1600831"),
    "palais_de_tokyo": ("Palais de Tokyo", "Q1535247"),
    "fondazione_prada": ("Fondazione Prada", "Q3747208"),
    "capc_bordeaux": ("CAPC musée d'art contemporain de Bordeaux", "Q2945071"),
    "kiasma": ("Kiasma", "Q1633361"),
    "mot_tokyo": ("東京都現代美術館 (Museum of Contemporary Art Tokyo)", "Q1649688"),
    "hara_museum": ("原美術館 (Hara Museum of Contemporary Art)", "Q3736155"),
    "fondation_beyeler": ("Fondation Beyeler", "Q673833"),
    "kunstmuseum_bern": ("Kunstmuseum Bern", "Q194622"),
    "mdbk_leipzig": ("Museum der bildenden Künste Leipzig", "Q566661"),
    "neue_nationalgalerie": ("Neue Nationalgalerie", "Q32659772"),
    "kunsthalle_bielefeld": ("Kunsthalle Bielefeld", "Q321716"),
    "sprengel_museum": ("Sprengel Museum", "Q510144"),
    "kroller_muller": ("Kröller-Müller Museum", "Q1051928"),
    "groninger_museum": ("Groninger Museum", "Q1542668"),
    "museum_arnhem": ("Museum Arnhem", "Q2114028"),
    "gulbenkian_modern": ("Centro de Arte Moderna Gulbenkian", "Q1054339"),
    "turner_contemporary": ("Turner Contemporary", "Q1391289"),
    "baltic_centre": ("Baltic Centre for Contemporary Art", "Q4852693"),
    "bildmuseet": ("Bildmuseet", "Q4907651"),
    "malmo_konsthall": ("Malmö Konsthall", "Q633078"),
    "kunsthal_rotterdam": ("Kunsthal Rotterdam", "Q1668856"),
    "vasarely_museum": ("Victor Vasarely Museum", "Q1426026"),
}

# instance-of 필터: 회화, 조각, 드로잉, 판화
ART_TYPES = ["Q3305213", "Q860861", "Q93184", "Q11060274"]

QUERY_TEMPLATE = """
SELECT ?item ?itemLabel ?creatorLabel ?inception ?materialLabel ?invNumber WHERE {{
  ?item wdt:P195 wd:{qid} .
  VALUES ?type {{ {types} }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P170 ?creator. }}
  OPTIONAL {{ ?item wdt:P571 ?inception. }}
  OPTIONAL {{ ?item wdt:P186 ?material. }}
  OPTIONAL {{ ?item wdt:P217 ?invNumber. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,ko". }}
}}
"""


def _run_query(qid: str) -> list[dict]:
    types = " ".join(f"wd:{t}" for t in ART_TYPES)
    query = QUERY_TEMPLATE.format(qid=qid, types=types)

    def _do():
        resp = requests.get(SPARQL_URL, params={"query": query, "format": "json"}, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return resp.json()

    data = with_retry(_do, attempts=3, base_delay=5.0)
    return data["results"]["bindings"]


def crawl(museum_key: str, skip_existing: bool) -> None:
    display_name, qid = MUSEUMS[museum_key]
    site_name = f"wikidata_{museum_key}"

    bindings = _run_query(qid)
    print(f"[wikidata:{museum_key}] {display_name} 소장품 {len(bindings)}건 조회됨")

    saved = 0
    for row in bindings:
        item_uri = row["item"]["value"]
        qnum = item_uri.rsplit("/", 1)[-1]
        record_id = qnum

        if skip_existing and already_fetched(site_name, record_id):
            continue

        record = {k: v.get("value") for k, v in row.items()}
        record["museum"] = display_name
        record["wikidata_qid"] = qnum

        save_raw(site_name, record_id, json.dumps(record, ensure_ascii=False), url=item_uri, license_note=LICENSE_NOTE)
        saved += 1
        if saved % 500 == 0:
            print(f"[wikidata:{museum_key}] {saved}건 저장 진행 중...")
        time.sleep(0.05)

    print(f"[wikidata:{museum_key}] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wikidata 기반 미술관 소장품 보완 크롤러")
    parser.add_argument("--museum", type=str, default="all", help="MUSEUMS 키 (all 또는 쉼표 구분)")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 레코드도 다시 수집",
    )
    args = parser.parse_args()
    keys = list(MUSEUMS.keys()) if args.museum == "all" else args.museum.split(",")
    for key in keys:
        if key not in MUSEUMS:
            print(f"[wikidata] 알 수 없는 미술관 키: {key} (사용 가능: {list(MUSEUMS.keys())})")
            continue
        crawl(key, args.skip_existing)
