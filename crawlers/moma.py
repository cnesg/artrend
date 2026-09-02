"""MoMA(뉴욕현대미술관) 오픈 데이터 크롤러.

https://github.com/MuseumofModernArt/collection — CC0, 인증 불필요.
CSV 하나(Artworks.csv)에 전체 소장품이 들어있다. GitHub이 Git LFS로
저장해서 raw.githubusercontent.com이 아니라 media.githubusercontent.com에서
받아야 실제 파일 내용이 나온다(LFS 포인터 파일 주의).

사용법:
    python crawlers/moma.py
"""
from __future__ import annotations

import sys

import requests

from common import save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

CSV_URL = "https://media.githubusercontent.com/media/MuseumofModernArt/collection/main/Artworks.csv"
SITE_NAME = "moma"
LICENSE_NOTE = "CC0 - MoMA Collection Open Data (https://github.com/MuseumofModernArt/collection)"


def crawl() -> None:
    def _do():
        resp = requests.get(CSV_URL, timeout=120)
        resp.raise_for_status()
        return resp.content

    content = with_retry(_do, attempts=3, base_delay=5.0)
    save_raw(SITE_NAME, "Artworks", content, url=CSV_URL, license_note=LICENSE_NOTE, ext="csv")
    print(f"[moma] 완료 — Artworks.csv 저장 ({len(content) / 1_000_000:.1f}MB)")


if __name__ == "__main__":
    crawl()
