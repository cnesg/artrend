"""소장품(museum_holdings) 0건인 "Institute"/"Academy" 유령 museums 행 정리.

docs/정합성작업.md §7·§11에서 발견/기록된 잔여 항목 — foundation과 같은
근본 원인. `provenance_extract.py`의 `_classify_owner_type()`이
`\binstitute\b|\bacademy\b`를 항상 museum으로 분류해서 실제 소장 기관이
아닌 이름("Agnew to the Art Institute"류 크레딧라인 추출 오류, "American
Institute of Interior Designers"/"United States Military Academy"처럼
실존 단체지만 미술관이 아닌 경우)에도 museums 행이 만들어졌다. 검증
결과(2026-09-08) institute 이름 매칭 299건 중 288건, academy 이름 매칭
25건 중 21건이 소장품 0건 — 나머지(Art Institute of Chicago, Minneapolis
Institute of Art 등 11건 + Romanian Academy 등 4건)는 실제 소장품이 있어
정상. 분류 로직은 `INSTITUTE_ACADEMY_RE` + `KNOWN_MUSEUM_INSTITUTES`
화이트리스트로 이미 수정 완료 — 이 스크립트는 기존에 잘못 만들어진
museums 행을 같은 기준으로 백필한다.

방법: `fix_foundation_museum_misclass.py`와 동일 — 소장품 0건이고 이름이
`INSTITUTE_ACADEMY_RE`에 매칭하며 `KNOWN_MUSEUM_INSTITUTES`에 없는
museums 행을 collectors(is_institution=true)로 재연결 후 museums 행 삭제.

사용법:
    python pipeline/fix_institute_academy_museum_misclass.py            # 리포트만
    python pipeline/fix_institute_academy_museum_misclass.py --apply    # 실제 반영
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
from provenance_extract import INSTITUTE_ACADEMY_RE, KNOWN_MUSEUM_INSTITUTES

DOCS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "docs"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Institute/Academy 유령 museums 행 정리")
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
        if INSTITUTE_ACADEMY_RE.search(name) and name.strip().lower() not in KNOWN_MUSEUM_INSTITUTES
    ]
    print(f"[fix_institute_academy_museum] 소장품 0건 museums {len(ghost)}건 중 정리 대상 {len(targets)}건")

    for mid, name in targets[: args.sample]:
        print(f"  {mid}: {name!r}")
    if len(targets) > args.sample:
        print(f"  ... 외 {len(targets) - args.sample}건 더 있음")

    if not args.apply:
        print("\n[fix_institute_academy_museum] --apply 없이 리포트만 실행함 (DB 변경 없음)")
        return

    # 삭제 전 롤백용 전체 대상 덤프 — 콘솔 샘플만으로는 사후 재현이 안 됨
    # (2026-09-08, 이 스크립트의 첫 --apply 실행 때 이 로그가 없어서 지적받음).
    log_path = os.path.join(
        DOCS_DIR, f"museums_institute_academy_삭제대상_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump([{"id": str(mid), "name": name} for mid, name in targets], f, ensure_ascii=False, indent=2)
    print(f"[fix_institute_academy_museum] 삭제 전 전체 대상({len(targets)}건) 로그 저장: {log_path}")

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
        f"\n[fix_institute_academy_museum] 완료 — museums 삭제 {total_museums_deleted}건, "
        f"provenance_records 재연결 {total_records_reconnected}건"
    )


if __name__ == "__main__":
    main()
