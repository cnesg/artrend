"""auction_houses 표기 변형 병합 — 2026-09-15 작업분담 §W8

Christie's/Sotheby's/Bonhams/Phillips 4대 경매사의 표기 변형(악센트/구두점/
지점명/역사적 사명 변경)을 canonical 하나로 병합한다. merge_dup_museums.py와
같은 relink-then-delete 패턴 — auctions.auction_house_id,
provenance_records.owner_auction_house_id를 canonical로 재연결 후 loser 행 삭제.

**정규화 매칭이 아니라 하드코딩 alias 표를 쓴다** — 4대 경매사 이름은 흔한
단어(Christie, Phillips 등)와 겹쳐 오탐 위험이 커서, 실제 auction_houses.name
전수를 육안 검토해 진짜 변형만 골랐다(2026-09-15). 다음은 **의도적으로 제외**:
  - "Foster (Edward)", "Phillips (Harry)" 같은 역사 개인 경매인 이름
    (괄호 안 이름 패턴 — Getty provenance-index 특유의 인물 표기)
  - "Christie McDonald and Joan McD Miller", "James E. Christie",
    "Graham and Phillips", "Hoggart and Phillips" 등 사람 이름이 우연히
    브랜드명을 포함하는 경우
  - "Colnaghi at Sotheby's", "Artist's estate stamp created by Christie's in 2003"
    처럼 다른 주체가 주(主)이고 경매사명이 부수적으로 언급된 문장형 값
  - "Christie"(단독), "Sotheby Mak van Waay"(공동 브랜드) — 동일 개체인지
    확신할 근거 부족, 자동 병합 대상에서 제외하고 리포트에 남겨 메인/사용자
    판단을 받는다.

**기본은 dry-run(리포트만)이며, --apply 없이는 절대 UPDATE/DELETE하지 않는다.**
idempotent — 재실행 시 대상 0건.

사용법:
    python pipeline/merge_auction_house_variants.py              # dry-run, 리포트 JSON 저장
    python pipeline/merge_auction_house_variants.py --apply       # 실제 반영
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path(__file__).parent / ".env")

from db import get_connection  # noqa: E402

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "logs"

# canonical -> 병합 대상 표기 변형 목록(canonical 자신 포함하지 않음)
MERGE_GROUPS: dict[str, list[str]] = {
    "Christie's": [
        "Christie's Auction House",
        "Christie's Contemporary Art",
        "Christie's Contemporary Art 1979",
        "Christie's East",
        "Christie's London",
        "Christie's New York",
        "Christie's New York 10 April 2013",
        "Christie's Old Master and 19th Century Drawings",
        "Christie's Paris",
        "Christie's South Kensington",
        "Christie's, New York",
        "Christie's, Paris",
        "Christie's 1 July 1969",
        "Christie’s",
        "Christie’s London",
        "Christie’s New York",
        "Christies",
        "Christies auction 5138",
        "Christies London",
        "Christie & Manson",
    ],
    "Sotheby's": [
        "Sotheby's' London",
        "Sotheby's Amsterdam",
        "Sotheby's Fine Art Auctions",
        "Sotheby's London",
        "Sotheby's London 20 November 2003",
        "Sotheby's New York",
        "Sotheby's Olympia",
        "Sotheby's)",
        "Sotheby’s",
        "Sotheby’s London",
        "Sotheby’s New York",
        "Sotheby",
        "Sotheby & Co",
        "Sotheby Parke-Bernet",
        "Sotheby Parke Bernet",
        "Sotheby Parke Bernet & Co",
    ],
    "Bonhams": [
        "Bonhams & Butterfields",
        "Bonhams Edinborough",
        "Bonhams Fine Art Auctioneers",
        "Bonhams London",
    ],
    "Phillips": [
        "Phillips de Pury",
        "Phillips de Pury & Company",
        "Phillips de Pury & Luxembourg",
        "Phillips de Pury and Luxembourg",
    ],
    # 2026-09-22 추가 — K-ARTMARKET 낙찰 작품 DB(`k_artmarket_works`) 적재분.
    # **출처 데이터가 경매사 칸을 잘라 넣은 행**이 소수 있다(전체 52,651건 중 132건).
    # 아래 셋은 전부 canonical 이름의 **정확한 접두 부분문자열**이고, 그 접두사로
    # 시작하는 국내 경매사가 그 하나뿐이라 동일 개체가 확실하다(유사도 매칭 아님).
    # 같은 원인으로 생긴 'HERALD ARTDAY AUCTION'(영문 병기)과 '마아아트옥션'(오타)은
    # 접두 관계가 아니라 판단 근거가 약해 **아래 EXCLUDED_AMBIGUOUS로 남긴다**.
    "라이즈아트": ["라이즈"],
    "마이아트옥션": ["마이", "마이아"],
}

# 검토했으나 근거 부족으로 자동 병합에서 제외한 것들 (리포트에만 남김)
EXCLUDED_AMBIGUOUS = [
    # 2026-09-22 K-ARTMARKET 적재분에서 나온 출처 표기 이상 — 접두 관계가 아니라
    # 자동 병합 근거가 약해 제외하고 사람 판단으로 남긴다.
    "HERALD ARTDAY AUCTION (헤럴드아트데이의 영문 병기로 보이나 교차언어 매칭이라 제외)",
    "마아아트옥션 (마이아트옥션 오타로 보이나 접두 일치가 아니라 제외)",
    "크리스티 (Christie's 한글 표기로 보이나 교차언어 매칭이라 제외)",
    "Christie",
    "Christie & Manson (재검토용 — 포함됨, 혼동 방지 주석)",
    "Sotheby Mak van Waay",
    "Sotheby's Mak van Waay",
    "Sotheby Mak van Waay B.V",
    "Colnaghi at Sotheby's",
    "Artist's estate stamp created by Christie's in 2003",
    "Phillips (Harry)",
    "Graham and Phillips",
    "Hoggart and Phillips",
    "Phillips and Morris",
    "James E. Christie",
    "Christie McDonald and Joan McD Miller",
    "Christie Zhou and The Gogel Collection",
    "Dr. Guthrie McConnell and Christie McConnell",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 병합한다")
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    plan = []
    for canonical, variants in MERGE_GROUPS.items():
        cur.execute("select id, name from auction_houses where name = %s", (canonical,))
        canon_row = cur.fetchone()
        if not canon_row:
            print(f"[merge_ah] 경고: canonical '{canonical}' 행이 DB에 없음 — 이 그룹 스킵")
            continue
        canonical_id = str(canon_row[0])

        cur.execute("select id, name from auction_houses where name = any(%s)", (variants,))
        found = cur.fetchall()
        found_names = {r[1] for r in found}
        missing = [v for v in variants if v not in found_names]
        if missing:
            print(f"[merge_ah] '{canonical}' 그룹: DB에 없는 변형 {len(missing)}개(이미 정리됐거나 오타) — {missing}")

        loser_ids = [str(r[0]) for r in found]
        if not loser_ids:
            continue

        cur.execute("select count(*) from auctions where auction_house_id = any(%s::uuid[])", (loser_ids,))
        auctions_affected = cur.fetchone()[0]
        cur.execute(
            "select count(*) from provenance_records where owner_auction_house_id = any(%s::uuid[])",
            (loser_ids,),
        )
        provenance_affected = cur.fetchone()[0]

        plan.append(
            {
                "canonical": canonical,
                "canonical_id": canonical_id,
                "loser_names": sorted(found_names),
                "loser_ids": loser_ids,
                "auctions_to_repoint": auctions_affected,
                "provenance_to_repoint": provenance_affected,
            }
        )
        print(
            f"[merge_ah] '{canonical}' <- {len(loser_ids)}개 변형 "
            f"(auctions {auctions_affected}건, provenance {provenance_affected}건 재연결 예정)"
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plan": plan,
        "excluded_ambiguous": EXCLUDED_AMBIGUOUS,
    }
    out_path = DOCS_DIR / f"auction_houses_병합_리포트_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n[merge_ah] 상세 리포트 저장: {out_path}")
    print(f"[merge_ah] 제외(근거부족, 자동병합 안함) {len(EXCLUDED_AMBIGUOUS)}건 — 리포트에 목록 기록")

    if not args.apply:
        print("\n[merge_ah] dry-run — 변경 없음. --apply로 실행하면 실제 반영됩니다.")
        cur.close()
        conn.close()
        return

    total_merged = 0
    total_repointed = 0
    for item in plan:
        canonical_id = item["canonical_id"]
        loser_ids = item["loser_ids"]
        cur.execute(
            "update auctions set auction_house_id = %s where auction_house_id = any(%s::uuid[])",
            (canonical_id, loser_ids),
        )
        n1 = cur.rowcount
        cur.execute(
            "update provenance_records set owner_auction_house_id = %s where owner_auction_house_id = any(%s::uuid[])",
            (canonical_id, loser_ids),
        )
        n2 = cur.rowcount
        cur.execute("delete from auction_houses where id = any(%s::uuid[])", (loser_ids,))
        conn.commit()
        total_merged += len(loser_ids)
        total_repointed += n1 + n2
        print(f"[merge_ah] '{item['canonical']}' 병합 완료 — {len(loser_ids)}개 행 삭제, {n1 + n2}건 재연결")

    print(f"\n[merge_ah] 전체 완료 — 삭제된 auction_houses {total_merged}건, 재연결 {total_repointed}건")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
