"""R2 후속 정제 — 언론보도/서지 인용이 전시로 오탐 적재된 행 제거.

gallery_exhibitions_from_raw.py(2026-09-15)가 만든 exhibitions/exhibition_artists
중, CV 페이지의 "Selected Press"/"Bibliography" 섹션이 STOP_HEADING에 걸리지
않고 넘어가 매체명·기사 인용이 "전시"로 캡처된 사례가 있다(pace/kukje 표본 확인,
2026-09-15 작업분담 로그). 신규 크롤 없이 기존 적재분만 규칙 매칭으로 골라
report→검수→apply로 삭제한다.

판정 규칙 (title 또는 venue_name에 매칭되면 오탐):
- 매체명 목록(영문/국문 미술지·언론사)
- 서지 인용 표지: vol./no./pp./p./ISBN/Interview/Review(ed)

대상은 gallery_exhibitions_from_raw.py가 실제 적재한 13개 갤러리로 한정한다
(그 외 exhibitions는 R2 소관 밖 — 잘못 건드리지 않도록 gallery_id로 스코프).

사용법:
    python pipeline/clean_gallery_exhibitions_press_noise.py            # 리포트만
    python pipeline/clean_gallery_exhibitions_press_noise.py --apply     # 실제 삭제
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
from galleries import GALLERY_INFO  # noqa: E402

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "logs"

R2_GALLERY_KEYS = [
    "kukje", "pace", "lehmannmaupin", "perrotin", "gladstone", "alminerech",
    "mennour", "vielmetter", "zenox", "gallerykiche", "taronasu", "takaishii",
    "simon", "pyo",
]

MEDIA_OUTLETS = [
    "Artforum", "Frieze", "ARTnews", "Art in America", "The New York Times",
    "New York Times", "NYTimes", "New Yorker", "Ocula", "Hyperallergic",
    "Artnet", "The Art Newspaper", "Wallpaper", "W Magazine", "Vogue",
    "Financial Times", "The Guardian", "Elephant", "Whitewall", "Cultured",
    "Interview Magazine", "Apollo Magazine", "The Brooklyn Rail", "Artsy",
    "월간미술", "아트인컬처", "헤럴드경제", "경향신문", "한국경제", "한국일보",
    "중앙일보", "조선일보", "동아일보", "뉴시스", "연합뉴스", "이데일리",
    "파이낸셜뉴스", "매일경제", "서울경제", "노블레스", "여성조선",
]
MEDIA_RE = re.compile("|".join(re.escape(m) for m in MEDIA_OUTLETS), re.I)
CITATION_RE = re.compile(
    r"\bvol\.\s*\d|\bno\.\s*\d|\bpp?\.\s*\d|ISBN|\binterview(ed)?\b|\breview(ed)?\b",
    re.I,
)


def is_press_noise(title: str | None, venue_name: str | None) -> bool:
    text = f"{title or ''} {venue_name or ''}"
    return bool(MEDIA_RE.search(text) or CITATION_RE.search(text))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    gallery_display_names = [GALLERY_INFO[k][0] for k in R2_GALLERY_KEYS if k in GALLERY_INFO]
    cur.execute("select id, name from galleries where name = any(%s)", (gallery_display_names,))
    gallery_ids = [str(r[0]) for r in cur.fetchall()]

    # exhibitions.gallery_id는 venue 매칭 결과(자기 갤러리/다른 갤러리/None)일 뿐이라
    # R2가 실제로 적재한 행을 다 잡으려면 exhibition_artists -> artists ->
    # gallery_representations 경로로 "이 13개 갤러리 로스터 작가가 걸린 전시"를 스코프한다.
    cur.execute(
        """
        select distinct e.id, e.title, e.venue_name, g.name
        from exhibitions e
        join exhibition_artists ea on ea.exhibition_id = e.id
        join gallery_representations gr on gr.artist_id = ea.artist_id
        join galleries g on g.id = gr.gallery_id
        where gr.gallery_id = any(%s::uuid[])
        """,
        (gallery_ids,),
    )
    rows = cur.fetchall()

    flagged: list[tuple[str, str, str, str]] = []
    for exh_id, title, venue_name, gname in rows:
        if is_press_noise(title, venue_name):
            flagged.append((str(exh_id), title, venue_name, gname))

    by_gallery: dict[str, int] = {}
    for _, _, _, gname in flagged:
        by_gallery[gname] = by_gallery.get(gname, 0) + 1

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_exhibitions_scoped": len(rows),
        "flagged_count": len(flagged),
        "flagged_by_gallery": by_gallery,
        "samples": [
            {"title": t, "venue_name": v, "gallery": g}
            for _, t, v, g in flagged[:20]
        ],
    }
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DOCS_DIR / f"gallery_전시_언론오탐_리포트_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[clean_press_noise] 스코프 {len(rows)}건 중 오탐 {len(flagged)}건 ({len(flagged)/len(rows)*100:.1f}%)" if rows else "[clean_press_noise] 스코프 0건")
    for gname, cnt in sorted(by_gallery.items(), key=lambda x: -x[1]):
        print(f"  {gname}: {cnt}")
    print(f"[clean_press_noise] 리포트: {report_path}")

    if not args.apply:
        print("[clean_press_noise] dry-run — --apply로 실제 삭제")
        return

    ids = [fid for fid, _, _, _ in flagged]
    if ids:
        cur.execute("delete from exhibition_artists where exhibition_id = any(%s::uuid[])", (ids,))
        link_deleted = cur.rowcount
        cur.execute("delete from exhibitions where id = any(%s::uuid[])", (ids,))
        exh_deleted = cur.rowcount
        conn.commit()
        print(f"[clean_press_noise] 삭제 완료 — exhibitions {exh_deleted}건, exhibition_artists {link_deleted}건")
    else:
        print("[clean_press_noise] 삭제 대상 없음")


if __name__ == "__main__":
    main()
