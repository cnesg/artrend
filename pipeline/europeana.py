"""raw/europeana(300,226건, 2026-09-03 크롤링 완료분)를 DB로 정규화하는 로더.

Europeana는 미술관뿐 아니라 도서관/기록보관소도 아우르는 범유럽 통합 아카이브라
"소장 기관"이 `dataProvider` 필드(실제 소장처)로 따로 들어있고, `provider`는
그 기관을 Europeana에 연동해주는 애그리게이터(예: kulturpool.at)라 소장처가
아니다 — museum_holdings에는 반드시 dataProvider를 써야 한다.

다른 소스와 달리 credit-line/provenance 자유텍스트가 거의 없어(개별 레코드가
아니라 기관 카탈로그 메타데이터 위주) provenance_extract.py가 걸어낼 것도
거의 없을 것으로 예상 — description은 있으면 채우되 기대치는 낮춤.
"""
from __future__ import annotations

import re

from raw_iter import iter_records

SITE_NAME = "europeana"

# dcCreator/creatorLabel류가 사람 이름 대신 내부 authority ID나 URL을
# 그대로 반환하는 경우가 있음 (예: "1132_person", GND/wikidata URL) —
# 이런 값은 이름이 아니라 "이름 없음"으로 취급해야 함.
_NOT_A_NAME_RE = re.compile(r"^\d+_person$|^https?://|^http://.*\.well-known/genid/")


def _is_real_name(value: str | None) -> bool:
    return bool(value) and not _NOT_A_NAME_RE.match(value.strip())


def _first(value) -> str | None:
    if isinstance(value, list):
        return value[0].strip() if value and str(value[0]).strip() else None
    if isinstance(value, str):
        return value.strip() or None
    return None


def _creator_name(value) -> str | None:
    """dcCreator는 리스트에 사람 이름과 authority URL/ID가 섞여 들어옴
    (예: ['Goyen, Jan van', 'http://data.europeana.eu/agent/146860']) —
    실제 이름인 첫 항목을 골라야 함. 전부 URL/ID뿐이면 이름 없음."""
    items = value if isinstance(value, list) else ([value] if value else [])
    for item in items:
        item = str(item).strip() if item else ""
        if _is_real_name(item):
            return item
    return None


def _lang_aware(value: dict | None) -> list[str] | None:
    """{'def': [...], 'de': [...], ...} 형태 필드에서 언어 우선순위대로 리스트 하나 고름."""
    if not isinstance(value, dict):
        return None
    for lang in ("def", "en"):
        if value.get(lang):
            return value[lang]
    for v in value.values():
        if v:
            return v
    return None


def _medium(value: dict | None) -> str | None:
    """dcTypeLangAware는 concept URI와 사람이 읽는 라벨이 섞여있어 URL이 아닌 첫 값만 취함."""
    items = _lang_aware(value) or []
    for item in items:
        if item and not str(item).startswith("http"):
            return str(item).strip()
    return None


def load(store) -> int:
    loaded = 0
    for _record_id, data, meta in iter_records(SITE_NAME):
        if store.source_already_loaded(meta["raw_path"]):
            continue
        museum_name = _first(data.get("dataProvider"))
        if not museum_name:
            # 소장 기관을 특정 못 하면 museum_holdings에 넣을 수 없어 스킵 —
            # artworks 단독으로 남기는 것도 스코프 밖(다른 로더는 전부
            # museum_holdings 연결을 전제로 함).
            continue
        source_id = store.insert_source(meta)
        museum_id = store.get_or_create_museum(museum_name)

        artist_name = _creator_name(data.get("dcCreator"))
        artist_id = (
            store.get_or_create_artist_safe(artist_name, source_id=source_id)
            if artist_name
            else None
        )

        title = _first(data.get("title")) or "(제목 없음)"
        medium = _medium(data.get("dcTypeLangAware"))
        description = _first(_lang_aware(data.get("dcDescriptionLangAware")))

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=title,
            year_created=_first(data.get("year")),
            medium=medium,
            dimensions=None,
            description=description,
            source_id=source_id,
        )
        store.insert_museum_holding(
            museum_id=museum_id,
            artwork_id=artwork_id,
            accession_number=None,
            source_id=source_id,
        )
        loaded += 1
        if loaded % 10000 == 0:
            print(f"[pipeline:europeana] {loaded}건 진행 중...")
    store.commit()
    print(f"[pipeline:europeana] {loaded}건 적재")
    return loaded
