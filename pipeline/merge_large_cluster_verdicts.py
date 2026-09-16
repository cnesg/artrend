"""철자변형_대형클러스터_리서치판정_20260908.json 반영.

여전히 대형(>10건)이라 자동 병합 보류했던 10개 클러스터를 artrend-3a가
웹서치로 개별 판정(120쌍: merge 103 / keep_separate 17 / uncertain 5)한
결과를 실제 DB에 반영한다.

- decision=="merge": 각 클러스터의 keep_id로 정상 병합.
- keep_separate 중 "원래 클러스터와는 다르지만 자기들끼리는 같은 인물"인
  두 서브그룹은 별도로 처리(웹서치 판정문에 명시된 대로):
    1. la Rue 클러스터의 La Joue/La Jouë/la Joüe/La Joué 4건
       = Jacques de Lajoüe(1687-1761) 한 명 -> richness 최고인 "La Joue"를
         canonical로 나머지 3건 병합.
    2. Vander Helst 클러스터의 Vander Aelst/Vander Ælst 2건
       = Willem van Aelst(1627-c.1683) 한 명 -> richness 높은 "Vander Aelst"를
         canonical로 "Vander Ælst" 병합.
  그 외 keep_separate(La Rive, Vander Horst 등 진짜 별개 인물)와 uncertain은
  그대로 둔다.

기존 merge_research_verdicts.py와 동일한 롤백 가능 로그 패턴 사용.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import psycopg2

sys.stdout.reconfigure(encoding="utf-8")

VERDICT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "docs", "철자변형_대형클러스터_리서치판정_20260908.json")
)

# 웹서치 판정문에서 "서로 병합해도 됨"이라고 명시한 추가 서브그룹 병합
# (keep_separate로 분류돼 표준 merge 루프에는 안 걸리는 것들)
EXTRA_MERGES = [
    {
        "keep_id": "98a44f8c-6df0-4edb-aed1-1cf260d3f6db",
        "keep_name": "La Joue",
        "dupes": [
            {"id": "c6fa7c82-2e4b-498a-8324-10ddb17a631e", "name": "La Jouë",
             "reasoning": "Jacques de Lajoüe(1687-1761) 동일인 표기 변형, richness 최고인 La Joue를 canonical로"},
            {"id": "56ed8dff-923c-4e93-8aa9-814147350086", "name": "la Joüe",
             "reasoning": "Jacques de Lajoüe 동일인 표기 변형"},
            {"id": "0653f2ca-e30f-4c5e-9df3-f8a67f12bcbe", "name": "La Joué",
             "reasoning": "Jacques de Lajoüe 동일인 표기 변형"},
        ],
    },
    {
        "keep_id": "9af21d25-bf98-4bdc-99ec-5dff51c1b70b",
        "keep_name": "Vander Aelst",
        "dupes": [
            {"id": "6c2dad41-d37d-4744-8bc7-0d442012ea88", "name": "Vander Ælst",
             "reasoning": "Willem van Aelst(1627-c.1683) 동일인, Ælst는 Aelst의 리가처 표기 -- richness 높은 Vander Aelst를 canonical로"},
        ],
    },
]


def apply_merges(cur, merges_by_keep: dict[str, list[dict]]) -> tuple[int, list[dict]]:
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
    return merged, log_entries


def main() -> None:
    with open(VERDICT_PATH, encoding="utf-8") as f:
        verdicts = json.load(f)

    by_decision: dict[str, list] = {"merge": [], "keep_separate": [], "uncertain": []}
    for v in verdicts:
        by_decision.setdefault(v["decision"], []).append(v)

    print(f"[cluster-verdict] 판정 로드: merge={len(by_decision['merge'])} "
          f"keep_separate={len(by_decision['keep_separate'])} uncertain={len(by_decision.get('uncertain', []))}")

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    merges_by_keep: dict[str, list[dict]] = {}
    for v in by_decision["merge"]:
        merges_by_keep.setdefault(v["keep_id"], []).append(v)

    merged, log_entries = apply_merges(cur, merges_by_keep)
    print(f"[cluster-verdict] 표준 merge 판정 반영: {merged}건 ({len(log_entries)}개 canonical)")

    extra_merges_by_keep: dict[str, list[dict]] = {}
    for group in EXTRA_MERGES:
        extra_merges_by_keep[group["keep_id"]] = [
            {"dupe_id": d["id"], "dupe_name": d["name"], "keep_name": group["keep_name"], "reasoning": d["reasoning"]}
            for d in group["dupes"]
        ]
    extra_merged, extra_log_entries = apply_merges(cur, extra_merges_by_keep)
    print(f"[cluster-verdict] 서브그룹 추가 병합 반영: {extra_merged}건 ({len(extra_log_entries)}개 canonical) "
          "-- La Joue 계열, Vander Aelst 계열")

    conn.commit()
    total = merged + extra_merged
    print(f"[cluster-verdict] 전체 병합 완료: {total}건")

    log_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__), "..", "docs",
            f"철자변형_대형클러스터_병합로그_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json",
        )
    )
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({"standard_merges": log_entries, "extra_subgroup_merges": extra_log_entries}, f, ensure_ascii=False, indent=2)
    print(f"[cluster-verdict] 병합 로그 저장: {log_path}")

    kept_separate_names = [f"{v['dupe_name']} (vs {v['keep_name']})" for v in by_decision["keep_separate"]]
    uncertain_names = [f"{v['dupe_name']} (vs {v['keep_name']})" for v in by_decision.get("uncertain", [])]
    print(f"[cluster-verdict] keep_separate로 유지({len(kept_separate_names)}건): {kept_separate_names}")
    print(f"[cluster-verdict] uncertain으로 보류({len(uncertain_names)}건): {uncertain_names}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
