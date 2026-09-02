"""The Met (Metropolitan Museum of Art) 오픈 데이터 크롤러.

https://github.com/metmuseum/openaccess — CC0, 인증 불필요.
원래 오브젝트당 API 요청 1회(공식 v1 API) 방식으로 짰었지만 실측 결과
3시간에 2천여 건(전체 완주까지 약 17일 예상)으로 너무 느려서, MoMA/Tate와
같은 방식으로 공식 GitHub CSV 벌크 데이터셋(MetObjects.csv, ~470만 행)을
통째로 받는 방식으로 전환함 (2026-09-02). GitHub이 Git LFS로 저장해서
raw.githubusercontent.com이 아니라 media.githubusercontent.com에서
받아야 실제 파일 내용이 나온다(LFS 포인터 파일 주의, MoMA와 동일 이슈).

사용법:
    python crawlers/met.py
"""
from __future__ import annotations

import sys

import requests

from common import save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

CSV_URL = "https://media.githubusercontent.com/media/metmuseum/openaccess/master/MetObjects.csv"
SITE_NAME = "met"
LICENSE_NOTE = "CC0 - The Met Open Access (https://github.com/metmuseum/openaccess)"


def crawl() -> None:
    def _do():
        resp = requests.get(CSV_URL, timeout=180)
        resp.raise_for_status()
        return resp.content

    content = with_retry(_do, attempts=3, base_delay=5.0)
    save_raw(SITE_NAME, "MetObjects", content, url=CSV_URL, license_note=LICENSE_NOTE, ext="csv")
    print(f"[met] 완료 — MetObjects.csv 저장 ({len(content) / 1_000_000:.1f}MB)")


if __name__ == "__main__":
    crawl()
