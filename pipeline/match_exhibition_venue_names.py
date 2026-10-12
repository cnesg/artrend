"""R5 후속(2) — venue_name만 있고 museum_id/gallery_id가 둘 다 NULL인 exhibitions를
기존 museums/galleries에 연결.

대상: R4(Wikidata 전시)·갤러리 전시 등에서 기관/갤러리 이름을 텍스트로만
저장하고 정본 매칭을 안 한 행. **대소문자 무시 정확 일치만** 허용(부분
일치·유사도 매칭 금지 — 메인 지시). museums는 name/name_en 둘 다 후보,
galleries는 로스터(gallery_representations에 최소 1건 있는) 93곳만 후보로
쓴다 — 로스터 없는 갤러리는 R2/R5 스코프 밖이라 오매칭 위험이 더 큼.

Wikidata 한국어 라벨('취리히 미술관' 등)이 이 방식으로 안 붙는 것은
정상(원문 기관명과 한국어 번역 라벨이 문자열로 다름) — 메인이 QID 경로로
별도 처리 중이므로 이 스크립트는 건드리지 않는다.

사용법:
    python pipeline/match_exhibition_venue_names.py            # 리포트만
    python pipeline/match_exhibition_venue_names.py --apply     # 실제 반영
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from db import get_connection  # noqa: E402

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "logs"


PAREN_RE = re.compile(r"^(.*?)\s*\(([^()]+)\)\s*$")


def name_keys(name: str) -> list[str]:
    """이름 문자열 자체(정확 일치)와, "한글이름 (English)" 관례를 따르는 경우
    괄호 안/밖 두 조각도 각각 정확 일치 키로 추가한다(museums/galleries 양쪽에
    실제로 쓰이는 표기 관례 — 부분/유사도 매칭이 아니라 구조화된 이표기 필드
    그대로를 키로 쓰는 것). "括호 안 = 영문", "괄호 밖 = 한글/현지어" 순서만
    지원(그 반대는 이 데이터에 없음)."""
    name = name.strip()
    keys = [name.lower()]
    m = PAREN_RE.match(name)
    if m:
        outside, inside = m.group(1).strip(), m.group(2).strip()
        if outside:
            keys.append(outside.lower())
        if inside:
            keys.append(inside.lower())
    return keys


def build_museum_map(cur) -> dict[str, str]:
    cur.execute("select id, name, name_en from museums")
    m: dict[str, str] = {}
    for mid, name, name_en in cur.fetchall():
        for n in (name, name_en):
            if n and n.strip():
                for k in name_keys(n):
                    m.setdefault(k, str(mid))
    return m


def build_gallery_map(cur) -> dict[str, str]:
    cur.execute(
        """
        select g.id, g.name
        from galleries g
        where g.id in (select distinct gallery_id from gallery_representations)
        """
    )
    m: dict[str, str] = {}
    for gid, name in cur.fetchall():
        if name and name.strip():
            for k in name_keys(name):
                m.setdefault(k, str(gid))
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    museum_map = build_museum_map(cur)
    gallery_map = build_gallery_map(cur)

    cur.execute(
        """
        select id, venue_name from exhibitions
        where museum_id is null and gallery_id is null
          and venue_name is not null and trim(venue_name) != ''
        """
    )
    rows = cur.fetchall()

    matched_museum = []
    matched_gallery = []
    for eid, venue_name in rows:
        key = venue_name.strip().lower()
        if key in museum_map:
            matched_museum.append({"id": str(eid), "venue_name": venue_name, "museum_id": museum_map[key]})
        elif key in gallery_map:
            matched_gallery.append({"id": str(eid), "venue_name": venue_name, "gallery_id": gallery_map[key]})

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_candidates": len(rows),
        "matched_museum": len(matched_museum),
        "matched_gallery": len(matched_gallery),
        "unmatched": len(rows) - len(matched_museum) - len(matched_gallery),
        "sample_museum_matches": matched_museum[:20],
        "sample_gallery_matches": matched_gallery[:20],
        "top_unmatched_venue_names": [],
    }

    matched_ids = {r["id"] for r in matched_museum} | {r["id"] for r in matched_gallery}
    unmatched_counter = Counter(vn for eid, vn in rows if str(eid) not in matched_ids)
    report["top_unmatched_venue_names"] = unmatched_counter.most_common(20)

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DOCS_DIR / f"전시_venue매칭_리포트_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[match_exhibition_venue_names] 후보 {len(rows)}건 — museum 매칭 {len(matched_museum)}, gallery 매칭 {len(matched_gallery)}, 미매칭 {report['unmatched']}")
    print(f"[match_exhibition_venue_names] 리포트: {report_path}")

    if not args.apply:
        print("[match_exhibition_venue_names] dry-run — --apply로 실제 반영")
        return

    updated = 0
    for r in matched_museum:
        cur.execute(
            "update exhibitions set museum_id = %s, venue_kind = 'museum' where id = %s and museum_id is null and gallery_id is null",
            (r["museum_id"], r["id"]),
        )
        updated += cur.rowcount
    for r in matched_gallery:
        cur.execute(
            "update exhibitions set gallery_id = %s, venue_kind = 'gallery' where id = %s and museum_id is null and gallery_id is null",
            (r["gallery_id"], r["id"]),
        )
        updated += cur.rowcount

    conn.commit()
    print(f"[match_exhibition_venue_names] 적용 완료 — {updated}건 연결")


if __name__ == "__main__":
    main()
