"""artworks.description(크레딧라인/프로버넌스 원문) -> collectors/provenance_records 역추출.

새 크롤링이 아니라 이미 DB에 적재된 텍스트를 재활용한다. met/aic/cleveland/moma/tate/
smk/mia/walters/smithsonian 로더는 credit line을, nga 로더는 provenancetext(없으면
creditline)를 artworks.description에 그대로 보존만 해뒀다(구조화 안 됨) — 이 스크립트가
그 자유 텍스트에서 소유자(컬렉터/미술관/갤러리/경매사)와 취득 방식을 정규식/휴리스틱으로
추출해 provenance_records를 채운다.

완벽한 NER이 아니라 규칙 기반이다 — 매칭 안 되는 문장(다른 언어 서술형 설명 등)은
조용히 건너뛴다(오탐보다 누락이 안전). 이름을 못 뽑고 취득 방식 키워드만 확인되면
owner_type='unknown'으로 기록한다(스키마 constraint가 이 경우 owner_*_id 전부 null 허용).

NGA provenancetext는 세미콜론으로 구분된 소유 이력 체인이라(예: "A [d. 1942], London;
(Sotheby, London, sale 1942); B; gift to NGA, 1951") 세미콜론 단위로 세그먼트를 나눠
각각 처리한다 — 다른 소스의 단문 credit line은 세그먼트가 하나뿐이라 동일 로직이 그대로
적용된다. "NGA"/"National Gallery of Art"를 언급하는 세그먼트(= 이 미술관 자체로의 최종
취득)는 museum_holdings에 이미 반영돼 있어 중복이므로 건너뛴다.

사용법:
    python provenance_extract.py --dry-run --limit 2000   # 파싱 검증만
    python provenance_extract.py                           # 실제 적재 (DATABASE_URL 필요)
"""
from __future__ import annotations

import argparse
import os
import re
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

from db import get_connection
from raw_iter import year_to_date
from store import DryRunStore, PgStore

# 이 텍스트가 언급되면 "우리 DB에 이미 museum_holdings로 반영된 최종 소장처" 세그먼트로
# 보고 건너뛴다 — provenance_records에 다시 넣으면 museum_holdings와 중복.
SELF_MUSEUM_RE = re.compile(r"\bnga\b|national gallery of art", re.IGNORECASE)

# 세그먼트 자체가 정보 없는 상투구인 경우 스킵 (owner_type=unknown으로도 남길 가치가 없음)
NOISE_SEGMENT_RE = re.compile(
    r"^\s*(the artist('s)?( estate)?|artist('s)? estate|unknown|n/?a|no provenance)\s*[.,]?\s*$",
    re.IGNORECASE,
)

METHOD_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bbequest(ed)?\b|\bbequeathed\b", re.I), "유증 (Bequest)"),
    (re.compile(r"\binheritance\b|\binherited\b", re.I), "상속 (Inheritance)"),
    (re.compile(r"\bgift\b|\bgiven by\b|\bpresented by\b|\bdonated\b", re.I), "기증 (Gift)"),
    (re.compile(r"\bpurchase(d)?\b|\bbought\b|\bacquired\b|\bsold\b|\bsale\b", re.I), "구입/매매 (Purchase/Sale)"),
]

# "Gift of X", "Bequest of X", "Estate of X", "Collection of X" — X를 이름으로 추출
NAME_AFTER_KEYWORD_RE = re.compile(
    r"\b(?:gift of|bequest of|estate of|collection of|given by|presented by|donated by|"
    r"purchase(?:d)?\s+from|painted for|commissioned by|acquired by|sold to|sold by)\s+"
    r"(.+)",
    re.IGNORECASE,
)
# "X Collection" — X를 이름으로 추출 (접미사형). 길이를 짧게 제한하지 않으면 Cleveland
# 같은 "tombstone" 포맷(제목+매체+박물관명+실제 크레딧라인이 세미콜론 없이 한 문장으로
# 이어짐) 소스에서 훨씬 앞쪽에 있는 작품 제목까지 통째로 삼켜버린다
# (예: "A Series of Subjects ... : Place du Molard, Switzerland, 1829. ... The Cleveland
# Museum of Art, Twenty-fifth anniversary gift, Mr. and Mrs. Lewis B. Williams Collection").
NAME_BEFORE_COLLECTION_RE = re.compile(r"^(.{1,70}?)\s+Collection\b", re.IGNORECASE)
# "the Joel W. Solomon Estate" 처럼 문장 중간에 등장하는 Estate/Fund/Trust/Foundation
# 단체명 — 접두 키워드가 없어도 문장 아무데서나 찾아 최후 시도로 사용
SUFFIX_ENTITY_RE = re.compile(r"([A-Z][A-Za-z.&'\- ]{2,60}?\s+(?:Estate|Fund|Trust|Foundation))\b")

YEAR_RE = re.compile(r"\b(1[4-9]\d{2}|20[0-2]\d)\b")

# 생몰년 대괄호([1891-1979], [d. 1942]) / 콜렉터 마크((L.1932d), Lugt) — 이 표기가 있으면
# 세그먼트가 진짜 프로버넌스 소유자 항목일 확률이 높다 (서술형 설명문엔 거의 안 나타남)
COLLECTOR_MARK_RE = re.compile(r"\[\s*(?:d\.\s*)?\d{4}|\(L\.\s*\d|\bLugt\b", re.IGNORECASE)

# 이름 후보가 실제 개체명이 아니라 서술절/각주일 가능성이 높은 경우 배제 —
# "removed by government decree...", "no longer traceable" 같은 문장은 이름이 아님
NAME_STOPWORD_RE = re.compile(
    r"\bremoved\b|\bdeposited\b|\bdestroyed\b|\bno longer\b|\bwhereabouts\b|\breturned\b|"
    r"\btransferred\b|\bseized\b|\bconfiscated\b|\brestitut|\bon loan\b|\blent to\b|"
    r"\bexhibited\b|\bpublished\b|\brecorded\b|\bdocumented\b|\buntil at least\b|"
    r"\blocation unknown\b|\bnot traced\b|\buntraced\b",
    re.IGNORECASE,
)

INSTITUTION_MUSEUM_RE = re.compile(
    r"\bmuseum\b|\binstitute\b|\bacademy\b|national gallery|kunsthalle|kunstmuseum|rijksmuseum",
    re.IGNORECASE,
)
FOUNDATION_RE = re.compile(r"\bfoundation\b", re.IGNORECASE)
# "Foundation"은 museum(위 정규식)과 collector-fund(아래 INSTITUTION_ORG_RE) 양쪽에
# 다 걸칠 수 있는 애매한 단어다 — Barnes Foundation처럼 실제 소장 기관인 경우가 있는
# 반면 "Quentin Foundation", "Purchased with funds provided by The Judith Rothschild
# Foundation"처럼 순수 기부 펀드/크레딧라인이 훨씬 많다(museums 0건-소장 유령 행 1,441개
# 중 920개가 이 패턴 — 2026-09-04 메인 세션이 발견, docs/정합성작업.md §7 참고).
# 무작정 museum에서 빼면 실제 재단형 미술관(우리가 이미 크롤링한 아래 13곳)이 향후
# provenance 텍스트에 다시 언급될 때 collector로 잘못 분류돼버리므로, "이미 실제 소장
# 기관으로 확인된 이름과 정확히 일치할 때만" museum으로 인정하고 나머지는 collector+
# is_institution=true로 보낸다.
KNOWN_MUSEUM_FOUNDATIONS = {
    "aikaterini laskaridis foundation",
    "athens city museum – vouros-eutaxias foundation",
    "b&m theocharakis foundation for the fine arts and music",
    "barnes foundation",
    "calouste gulbenkian foundation",
    "europeana foundation",
    "foundation baron michael tossizza",
    "hellenic literary and historical archive - cultural foundation of the national bank of greece",
    "ignacio larramendi foundation",
    "national museum of world cultures foundation",
    "nordic museum foundation",
    "prince-pückler-museum park and palace branitz foundation",
    "st. john's co-cathedral foundation",
}
GALLERY_RE = re.compile(
    r"\bgallery\b|\bgalerie\b|fine arts?\b|\bkunst\b(?!halle|museum)|art advisory|\bdealers?\b|\bgmbh\b|\bltd\b|\binc\.?\b",
    re.IGNORECASE,
)
AUCTION_HOUSE_RE = re.compile(
    r"sotheby|christie|phillips\b|bonhams|dorotheum|auktion|auction|\bsale\b",
    re.IGNORECASE,
)
# 개인이 아니라 펀드/단체/행사 — collectors.is_institution=true로 표시할 대상.
# museum/gallery/auction_house로는 안 잡히지만 실존 인물도 아닌 "Larry Aldrich Fund",
# "Washington Print Fair" 같은 이름들이 기본값(collector, is_institution=false)으로
# 잘못 들어가던 걸 표본 검증(2026-09-03)에서 발견해 추가.
INSTITUTION_ORG_RE = re.compile(
    r"\bfund\b|\btrust\b|\bstudio\b|\bfair\b|\bsociety\b|\bendowment\b|"
    r"\bcommittee\b|\bassociation\b|\bcouncil\b|\bfriends of\b",
    re.IGNORECASE,
)


def _clean_name(raw: str) -> str | None:
    name = raw.strip()
    # "Purchased as part of the Oppé Collection" 같은 문장이 NAME_BEFORE_COLLECTION_RE에
    # 걸리면 "X Collection"의 X 자리에 동사구가 통째로 들어온다 — 이름이 아니라 취득 서술
    # 앞부분이므로 벗겨낸다 (표본 검증 2026-09-03에서 "Purchased as part of the Oppé"
    # 같은 잘린 이름이 발견되어 추가).
    name = re.sub(
        r"^(?:purchased|acquired|bought|sold)\s+(?:as\s+part\s+of\s+)?",
        "",
        name,
        flags=re.IGNORECASE,
    )
    name = re.sub(r"^(the|his|her|their)\s+", "", name, flags=re.IGNORECASE)
    # 대괄호(생몰년/주석), 뒤따르는 "in honor of"/"through"류 수식절 이하는 잘라낸다
    # "Antiquarian Society bought from Mrs. X" / "Albertina as a duplicate to C.G. Boerner"
    # 처럼 콤마 없이 두 개체가 이어지는 문장은 첫 번째 개체명 뒤에서 잘라야 한다 —
    # 표본 검증 2026-09-03에서 이런 이어붙은 이름이 그대로 저장되는 걸 발견해 추가.
    name = re.split(
        r"\[|\(|,|\bin honor of\b|\bin memory of\b|\bthrough\b|\bfor the\b|;|"
        r"\bbought from\b|\bsold to\b|\bsold by\b|\bacquired from\b|\bpurchased from\b|"
        r"\bas a duplicate\b",
        name,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    name = name.strip(" .\t")
    # 위 split이 접속사 앞에서 끊기면 "Daniel Searle and"처럼 매달린 접속사가 남는다.
    name = re.sub(r"\s+(?:and|with|through)\s*$", "", name, flags=re.IGNORECASE)
    if len(name) < 2 or len(name) > 120:
        return None
    if NOISE_SEGMENT_RE.match(name):
        return None
    if NAME_STOPWORD_RE.search(name):
        return None
    # 고유명사/기관명은 대문자로 시작하는 게 일반적 — 소문자로 시작하면 서술절일 확률이 높음
    if not re.match(r"^[A-Z0-9\"'À-ÖØ-öø-ſ]", name):
        return None
    return name


def _extract_name(segment: str) -> str | None:
    m = NAME_AFTER_KEYWORD_RE.search(segment)
    if m:
        return _clean_name(m.group(1))

    m = NAME_BEFORE_COLLECTION_RE.match(segment)
    if m:
        return _clean_name(m.group(1))

    stripped = segment.strip()
    if stripped.startswith("("):
        inner = stripped.strip("()")
        inner = re.sub(r"^sale[,:]?\s*", "", inner, flags=re.IGNORECASE)
        return _clean_name(inner)

    # 아래 두 tier는 앵커 키워드 없이 문장 아무 데서나 이름을 추정하는 방식이라 긴
    # 각주/서술형 문단(NGA provenancetext에 흔한 학술 각주)에 잘못 걸리기 쉽다 —
    # 짧은 세그먼트(한 owner 항목 정도 길이)에서만 시도한다.
    if len(stripped) > 200:
        return None

    # 일반 체인 세그먼트: "Lessing J. Rosenwald [1891-1979], Philadelphia" 형태.
    # 키워드 매칭 없이 순전히 "대문자로 시작 + 쉼표"만으로 이름을 뽑으면 Rijksmuseum/
    # 일본 소스처럼 다른 언어 서술형 설명(예: 네덜란드어 판화 설명)의 앞부분을 이름으로
    # 오인하는 경우가 많다 — 생몰년 대괄호([1891-1979] 등)나 콜렉터 마크((L.xxxx)/Lugt)
    # 같은 프로버넌스 특유 표기가 있을 때만 이 fallback을 적용한다. 마크는 반드시
    # 세그먼트 앞쪽(이름 바로 뒤)에 있어야 한다 — 문장 뒤쪽 각주에 있는 연도([1690] p.164
    # 같은 인용)까지 search()로 잡으면 "Commissioned by Guillaume Brissonnet (died 1674)
    # in 1650 ... [according to ... [1690], p. 164]" 같은 서술문 전체를 이름으로 오인한다.
    if COLLECTOR_MARK_RE.search(stripped[:60]):
        return _clean_name(stripped)

    # 마지막 시도: 앞의 어떤 패턴도 안 맞았지만 문장 중간에 Estate/Fund/Trust/Foundation
    # 형태의 단체명이 있으면 그거라도 건진다 (예: "Acquired through the generosity of
    # the Joel W. Solomon Estate")
    m = SUFFIX_ENTITY_RE.search(stripped)
    if m:
        return _clean_name(m.group(1))
    return None


def _classify_owner_type(name: str) -> tuple[str, bool]:
    """(owner_type, is_institution) — is_institution은 owner_type='collector'일 때만 의미 있음."""
    if INSTITUTION_MUSEUM_RE.search(name):
        return "museum", False
    if FOUNDATION_RE.search(name):
        if name.strip().lower() in KNOWN_MUSEUM_FOUNDATIONS:
            return "museum", False
        return "collector", True  # 실제 소장 기관으로 확인 안 된 foundation — 펀드/단체로 취급
    if AUCTION_HOUSE_RE.search(name):
        return "auction_house", False
    if GALLERY_RE.search(name):
        return "gallery", False
    if INSTITUTION_ORG_RE.search(name):
        return "collector", True
    return "collector", False


def _extract_method(segment: str) -> str | None:
    for pattern, label in METHOD_PATTERNS:
        if pattern.search(segment):
            return label
    return None


def _extract_date(segment: str) -> str | None:
    m = YEAR_RE.search(segment)
    if not m:
        return None
    return year_to_date(m.group(1))


def process_description(store, artwork_id: str, description: str, source_id: str | None) -> int:
    created = 0
    for raw_segment in description.split(";"):
        segment = raw_segment.strip()
        if len(segment) < 3:
            continue
        if SELF_MUSEUM_RE.search(segment):
            continue
        if NOISE_SEGMENT_RE.match(segment):
            continue

        method = _extract_method(segment)
        name = _extract_name(segment)
        # 취득 방식 키워드가 없는 순수 인물/기관 세그먼트(예: 생몰년만 있는 소유자 이름)는
        # 세그먼트 안의 연도가 생몰년일 뿐 취득 연도가 아닐 수 있어 date를 비워둔다
        acquired_date = _extract_date(segment) if method else None
        note = segment[:500]

        if name is None:
            if method is None:
                # 이름도, 취득 방식도 못 뽑으면 노이즈로 보고 skip
                continue
            store.insert_provenance_record(
                artwork_id=artwork_id,
                owner_type="unknown",
                acquired_date=acquired_date,
                acquired_method=method,
                note=note,
                source_id=source_id,
            )
            created += 1
            continue

        owner_type, is_institution = _classify_owner_type(name)
        fields: dict = {
            "artwork_id": artwork_id,
            "owner_type": owner_type,
            "acquired_date": acquired_date,
            "acquired_method": method,
            "note": note,
            "source_id": source_id,
        }
        if owner_type == "museum":
            fields["owner_museum_id"] = store.get_or_create_museum(name)
        elif owner_type == "gallery":
            fields["owner_gallery_id"] = store.get_or_create_gallery(name)
        elif owner_type == "auction_house":
            fields["owner_auction_house_id"] = store.get_or_create_auction_house(name)
        else:
            fields["owner_collector_id"] = store.get_or_create_collector(name, is_institution=is_institution)

        store.insert_provenance_record(**fields)
        created += 1

    return created


def run(store, limit: int | None, offset: int = 0, batch_log_every: int = 20000) -> None:
    # 읽기 전용 커넥션을 store의 쓰기 커넥션과 분리한다 — 같은 커넥션을 쓰면 store.commit()이
    # 진행 중인 서버사이드(named) 커서를 무효화시켜(named cursor isn't valid anymore) 스캔이
    # 중간에 죽는다.
    read_conn = get_connection()
    cur = read_conn.cursor(name="provenance_extract_cursor")
    cur.itersize = 2000

    # id로 정렬해 --offset으로 재개 가능하게 한다 — 대량(140만+) 스캔이 중간에 끊겨도
    # 처음부터 다시 돌리면 이미 만든 provenance_records가 전부 중복되므로, 진행 로그에
    # 찍히는 processed 건수를 다음 --offset으로 넘겨 이어서 돌린다.
    query = "select id, description, source_id from artworks where description is not null and length(description) > 5 order by id"
    if limit is not None:
        query += f" limit {int(limit)}"
    if offset:
        query += f" offset {int(offset)}"
    cur.execute(query)

    processed = offset
    created_total = 0
    for artwork_id, description, source_id in cur:
        processed += 1
        created_total += process_description(store, str(artwork_id), description, str(source_id) if source_id else None)
        if processed % batch_log_every == 0:
            store.commit()
            print(f"[provenance_extract] {processed}건 스캔(offset 재개용), provenance_records 누적 {created_total}건(이번 실행분) 생성 진행 중...", flush=True)

    store.commit()
    print(f"[provenance_extract] 완료 — artworks {processed - offset}건 스캔(offset={offset}), provenance_records {created_total}건 생성")
    if isinstance(store, DryRunStore):
        print("[provenance_extract] dry-run 집계:", store.counts)
        if store.samples:
            print("[provenance_extract] 샘플 provenance_record:")
            for sample in store.samples:
                print(" ", sample)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="artworks.description -> collectors/provenance_records 역추출")
    parser.add_argument("--limit", type=int, default=None, help="스캔할 artworks 최대 건수 (검증용)")
    parser.add_argument("--offset", type=int, default=0, help="이 건수만큼 건너뛰고 시작 (중단 후 재개용)")
    parser.add_argument("--dry-run", action="store_true", help="DB에 쓰지 않고 파싱 결과만 집계")
    args = parser.parse_args()

    dry_run = args.dry_run or not os.environ.get("DATABASE_URL")
    if dry_run:
        print("[provenance_extract] DRY-RUN 모드 — 조회는 실제 DB로 하되 쓰기는 안 함" + ("" if args.dry_run else " (DATABASE_URL 미설정)"))
        run(DryRunStore(), limit=args.limit, offset=args.offset)
    else:
        run(PgStore(get_connection()), limit=args.limit, offset=args.offset)
