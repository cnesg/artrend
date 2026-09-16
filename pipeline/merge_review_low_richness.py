"""철자변형_검토대상.json(tier B, 편집거리==2)에서 dupe richness<=3인 항목만 병합.

사용자가 richness<=3(소장/작품 3건 이하 — 거의 확실히 동일 인물의 사소한
표기변형이고, 설령 오탐이어도 피해 규모가 작음)는 병합 진행, richness>=4는
artrend-3a가 사용자와 인터뷰로 개별 판단 중이므로 그대로 둔다.

실행 후 검토 파일 자체를 richness>=4 항목만 남도록 갱신해서 인터뷰 대상이
줄어든 걸 반영한다.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import psycopg2

sys.stdout.reconfigure(encoding="utf-8")

REVIEW_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "철자변형_검토대상.json")
REVIEW_PATH = os.path.abspath(REVIEW_PATH)
RICHNESS_THRESHOLD = 3


def main() -> None:
    with open(REVIEW_PATH, encoding="utf-8") as f:
        review_entries = json.load(f)

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    log_entries = []
    remaining_review_entries = []
    merged = 0

    for entry in review_entries:
        low_dupes = [d for d in entry["dupes"] if d["richness"] <= RICHNESS_THRESHOLD]
        high_dupes = [d for d in entry["dupes"] if d["richness"] > RICHNESS_THRESHOLD]

        if high_dupes:
            remaining_review_entries.append(
                {
                    "keep_id": entry["keep_id"],
                    "keep_name": entry["keep_name"],
                    "keep_richness": entry["keep_richness"],
                    "dupes": high_dupes,
                }
            )

        if not low_dupes:
            continue

        keep_id = entry["keep_id"]
        dupe_ids = [d["id"] for d in low_dupes]

        cur.execute("select id from artworks where artist_id = any(%s::uuid[])", (dupe_ids,))
        moved_artwork_ids = [str(r[0]) for r in cur.fetchall()]
        cur.execute(
            "select id from gallery_representations where artist_id = any(%s::uuid[])",
            (dupe_ids,),
        )
        moved_gallery_representation_ids = [str(r[0]) for r in cur.fetchall()]

        cur.execute(
            "update artworks set artist_id = %s where artist_id = any(%s::uuid[])",
            (keep_id, dupe_ids),
        )
        cur.execute(
            "update gallery_representations set artist_id = %s where artist_id = any(%s::uuid[])",
            (keep_id, dupe_ids),
        )
        cur.execute("delete from artists where id = any(%s::uuid[])", (dupe_ids,))
        merged += len(dupe_ids)

        log_entries.append(
            {
                "keep_id": keep_id,
                "keep_name": entry["keep_name"],
                "keep_richness": entry["keep_richness"],
                "dupes": low_dupes,
                "moved_artwork_ids": moved_artwork_ids,
                "moved_gallery_representation_ids": moved_gallery_representation_ids,
            }
        )

    conn.commit()
    print(f"[merge] richness<={RICHNESS_THRESHOLD} 병합 완료: {merged}건 ({len(log_entries)}개 그룹)")

    log_path = os.path.join(
        os.path.dirname(__file__), "..", "docs",
        f"철자변형_저위험병합로그_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json",
    )
    log_path = os.path.abspath(log_path)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_entries, f, ensure_ascii=False, indent=2)
    print(f"[merge] 병합 로그 저장: {log_path}")

    with open(REVIEW_PATH, "w", encoding="utf-8") as f:
        json.dump(remaining_review_entries, f, ensure_ascii=False, indent=2)
    remaining_count = sum(len(e["dupes"]) for e in remaining_review_entries)
    print(
        f"[merge] 검토 파일 갱신 완료: {REVIEW_PATH} "
        f"(남은 richness>{RICHNESS_THRESHOLD} 항목 {remaining_count}건, {len(remaining_review_entries)}개 그룹)"
    )

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
