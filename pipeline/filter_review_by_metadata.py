"""철자변형_검토대상.json(593건/532그룹)을 DB의 nationality/birth_year로 재검증.

backfill_artist_metadata.py로 채워진 artists.nationality/birth_year를 이용해,
keep 작가와 dupe 후보가 국적이 다르거나(둘 다 non-null인데 불일치) 생몰년이
크게 다르면(둘 다 non-null인데 15년 넘게 차이) "동명이인 확정"으로 보고
검토 리스트에서 제외한다. 그 외(메타데이터 일치 또는 데이터 없음)는 계속
사용자 판단 대기로 남긴다. **자동 병합은 하지 않는다** — 이건 리스트를
줄이는 필터링만 수행.
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
BIRTH_YEAR_GAP_THRESHOLD = 15


def confirmed_different(keep_meta, dupe_meta) -> str | None:
    keep_nat, keep_birth = keep_meta
    dupe_nat, dupe_birth = dupe_meta
    if keep_nat and dupe_nat and keep_nat.strip().lower() != dupe_nat.strip().lower():
        return f"nationality mismatch: {keep_nat!r} vs {dupe_nat!r}"
    if keep_birth and dupe_birth and abs(keep_birth - dupe_birth) > BIRTH_YEAR_GAP_THRESHOLD:
        return f"birth_year gap {abs(keep_birth - dupe_birth)}: {keep_birth} vs {dupe_birth}"
    return None


def main() -> None:
    with open(REVIEW_PATH, encoding="utf-8") as f:
        review_entries = json.load(f)

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    all_ids = set()
    for entry in review_entries:
        all_ids.add(entry["keep_id"])
        for d in entry["dupes"]:
            all_ids.add(d["id"])

    cur.execute(
        "select id, nationality, birth_year from artists where id = any(%s::uuid[])",
        (list(all_ids),),
    )
    meta_by_id = {str(r[0]): (r[1], r[2]) for r in cur.fetchall()}

    excluded = []
    remaining_entries = []
    no_metadata_count = 0
    total_pairs = 0

    for entry in review_entries:
        keep_meta = meta_by_id.get(entry["keep_id"], (None, None))
        still_dupes = []
        for d in entry["dupes"]:
            total_pairs += 1
            dupe_meta = meta_by_id.get(d["id"], (None, None))
            reason = confirmed_different(keep_meta, dupe_meta)
            if reason:
                excluded.append(
                    {
                        "keep_id": entry["keep_id"],
                        "keep_name": entry["keep_name"],
                        "dupe_id": d["id"],
                        "dupe_name": d["name"],
                        "reason": reason,
                    }
                )
            else:
                if keep_meta == (None, None) and dupe_meta == (None, None):
                    no_metadata_count += 1
                still_dupes.append(d)
        if still_dupes:
            remaining_entries.append(
                {
                    "keep_id": entry["keep_id"],
                    "keep_name": entry["keep_name"],
                    "keep_richness": entry["keep_richness"],
                    "dupes": still_dupes,
                }
            )

    print(f"[filter] 검토 대상 총 {total_pairs}쌍 재검증")
    print(f"[filter] 메타데이터로 '동명이인 확정' -> 제외: {len(excluded)}쌍")
    print(f"[filter] 양쪽 다 메타데이터 없어 판단 불가(그대로 남음): {no_metadata_count}쌍")
    remaining_count = sum(len(e["dupes"]) for e in remaining_entries)
    print(f"[filter] 최종 남은 검토 대상: {remaining_count}쌍 ({len(remaining_entries)}개 그룹)")

    with open(REVIEW_PATH, "w", encoding="utf-8") as f:
        json.dump(remaining_entries, f, ensure_ascii=False, indent=2)
    print(f"[filter] 검토 파일 갱신: {REVIEW_PATH}")

    excluded_path = os.path.join(
        os.path.dirname(__file__), "..", "docs",
        f"철자변형_동명이인제외_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json",
    )
    excluded_path = os.path.abspath(excluded_path)
    with open(excluded_path, "w", encoding="utf-8") as f:
        json.dump(excluded, f, ensure_ascii=False, indent=2)
    print(f"[filter] 제외 근거 로그 저장: {excluded_path}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
