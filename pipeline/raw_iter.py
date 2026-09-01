"""crawlers/raw/<site>/ 순회 공통 유틸 — <id>.meta.json + <id>.json 쌍을 읽는다."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

RAW_ROOT = Path(__file__).resolve().parent.parent / "crawlers" / "raw"


def iter_records(site_name: str) -> Iterator[tuple[str, dict, dict]]:
    """(record_id, data, meta) 를 순회한다. meta는 sources 테이블 적재용."""
    site_dir = RAW_ROOT / site_name
    for meta_path in sorted(site_dir.glob("*.meta.json")):
        record_id = meta_path.name[: -len(".meta.json")]
        raw_path = meta_path.with_name(f"{record_id}.json")
        if not raw_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        data = json.loads(raw_path.read_text(encoding="utf-8"))
        yield record_id, data, meta


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
