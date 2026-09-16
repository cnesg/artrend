"""R5 후속(2) — exhibitions 교차 중복 탐지 (리포트 전용, 삭제/병합 안 함).

R2(갤러리 raw_html 파싱)·R4(Wikidata 사건)·R5(MMCA/부산/GMoMA 기관 페이지)가
서로 다른 url로 같은 전시를 각자 적재했을 가능성을 점검한다. (정규화 제목,
start_date 연도) 기준으로 그룹핑해 source가 2개 이상 섞인 그룹만 추린다.
병합 여부는 메인이 이 리포트를 보고 판단 — 이 스크립트는 삭제/업데이트를
전혀 하지 않는다.

source 태그는 url 패턴으로 근사 판정(정확한 출처 컬럼이 없어서):
  - wikidata.org 포함            -> wikidata (R4)
  - mmca.go.kr / art.busan.go.kr / gmoma.ggcf.kr 포함 -> institution (R5)
  - 그 외 gallery_id 있음         -> gallery_raw (R2)
  - 그 외                        -> other

사용법:
    python pipeline/find_exhibition_cross_duplicates.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from db import get_connection  # noqa: E402

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "logs"

WS_RE = re.compile(r"\s+")
STRIP_CHARS = "《》«»\"'“”<>「」『』"


def normalize_title(title: str) -> str:
    t = title.strip().lower()
    t = "".join(c for c in t if c not in STRIP_CHARS)
    t = WS_RE.sub(" ", t).strip()
    return t


def source_tag(url: str | None, gallery_id) -> str:
    if url:
        u = url.lower()
        if "wikidata.org" in u:
            return "wikidata_R4"
        if "mmca.go.kr" in u:
            return "mmca_R5"
        if "art.busan.go.kr" in u:
            return "busan_R5"
        if "gmoma.ggcf.kr" in u:
            return "gmoma_R5"
    if gallery_id:
        return "gallery_raw_R2"
    return "other"


def main():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "select id, title, start_date, url, gallery_id, museum_id, venue_name from exhibitions"
    )
    rows = cur.fetchall()

    groups: dict[tuple[str, int | None], list[dict]] = defaultdict(list)
    for eid, title, start_date, url, gallery_id, museum_id, venue_name in rows:
        norm = normalize_title(title)
        if not norm:
            continue
        year = start_date.year if start_date else None
        groups[(norm, year)].append(
            {
                "id": str(eid),
                "title": title,
                "start_date": str(start_date) if start_date else None,
                "url": url,
                "venue_name": venue_name,
                "source": source_tag(url, gallery_id),
            }
        )

    cross_groups = []
    for (norm, year), items in groups.items():
        sources = {it["source"] for it in items}
        if len(items) >= 2 and len(sources) >= 2:
            cross_groups.append(
                {
                    "normalized_title": norm,
                    "year": year,
                    "row_count": len(items),
                    "sources": sorted(sources),
                    "items": items,
                }
            )

    cross_groups.sort(key=lambda g: -g["row_count"])

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_exhibitions_scanned": len(rows),
        "total_groups": len(groups),
        "cross_source_dup_group_count": len(cross_groups),
        "cross_source_dup_row_count": sum(g["row_count"] for g in cross_groups),
        "samples": cross_groups[:30],
    }

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DOCS_DIR / f"전시_교차중복_리포트_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[find_exhibition_cross_duplicates] 스캔 {len(rows)}건, 그룹 {len(groups)}개")
    print(
        f"[find_exhibition_cross_duplicates] 교차 소스 중복 그룹 {len(cross_groups)}개 "
        f"(행 {report['cross_source_dup_row_count']}건) — 삭제 안 함, 리포트만"
    )
    print(f"[find_exhibition_cross_duplicates] 리포트: {report_path}")


if __name__ == "__main__":
    main()
