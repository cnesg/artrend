"""R5 후속(1) — 기관 전시 제목의 "기관명 접두 + 《》/«» 전체감싸기" 정정.

GMoMA(경기도미술관) 전시 제목이 "경기도미술관 《그림이 된 벽 …》"처럼
기관명 접두사 뒤에 남은 텍스트 전체가 《 》/« »로 감싸인 채 들어온 사례가
다수 확인됨(institution_exhibitions_load.py는 raw title을 그대로 저장하므로
원본 사이트 표기를 이어받음). 접두사+전체감싸기 두 조건을 모두 만족하는
행만 정정한다 — "MMCA 현대차 시리즈 2022: 최우람 - 작은 방주"처럼 기관명이
실제 공식 전시명의 일부인 경우(괄호로 전체를 감싸지 않음)는 건드리지 않는다
(메인 지시 "같은 패턴이 있으면" = 접두사+전체감싸기 조합만).

정정 후 제목이 기존 다른 행과 (url, title, start_date) 유니크 인덱스에서
충돌하면: 기존 행을 정본으로 유지, 이 행의 exhibition_artists 링크를
정본으로 옮긴 뒤(중복은 무시) 이 행을 삭제.

사용법:
    python pipeline/fix_institution_title_prefix.py            # 리포트만
    python pipeline/fix_institution_title_prefix.py --apply     # 실제 반영
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from db import get_connection  # noqa: E402

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "logs"

# museum_id -> 제거 대상 접두사 목록 (긴 것부터, 같은 museum에 여러 표기 존재)
PREFIXES = {
    "2cb82827-c5f0-43ee-911b-ba05554211a3": ["국립현대미술관", "MMCA"],  # MMCA
    "08637076-4e8c-484a-a899-e2ad2f2f796f": ["부산시립미술관"],  # Busan Museum of Art
    "224e8433-02f6-4401-90a3-0e6dda67f427": ["경기도미술관"],  # GMoMA
}

BRACKET_RE = re.compile(r"^[《«](.+)[》»]$")


def compute_new_title(title: str, museum_id: str) -> str | None:
    for prefix in PREFIXES.get(museum_id, []):
        if title.startswith(prefix):
            rest = title[len(prefix):].strip()
            m = BRACKET_RE.match(rest)
            if m:
                new_title = m.group(1).strip()
                if new_title and new_title != title:
                    return new_title
            break
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "select id, title, museum_id, url, start_date from exhibitions where museum_id = any(%s::uuid[])",
        (list(PREFIXES.keys()),),
    )
    rows = cur.fetchall()

    changes = []
    for eid, title, museum_id, url, start_date in rows:
        new_title = compute_new_title(title, str(museum_id))
        if new_title is None:
            continue
        changes.append(
            {
                "id": str(eid),
                "old_title": title,
                "new_title": new_title,
                "museum_id": str(museum_id),
                "url": url,
                "start_date": str(start_date) if start_date else None,
            }
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_scanned": len(rows),
        "total_changes": len(changes),
        "samples": changes[:30],
    }
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DOCS_DIR / f"기관전시_제목정정_리포트_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[fix_institution_title_prefix] 스캔 {len(rows)}건, 정정 대상 {len(changes)}건")
    print(f"[fix_institution_title_prefix] 리포트: {report_path}")

    if not args.apply:
        print("[fix_institution_title_prefix] dry-run — --apply로 실제 반영")
        return

    updated = 0
    merged = 0
    links_moved = 0
    for c in changes:
        eid = c["id"]
        new_title = c["new_title"]

        # 정정 후 다른 행과 유니크 인덱스 충돌하는지 확인
        cur.execute(
            """
            select id from exhibitions
            where coalesce(url,'') = coalesce(%s,'')
              and title = %s
              and coalesce(start_date, date '0001-01-01') = coalesce(%s::date, date '0001-01-01')
              and id != %s
            """,
            (c["url"], new_title, c["start_date"], eid),
        )
        collision = cur.fetchone()

        if collision is None:
            cur.execute("update exhibitions set title = %s where id = %s", (new_title, eid))
            updated += 1
        else:
            target_id = str(collision[0])
            cur.execute(
                "select artist_id, role from exhibition_artists where exhibition_id = %s",
                (eid,),
            )
            for artist_id, role in cur.fetchall():
                cur.execute(
                    """
                    insert into exhibition_artists (exhibition_id, artist_id, role)
                    values (%s, %s, %s)
                    on conflict (exhibition_id, artist_id) do nothing
                    """,
                    (target_id, artist_id, role),
                )
                links_moved += cur.rowcount
            cur.execute("delete from exhibitions where id = %s", (eid,))
            merged += 1

    conn.commit()
    print(
        f"[fix_institution_title_prefix] 적용 완료 — 제목 정정 {updated}건, "
        f"중복 병합(기존 행 유지·삭제) {merged}건, 옮긴 exhibition_artists 링크 {links_moved}건"
    )


if __name__ == "__main__":
    main()
