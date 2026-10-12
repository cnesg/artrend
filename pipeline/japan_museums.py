"""일본 국립미술관 통합검색(raw/japan_museums/*.json, records.php HTML) -> DB 적재.

원본이 JSON이 아니라 고정폭 테이블 HTML(정부 레거시 사이트)이라 정규식으로
파싱한다. "作品詳細"(작품 상세) 섹션 안에 일본어 블록 다음 영어 블록이 이어지는
고정 구조: 장르행 -> 제목행(굵게) -> 연도/재료/크기행 -> ... -> 소장처행(굵게).
굵은 셀이 총 4개(일본어 제목/소장처, 영어 제목/소장처)면 영어 제목도 채운다 —
그렇지 않으면 일본어 제목만 채우고 넘어간다(최선 노력 파싱, 완벽하지 않음).
"""
from __future__ import annotations

import re

from raw_iter import RAW_ROOT

JP_DIR = RAW_ROOT / "japan_museums"
MUSEUM_CACHE_KEY = "일본 국립미술관 통합검색"

ARTIST_RE = re.compile(
    r"<BIG[^>]*><B>(.*?)</B></BIG>.*?(\d{4})\s*-\s*(\d{4}|)?.*?<br>(.*?)&nbsp;",
    re.S,
)
DETAIL_SECTION_RE = re.compile(
    r"作品詳細</SPAN>.*?<DIV[^>]*>(.*?)</table>", re.S
)
TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
BOLD_RE = re.compile(r"<b>(.*?)</b>", re.S | re.I)


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def _parse_html(content: str) -> dict:
    result: dict = {}

    artist_m = re.search(r"<BIG[^>]*><B>(.*?)</B></BIG>", content, re.S)
    if artist_m:
        result["artist_jp"] = _clean(artist_m.group(1))

    life_m = re.search(r"</BIG>&nbsp;&nbsp;\s*&nbsp;(\d{4})\s*-\s*(\d{4})?", content)
    if life_m:
        result["birth_year"] = life_m.group(1)
        result["death_year"] = life_m.group(2)

    section_m = DETAIL_SECTION_RE.search(content)
    if not section_m:
        return result

    cells = [_clean(td) for td in TD_RE.findall(section_m.group(1))]
    cells = [c for c in cells if c]

    bolds = [_clean(b) for b in BOLD_RE.findall(section_m.group(1))]
    bolds = [b for b in bolds if b]

    if bolds:
        result["title_jp"] = bolds[0]
        result["museum"] = bolds[-1]
        if len(bolds) >= 4:
            result["title_en"] = bolds[2]

    if cells:
        result["detail_cells"] = cells

    return result


def load(store) -> int:
    museum_id = store.get_or_create_museum(MUSEUM_CACHE_KEY, "Japan National Museums (Integrated Search)")
    loaded = 0

    for html_path in sorted(JP_DIR.glob("*.json")):
        if html_path.name.endswith(".meta.json"):
            continue
        record_id = html_path.stem
        meta_path = html_path.with_name(f"{record_id}.meta.json")
        if not meta_path.exists():
            continue

        import json

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if store.source_already_loaded(meta["raw_path"]):
            continue

        content = html_path.read_text(encoding="utf-8", errors="replace")
        parsed = _parse_html(content)
        if not parsed.get("title_jp"):
            continue

        source_id = store.insert_source(meta)

        artist_name = parsed.get("artist_jp")
        artist_id = store.get_or_create_artist(
            artist_name,
            birth_year=int(parsed["birth_year"]) if (parsed.get("birth_year") or "").isdigit() else None,
            death_year=int(parsed["death_year"]) if (parsed.get("death_year") or "").isdigit() else None,
            source_id=source_id,
        )

        title = parsed.get("title_en") or parsed.get("title_jp")
        description = " / ".join(parsed.get("detail_cells", [])[:6]) or None

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=title,
            title_en=parsed.get("title_en"),
            year_created=None,
            medium=None,
            dimensions=None,
            description=description,
            source_id=source_id,
        )

        store.insert_museum_holding(
            museum_id=museum_id,
            artwork_id=artwork_id,
            accession_number=record_id,
            source_id=source_id,
        )
        loaded += 1

    store.commit()
    print(f"[pipeline:japan_museums] {loaded}건 적재")
    return loaded
