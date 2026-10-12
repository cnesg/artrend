"""이미 적재된 K-ARTMARKET 로트 중 '영문 작가명만 있던' 행을 뒤늦게 작가에 연결한다.

배경: `pipeline/k_artmarket_works.py`는 처음에 한글 작가명(`list-name`)만 썼다. 출처에는
한글명이 비고 **영문명만 있는 행이 1,103건** 있는데(전부 한국 작가의 로마자 표기 —
"Paik Nam June", "Pyon Kwan Sik" 등), 이 행들이 전부 작가 미연결로 적재됐다.

이걸 그대로 `get_or_create_artist_safe`에 넘기면 기존 "백남준"과 별개의 로마자 작가 행이
새로 생겨 **교차언어 중복**을 만든다 — 이 프로젝트가 자동으로 하지 않기로 한 바로 그 작업이다.
그래서 **이미 DB에 있는 artists의 `name_en`/`name`과 정확히 일치할 때만** 연결하고,
일치하는 게 없으면(로마자 표기가 달라서) **그냥 미연결로 둔다**. 같은 `name_en`을 가진
작가가 둘 이상이면 동명이인 위험이 있어 역시 연결하지 않는다.

로더는 세일(페이지) 단위 `source_already_loaded` 스킵을 하기 때문에 로직만 고쳐서
재실행해도 이미 적재된 1,162페이지는 통째로 건너뛴다 — 그래서 이 백필을 따로 둔다
(`pipeline/bonhams_backfill_departments.py`와 같은 패턴).

**기본은 리포트, `--apply`로만 반영**하고 재실행해도 결과가 같다(이미 artist_id가 있는
artworks는 건드리지 않는다). 작품 행 특정은 (source_id, 제목, 재질, 규격) 조합으로 하고,
그 조합이 그 페이지 안에서 **유일할 때만** 갱신한다(동일 스펙 작품이 둘 이상이면 보류).

사용법:
    python pipeline/k_artmarket_backfill_artist_en.py            # 리포트만
    python pipeline/k_artmarket_backfill_artist_en.py --apply    # 실제 반영
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

from db import get_connection  # noqa: E402
from k_artmarket_works import SITE_NAME, build_en_artist_index, parse_items  # noqa: E402
from raw_iter import iter_records  # noqa: E402


class _CurOnly:
    """build_en_artist_index가 기대하는 최소 인터페이스(store.cur)만 제공."""

    def __init__(self, cur):
        self.cur = cur


def main() -> None:
    parser = argparse.ArgumentParser(description="K-ARTMARKET 영문명 작가 뒤늦은 연결")
    parser.add_argument("--apply", action="store_true", help="실제 DB에 반영(기본은 리포트만)")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    en_index = build_en_artist_index(_CurOnly(cur))
    print(f"[kam-backfill] 영문/한글 정확일치 인덱스 {len(en_index)}건")

    cur.execute("select raw_path, id::text from sources where site_name = %s", (SITE_NAME,))
    source_by_path = dict(cur.fetchall())
    print(f"[kam-backfill] 적재된 페이지 {len(source_by_path)}건")

    reasons: Counter[str] = Counter()
    updated = 0

    for _record_id, page_html, meta in iter_records(SITE_NAME, ext="html"):
        source_id = source_by_path.get(meta["raw_path"])
        if source_id is None:
            continue

        targets = []
        for item in parse_items(page_html):
            if item["artist_name"]:
                continue
            name_en = (item["artist_name_en"] or "").strip().lower()
            if not name_en:
                reasons["작가명 자체가 없음(민화·전통공예 등 구조적 미연결)"] += 1
                continue
            artist_id = en_index.get(name_en)
            if artist_id is None:
                reasons["영문명이 기존 작가와 정확히 일치하지 않음(로마자 표기 차이)"] += 1
                continue
            targets.append((item, artist_id))

        if not targets:
            continue

        cur.execute(
            "select id::text, title, medium, dimensions from artworks "
            "where source_id = %s::uuid and artist_id is null",
            (source_id,),
        )
        by_key: dict[tuple, list[str]] = {}
        for aid, title, medium, dimensions in cur.fetchall():
            by_key.setdefault((title, medium, dimensions), []).append(aid)

        for item, artist_id in targets:
            key = (item["title"] or "(제목 미상)", item["medium"], item["dimensions"])
            candidates = by_key.get(key) or []
            if len(candidates) != 1:
                reasons["작품 행 특정 실패(동일 스펙 중복 또는 이미 연결됨)"] += 1
                continue
            if args.apply:
                cur.execute(
                    "update artworks set artist_id = %s::uuid where id = %s::uuid and artist_id is null",
                    (artist_id, candidates[0]),
                )
            updated += 1

    if args.apply:
        conn.commit()

    print(f"[kam-backfill] {'연결' if args.apply else '연결 예정'} {updated}건")
    print("[kam-backfill] 미연결 사유 분해:")
    for reason, count in reasons.most_common():
        print(f"    {count:>6}  {reason}")
    if not args.apply:
        print("[kam-backfill] 리포트 모드 — 반영하려면 --apply")


if __name__ == "__main__":
    main()
