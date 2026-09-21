"""한국미술시장정보시스템(K-ARTMARKET, 예술경영지원센터 「미술시장 실태조사」 공개
통계 페이지) 크롤러 — R5-통계.

로트 단위가 아니라 **연도별 집계**(화랑/경매사/아트페어 판매금액·낙찰률 등)만
다룬다. 대상 페이지(`/member/stats/timeseries/MarketSizeProgress.do`)는
서버 렌더링된 HTML 테이블(2010~2024년 시계열)이라 로그인·AJAX 없이 그대로
읽힌다. robots.txt(2026-09-15 확인, `k-artmarket.kr/robots.txt`)는
`User-agent: *`에 `Disallow` 없이 `Allow: /`만 명시 — 전체 허용.

정규화는 별도 스크립트(`pipeline/kams_stats_load.py`)가 담당하고 여기서는
원본 HTML만 보존한다.

2026-09-17 갱신잡 정리(docs/갱신잡_20260917.md) 후속 수정: record_id가 고정값
("market_size_progress")이라 최초 1회 이후 원문이 갱신돼도(신규 연도 행 추가 등)
already_fetched가 영구 스킵하는 결함이 있었음 — record_id에 수집 연월(YYYYMM)을
넣어 매달 최대 1회는 새로 저장되도록 바꿨다. 같은 달에 재실행하면 여전히
already_fetched로 스킵(중복 요청 방지 유지), 달이 바뀌면 새 raw 파일 생성.
`--force`로 같은 달이어도 강제 재수집 가능(원문이 갑자기 갱신됐을 때 수동 확인용).

사용법:
    python crawlers/kams_stats.py
    python crawlers/kams_stats.py --force   # 같은 달이어도 강제 재수집
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import requests

from common import already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "https://k-artmarket.kr"
PAGE_URL = f"{BASE_URL}/member/stats/timeseries/MarketSizeProgress.do"
SITE_NAME = "kams_stats"
LICENSE_NOTE = (
    "K-ARTMARKET 미술시장 영역별 규모 통계 페이지 (robots.txt 전체 허용, 2026-09-15 확인) — "
    "화랑/경매사/아트페어/미술관 연도별 집계(2010~2024), 서버 렌더링 HTML 테이블 그대로 보존"
)
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}


def crawl(force: bool = False) -> None:
    record_id = f"market_size_progress_{datetime.now(timezone.utc).strftime('%Y%m')}"

    if not force and already_fetched(SITE_NAME, record_id, ext="html"):
        print(f"[kams_stats] 이번 달 이미 수집됨({record_id}) — 스킵")
        return

    def _fetch():
        resp = requests.get(PAGE_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.text

    html = with_retry(_fetch)
    save_raw(SITE_NAME, record_id, html, url=PAGE_URL, license_note=LICENSE_NOTE, ext="html")
    print(f"[kams_stats] 저장 완료 — {PAGE_URL} ({record_id})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="K-ARTMARKET 통계 페이지 크롤러")
    parser.add_argument("--force", action="store_true", help="이번 달에 이미 수집됐어도 강제 재수집")
    args = parser.parse_args()
    crawl(force=args.force)
