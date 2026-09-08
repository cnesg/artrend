"""게티미술관(J. Paul Getty Museum) 크롤러.

data.getty.edu — 공식 SPARQL 엔드포인트 + REST(JSON-LD, Linked Art 포맷) 제공,
CC0, 인증 불필요(2026-09-02 확인). REST API 문서는 "전체 목록 나열 기능은
없다"고 명시하므로, SPARQL로 오브젝트 URI를 OFFSET/LIMIT 페이지네이션으로
모두 뽑은 뒤 REST 엔드포인트에서 개별 JSON을 가져온다. 총 168,970건(확인일 기준).

사용법:
    python getty.py --limit 5000
"""
from __future__ import annotations

import argparse
import re
import sys
import time

import requests

from common import already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

SITE_NAME = "getty"
SPARQL_URL = "https://data.getty.edu/museum/collection/sparql"
LICENSE_NOTE = "Getty Museum Open Content (data.getty.edu) — CC0, 인증 불필요, 2026-09-02"
HEADERS = {"User-Agent": "artgraph-research-bot/1.0"}
PAGE_SIZE = 5000

SPARQL_QUERY = """
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
SELECT ?obj WHERE {{
  ?obj a crm:E22_Human-Made_Object .
}} ORDER BY ?obj LIMIT {limit} OFFSET {offset}
"""


def _fetch_json(url: str, **params) -> dict:
    def _do():
        resp = requests.get(url, params=params, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return resp.json()

    return with_retry(_do)


def collect_object_uris() -> list[str]:
    uris: list[str] = []
    offset = 0
    while True:
        query = SPARQL_QUERY.format(limit=PAGE_SIZE, offset=offset)
        data = _fetch_json(SPARQL_URL, query=query, format="json")
        bindings = data["results"]["bindings"]
        if not bindings:
            break
        uris.extend(b["obj"]["value"] for b in bindings if b["obj"].get("type") == "uri")
        offset += PAGE_SIZE
        print(f"[getty] SPARQL 오브젝트 ID {len(uris)}건 확인...")
    return uris


def crawl(limit: int | None, delay: float, skip_existing: bool) -> None:
    uris = collect_object_uris()
    if limit:
        uris = uris[:limit]
    print(f"[getty] 오브젝트 {len(uris)}건 확인, 저장 시작")

    saved = 0
    for uri in uris:
        obj_id = uri.rstrip("/").rsplit("/", 1)[-1]
        record_id = re.sub(r"[^a-zA-Z0-9]+", "_", obj_id)

        if skip_existing and already_fetched(SITE_NAME, record_id):
            continue

        def _do(u=uri):
            resp = requests.get(u, headers={**HEADERS, "Accept": "application/json"}, timeout=30)
            resp.raise_for_status()
            return resp.text

        try:
            content = with_retry(_do)
        except requests.RequestException as exc:
            print(f"[getty] {uri} 조회 실패: {exc}")
            continue

        save_raw(SITE_NAME, record_id, content, url=uri, license_note=LICENSE_NOTE)
        saved += 1
        if saved % 1000 == 0:
            print(f"[getty] {saved}건 저장 진행 중...")
        time.sleep(delay)

    print(f"[getty] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="게티미술관 SPARQL+REST 크롤러")
    parser.add_argument("--limit", type=int, default=None, help="수집 건수 제한")
    parser.add_argument("--delay", type=float, default=0.1, help="요청 간 대기(초)")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 레코드도 다시 수집",
    )
    args = parser.parse_args()
    crawl(args.limit, args.delay, args.skip_existing)
