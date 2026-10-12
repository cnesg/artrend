"""갤러리 raw_html(작가 프로필 페이지)에서 전시이력 파싱 -> exhibitions/exhibition_artists 적재.

2026-09-15 작업분담 R2. 신규 웹 요청 없음 — 이미 수집된 crawlers/raw/gallery_<key>/
파일(93곳 중 raw_html이 비어있지 않은 87곳)만 사용한다.

갤러리마다 HTML 구조가 제각각이라 사이트별 파서 대신 범용 휴리스틱을 쓴다:
1. 텍스트 라인을 순회하며 "Solo/One-Artist Exhibitions", "Group Exhibitions",
   "개인전", "단체전" 헤딩을 만나면 role(solo/group)을 정하고 캡처 모드로 들어간다.
2. Education/Awards/Bibliography/Press/Collections 등 다른 헤딩을 만나면 캡처를 멈춘다.
3. 캡처 모드에서 `^(19|20)\\d{2}` 로 시작하는 줄이 새 항목의 시작 — 다음 연도줄이
   나올 때까지 이어지는 줄들을 한 항목으로 묶어 콤마 기준으로 title/venue/city를
   뽑는다. 콤마가 없으면(장소 언급 없음) 갤러리 자체 전시로 간주.
4. venue_name이 galleries.name/museums.name과 정확히 일치하면 그 기관으로 연결,
   실패하면 venue_kind='other' + venue_name 원문 보존.
5. 작가는 로스터 작가(raw 파일의 data["name"] -> artists 테이블, 대소문자 무시
   정확 일치)로만 연결한다 — 신규 artists 행 생성 안 함, 매칭 실패시 스킵.

idempotent: exhibitions에는 0009 마이그레이션의 유니크 인덱스
(coalesce(url,''), title, coalesce(start_date, '0001-01-01'))가 있어
ON CONFLICT DO NOTHING으로 재실행 안전.

사용법:
    python pipeline/gallery_exhibitions_from_raw.py               # 리포트만, DB 미변경
    python pipeline/gallery_exhibitions_from_raw.py --apply        # 실제 반영
    python pipeline/gallery_exhibitions_from_raw.py --exclude gladstone,pyo  # 특정 갤러리 스킵
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from db import get_connection  # noqa: E402
from galleries import GALLERY_INFO  # noqa: E402
from raw_iter import iter_records  # noqa: E402

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "logs"

YEAR_RE = re.compile(r"^(19|20)\d{2}\b")
YEAR_ONLY_RE = re.compile(r"^((19|20)\d{2})\.?$")
YEAR_PREFIX_RE = re.compile(r"^((19|20)\d{2})\b[.,:\s]*(.*)$")

SOLO_HEADING_RE = re.compile(
    r"^(solo|one[- ]artist|one[- ]person|개인전)\s*(exhibitions?|shows?)?$", re.I
)
GROUP_HEADING_RE = re.compile(r"^(group)\s*(exhibitions?|shows?)?$|^단체전$", re.I)
GENERIC_EXH_HEADING_RE = re.compile(
    r"^(selected\s+)?exhibitions?( history)?$|^전시\s*(이력)?$", re.I
)
STOP_HEADING_RE = re.compile(
    r"^(education|awards?|residenc|honors?|collections?|bibliography|"
    r"publications?|press|selected\s+(press|publications?|collections?|bibliography)|"
    r"about|biography|dates?|born|lives?\s+and\s+works?|contact|curatorial|"
    r"teaching|works?$|"
    r"언론\s*보도?|보도\s*자료?|출판물?|서지|문헌|수상\s*경력?|학력|약력|소장처?)\b",
    re.I,
)

# 2026-09-15 후속 정제(docs/작업분담_20260915.md R2) — pace/kukje 표본에서 발견된
# 언론보도·서지 인용 오탐(매체명·vol./no./pp./ISBN/Interview/Review 패턴)을 파싱
# 단계에서부터 차단한다. clean_gallery_exhibitions_press_noise.py의 규칙과 동일.
_MEDIA_OUTLETS = [
    "Artforum", "Frieze", "ARTnews", "Art in America", "The New York Times",
    "New York Times", "NYTimes", "New Yorker", "Ocula", "Hyperallergic",
    "Artnet", "The Art Newspaper", "Wallpaper", "W Magazine", "Vogue",
    "Financial Times", "The Guardian", "Elephant", "Whitewall", "Cultured",
    "Interview Magazine", "Apollo Magazine", "The Brooklyn Rail", "Artsy",
    "월간미술", "아트인컬처", "헤럴드경제", "경향신문", "한국경제", "한국일보",
    "중앙일보", "조선일보", "동아일보", "뉴시스", "연합뉴스", "이데일리",
    "파이낸셜뉴스", "매일경제", "서울경제", "노블레스", "여성조선",
]
PRESS_NOISE_RE = re.compile(
    "|".join(re.escape(m) for m in _MEDIA_OUTLETS)
    + r"|\bvol\.\s*\d|\bno\.\s*\d|\bpp?\.\s*\d|ISBN|\binterview(ed)?\b|\breview(ed)?\b",
    re.I,
)
# 헤딩으로 볼만한 줄: 60자 이하, 숫자 없음, 문장부호로 안 끝남
def _looks_like_heading(line: str) -> bool:
    if len(line) > 60:
        return False
    if re.search(r"\d", line):
        return False
    if line.endswith((".", ",", ";")):
        return False
    return True


DIMENSION_RE = re.compile(r"\d+[.,]?\d*\s*[x×]\s*\d+|\bcm\b|\bedition of\b", re.I)
MEDIUM_HINT_RE = re.compile(
    r"\b(acrylic|oil on|canvas|paper mounted|silkscreen|digital print|mounted on|"
    r"gesso|graphite|watercolou?r|c-print|archival pigment|inkjet)\b", re.I
)


def _has_upcoming_year(lines: list[str], start_idx: int, window: int = 5) -> bool:
    for j in range(start_idx + 1, min(start_idx + 1 + window, len(lines))):
        cand = lines[j]
        if not cand:
            continue
        if YEAR_ONLY_RE.match(cand) or YEAR_PREFIX_RE.match(cand):
            return True
        if SOLO_HEADING_RE.match(cand) or GROUP_HEADING_RE.match(cand):
            return True
        if _looks_like_heading(cand) and not YEAR_RE.match(cand):
            return False
    return False


def _extract_entries(raw_html: str) -> tuple[list[dict], list[str]]:
    """(entries, parse_fail_samples) 반환."""
    soup = BeautifulSoup(raw_html or "", "html.parser")
    text = soup.get_text("\n")
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    entries: list[dict] = []
    fail_samples: list[str] = []
    role = None
    block: list[str] = []
    block_year: str | None = None

    def flush():
        nonlocal block, block_year
        if role and block_year and block:
            joined = " ".join(block).strip()
            if DIMENSION_RE.search(joined) or MEDIUM_HINT_RE.search(joined):
                block = []
                block_year = None
                return
            parsed = _parse_block(joined, block_year)
            if parsed:
                parsed["role"] = role
                entries.append(parsed)
            elif len(fail_samples) < 40:
                fail_samples.append(f"[{role}] {block_year}: {joined[:150]}")
        block = []
        block_year = None

    for idx, line in enumerate(lines):
        if SOLO_HEADING_RE.match(line):
            flush()
            role = "solo"
            continue
        if GROUP_HEADING_RE.match(line):
            flush()
            role = "group"
            continue
        if GENERIC_EXH_HEADING_RE.match(line):
            flush()
            if _has_upcoming_year(lines, idx):
                role = role or "group"  # 구분 없는 "Exhibitions" 헤딩은 group으로 보수적 분류
            else:
                role = None  # 근처에 연도줄이 없으면 nav 메뉴 등 오탐 — 무시
            continue
        if STOP_HEADING_RE.match(line) and _looks_like_heading(line):
            flush()
            role = None
            continue
        if role is None:
            continue

        # 치수/재료 서술로 보이면 CV 목록이 아니라 작품 목록으로 흘러간 것 — 섹션 종료
        if DIMENSION_RE.search(line) or MEDIUM_HINT_RE.search(line):
            flush()
            role = None
            continue

        m = YEAR_ONLY_RE.match(line) or YEAR_PREFIX_RE.match(line)
        if m and (YEAR_ONLY_RE.match(line) or len(line) < 80):
            # 새 항목 시작
            flush()
            block_year = m.group(1)
            rest = line[m.end():].lstrip(".,: ") if YEAR_PREFIX_RE.match(line) else ""
            if rest:
                block.append(rest)
            continue

        if block_year:
            if _looks_like_heading(line) and STOP_HEADING_RE.match(line):
                flush()
                role = None
                continue
            if len(block) < 6:  # 폭주 방지 — 항목당 최대 6줄까지만 결합
                block.append(line)

    flush()
    return entries, fail_samples


MAX_BLOCK_LEN = 180  # 정상 CV 한 항목은 보통 이 범위 내 — 초과하면 같은 연도 아래
                       # 여러 항목이 줄 경계 없이 뭉친 것으로 보고 버린다.
MAX_PARTS = 6          # 콤마 파편이 너무 많으면(항목 여러 개 병합) 버린다.


def _parse_block(text: str, year: str) -> dict | None:
    text = text.strip().strip(",").strip()
    if not text or len(text) > MAX_BLOCK_LEN:
        return None
    if PRESS_NOISE_RE.search(text):
        return None
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts or len(parts) > MAX_PARTS:
        return None
    title = parts[0].rstrip(".:").strip('"“” ')
    if not title or len(title) < 2:
        return None
    venue = parts[1] if len(parts) > 1 else None
    city = parts[2] if len(parts) > 2 else None
    return {"year": year, "title": title, "venue_raw": venue, "city_raw": city}


def _load_gallery_artist_map(cur, gallery_key: str, display_name: str) -> tuple[str | None, dict[str, str]]:
    cur.execute("select id from galleries where name = %s limit 1", (display_name,))
    row = cur.fetchone()
    if not row:
        return None, {}
    gallery_id = str(row[0])
    cur.execute(
        """
        select lower(a.name), a.id
        from gallery_representations gr join artists a on a.id = gr.artist_id
        where gr.gallery_id = %s
        """,
        (gallery_id,),
    )
    name_map = {name: str(aid) for name, aid in cur.fetchall()}
    return gallery_id, name_map


def build_venue_lookup(cur) -> dict[str, tuple[str, str]]:
    lookup: dict[str, tuple[str, str]] = {}
    cur.execute("select id, name from museums")
    for mid, name in cur.fetchall():
        if name:
            lookup[name.strip().lower()] = ("museum", str(mid))
    cur.execute("select id, name from galleries")
    for gid, name in cur.fetchall():
        if name:
            lookup[name.strip().lower()] = ("gallery", str(gid))
    return lookup


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--exclude", default="", help="콤마구분 gallery key 목록(수동 제외)")
    ap.add_argument("--min-rate", type=float, default=0.15, help="작가당 평균 추출 항목 최소치 미달 갤러리는 리포트에서 제외 후보로 표시")
    args = ap.parse_args()
    manual_exclude = {k.strip() for k in args.exclude.split(",") if k.strip()}

    conn = get_connection()
    cur = conn.cursor()

    venue_lookup = build_venue_lookup(cur)

    per_gallery_report = []
    to_insert: list[dict] = []  # {title, venue_kind, museum_id, gallery_id, venue_name, city, start_date, source_id, artist_ids: [], role}
    fail_samples_all: list[str] = []
    skipped_no_artist = 0

    for key, (display_name, city, country) in GALLERY_INFO.items():
        site_name = f"gallery_{key}"
        if key in manual_exclude:
            per_gallery_report.append({"key": key, "excluded": "manual", "files": 0, "entries": 0})
            continue

        gallery_id, name_map = _load_gallery_artist_map(cur, key, display_name)
        if gallery_id is None:
            per_gallery_report.append({"key": key, "excluded": "no_gallery_row", "files": 0, "entries": 0})
            continue

        files = 0
        entries_total = 0
        gallery_fail_samples = []
        gallery_entries = []

        for record_id, data, meta in iter_records(site_name):
            raw_html = data.get("raw_html") or ""
            if not raw_html:
                continue
            files += 1
            artist_name = (data.get("name") or "").strip()
            artist_id = name_map.get(artist_name.lower())
            if artist_id is None:
                skipped_no_artist += 1
                continue

            entries, fail_samples = _extract_entries(raw_html)
            gallery_fail_samples.extend(f"{key}/{record_id}: {s}" for s in fail_samples[:3])
            for e in entries:
                e["artist_id"] = artist_id
                e["source_raw_path"] = meta["raw_path"]
                gallery_entries.append(e)
            entries_total += len(entries)

        rate = (entries_total / files) if files else 0
        low_quality = files > 0 and rate < args.min_rate
        per_gallery_report.append(
            {
                "key": key,
                "files": files,
                "entries": entries_total,
                "rate_per_file": round(rate, 2),
                "low_quality_flag": low_quality,
            }
        )
        fail_samples_all.extend(gallery_fail_samples[:5])

        if low_quality:
            continue  # 추출률 너무 낮은 갤러리는 apply 대상에서 자동 제외

        for e in gallery_entries:
            venue_kind = "gallery"
            museum_id = None
            gid = gallery_id
            venue_name = None
            if e.get("venue_raw"):
                match = venue_lookup.get(e["venue_raw"].strip().lower())
                if match:
                    venue_kind, matched_id = match
                    if venue_kind == "museum":
                        museum_id, gid = matched_id, None
                    else:
                        gid, museum_id = matched_id, None
                    venue_name = None
                else:
                    venue_kind, museum_id, gid, venue_name = "other", None, None, e["venue_raw"]
            to_insert.append(
                {
                    "title": e["title"],
                    "venue_kind": venue_kind,
                    "museum_id": museum_id,
                    "gallery_id": gid,
                    "venue_name": venue_name,
                    "city": e.get("city_raw"),
                    "start_date": f"{e['year']}-01-01",
                    "role": e["role"],
                    "artist_id": e["artist_id"],
                    "source_raw_path": e["source_raw_path"],
                }
            )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "galleries": per_gallery_report,
        "total_galleries_processed": sum(1 for g in per_gallery_report if not g.get("excluded")),
        "total_entries_to_insert": len(to_insert),
        "skipped_no_artist_match": skipped_no_artist,
        "parse_fail_samples": fail_samples_all[:20],
    }

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DOCS_DIR / f"gallery_전시이력_리포트_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[gallery_exhibitions] 갤러리 {report['total_galleries_processed']}곳 처리, "
          f"삽입 대상 {len(to_insert)}건, artist 미매칭 스킵 {skipped_no_artist}건")
    low_q = [g["key"] for g in per_gallery_report if g.get("low_quality_flag")]
    if low_q:
        print(f"[gallery_exhibitions] 추출률 낮아 apply 제외된 갤러리({len(low_q)}): {', '.join(low_q)}")
    print(f"[gallery_exhibitions] 리포트: {report_path}")

    if not args.apply:
        print("[gallery_exhibitions] dry-run — --apply로 실제 반영")
        return

    inserted = 0
    exh_link_created = 0
    for row in to_insert:
        cur.execute(
            """
            insert into exhibitions (title, venue_kind, museum_id, gallery_id, venue_name, city, start_date)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (coalesce(url,''), title, coalesce(start_date, date '0001-01-01')) do nothing
            returning id
            """,
            (
                row["title"],
                row["venue_kind"],
                row["museum_id"],
                row["gallery_id"],
                row["venue_name"],
                row["city"],
                row["start_date"],
            ),
        )
        result = cur.fetchone()
        if result is None:
            # 이미 존재 — 기존 exhibition_id 조회해서 작가 링크만 시도
            cur.execute(
                "select id from exhibitions where title = %s and coalesce(start_date, date '0001-01-01') = %s and coalesce(url,'') = ''",
                (row["title"], row["start_date"]),
            )
            existing = cur.fetchone()
            if existing is None:
                continue
            exh_id = str(existing[0])
        else:
            exh_id = str(result[0])
            inserted += 1

        cur.execute(
            "insert into exhibition_artists (exhibition_id, artist_id, role) values (%s, %s, %s) on conflict do nothing",
            (exh_id, row["artist_id"], row["role"]),
        )
        exh_link_created += cur.rowcount

    conn.commit()
    print(f"[gallery_exhibitions] 적용 완료 — exhibitions 신규 {inserted}건, exhibition_artists 링크 {exh_link_created}건")


if __name__ == "__main__":
    main()
