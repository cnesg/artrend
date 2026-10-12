"""MoMA 콤마 다중작가 오염 artists 백필 (2026-09-15 작업분담 §M4, 진단 §3-2-3).

`pipeline/moma.py`가 "Pablo Picasso, Ilia Zdanevich" / nationality "Spanish) (Georgian" 처럼
병렬 나열 필드를 안 쪼개고 저장했던 행(1,126건)을 Met "|" 백필과 같은 방식으로 정리한다.
판정 규칙(보수적): name을 ", "로 나눈 토큰 수 == nationality를 ") ("로 나눈 그룹 수 (>= 2).
  → 첫 토큰이 주작가. 첫 토큰이 익명 표기(Various Artists/Unknown artist/Unidentified ...)면
    다음 토큰을 쓰지 않고 행을 그대로 두되 entity_kind 분류(classify_artist_entity_kind.py)에 맡긴다.
처리: 정식 이름의 기존 행이 있으면 재연결 후 삭제, 없으면 in-place 정정(같은 정식 이름 그룹은 1건만).
기본 리포트, --apply 시 반영. idempotent.
"""
from __future__ import annotations

import argparse
import re
import sys

from artist_merge_util import fill_missing_meta, get_conn, norm_exact, relink_and_delete

sys.stdout.reconfigure(encoding="utf-8")

ANON_FIRST = re.compile(r"^(various artists?|unknown|unidentified|anonymous|unknown artist|unidentified photographer)\b", re.I)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """select a.id::text, a.name, a.nationality, a.birth_year, a.death_year, a.bio
           from artists a join sources s on s.id = a.source_id
           where s.site_name = 'moma' and a.name like '%, %' and a.nationality like '%) (%'"""
    )
    rows = cur.fetchall()
    cur.execute("select id::text, name from artists")
    by_key: dict[str, str] = {}
    for aid, name in cur.fetchall():
        by_key.setdefault(norm_exact(name), aid)

    plan_relink, plan_inplace, skipped_anon, skipped_mismatch = [], [], [], []
    inplace_taken: dict[str, str] = {}
    for aid, name, nat, by, dy, bio in rows:
        toks = [t.strip() for t in name.split(", ") if t.strip()]
        nats = nat.split(") (")
        # nationality에 ") ("가 있는 행은 MoMA 다중작가 병렬 나열이 확실(다른 소스엔 이 패턴 없음, audit5).
        # 빈 그룹 "()"이 strip으로 사라져 토큰 수가 안 맞는 경우가 있어 개수 일치는 요구하지 않는다.
        if len(toks) < 2 or len(nats) < 2:
            skipped_mismatch.append(name)
            continue
        first = toks[0]
        if ANON_FIRST.match(first):
            skipped_anon.append(name)
            continue
        key = norm_exact(first)
        first_nat = nats[0].strip("() ") or None
        first_bio = (bio or "").split(") (")[0].strip("() ") or None if bio else None
        if key in by_key and by_key[key] != aid:
            plan_relink.append((aid, by_key[key], name, first))
        elif key in inplace_taken:
            plan_relink.append((aid, inplace_taken[key], name, first))
        else:
            inplace_taken[key] = aid
            plan_inplace.append((aid, name, first, first_nat, first_bio))

    print(f"대상 {len(rows)} → 재연결 {len(plan_relink)} / in-place {len(plan_inplace)} / 익명 선두 스킵 {len(skipped_anon)} / 토큰수 불일치 스킵 {len(skipped_mismatch)}")
    for x in plan_relink[:8]:
        print("  relink:", x[2][:60], "→", x[3])
    for x in plan_inplace[:8]:
        print("  inplace:", x[1][:60], "→", x[2], x[3])
    for x in skipped_mismatch[:5]:
        print("  mismatch:", x[:80])
    if not args.apply:
        print("--apply 없음: 리포트만")
        return

    n = 0
    for aid, cid, _, _ in plan_relink:
        fill_missing_meta(cur, cid, aid)
        n += relink_and_delete(cur, aid, cid)
        conn.commit()
    for aid, _, first, first_nat, first_bio in plan_inplace:
        cur.execute(
            "update artists set name = %s, nationality = %s, bio = %s, updated_at = now() where id = %s",
            (first, first_nat, first_bio, aid),
        )
    conn.commit()
    print(f"완료: 재연결 {n}건, in-place {len(plan_inplace)}건")


if __name__ == "__main__":
    main()
