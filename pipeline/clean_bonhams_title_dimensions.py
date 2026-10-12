"""Bonhams 작품 제목 끝에 뭉쳐 있는 치수(예: 'Still life 75 x 60cm', 'Femme au béret 16 1/8 x 13 in (41 x 33 cm) (Painted ...')를
artworks.dimensions 로 옮기고 제목에서 제거 (2026-09-16, 계획 P1-7 후속 / 메인 전용).

fix_bonhams_artist_titles.py 는 작가명 분리만 했고 치수는 제목에 남았다(12,438건). 규칙:
  - 제목에서 첫 치수 토큰(숫자[분수/소수] x 숫자 + cm/in/mm)부터 끝까지를 잘라 dimensions 로(비어 있을 때만 coalesce).
  - 잘린 뒤 남는 제목이 3자 미만이면 건드리지 않음. 원제는 description 이 비어 있으면 '[Bonhams 원제] ...'로 보존.
기본: 리포트(표본 30) → --apply. idempotent(치수 패턴이 남아 있는 행만 대상).
"""
from __future__ import annotations

import argparse
import re
import sys

from artist_merge_util import get_conn

sys.stdout.reconfigure(encoding="utf-8")
NUM = r"\d+(?:\s\d+/\d+|[.,]\d+)?"
DIM_RE = re.compile(rf"[\s,;(]*(?:each\s+|overall\s+|image\s+|sheet\s+)?{NUM}\s?(?:x|×|by)\s?{NUM}(?:\s?(?:x|×)\s?{NUM})?\s?(?:cm|in|mm)\b.*$", re.I)


def split(title: str) -> tuple[str, str] | None:
    m = DIM_RE.search(title)
    if not m:
        return None
    head, tail = title[:m.start()].strip(" ,;:-"), title[m.start():].strip(" ,;")
    head = re.sub(r"\s*(?:image|framed|unframed|plate|sheet|overall|each|the full sheet)\s*[:;,]?$", "", head, flags=re.I).strip(" ,;:-")
    if len(head) < 3:
        return None
    return head, tail


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        r"""select a.id::text, a.title, a.dimensions, a.description is null
            from artworks a join sources s on s.id = a.source_id
            where s.site_name = 'bonhams' and a.title ~ '\d+ ?(x|×|by) ?\d+ ?(cm|in|mm)'"""
    )
    rows = cur.fetchall()
    plan, skipped = [], 0
    for aid, title, dims, desc_empty in rows:
        r = split(title)
        if not r:
            skipped += 1
            continue
        head, tail = r
        plan.append((head, tail if not dims else None, f"[Bonhams 원제] {title}" if desc_empty else None, aid))
    print(f"대상 {len(rows)} → 정리 {len(plan)} / 보류(남는 제목 3자 미만·패턴 불일치) {skipped}")
    import random
    random.seed(1)
    for head, tail, _, _ in random.sample(plan, min(30, len(plan))):
        print(f"  '{head}'  ⟵  치수 '{(tail or '(기존 dimensions 유지)')[:60]}'")
    if not args.apply:
        print("--apply 없음: 리포트만")
        return
    for i in range(0, len(plan), 5000):
        cur.executemany(
            "update artworks set title = %s, dimensions = coalesce(dimensions, %s), description = coalesce(description, %s), updated_at = now() where id = %s",
            plan[i:i + 5000],
        )
        conn.commit()
    cur.execute(r"select count(*) from artworks a join sources s on s.id = a.source_id where s.site_name = 'bonhams' and a.title ~ '\d+ ?(x|×|by) ?\d+ ?(cm|in|mm)'")
    print("완료: 잔여 치수 포함 제목 =", cur.fetchone()[0])


if __name__ == "__main__":
    main()
