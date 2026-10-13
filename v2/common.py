"""아트그래프 v2 공통 — 데이터 경로, DB 접속, 원본 저장, HTTP.

v1(crawlers/common.py, pipeline/db.py)을 import하지 않는다 — v2는 독립 실행.

    python v2/common.py --init-db     # artgraph_v2 DB 생성 + db/*.sql 적용 (idempotent)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar

import psycopg2
import requests

V2_ROOT = Path(__file__).resolve().parent
# 원본은 git 밖에 둔다(worktree 정리·브랜치 전환과 무관하게 보존).
DATA_ROOT = Path(os.environ.get("ARTGRAPH_V2_DATA") or Path.home() / "artgraph_v2_data")
RAW_ROOT = DATA_ROOT / "raw"
# v1과 같은 로컬 Postgres 인스턴스, DB만 분리. 기본값이 있어 "환경변수 없어서 조용히 dry-run" 함정이 없다.
DSN = os.environ.get("V2_DATABASE_URL") or "postgresql://postgres@127.0.0.1:5433/artgraph_v2"
USER_AGENT = "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"
SOURCE_TIERS = ("official", "official_pdf", "archive", "wikipedia", "press")

T = TypeVar("T")


def get_conn():
    return psycopg2.connect(DSN, connect_timeout=10)


def alias_key(s: str | None) -> str | None:
    """작가·갤러리 동일성 키: NFC + 공백 정리 + casefold. 유사도 비교는 하지 않는다."""
    if not s:
        return None
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.casefold() or None


def with_retry(fn: Callable[[], T], *, attempts: int = 5, base_delay: float = 2.0) -> T:
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except requests.RequestException as exc:
            if attempt == attempts:
                raise
            wait = base_delay * (2 ** (attempt - 1))
            msg = str(exc)
            print(f"[retry] {msg[:160]}{'…' if len(msg) > 160 else ''} — {wait:.0f}s 후 재시도 ({attempt}/{attempts})", flush=True)
            time.sleep(wait)
    raise AssertionError("unreachable")


class PoliteSession:
    """호스트별 최소 간격을 지키는 requests 세션 (웨이백은 더 느리게)."""

    def __init__(self, default_delay: float = 1.5, wayback_delay: float = 3.0):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self.default_delay = default_delay
        self.wayback_delay = wayback_delay
        self._last: dict[str, float] = {}

    def get(self, url: str, delay: float | None = None, method: str = "GET", **kw) -> requests.Response:
        host = re.sub(r"^https?://([^/]+).*$", r"\1", url)
        if delay is None:
            delay = self.wayback_delay if "web.archive.org" in host else self.default_delay
        wait = self._last.get(host, 0) + delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)

        def _do():
            r = self.s.request(method, url, timeout=60, **kw)
            if r.status_code == 429:  # Retry-After 존중 후 재시도
                ra = r.headers.get("Retry-After", "")
                time.sleep(min(int(ra) if ra.isdigit() else 30, 120))
                raise requests.HTTPError(f"429 {url}", response=r)
            r.raise_for_status()
            return r

        try:
            return with_retry(_do)
        finally:
            self._last[host] = time.monotonic()


def _safe_id(record_id: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in str(record_id))


def raw_path_for(site: str, record_id: str, ext: str) -> Path:
    return RAW_ROOT / site / f"{_safe_id(record_id)}.{ext}"


def already_fetched(site: str, record_id: str, ext: str) -> bool:
    return raw_path_for(site, record_id, ext).exists()


def save_raw(site: str, record_id: str, content: bytes | str, *, url: str | None, ext: str,
             source_tier: str, license_note: str, extra: dict | None = None) -> Path:
    assert source_tier in SOURCE_TIERS, source_tier
    path = raw_path_for(site, record_id, ext)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    meta = {
        "site": site,
        "record_id": record_id,
        "url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "raw_path": str(path.relative_to(DATA_ROOT)).replace("\\", "/"),
        "source_tier": source_tier,
        "license_note": license_note,
        **(extra or {}),
    }
    path.with_name(path.name[: -len(ext) - 1] + ".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_meta(raw_path: Path) -> dict:
    stem = raw_path.name.rsplit(".", 1)[0]
    return json.loads((raw_path.parent / f"{stem}.meta.json").read_text(encoding="utf-8"))


def init_db():
    dbname = DSN.rsplit("/", 1)[1].split("?")[0]
    admin = psycopg2.connect(DSN.rsplit("/", 1)[0] + "/postgres", connect_timeout=10)
    admin.autocommit = True
    cur = admin.cursor()
    cur.execute("select 1 from pg_database where datname=%s", (dbname,))
    if not cur.fetchone():
        cur.execute(f'create database "{dbname}"')
        print("created database", dbname)
    admin.close()
    conn = get_conn()
    for sql in sorted((V2_ROOT / "db").glob("*.sql")):
        with conn.cursor() as c:
            c.execute(sql.read_text(encoding="utf-8"))
        conn.commit()
        print("applied", sql.name)
    conn.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--init-db" in sys.argv:
        init_db()
    print("DATA_ROOT", DATA_ROOT)
    print("DSN", DSN)
