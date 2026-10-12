"""collectors 테이블 오분류 감사/정정 스크립트.

pipeline/provenance_extract.py가 규칙 기반으로 추출한 collectors 32,824건 중
펀드/기관/행사/단체명이 개인 컬렉터(is_institution=false)로 잘못 들어간 사례를
찾아 is_institution=true로 정정한다.

패턴: 이름 어디든 "기관성 명사"가 단어 경계로 등장하면 기관으로 분류한다.
과잉 매칭을 피하려고 실제 인명에 흔한 단어(Banks/Wood/Baker 등 사람 성씨로도
쓰이는 단어)는 넣지 않았고, 전부 \\b 단어 경계로만 매칭한다.

사용법:
    python pipeline/audit_collectors.py                 # 리포트만 (DB 변경 없음)
    python pipeline/audit_collectors.py --apply          # 실제 is_institution 정정
    python pipeline/audit_collectors.py --apply --limit 500  # 일부만 정정(검증용)
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from db import get_connection

# 카테고리 -> 정규식 (전부 대소문자 무시, 단어 경계 \b 사용).
# Grant/Church/Temple/Press처럼 실제 인명(성)으로도 흔히 쓰이는 단어는 오탐이
# 확인돼(예: "Duncan Grant"라는 화가, "Frederic Edwin Church"라는 화가) 뺐다 —
# 아래 "제외 패턴"에서 별도로 잡는다.
PATTERNS: dict[str, str] = {
    "fund/grant": r"\b(Fund|Funds|Endowment)\b",
    "fair/event": r"\b(Fair|Fairs|Biennale|Biennial|Triennial|Exposition)\b",
    "society/club": r"\b(Society|Societies|Club|Circle|Guild|Fellowship)\b",
    "trust/foundation": r"\b(Trust|Trustees|Foundation|Fondation|Fondazione|Stiftung)\b",
    "institute/academy": r"\b(Institute|Institut|Academy|Akademie|School|College|University)\b",
    "museum/gallery": r"\b(Museum|Museo|Musée|Gallery|Galleries|Galerie|Kunsthalle|Kunstverein|Sammlung)\b",
    "company/corp": r"\b(Company|Co\.|Corporation|Corp\.|Inc\.|Incorporated|LLC|Ltd\.?|GmbH|N\.V\.|S\.A\.|Group)\b",
    "assoc/committee": r"\b(Association|Committee|Council|Consortium|Alliance|Union|Federation|Board)\b",
    "gov/office": r"\b(Department|Ministry|Agency|Bureau|Commission|Office)\b",
    "auction/sale": r"\b(Auction|Auctions|Sale Room|Saleroom)\b",
    "publishing": r"\b(Publishing|Publishers?)\b",
    "religious": r"\b(Cathedral|Chapel|Diocese|Synagogue|Mosque)\b",
    "library/archive": r"\b(Library|Libraries|Archive|Archives)\b",
    "bank": r"\b(Bank|Banking)\b",
}

# 실제로는 개인명인데 기관성 단어와 겹치는 경우를 걸러내는 예외 패턴.
# "Funds from X"/"Grant Pick"처럼 provenance_extract.py가 애초에 이름을
# 잘못 뽑은 케이스도 있지만, 그건 이 스크립트가 아니라 별도 이슈로 문서에만
# 기록하고 여기서는 is_institution 오분류만 막는다.
EXCLUDE_PATTERN = re.compile(r"^\s*Funds?\s+from\s+", re.IGNORECASE)

COMBINED_PATTERN = re.compile(
    "|".join(f"(?P<{re.sub(r'[^a-zA-Z0-9]', '_', k)}>{v})" for k, v in PATTERNS.items()),
    re.IGNORECASE,
)


def classify(name: str) -> str | None:
    if EXCLUDE_PATTERN.match(name):
        return None
    m = COMBINED_PATTERN.search(name)
    if not m:
        return None
    for k, v in m.groupdict().items():
        if v:
            # 원래 카테고리 라벨로 되돌리기 (언더스코어 치환 역matching)
            for label in PATTERNS:
                if re.sub(r"[^a-zA-Z0-9]", "_", label) == k:
                    return label
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="collectors 기관 오분류 감사/정정")
    parser.add_argument("--apply", action="store_true", help="실제 is_institution=true UPDATE 실행")
    parser.add_argument("--limit", type=int, default=None, help="--apply 시 처리할 최대 건수(검증용)")
    parser.add_argument("--sample", type=int, default=5, help="카테고리별 출력할 예시 건수")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("select id, name from collectors where is_institution = false")
    rows = cur.fetchall()
    print(f"[audit_collectors] is_institution=false {len(rows)}건 검사")

    by_category: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for cid, name in rows:
        cat = classify(name)
        if cat:
            by_category[cat].append((str(cid), name))

    total_flagged = sum(len(v) for v in by_category.values())
    print(f"[audit_collectors] 기관성 패턴 매칭 {total_flagged}건 발견\n")

    for cat, items in sorted(by_category.items(), key=lambda kv: -len(kv[1])):
        print(f"  {cat}: {len(items)}건")
        for _, name in items[: args.sample]:
            print(f"      예시: {name}")
    print()

    if not args.apply:
        print("[audit_collectors] --apply 없이 리포트만 실행함 (DB 변경 없음)")
        return

    all_ids = [cid for items in by_category.values() for cid, _ in items]
    if args.limit:
        all_ids = all_ids[: args.limit]

    updated = 0
    BATCH = 500
    for i in range(0, len(all_ids), BATCH):
        chunk = all_ids[i : i + BATCH]
        cur.execute(
            "update collectors set is_institution = true where id = any(%s::uuid[])",
            (chunk,),
        )
        updated += len(chunk)
        conn.commit()
        print(f"[audit_collectors] {updated}/{len(all_ids)}건 정정 커밋")

    print(f"[audit_collectors] 완료 — {updated}건 is_institution=true로 정정")


if __name__ == "__main__":
    main()
