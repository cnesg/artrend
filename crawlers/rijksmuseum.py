"""릭스뮤지엄(Rijksmuseum, 네덜란드) OAI-PMH API 크롤러.

data.rijksmuseum.nl/oai — 가입/키 불필요, 공개 OAI-PMH 2.0 엔드포인트.
oai_dc(Dublin Core) 포맷으로 전체 소장품 84만여 건을 resumptionToken
페이지네이션으로 순회한다. (2026-09-02 확인: completeListSize=844,844)

사용법:
    python rijksmuseum.py --limit 5000
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET

import requests

from common import already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

SITE_NAME = "rijksmuseum"
OAI_URL = "https://data.rijksmuseum.nl/oai"
LICENSE_NOTE = "Rijksmuseum OAI-PMH API (data.rijksmuseum.nl/oai) — 공개, 가입 불필요, 2026-09-02"
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}

NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
}


def _fetch(params: dict) -> str:
    def _do():
        resp = requests.get(OAI_URL, params=params, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return resp.text

    return with_retry(_do)


def _record_to_dict(record_el: ET.Element) -> tuple[str, dict]:
    header = record_el.find("oai:header", NS)
    identifier = header.find("oai:identifier", NS).text
    dc = record_el.find("oai:metadata/oai_dc:dc", NS)
    data = {}
    if dc is not None:
        for child in dc:
            tag = child.tag.split("}")[-1]
            data.setdefault(tag, []).append(child.text)
    return identifier, data


def crawl(limit: int | None, skip_existing: bool) -> None:
    saved = 0
    params = {"verb": "ListRecords", "metadataPrefix": "oai_dc"}

    while True:
        xml_text = _fetch(params)
        root = ET.fromstring(xml_text)

        error = root.find("oai:error", NS)
        if error is not None:
            print(f"[rijksmuseum] OAI 오류: {error.text}")
            break

        list_records = root.find("oai:ListRecords", NS)
        if list_records is None:
            break

        for record_el in list_records.findall("oai:record", NS):
            identifier, data = _record_to_dict(record_el)
            record_id = re.sub(r"[^a-zA-Z0-9]+", "_", identifier).strip("_")

            if skip_existing and already_fetched(SITE_NAME, record_id):
                continue

            save_raw(
                SITE_NAME,
                record_id,
                json.dumps({"oai_identifier": identifier, **data}, ensure_ascii=False),
                url=identifier,
                license_note=LICENSE_NOTE,
            )
            saved += 1
            if saved % 2000 == 0:
                print(f"[rijksmuseum] {saved}건 저장 진행 중...")
            if limit and saved >= limit:
                print(f"[rijksmuseum] limit({limit}) 도달, 종료")
                return

        token_el = list_records.find("oai:resumptionToken", NS)
        if token_el is None or not (token_el.text or "").strip():
            break
        params = {"verb": "ListRecords", "resumptionToken": token_el.text.strip()}

    print(f"[rijksmuseum] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="릭스뮤지엄 OAI-PMH 크롤러")
    parser.add_argument("--limit", type=int, default=None, help="수집 건수 제한")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 레코드도 다시 수집",
    )
    args = parser.parse_args()
    crawl(args.limit, args.skip_existing)
