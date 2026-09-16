"""자유텍스트(smithsonian artist name 자체, aic artist_display)에서
nationality/birth_year/death_year를 정규식으로 뽑아내는 파서.

**Smithsonian**: smithsonian.py 로더가 원래 artist_name으로 저장한 값이
"Edwin Austin Abbey, born Philadelphia, PA 1852-died London, England 1911"
처럼 전기(bio) 문장 전체다 — 즉 DB의 artists.name 컬럼 자체에 이미 생몰년이
박혀 있다. raw 재스캔 없이 DB name 컬럼만 정규식으로 파싱하면 된다.

**AIC**: raw artist_display 필드가 "Name\nNationality, YYYY-YYYY" 또는
"Name (Nationality, born YYYY)" 형태 — 콜라보레이터(printed by/published by 등)가
같은 필드에 이어 붙는 경우가 있어, 그 지점에서 잘라내고 첫 부분만 파싱한다.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from audit_attribution_variants import normalize, extract_core  # noqa: E402

_CUTOFF_RE = re.compile(
    r"\n(?:printed by|published by|manufactured by|assembled by|designed by|woven by|distributed by)",
    re.IGNORECASE,
)

# "Name, born Place YYYY-died Place YYYY" / "Name, Nationality, born YYYY?-died YYYY"
_SM_BORN_DIED_RE = re.compile(r"\bborn\b(?P<birth_part>.*?)-\s*died\b(?P<death_part>.*)$", re.IGNORECASE)
_SM_BORN_ONLY_RE = re.compile(r"\bborn\b(?P<birth_part>.*)$", re.IGNORECASE)
_SM_NAT_RE = re.compile(r",\s*([A-Za-z]{3,20}),\s*born\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"(\d{4})")

# 활동시기("active 1850-1875")는 생몰년이 아니므로 제외 대상
_ACTIVE_ONLY_RE = re.compile(r"\bactive\b", re.IGNORECASE)


def parse_smithsonian_name(name: str) -> tuple[str | None, int | None, int | None]:
    """artists.name(예: 'X, born Place YYYY-died Place YYYY')에서 파싱.
    "born"이 없거나 "active"만 있으면 (None, None, None)."""
    if "born" not in name.lower():
        return (None, None, None)

    m = _SM_BORN_DIED_RE.search(name)
    birth_year = death_year = None
    if m:
        birth_years = _YEAR_RE.findall(m.group("birth_part"))
        death_years = _YEAR_RE.findall(m.group("death_part"))
        birth_year = int(birth_years[-1]) if birth_years else None
        death_year = int(death_years[0]) if death_years else None
    else:
        m2 = _SM_BORN_ONLY_RE.search(name)
        if m2 and "died" not in name.lower():
            birth_years = _YEAR_RE.findall(m2.group("birth_part"))
            birth_year = int(birth_years[0]) if birth_years else None

    nat_match = _SM_NAT_RE.search(name)
    nationality = nat_match.group(1) if nat_match else None
    if nationality and not _looks_like_nationality(nationality):
        nationality = None

    return (nationality, birth_year, death_year)


# artists.bio 컬럼 자체(met/cleveland/aic 등에서 이미 채워둔 텍스트, name 없이
# "Nationality, [Place] YYYY-YYYY [Place][, extra]" 형태)에서 직접 파싱.
# 이미 DB에 저장돼 있으므로 raw 재스캔이 필요 없다.
#
# 2026-09-08 시도에서 발견된 오탐(전부 확인됨, 아래 가드로 대응):
#   - Cleveland 긴 전기 산문에서 전시 연도("(1953-1960)")를 생몰년으로 오인
#     -> 짧은 bio만 파싱(MAX_BIO_LEN)
#   - "Various Artists, X, Y, Z" 같은 복수인물 합성 행에서 한 사람의 생몰년을
#     행 전체에 잘못 귀속 -> name에 콤마 있으면 파싱 자체를 건너뜀
#   - [A-Za-z\s\-]의 \s가 개행까지 매칭해 "Traut\nUnknown"을 국적 하나로 캡처
#     -> \s 대신 " "(공백 1개)만 허용
#   - "Patterns, Inc." 같은 회사명이 국적 형태 검사를 통과 -> 회사 접미사 차단
#   - 괄호가 여러 개인 bio는 구조가 복잡해(합성/각주 포함 가능성) 오탐 위험이
#     높다고 판단 -> 괄호가 0개 또는 1개인 경우만 파싱
_BIO_NAT_RE = re.compile(r"^([A-Za-z][A-Za-z \-]*?),")
_BIO_RANGE_RE = re.compile(r"(\d{4})\s*[-–—]\s*(\d{4})")
_BIO_BORN_RE = re.compile(r"\bborn\s+(\d{4})", re.IGNORECASE)
MAX_BIO_LEN = 120
_COMPANY_SUFFIXES = {"inc", "inc.", "co", "co.", "ltd", "ltd.", "llc", "studio", "studios", "workshop", "gallery"}
# 2026-09-08 샘플 검증에서 추가로 발견된 오탐 2종:
#   - "회사/공방" 이름(예: "Ferdinand Favre et Cie")의 설립/폐업 연도가
#     birth_year/death_year로 오추출 -> name 자체에 회사 표지어가 있으면 전부 스킵
#   - "active YYYY-YYYY"(활동시기)가 생몰년 범위와 형태가 같아 그대로
#     birth_year/death_year로 오추출(Archibald Davidson, Emile Hurtré 등,
#     전부 확인된 오탐) -> range 앞에 "active"가 있고 그 사이에 "born"이
#     없으면(=활동시기이지 생몰년이 아니면) 범위를 버림. "born ... active
#     Place, YYYY-YYYY" 같은 진짜 생몰년 표기까지 놓칠 수 있지만, 잘못된
#     연도를 심는 것보다 놓치는 쪽이 안전하다는 원칙(과거 오탐 대응 방식)을
#     그대로 따름.
_COMPANY_NAME_RE = re.compile(
    r"\b(co\.?|inc\.?|ltd\.?|llc|gmbh|ag|cie|s\.a\.|corp\.?|company|manufactory|firm|"
    r"workshop|press|pottery|porcelain|publishers?|agency|associates|brothers)\b",
    re.IGNORECASE,
)


def parse_bio_text(name: str, bio: str) -> tuple[str | None, int | None, int | None]:
    if not bio or not name:
        return (None, None, None)
    if len(bio) > MAX_BIO_LEN:
        return (None, None, None)
    if "," in name:
        return (None, None, None)
    if _COMPANY_NAME_RE.search(name):
        return (None, None, None)
    # 귀속표기(School of/Circle of/Attributed to/After 등) 붙은 이름은 원작가와
    # 다른 별개 개체로 취급하기로 이미 결정한 정책(2026-09-08 귀속변형 스코프
    # 리포트)이 있다 — 원작가의 생몰년을 여기 그대로 붙이면 나중에 메타데이터
    # 기반 병합 로직이 "같은 사람"으로 오판할 위험이 생겨 정책과 충돌한다.
    _, has_attr = extract_core(normalize(name))
    if has_attr:
        return (None, None, None)
    if bio.count("(") > 1 or bio.count(")") > 1:
        return (None, None, None)
    if _ACTIVE_ONLY_RE.search(bio) and not _BIO_RANGE_RE.search(bio):
        return (None, None, None)

    nat_match = _BIO_NAT_RE.match(bio)
    nationality = nat_match.group(1).strip() if nat_match else None
    if nationality and nationality.lower().split()[-1] in _COMPANY_SUFFIXES:
        nationality = None
    if nationality and not _looks_like_nationality(nationality):
        nationality = None
    # "City, Country"류(예: "Bologna, Italy")는 콤마 앞부분이 국적이 아니라
    # 도시명인 경우가 있음 — bio에 연도가 전혀 없으면(생몰년/활동시기 등 다른
    # 근거가 없으면) 이 판별 자체가 약한 신호라 국적도 채택하지 않는다.
    if nationality and not re.search(r"\d", bio):
        nationality = None

    birth_year = death_year = None
    range_match = _BIO_RANGE_RE.search(bio)
    if range_match:
        before = bio[: range_match.start()].lower()
        active_idx = before.rfind("active")
        if active_idx != -1 and "born" not in before[active_idx:]:
            range_match = None
    if range_match:
        birth_year = int(range_match.group(1))
        death_year = int(range_match.group(2))
    else:
        born_match = _BIO_BORN_RE.search(bio)
        if born_match:
            birth_year = int(born_match.group(1))

    return (nationality, birth_year, death_year)


# AIC: "(Nationality, born YYYY)" / "(Nationality, YYYY-YYYY)" / "(Nationality, active YYYY)"
_AIC_PAREN_RE = re.compile(r"\(([^()]*)\)")
_AIC_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z\s\-.]*?),\s*(.+)$")

_PLACEHOLDER_PREFIXES = ("unknown", "possibly", "attributed", "manner of", "circle of", "follower of", "school of")

# 지명/행정구역/시대 등 국적이 아닌 단어가 콤마 앞에 우연히 걸리는 경우 방지
# (예: "Kuba\nKasai region, Democratic Republic of the Congo" -> "Kasai region"은 국적이 아님)
_NON_NATIONALITY_WORDS = {
    "region", "province", "district", "territory", "republic", "kingdom", "empire",
    "county", "department", "colony", "period", "century", "dynasty", "era",
    "master", "workshop", "school", "circle", "manner", "follower", "attributed",
}
_NATIONALITY_SHAPE_RE = re.compile(r"^[A-Z][a-zA-Z]*(\s[A-Z][a-zA-Z]*){0,1}$")


def _looks_like_nationality(candidate: str) -> bool:
    words = candidate.lower().split()
    if any(w in _NON_NATIONALITY_WORDS for w in words):
        return False
    return bool(_NATIONALITY_SHAPE_RE.match(candidate))


def parse_aic_display(artist_display: str) -> tuple[str | None, int | None, int | None]:
    if not artist_display:
        return (None, None, None)

    text = artist_display
    cut = _CUTOFF_RE.search(text)
    if cut:
        text = text[: cut.start()]

    first_line = text.split("\n", 1)[0].strip()
    if first_line.lower().startswith(_PLACEHOLDER_PREFIXES):
        return (None, None, None)

    # 괄호 안: "(Nationality, born YYYY)" 또는 "(Nationality, YYYY-YYYY)"
    paren = _AIC_PAREN_RE.search(text)
    segment = None
    if paren:
        segment = paren.group(1)
    else:
        # 둘째 줄: "Nationality, YYYY-YYYY"
        lines = text.split("\n")
        if len(lines) > 1:
            segment = lines[1].strip()

    if not segment or _ACTIVE_ONLY_RE.search(segment):
        return (None, None, None)

    nat_match = re.match(r"^([A-Za-z][A-Za-z\s\-]*?),", segment)
    nationality = nat_match.group(1).strip() if nat_match else None
    if nationality and not _looks_like_nationality(nationality):
        nationality = None

    birth_year = death_year = None
    born_match = re.search(r"\bborn\s+(\d{4})", segment, re.IGNORECASE)
    if born_match:
        birth_year = int(born_match.group(1))
    else:
        range_match = re.search(r"(\d{4})\s*[-–—]\s*(\d{4})?", segment)
        if range_match:
            birth_year = int(range_match.group(1))
            if range_match.group(2):
                death_year = int(range_match.group(2))

    return (nationality, birth_year, death_year)
