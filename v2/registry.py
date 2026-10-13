"""시리즈·회차 메타 + 회차별 원본 URL·파서 지정.

EDITIONS[edition_id] = {
  "series", "year", "label", "title", "start_date", "end_date", "city"(시리즈와 다를 때),
  "announced"(공표 인원/갤러리 수), "coverage"(complete|partial|none), "coverage_note",
  "sources": [{"url", "fetch"(html|json|pdf|wikitext|text), "tier"(official|official_pdf|archive|wikipedia|press),
               "license", "headers"?, "delay"?(호스트 최소 간격 초), "parser"?("모듈:함수", 페이지 단위),
               "discover"?(목록 -> 상세 URL 함수), "detail_parser"?, "detail_fetch"?}],
  파싱은 셋 중 하나: 소스별 "parser" / 그 결과를 합치는 회차 "combine" / 회차 원본 전체를 받는
  "edition_parser"(+ "edition_parser_kwargs").
}
회차 정의는 editions_*.py 파일들에 그룹별로 나눠 두고 여기서 합친다.
"""
from __future__ import annotations

import importlib
from pathlib import Path

SERIES = {
    # 비엔날레 — 한국
    "gwangju_biennale": {"kind": "biennale", "name": "Gwangju Biennale", "name_ko": "광주비엔날레", "city": "Gwangju", "country": "대한민국"},
    "busan_biennale": {"kind": "biennale", "name": "Busan Biennale", "name_ko": "부산비엔날레", "city": "Busan", "country": "대한민국"},
    "seoul_mediacity_biennale": {"kind": "biennale", "name": "Seoul Mediacity Biennale", "name_ko": "서울미디어시티비엔날레", "city": "Seoul", "country": "대한민국"},
    # 비엔날레 — 해외
    "venice_biennale": {"kind": "biennale", "name": "Venice Biennale (Biennale Arte)", "name_ko": "베니스 비엔날레", "city": "Venice", "country": "이탈리아"},
    "documenta": {"kind": "biennale", "name": "documenta", "name_ko": "카셀 도큐멘타", "city": "Kassel", "country": "독일"},
    "whitney_biennial": {"kind": "biennale", "name": "Whitney Biennial", "name_ko": "휘트니 비엔날레", "city": "New York", "country": "미국"},
    "saopaulo_bienal": {"kind": "biennale", "name": "Bienal de São Paulo", "name_ko": "상파울루 비엔날레", "city": "São Paulo", "country": "브라질"},
    "sydney_biennale": {"kind": "biennale", "name": "Biennale of Sydney", "name_ko": "시드니 비엔날레", "city": "Sydney", "country": "오스트레일리아"},
    "istanbul_biennial": {"kind": "biennale", "name": "Istanbul Biennial", "name_ko": "이스탄불 비엔날레", "city": "Istanbul", "country": "튀르키예"},
    "berlin_biennale": {"kind": "biennale", "name": "Berlin Biennale", "name_ko": "베를린 비엔날레", "city": "Berlin", "country": "독일"},
    "lyon_biennale": {"kind": "biennale", "name": "Biennale de Lyon", "name_ko": "리옹 비엔날레", "city": "Lyon", "country": "프랑스"},
    "shanghai_biennale": {"kind": "biennale", "name": "Shanghai Biennale", "name_ko": "상하이 비엔날레", "city": "Shanghai", "country": "중국"},
    "sharjah_biennial": {"kind": "biennale", "name": "Sharjah Biennial", "name_ko": "샤르자 비엔날레", "city": "Sharjah", "country": "아랍에미리트"},
    "manifesta": {"kind": "biennale", "name": "Manifesta", "name_ko": "마니페스타", "city": None, "country": None},  # 회차마다 도시 이동
    # 아트페어
    "kiaf": {"kind": "fair", "name": "Kiaf SEOUL", "name_ko": "키아프 서울", "city": "Seoul", "country": "대한민국"},
    "frieze_london": {"kind": "fair", "name": "Frieze London", "name_ko": "프리즈 런던", "city": "London", "country": "영국"},
    "frieze_masters": {"kind": "fair", "name": "Frieze Masters", "name_ko": "프리즈 마스터스", "city": "London", "country": "영국"},
    "frieze_ny": {"kind": "fair", "name": "Frieze New York", "name_ko": "프리즈 뉴욕", "city": "New York", "country": "미국"},
    "frieze_la": {"kind": "fair", "name": "Frieze Los Angeles", "name_ko": "프리즈 LA", "city": "Los Angeles", "country": "미국"},
    "frieze_seoul": {"kind": "fair", "name": "Frieze Seoul", "name_ko": "프리즈 서울", "city": "Seoul", "country": "대한민국"},
}

EDITIONS: dict[str, dict] = {}
for _path in sorted(Path(__file__).resolve().parent.glob("editions_*.py")):
    _dup = EDITIONS.keys() & (_eds := importlib.import_module(_path.stem).EDITIONS).keys()
    assert not _dup, (_path.name, _dup)
    EDITIONS.update(_eds)

for _eid, _e in EDITIONS.items():
    assert _e["series"] in SERIES, (_eid, _e["series"])


def resolve(ref: str):
    """'모듈:함수' -> parsers/<모듈>.py의 함수."""
    mod, fn = ref.split(":")
    return getattr(importlib.import_module(f"parsers.{mod}"), fn)
