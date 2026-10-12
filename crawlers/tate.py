"""Tate(영국, 테이트 갤러리) 오픈 데이터 크롤러.

https://github.com/tategallery/collection — CC0(비상업적 재사용 조건부, LICENCE 참고), 인증 불필요.
artwork_data.csv + artist_data.csv 두 파일을 통째로 받는다.

사용법:
    python crawlers/tate.py
"""
from __future__ import annotations

import sys

import requests

from common import save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

BASE_URL = "https://raw.githubusercontent.com/tategallery/collection/master"
SITE_NAME = "tate"
LICENSE_NOTE = "CC0 - Tate Collection Open Data (https://github.com/tategallery/collection)"
FILES = ["artwork_data.csv", "artist_data.csv"]


def crawl() -> None:
    for filename in FILES:
        def _do():
            resp = requests.get(f"{BASE_URL}/{filename}", timeout=120)
            resp.raise_for_status()
            return resp.content

        content = with_retry(_do, attempts=3, base_delay=5.0)
        save_raw(SITE_NAME, filename.replace(".csv", ""), content, url=f"{BASE_URL}/{filename}", license_note=LICENSE_NOTE, ext="csv")
        print(f"[tate] {filename} 저장 ({len(content) / 1_000_000:.1f}MB)")

    print("[tate] 완료")


if __name__ == "__main__":
    crawl()
