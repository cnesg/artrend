"""Minneapolis Institute of Art(Mia) 원본(CC0, GitHub 저장소 objects/<bucket>/<id>.json)
-> museums/artists/artworks/museum_holdings 적재.

git clone 스냅샷 전체(raw/mia_repo/objects/**/*.json)를 하나의 벌크 소스로 취급한다
(met/nga/tate/moma/walters와 동일한 패턴 — 파일마다 source row를 만들지 않고
스냅샷 하나에 source_id 하나).
"""
from __future__ import annotations

import json
import re

from raw_iter import RAW_ROOT

MUSEUM_NAME = "Minneapolis Institute of Art"
MIA_DIR = RAW_ROOT / "mia_repo"

_ROLE_PREFIX_RE = re.compile(r"^([A-Za-z][A-Za-z .]{1,30}):\s*(.*)$")

# 실제로 "만든 사람"(시각예술 창작 행위)에 해당하는 역할만 화이트리스트로 인정.
# publisher/printer/author/translator/distributor/manufacturer 등 서지·유통·행정
# 역할은 제외 — 이런 역할이 첫 세그먼트에 오면(예: "Printer: Wolfgang Kilian;
# Engraver: Michiel Jansz. van Mierevelt") 실제 작가는 뒤 세그먼트인데 앞
# 세그먼트를 작가로 잘못 뽑는 오탐을 냈었다(2026-09-04 fix_mia_after_artist_names.py
# 리포트에서 398건 발견, docs/정합성작업.md §6 후속 참고).
_MAKER_ROLES = {
    "designer", "engraver", "painter", "photographer", "lithographer", "carver",
    "etcher", "delineator", "sculptor", "draftsman", "cartoonist", "calligrapher",
    "illustrator", "colorist", "architect", "weaver", "decorator", "potter",
    "silversmith", "woodcutter", "gilder", "goldsmith", "jeweler", "embroiderer",
    "ceramist", "enameller", "modeler", "caster", "fabricator", "composer", "poet",
    "performer", "miniaturist", "creator", "maker", "printmaker",
}


def _role_value(segment: str) -> str:
    """"Etcher: Gabriel Huquier" -> "Gabriel Huquier"; 역할 라벨 없으면 그대로."""
    m = _ROLE_PREFIX_RE.match(segment)
    return m.group(2).strip() if m else segment


def _has_confident_role(segment: str) -> bool:
    """역할 라벨이 없는 맨 이름이거나, 화이트리스트의 창작 역할이면 신뢰."""
    m = _ROLE_PREFIX_RE.match(segment)
    if not m:
        return True
    return m.group(1).strip().lower() in _MAKER_ROLES


def parse_artist_name(raw: str | None) -> str | None:
    """Mia의 자유서술형 "artist" 필드에서 신뢰할 수 있는 주 작가명만 추출.

    Met의 "|" 필드와 달리 Mia는 구조화된 병렬 배열이 아니라 자유서술 크레딧
    라인이라(예: "Sculptor: After François du Quesnoy", "Engraver: Cornelis
    Bloemaert; Delineator: After Cyrus Ferrius; After Francisco Romanelli")
    단순 split(';')[0]은 "After X"(원작자 참조일 뿐 실제 활동 작가가 아님)를
    작가명으로 잘못 추출하는 오탐을 낸다(docs/정합성작업.md §6 후속 참고).

    "after"가 전혀 없는 문자열은 기존과 동일하게 첫 세그먼트를 신뢰(하위
    호환 — 이미 올바르게 동작하던 케이스, 예: "artist: Katsushika Hokusai;
    publisher: Nishimuraya Yohachi" -> "Katsushika Hokusai"). "after"가
    섞인 경우만 보수적으로 판단 — 명확한 "주 작가 하나 + after 귀속 하나"
    패턴만 살리고, 그 외(세그먼트 첫머리부터 after이거나 after가 여럿/애매한
    위치)는 작가 미상(None)으로 둔다 — 틀린 이름보다 모르는 게 낫다는 원칙
    (Europeana/Wikidata 오염 정리 때와 동일 원칙).
    """
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    if s.lower().startswith("artist:"):
        s = s[len("artist:"):].strip()
    if not s:
        return None

    segments = [seg.strip() for seg in s.split(";") if seg.strip()]
    if not segments:
        return None

    if len(segments) == 1:
        if _role_value(segments[0]).lower().startswith("after"):
            return None
        return segments[0]

    first = segments[0]
    if _role_value(first).lower().startswith("after"):
        return None
    if not _has_confident_role(first):
        return None  # 첫 세그먼트가 publisher/author 등 창작자가 아닌 역할 — 실제 작가는 뒤에 있을 수 있어 추측 안 함
    if len(segments) == 2 and _role_value(segments[1]).lower().startswith("after"):
        return first  # 주 작가 하나 + after 귀속 하나 — 명확한 경우만 신뢰
    if any(_role_value(seg).lower().startswith("after") for seg in segments[1:]):
        return None  # after가 섞였는데 구조가 애매(세그먼트 3개 이상 등)
    return first  # after가 전혀 없고 첫 세그먼트가 창작 역할이면 기존 동작대로 신뢰


def _read_meta() -> dict:
    return json.loads((MIA_DIR / "_snapshot.meta.json").read_text(encoding="utf-8"))


def load(store) -> int:
    meta = _read_meta()
    if store.source_already_loaded(meta["raw_path"]):
        print("[pipeline:mia] 이미 적재됨 — 건너뜀")
        return 0

    museum_id = store.get_or_create_museum(MUSEUM_NAME, "미니애폴리스, 미국")
    source_id = store.insert_source(meta)

    loaded = 0
    for path in (MIA_DIR / "objects").glob("*/*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue

        artist_name = parse_artist_name(data.get("artist"))

        artist_id = store.get_or_create_artist(
            artist_name,
            nationality=data.get("nationality") or None,
            source_id=source_id,
        )

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=data.get("title") or "(제목 없음)",
            year_created=data.get("dated") or None,
            medium=data.get("medium") or None,
            dimensions=data.get("dimension") or None,
            description=data.get("description") or data.get("creditline") or None,
            source_id=source_id,
        )

        store.insert_museum_holding(
            museum_id=museum_id,
            artwork_id=artwork_id,
            accession_number=data.get("accession_number") or None,
            source_id=source_id,
        )
        loaded += 1
        if loaded % 20000 == 0:
            print(f"[pipeline:mia] {loaded}건 진행 중...")

    store.commit()
    print(f"[pipeline:mia] {loaded}건 적재")
    return loaded
