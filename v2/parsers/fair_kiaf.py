"""Kiaf 회차 JSON(research/kiaf/build_kiaf.py 산출) -> v2 페어 레코드 정리.

- 특별전은 조립 단계에서 gallery 칸에 "Special Exhibition: ..."이 들어온다 -> 갤러리가 아니라
  작가 단위 항목(부스 없음)으로 돌리고 섹션명만 남긴다.
- 카탈로그·하이라이트 표기는 "Jin Han 한진", "KIM Jongwon / 김종원"처럼 한/영이 한 줄에 섞인 경우가
  있다. name_ko/name_en이 비어 있으면 문자 체계 기준으로 갈라 채운다(영문 부분에 한글이 없고
  한글 부분에 라틴 문자가 없을 때만).
- 2017 미디어 특별전의 "김준 영상, 설치" 같은 역할 꼬리를 떼어낸다.
"""
from __future__ import annotations

import re

SPECIAL = "Special Exhibition: "
ROLE_TAIL = re.compile(r"\s+(영상|사운드|설치|퍼포먼스)(\s*,\s*(영상|사운드|설치|퍼포먼스))*$")
HANGUL = re.compile(r"[가-힣]")
LATIN = re.compile(r"[A-Za-z]")


def _split_mixed(name: str) -> tuple[str | None, str | None]:
    """'Jin Han 한진' / '서용선 Yongsun Suh' / 'KIM Jongwon / 김종원' -> (en, ko)."""
    parts = [p.strip() for p in re.split(r"\s*/\s*", name) if p.strip()]
    if len(parts) == 2:
        a, b = parts
    else:
        m = re.match(r"^(.*?[A-Za-z][^가-힣]*?)\s+([가-힣][^A-Za-z]*)$", name) or \
            re.match(r"^([가-힣][^A-Za-z]*?)\s+([A-Za-z].*)$", name)
        if not m:
            return None, None
        a, b = m.group(1).strip(), m.group(2).strip()
    en, ko = (a, b) if LATIN.search(a) else (b, a)
    if HANGUL.search(en) or LATIN.search(ko):
        return None, None
    return en, ko


def adapt(records: list[dict], edition_id: str) -> list[dict]:
    out = []
    for b in records:
        b = dict(b)
        if (b.get("gallery") or "").startswith(SPECIAL):
            b["section"] = b["section"] or b["gallery"]
            b["gallery"] = None
        arts = []
        for a in b.get("artists") or []:
            a = dict(a)
            a["name"] = ROLE_TAIL.sub("", a["name"]).strip()
            if a.get("name_ko"):
                a["name_ko"] = ROLE_TAIL.sub("", a["name_ko"]).strip()
            if not a.get("name_ko") and HANGUL.search(a["name"]) and LATIN.search(a["name"]):
                en, ko = _split_mixed(a["name"])
                if en:
                    a["name_en"], a["name_ko"] = en, ko
            elif not a.get("name_ko") and HANGUL.search(a["name"]) and not LATIN.search(a["name"]):
                a["name_ko"] = a["name"]
            arts.append(a)
        # 같은 부스 안의 표기 중복(역할 꼬리 제거 후 '김준' 둘 등) 정리
        seen, uniq = set(), []
        for a in arts:
            k = (a.get("name_en") or a["name"]).casefold()
            if k not in seen:
                seen.add(k)
                uniq.append(a)
        b["artists"] = uniq
        out.append(b)
    return out
