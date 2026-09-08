"""Barnes Foundation "; "로 이어붙은 다중 작가 필드 백필.

Barnes API의 "people" 필드는 공저자가 있으면 "이름1 ; 이름2" 형태로 이어
붙여 반환한다(Met "|" 필드와 동일 컨벤션, 소규모 — 36건). `pipeline/barnes.py`
는 이미 첫 번째만 취하도록 수정 완료(재발 방지) — 이 스크립트는 기존 barnes
소스 artists 36건을 같은 규칙으로 백필한다.

사용법:
    python pipeline/fix_barnes_multiartist_dup_artists.py            # 리포트만
    python pipeline/fix_barnes_multiartist_dup_artists.py --apply    # 실제 반영
"""
from __future__ import annotations

import argparse
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from db import get_connection


def main() -> None:
    parser = argparse.ArgumentParser(description="Barnes 다중작가 필드 백필")
    parser.add_argument("--apply", action="store_true", help="실제 DB 반영")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "select a.id, a.name from artists a join sources s on a.source_id = s.id "
        "where s.site_name = 'barnes' and a.name like '%;%'"
    )
    rows = cur.fetchall()
    print(f"[fix_barnes] barnes 소스 다중작가 행 {len(rows)}건")

    plan = []
    for pid, name in rows:
        primary = name.split(";")[0].strip()
        if primary and primary != name:
            plan.append((pid, name, primary))

    cur.execute("select id, name from artists")
    by_lower = {n.lower(): i for i, n in cur.fetchall()}

    for pid, name, primary in plan:
        canonical = by_lower.get(primary.lower())
        tag = f"-> 재연결({canonical})" if canonical and canonical != pid else "-> in-place"
        print(f"  {name!r} => {primary!r} {tag}")

    if not args.apply:
        print("\n[fix_barnes] --apply 없이 리포트만 실행함 (DB 변경 없음)")
        return

    reconnected = 0
    fixed = 0
    for pid, name, primary in plan:
        canonical = by_lower.get(primary.lower())
        for attempt in range(3):
            try:
                if canonical and canonical != pid:
                    cur.execute(
                        "update artworks set artist_id = %s where artist_id = %s",
                        (canonical, pid),
                    )
                    cur.execute(
                        "update gallery_representations set artist_id = %s where artist_id = %s",
                        (canonical, pid),
                    )
                    cur.execute("delete from artists where id = %s", (pid,))
                    reconnected += 1
                else:
                    cur.execute(
                        "update artists set name = %s, updated_at = now() where id = %s",
                        (primary, pid),
                    )
                    by_lower[primary.lower()] = pid
                    fixed += 1
                conn.commit()
                break
            except Exception as e:
                conn.rollback()
                if attempt == 2:
                    print(f"  실패(재시도 초과): {pid} ({name!r}) — {e}")
                else:
                    print(f"  재시도 {attempt + 1}: {pid} ({name!r}) — {e}")

    print(f"\n[fix_barnes] 완료 — in-place 정정 {fixed}건, 재연결(삭제) {reconnected}건")


if __name__ == "__main__":
    main()
