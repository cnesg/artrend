"""sources.license_note 백필 — 2026-09-15 작업분담 §W6

site_name 단위로 UPDATE한다. 근거는 각 crawlers/<site>.py 상단 docstring +
docs/크롤러현황.md를 읽고 정리했다(아래 SITE_LICENSE_NOTES / PREFIX_LICENSE_NOTES).
site_name이 정확히 일치하거나(우선) 접두어(wikidata_*, gallery_*)가 일치하면 그 문구를,
둘 다 못 찾으면 'unverified (2026-09-15)'를 채우고 목록을 리포트에 남긴다
(--apply 후 메인에 unverified 목록 보고).

**기본은 dry-run(site_name별 적용 문구 리포트)이며, --apply 없이는 UPDATE하지 않는다.**
idempotent — license_note가 이미 채워진 행은 덮어쓰지 않는다(재실행 시 대상 0건).

사용법:
    python pipeline/backfill_source_license.py              # dry-run, 리포트 JSON 저장
    python pipeline/backfill_source_license.py --apply       # 실제 UPDATE
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path(__file__).parent / ".env")

from db import get_connection  # noqa: E402

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "logs"

# site_name 정확 일치 — crawlers/<site>.py docstring 근거 (2026-09-15 확인)
SITE_LICENSE_NOTES: dict[str, str] = {
    "met": "CC0 (github.com/metmuseum/openaccess), 인증 불필요",
    "aic": "Art Institute of Chicago Open Access API, CC0",
    "cleveland": "Cleveland Museum of Art Open Access API, CC0",
    "nga": "CC0 (github.com/NationalGalleryOfArt/opendata), 인증 불필요",
    "smithsonian": "Smithsonian Open Access API, CC0",
    "moma": "CC0 (github.com/MuseumofModernArt/collection), 인증 불필요",
    "tate": "CC0(비상업적 재사용 조건부, 저장소 LICENCE 파일 참고) — github.com/tategallery/collection",
    "smk": "SMK(덴마크 국립미술관) Open Data API — 인증키 불필요/무료, 크롤러 docstring엔 명시적 라이선스명 없음",
    "vam": "V&A Open API — Open Government Licence, 인증 불필요",
    "getty": "Getty REST API — CC0, 인증 불필요",
    "getty_provenance_sales": "Getty Research Institute GitHub(thegetty/provenance-index-csv) — CC0 1.0 Universal",
    "rijksmuseum": "Rijksmuseum 공개 OAI-PMH 2.0 엔드포인트(data.rijksmuseum.nl/oai) — 가입/키 불필요, 크롤러 docstring엔 명시적 라이선스명 없음",
    "europeana": "Europeana Search API, reusability:open 필터로 수집(퍼블릭도메인/오픈라이선스 항목만) — 항목별 실제 라이선스는 상이할 수 있음",
    "mmca": "국립현대미술관 내부 JSON 엔드포인트(AjaxCollectionsList.do) — robots.txt 허용 확인, 명시적 재사용 라이선스 고지 없음. 이미지 저작권은 레코드별 copyrightAllowYn 필드로 개별 확인 필요",
    "japan_museums": "일본 독립행정법인 국립미술관 통합검색(search.artmuseums.go.jp) — robots.txt 없음(404), 저작권은 작품별 Rights Statement로 개별 확인 필요. 메타데이터만 수집, 이미지 파일 다운로드 안 함",
    "busan_art_museum": "부산시립미술관 소장품 검색 페이지 — robots.txt 확인(2026-09-08) 목록 경로 허용, 명시적 재사용 라이선스 고지 없음",
    "sema": "서울시립미술관 소장품 검색 페이지 — robots.txt 확인(2026-09-08) 목록/상세 경로 허용, 명시적 재사용 라이선스 고지 없음. 이미지는 URL만 저장(다운로드 안 함)",
    "gmoma": "경기도미술관 개별 작품 페이지 — robots.txt 확인(2026-09-08) /collections/* 허용, 명시적 재사용 라이선스 고지 없음",
    "leeum": "리움미술관 내부 JSON 엔드포인트 — robots.txt 없음(404), ToS 스크래핑 금지 문구 없음 확인(2026-09-08), 명시적 재사용 라이선스 고지 없음",
    "barnes": "반스재단 /api/objects/<id> 엔드포인트 — robots.txt 없음(404), 명시적 재사용 라이선스 고지 없음",
    "bonhams": "Bonhams 경매 결과, Next.js SSR 임베디드 JSON — robots.txt/ToS 검토 후 크롤링 차단 시그널 없음 확인(2026-09-03). 상업 경매사 콘텐츠로 오픈라이선스 아님, 수집 허용 판단 근거만 확인된 것",
    "auctions_wikidata": "Wikidata SPARQL 엔드포인트만 사용 — Wikidata 데이터 자체는 CC0",
    "walters": "크롤러 파일 없음(레거시/수동 적재로 추정) — 근거 미확인",
    "mia": "크롤러 파일 없음(레거시/수동 적재로 추정) — 근거 미확인. artworks 이중적재 정리 대상이었던 소스(§W1)",
}

# site_name 접두어 일치 — 개별 파일이 아니라 공용 크롤러(wikidata_museums.py/galleries.py)가
# 만들어내는 동적 site_name들
PREFIX_LICENSE_NOTES: list[tuple[str, str]] = [
    (
        "wikidata_",
        "Wikidata SPARQL(P195 collection 속성 필터, wikidata_museums.py) — Wikidata 데이터 자체는 CC0(Wikidata:Licensing)",
    ),
    (
        "gallery_",
        "갤러리 작가 로스터 페이지(galleries.py) — 사이트별 robots.txt 개별 확인(2026-09-02) 후 일반 콘텐츠 경로만 수집. 작가 로스터/관계 데이터로 명시적 재사용 라이선스 없음(갤러리 자체 저작물)",
    ),
]


def resolve_note(site_name: str) -> str:
    if site_name in SITE_LICENSE_NOTES:
        return SITE_LICENSE_NOTES[site_name]
    for prefix, note in PREFIX_LICENSE_NOTES:
        if site_name.startswith(prefix):
            return note
    return "unverified (2026-09-15)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 UPDATE한다")
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "select site_name, count(*) from sources where license_note is null group by site_name order by count(*) desc"
    )
    rows = cur.fetchall()

    plan = []
    unverified_sites = []
    total_rows = 0
    for site_name, cnt in rows:
        note = resolve_note(site_name)
        if note.startswith("unverified"):
            unverified_sites.append(site_name)
        plan.append({"site_name": site_name, "row_count": cnt, "license_note": note})
        total_rows += cnt

    print(f"[backfill_license] license_note NULL인 sources: {total_rows}건, {len(rows)}개 site_name")
    print(f"[backfill_license] 근거 못 찾아 unverified 처리될 site_name: {len(unverified_sites)}개")
    for s in unverified_sites:
        print(f"  - {s}")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_rows_to_update": total_rows,
        "site_count": len(rows),
        "unverified_sites": unverified_sites,
        "plan": plan,
    }
    out_path = DOCS_DIR / f"sources_license_백필_리포트_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[backfill_license] 상세 리포트 저장: {out_path}")

    if not args.apply:
        print("\n[backfill_license] dry-run — UPDATE 없음. --apply로 실행하면 실제 반영됩니다.")
        cur.close()
        conn.close()
        return

    updated_total = 0
    for item in plan:
        cur.execute(
            "update sources set license_note = %s where site_name = %s and license_note is null",
            (item["license_note"], item["site_name"]),
        )
        updated_total += cur.rowcount
    conn.commit()
    print(f"\n[backfill_license] {updated_total}건 UPDATE 완료")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
