"""National Gallery of Art (Washington) Open Data 크롤러.

https://github.com/NationalGalleryOfArt/opendata — 인증 불필요, CC0.
개별 오브젝트 API가 아니라 CSV 전체 덤프를 매일 갱신해 배포하는 방식이라,
API 폴링이 아니라 GitHub raw 파일을 통째로 내려받아 원본으로 저장한다.

기본으로는 우리 스키마(artworks/artists/provenance)에 바로 쓰이는 4개 파일만 받는다.
필요해지면 --files로 다른 파일(예: published_images)도 추가로 받을 수 있다.

사용법:
    python crawlers/nga.py
    python crawlers/nga.py --files objects.csv objects_constituents.csv constituents.csv objects_historical_data.csv published_images.csv
"""
from __future__ import annotations

import argparse
import sys

import requests

from common import save_raw

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

RAW_BASE = "https://raw.githubusercontent.com/NationalGalleryOfArt/opendata/main/data"
SITE_NAME = "nga"
LICENSE_NOTE = "CC0 - National Gallery of Art Open Data Program (https://github.com/NationalGalleryOfArt/opendata)"

# 우리 스키마에 바로 대응되는 핵심 파일:
#   objects.csv             -> artworks (provenancetext 필드 포함)
#   objects_constituents.csv-> artworks<->artists (roletype으로 creator/donor 구분)
#   constituents.csv        -> artists / collectors 후보
#   objects_historical_data.csv -> provenance/exhibition history 원문
DEFAULT_FILES = [
    "objects.csv",
    "objects_constituents.csv",
    "constituents.csv",
    "objects_historical_data.csv",
]


def download_file(name: str) -> None:
    url = f"{RAW_BASE}/{name}"
    print(f"[nga] {name} 다운로드 중...")
    resp = requests.get(url, timeout=300, stream=True)
    resp.raise_for_status()
    content = resp.content  # 파일 전체를 한 번에 저장 (덤프 방식이라 개별 레코드 스트리밍 불필요)
    path = save_raw(SITE_NAME, name.replace(".csv", ""), content, url=url, license_note=LICENSE_NOTE, ext="csv")
    print(f"[nga] {name} 저장 완료 ({len(content) / 1_000_000:.1f} MB) -> {path}")


def crawl(files: list[str]) -> None:
    for name in files:
        try:
            download_file(name)
        except requests.RequestException as exc:
            print(f"[nga] {name} 다운로드 실패: {exc}")
    print("[nga] 완료")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="National Gallery of Art Open Data 크롤러")
    parser.add_argument("--files", nargs="+", default=DEFAULT_FILES, help="받을 CSV 파일 목록")
    args = parser.parse_args()
    crawl(args.files)
