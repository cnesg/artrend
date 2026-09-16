"""artrend-3a가 웹서치로 개별 판정한 철자변형_리서치판정_*.json을 반영.

decision=="merge"만 실제 병합(keep_id를 canonical로, 롤백 가능하게 로그).
keep_separate/uncertain은 병합하지 않고 docs/철자변형_검토대상.json에서만 제거
(uncertain은 근거 부족으로 그냥 보류 종료 — 더 이상 추적 안 함, 사용자 판단
필요하면 이 스크립트의 로그에서 다시 찾을 수 있음).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import psycopg2

sys.stdout.reconfigure(encoding="utf-8")

VERDICT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "docs", "철자변형_리서치판정_20260908.json")
)
REVIEW_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "docs", "철자변형_검토대상.json")
)


def main() -> None:
    with open(VERDICT_PATH, encoding="utf-8") as f:
        verdicts = json.load(f)

    by_decision: dict[str, list] = {"merge": [], "keep_separate": [], "uncertain": []}
    for v in verdicts:
        by_decision.setdefault(v["decision"], []).append(v)

    print(f"[verdict] 판정 로드: merge={len(by_decision['merge'])} "
          f"keep_separate={len(by_decision['keep_separate'])} uncertain={len(by_decision.get('uncertain', []))}")

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    # keep_id별로 dupe_id 묶기(같은 keep에 여러 dupe가 merge 판정났을 수 있음)
    merges_by_keep: dict[str, list[dict]] = {}
    for v in by_decision["merge"]:
        merges_by_keep.setdefault(v["keep_id"], []).append(v)

    log_entries = []
    merged = 0
    for keep_id, items in merges_by_keep.items():
        dupe_ids = [it["dupe_id"] for it in items]

        cur.execute("select id from artworks where artist_id = any(%s::uuid[])", (dupe_ids,))
        moved_artwork_ids = [str(r[0]) for r in cur.fetchall()]
        cur.execute(
            "select id from gallery_representations where artist_id = any(%s::uuid[])", (dupe_ids,)
        )
        moved_gallery_representation_ids = [str(r[0]) for r in cur.fetchall()]

        cur.execute(
            "update artworks set artist_id = %s where artist_id = any(%s::uuid[])", (keep_id, dupe_ids)
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
                "keep_name": items[0]["keep_name"],
                "dupes": [{"id": it["dupe_id"], "name": it["dupe_name"], "reasoning": it["reasoning"]} for it in items],
                "moved_artwork_ids": moved_artwork_ids,
                "moved_gallery_representation_ids": moved_gallery_representation_ids,
            }
        )

    conn.commit()
    print(f"[verdict] merge 판정 반영 완료: {merged}건 병합 ({len(log_entries)}개 canonical)")

    log_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__), "..", "docs",
            f"철자변형_리서치판정_병합로그_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json",
        )
    )
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_entries, f, ensure_ascii=False, indent=2)
    print(f"[verdict] 병합 로그 저장: {log_path}")

    # 검토 파일 갱신: merge/keep_separate/uncertain 전부 처리 완료로 보고 review에서 제거
    resolved_dupe_ids = {v["dupe_id"] for v in verdicts}
    with open(REVIEW_PATH, encoding="utf-8") as f:
        review_entries = json.load(f)

    remaining_entries = []
    for entry in review_entries:
        still_dupes = [d for d in entry["dupes"] if d["id"] not in resolved_dupe_ids]
        if still_dupes:
            remaining_entries.append({**entry, "dupes": still_dupes})

    with open(REVIEW_PATH, "w", encoding="utf-8") as f:
        json.dump(remaining_entries, f, ensure_ascii=False, indent=2)
    remaining_count = sum(len(e["dupes"]) for e in remaining_entries)
    print(f"[verdict] 검토 파일 갱신: {REVIEW_PATH} (남은 항목 {remaining_count}건, {len(remaining_entries)}개 그룹)")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
