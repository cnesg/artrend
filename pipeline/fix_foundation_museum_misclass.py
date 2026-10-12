"""소장품(museum_holdings) 0건인 "Foundation" 유령 museums 행 정리.

메인 세션이 발견: `museums` 1,980건 중 소장품 0건인 유령 행 1,441건이 있고,
그중 920건이 이름에 "Foundation"이 포함된 기부 펀드/크레딧라인 문자열
(예: "Quentin Foundation", "Purchased with funds provided by The Judith
Rothschild Foundation")이다. 원인은 `pipeline/provenance_extract.py`의
`_classify_owner_type()`이 `\bfoundation\b`을 항상 museum으로 분류해서
`get_or_create_museum()`이 실제 소장 기관이 아닌 이름에도 museums 행을
만들어버렸기 때문(상세는 docs/정합성작업.md §7 참고). 분류 로직은 이미
수정 완료(`FOUNDATION_RE` + `KNOWN_MUSEUM_FOUNDATIONS` 화이트리스트 —
실제로 크롤링해 소장품이 있는 13개 재단형 미술관만 museum으로 인정) —
이 스크립트는 기존에 잘못 만들어진 museums 행을 같은 기준으로 백필한다.

방법: 소장품 0건이고 이름이 `\bfoundation\b`에 매칭하며
`KNOWN_MUSEUM_FOUNDATIONS`에 없는 museums 행을 대상으로 —
1. 그 museum_id를 참조하는 provenance_records를 collectors로 재연결
   (get_or_create_collector, is_institution=true) — owner_type='collector',
   owner_collector_id=<id>, owner_museum_id=null로 갱신.
2. museums 행 삭제(참조가 다 사라졌으므로 안전).

사용법:
    python pipeline/fix_foundation_museum_misclass.py            # 리포트만
    python pipeline/fix_foundation_museum_misclass.py --apply    # 실제 반영
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from db import get_connection
from provenance_extract import FOUNDATION_RE, KNOWN_MUSEUM_FOUNDATIONS

DOCS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "docs"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Foundation 유령 museums 행 정리")
    parser.add_argument("--apply", action="store_true", help="실제 DB 반영")
    parser.add_argument("--sample", type=int, default=30, help="리포트에 출력할 행 수")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        select m.id, m.name from museums m
        left join museum_holdings h on h.museum_id = m.id
        where h.id is null
        """
    )
    ghost = cur.fetchall()
    targets = [
        (mid, name)
        for mid, name in ghost
        if FOUNDATION_RE.search(name) and name.strip().lower() not in KNOWN_MUSEUM_FOUNDATIONS
    ]
    print(f"[fix_foundation_museum] 소장품 0건 museums {len(ghost)}건 중 정리 대상 {len(targets)}건")

    for mid, name in targets[: args.sample]:
        print(f"  {mid}: {name!r}")
    if len(targets) > args.sample:
        print(f"  ... 외 {len(targets) - args.sample}건 더 있음")

    if not args.apply:
        print("\n[fix_foundation_museum] --apply 없이 리포트만 실행함 (DB 변경 없음)")
        return

    # 삭제 전 롤백용 전체 대상 덤프 (2026-09-08 institute/academy 스크립트 지적 반영,
    # 같은 패턴의 이 스크립트에도 소급 적용).
    log_path = os.path.join(
        DOCS_DIR, f"museums_foundation_삭제대상_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump([{"id": str(mid), "name": name} for mid, name in targets], f, ensure_ascii=False, indent=2)
    print(f"[fix_foundation_museum] 삭제 전 전체 대상({len(targets)}건) 로그 저장: {log_path}")

    total_museums_deleted = 0
    total_records_reconnected = 0
    for i, (mid, name) in enumerate(targets, 1):
        for attempt in range(3):
            try:
                cur.execute(
                    "select id from collectors where lower(name) = %s limit 1", (name.lower(),)
                )
                row = cur.fetchone()
                if row:
                    collector_id = row[0]
                else:
                    cur.execute(
                        "insert into collectors (name, is_institution) values (%s, true) returning id",
                        (name,),
                    )
                    collector_id = cur.fetchone()[0]

                cur.execute(
                    "update provenance_records set owner_type = 'collector', "
                    "owner_collector_id = %s, owner_museum_id = null where owner_museum_id = %s",
                    (collector_id, mid),
                )
                n = cur.rowcount
                cur.execute("delete from museums where id = %s", (mid,))
                conn.commit()
                total_museums_deleted += 1
                total_records_reconnected += n
                break
            except Exception as e:
                conn.rollback()
                if attempt == 2:
                    print(f"  실패(재시도 초과): {mid} ({name!r}) — {e}")
                else:
                    print(f"  재시도 {attempt + 1}: {mid} ({name!r}) — {e}")
        if i % 200 == 0:
            print(f"  ... 진행 {i}/{len(targets)}")

    print(
        f"\n[fix_foundation_museum] 완료 — museums 삭제 {total_museums_deleted}건, "
        f"provenance_records 재연결 {total_records_reconnected}건"
    )


if __name__ == "__main__":
    main()
