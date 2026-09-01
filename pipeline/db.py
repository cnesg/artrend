"""Supabase Postgres 연결 유틸.

DATABASE_URL 환경변수(Supabase 프로젝트의 connection string)가 필요하다.
아직 Supabase 프로젝트가 없다면 --dry-run으로 파싱만 검증할 것.
"""
from __future__ import annotations

import os

import psycopg2


def get_connection():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL 환경변수가 설정되지 않았습니다. "
            "Supabase 프로젝트 생성 후 connection string을 설정하세요."
        )
    return psycopg2.connect(dsn)
