"""크롤러 공통 유틸 — 원본 저장 + 출처 메타데이터 기록.

각 크롤러는 이 모듈로 원본을 그대로 저장하기만 한다.
정규화(DB 적재)는 pipeline/ 단계에서 이 raw/ 폴더를 읽어 처리한다.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar

import requests

RAW_ROOT = Path(__file__).resolve().parent / "raw"
PROJECT_ROOT = RAW_ROOT.parent.parent

T = TypeVar("T")


def with_retry(fn: Callable[[], T], *, attempts: int = 5, base_delay: float = 2.0) -> T:
    """일시적 네트워크 오류(타임아웃 등)에 지수 백오프로 재시도한다.

    몇 시간씩 도는 대량 수집에서 타임아웃 한 번에 전체 프로세스가 죽는 걸 막기 위함.
    """
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except requests.RequestException as exc:
            if attempt == attempts:
                raise
            wait = base_delay * (2 ** (attempt - 1))
            print(f"[retry] 요청 실패({exc}) — {wait:.0f}초 후 재시도 ({attempt}/{attempts})", flush=True)
            time.sleep(wait)
    raise AssertionError("unreachable")


def _safe_id(record_id: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in str(record_id))


def save_raw(
    site_name: str,
    record_id: str,
    content: Union[bytes, str],
    *,
    url: str | None,
    license_note: str,
    ext: str = "json",
) -> Path:
    """원본 파일 + 출처 메타데이터(.meta.json)를 crawlers/raw/<site_name>/ 아래 저장한다.

    반환값: 저장된 원본 파일 경로.
    옆에 생성되는 <id>.meta.json이 나중에 db.sources 테이블 적재의 근거가 된다.
    """
    site_dir = RAW_ROOT / site_name
    site_dir.mkdir(parents=True, exist_ok=True)

    safe_id = _safe_id(record_id)
    raw_path = site_dir / f"{safe_id}.{ext}"

    if isinstance(content, bytes):
        raw_path.write_bytes(content)
    else:
        raw_path.write_text(content, encoding="utf-8")

    meta = {
        "site_name": site_name,
        "record_id": record_id,
        "url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "raw_path": str(raw_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "license_note": license_note,
    }
    meta_path = site_dir / f"{safe_id}.meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return raw_path


def already_fetched(site_name: str, record_id: str, ext: str = "json") -> bool:
    """이미 수집된 레코드인지 확인 — 재실행 시 중복 요청 방지."""
    safe_id = _safe_id(record_id)
    return (RAW_ROOT / site_name / f"{safe_id}.{ext}").exists()
