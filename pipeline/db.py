"""Postgres 연결 유틸 — pipeline 전체의 단일 진입점 (2026-09-17 P3 일원화).

우선순위: 환경변수 DATABASE_URL → pipeline/.env 의 DATABASE_URL. 둘 다 없으면 예외.
스크립트에 접속 문자열을 하드코딩하지 말고 `from db import get_connection` 을 쓸 것.
현재 .env 는 로컬 pgportable(127.0.0.1:5433/artrend); Supabase 시절 URL은 주석으로만 남아 있다.
"""
from __future__ import annotations

import os
from pathlib import Path

import psycopg2

ENV_PATH = Path(__file__).resolve().parent / ".env"


def get_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        try:
            from dotenv import load_dotenv

            load_dotenv(ENV_PATH)
        except ImportError:
            pass
        dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            f"DATABASE_URL 이 환경변수에도 {ENV_PATH} 에도 없습니다. "
            "pipeline/.env 에 DATABASE_URL=postgresql://... 를 설정하세요."
        )
    return dsn


def get_connection(*, autocommit: bool = False):
    conn = psycopg2.connect(get_dsn())
    conn.set_client_encoding("UTF8")
    if autocommit:
        conn.autocommit = True
    return conn


get_conn = get_connection
