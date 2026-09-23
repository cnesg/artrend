"""crawlers/raw/<site>/ 순회 공통 유틸 — <id>.meta.json + <id>.json 쌍을 읽는다."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

# 기본은 이 체크아웃의 crawlers/raw/. 다만 `crawlers/raw/`는 gitignore 대상이라
# git worktree에서 작업하면 메인 체크아웃이 이미 받아 둔 원본이 안 보인다 —
# 그 경우 ARTREND_RAW_ROOT로 공용 raw 캐시를 가리킬 수 있게 한다.
# (meta.json의 raw_path는 어느 체크아웃에서 받았든 "crawlers/raw/..." 상대경로로
#  같은 문자열이라, sources.raw_path 기반 중복 방지는 그대로 동작한다.)
RAW_ROOT = Path(
    os.environ.get("ARTREND_RAW_ROOT")
    or Path(__file__).resolve().parent.parent / "crawlers" / "raw"
)


def iter_records(site_name: str, ext: str = "json") -> Iterator[tuple[str, object, dict]]:
    """(record_id, data, meta) 를 순회한다. meta는 sources 테이블 적재용.

    ext="json"(기본)이면 원본을 파싱한 dict를, ext="html" 등이면 파일 텍스트를 그대로
    돌려준다(HTML 목록 페이지를 원본으로 저장하는 크롤러용 — grisebach/kanauction/
    k_artmarket_works가 이 경로를 쓴다).
    """
    site_dir = RAW_ROOT / site_name
    for meta_path in sorted(site_dir.glob("*.meta.json")):
        record_id = meta_path.name[: -len(".meta.json")]
        raw_path = meta_path.with_name(f"{record_id}.{ext}")
        if not raw_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        text = raw_path.read_text(encoding="utf-8")
        yield record_id, (json.loads(text) if ext == "json" else text), meta


def to_int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def year_to_date(year_str) -> str | None:
    """'1907' 같은 연도 문자열을 'YYYY-01-01' date 리터럴로. 파싱 안 되면 None."""
    year = to_int(year_str)
    if year is None or not (1 <= year <= 9999):
        return None
    return f"{year:04d}-01-01"
