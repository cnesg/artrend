"""artworks 테이블(2,650,769건)과 vault/artworks(2,561,885건) 사이 88,884건
차이의 원인 조사 — 읽기 전용, DB/파일 변경 없음.

방법: export_vault.py의 slugify()가 파일명에 `(id 앞8자리)`를 박아두므로,
DB artworks.id 앞8자리 집합과 vault/artworks/*.md 파일명에서 뽑은 id8
집합을 비교해 "DB엔 있지만 vault엔 없는" 누락분을 구하고, source_id/
created_at으로 그룹핑해 어떤 소스·시점 적재분이 아직 vault에 안 나갔는지
확인한다.
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter
from pathlib import Path

import psycopg2

sys.stdout.reconfigure(encoding="utf-8")

VAULT_ARTWORKS = Path(__file__).resolve().parent.parent / "vault" / "artworks"
ID8_RE = re.compile(r"\(([0-9a-fA-F]{8})\)\.md$")


def main() -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    print("[audit] vault/artworks 파일명 스캔 중...")
    vault_id8 = set()
    for path in VAULT_ARTWORKS.glob("*.md"):
        m = ID8_RE.search(path.name)
        if m:
            vault_id8.add(m.group(1).lower())
    print(f"[audit] vault 파일 {len(vault_id8)}건 id8 수집 완료")

    print("[audit] DB artworks 로드 중...")
    cur.execute(
        """
        select a.id, s.site_name, a.created_at
        from artworks a
        join sources s on s.id = a.source_id
        """
    )
    rows = cur.fetchall()
    print(f"[audit] DB artworks {len(rows)}건 로드 완료")

    missing_by_source: Counter = Counter()
    missing_by_date: Counter = Counter()
    total_by_source: Counter = Counter()
    missing_count = 0

    for aid, site_name, created_at in rows:
        id8 = str(aid).replace("-", "")[:8].lower()
        total_by_source[site_name] += 1
        if id8 not in vault_id8:
            missing_count += 1
            missing_by_source[site_name] += 1
            if created_at:
                missing_by_date[created_at.date().isoformat()] += 1

    print(f"\n[audit] DB에는 있지만 vault엔 없는 artworks: {missing_count}건\n")
    print("[audit] 소스별 누락 (site_name: 누락/전체):")
    for site_name, n in missing_by_source.most_common(30):
        print(f"  {site_name}: {n}/{total_by_source[site_name]}")

    print("\n[audit] created_at 날짜별 누락 상위 20:")
    for date, n in sorted(missing_by_date.items(), key=lambda x: -x[1])[:20]:
        print(f"  {date}: {n}건")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
