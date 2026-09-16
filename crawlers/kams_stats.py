"""한국미술시장정보시스템(K-ARTMARKET, 예술경영지원센터 「미술시장 실태조사」 공개
통계 페이지) 크롤러 — R5-통계.

로트 단위가 아니라 **연도별 집계**(화랑/경매사/아트페어 판매금액·낙찰률 등)만
다룬다. 대상 페이지(`/member/stats/timeseries/MarketSizeProgress.do`)는
서버 렌더링된 HTML 테이블(2010~2024년 시계열)이라 로그인·AJAX 없이 그대로
읽힌다. robots.txt(2026-09-15 확인, `k-artmarket.kr/robots.txt`)는
`User-agent: *`에 `Disallow` 없이 `Allow: /`만 명시 — 전체 허용.

정규화는 별도 스크립트(`pipeline/kams_stats_load.py`)가 담당하고 여기서는
원본 HTML만 보존한다.

사용법:
    python crawlers/kams_stats.py
"""
from __future__ import annotations

import sys

import requests

from common import already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "https://k-artmarket.kr"
PAGE_URL = f"{BASE_URL}/member/stats/timeseries/MarketSizeProgress.do"
SITE_NAME = "kams_stats"
RECORD_ID = "market_size_progress"
LICENSE_NOTE = (
    "K-ARTMARKET 미술시장 영역별 규모 통계 페이지 (robots.txt 전체 허용, 2026-09-15 확인) — "
    "화랑/경매사/아트페어/미술관 연도별 집계(2010~2024), 서버 렌더링 HTML 테이블 그대로 보존"
)
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}


def crawl() -> None:
    if already_fetched(SITE_NAME, RECORD_ID, ext="html"):
        print(f"[kams_stats] 이미 수집됨 — 스킵")
        return

    def _fetch():
        resp = requests.get(PAGE_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.text

    html = with_retry(_fetch)
    save_raw(SITE_NAME, RECORD_ID, html, url=PAGE_URL, license_note=LICENSE_NOTE, ext="html")
    print(f"[kams_stats] 저장 완료 — {PAGE_URL}")


if __name__ == "__main__":
    crawl()
