"""merge_spelling_variant_artists.py가 자동 병합에서 제외했던 '대형 클러스터'
(중복 10건 초과, 오탐 위험 높다고 판단해 순수 문자열 유사도만으로는 못 거른
것들 — Wang Hui류/Gerard Dow-Douw류 등)을, 이후 두 차례 백필로 훨씬 많아진
nationality/birth_year 메타데이터로 다시 걸러본다.

**로직은 merge_spelling_variant_artists.py와 완전히 동일**(word 정렬 비교,
세대표기 가드, 편집거리 <=1 자동병합/==2 검토용 분리, metadata_conflicts로
동명이인 배제) — 다른 점은 metadata_conflicts가 이제 실제로 국적/생몰년
데이터를 갖고 판단할 수 있는 쌍이 많아졌다는 것뿐이다. 이 스크립트는
`docs/철자변형_검토대상.json`(기존에 쌓아온 517건 검토 리스트)을 절대
덮어쓰지 않는다 — 별도 파일에만 결과를 남긴다.

기본은 dry-run. --apply로 tier A(편집거리<=1, 메타데이터 비충돌)만 실제 병합.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

import psycopg2

sys.path.insert(0, os.path.dirname(__file__))
from audit_attribution_variants import normalize, extract_core  # noqa: E402
from merge_spelling_variant_artists import (  # noqa: E402
    is_placeholder,
    levenshtein,
    metadata_conflicts,
)

sys.stdout.reconfigure(encoding="utf-8")

MAX_BLOCK = 300
MAX_CLUSTER_DUPES = 10
MAX_WORD_EDIT_DISTANCE = 2
AUTO_MERGE_MAX_WORD_EDIT_DISTANCE = 1

# 흔한 동아시아 성(로마자 표기)으로 시작하는 이름은 편집거리<=1이어도 자동병합
# 금지, 검토용으로만 — 짧은 한자 이름(성+1~2음절)이 서로 다른 실존 인물인데
# 우연히 편집거리 1~2로 붙는 사례가 실제로 다수 확인됨(Zhang Hong/Heng/Zhong,
# Wu Bing/Bin 등, 2026-09-08). 성씨 자체가 흔해 진짜 철자변형인지 동명이인인지
# 문자열만으로 구분 불가 — 항상 사람 검토로 넘긴다.
EAST_ASIAN_SURNAMES = {
    "wang", "zhang", "wu", "li", "chen", "liu", "yang", "huang", "zhao", "zhou",
    "xu", "sun", "ma", "gao", "lin", "he", "guo", "luo", "song", "xie", "tang",
    "han", "cao", "deng", "xiao", "feng", "zeng", "cheng", "peng", "kim", "lee",
    "park", "choi", "jung", "kang", "cho", "yoon", "jang", "lim", "oh", "goto",
    "gotô", "sato", "suzuki", "takahashi", "watanabe", "ito", "yamamoto",
    "nakamura", "kobayashi", "utagawa", "katsushika", "tosa", "kano",
}


def is_east_asian_surname_led(core: str) -> bool:
    first_word = core.split(" ", 1)[0]
    return first_word in EAST_ASIAN_SURNAMES

GENERATION_RE = re.compile(r"^\(?(i|ii|iii|iv|v|jr\.?|sr\.?|the elder|the younger|[a-z])\)?[,.]?$")


def generation_marker(word: str) -> str | None:
    return word if GENERATION_RE.match(word) else None


def word_align(core_a: str, core_b: str) -> int | None:
    words_a = core_a.split(" ")
    words_b = core_b.split(" ")
    if len(words_a) != len(words_b):
        return None
    diff_words = 0
    max_dist = 0
    for wa, wb in zip(words_a, words_b):
        if wa == wb:
            continue
        gen_a, gen_b = generation_marker(wa), generation_marker(wb)
        if (gen_a or gen_b) and gen_a != gen_b:
            return None
        if abs(len(wa) - len(wb)) > MAX_WORD_EDIT_DISTANCE:
            return None
        d = levenshtein(wa, wb)
        if d > MAX_WORD_EDIT_DISTANCE:
            return None
        max_dist = max(max_dist, d)
        diff_words += 1
    if diff_words == len(words_a):
        return None
    return max_dist


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    cur.execute(
        """
        select a.id, a.name, a.nationality, a.birth_year,
               coalesce(aw.n, 0) as artwork_n,
               coalesce(mh.n, 0) as holding_n
        from artists a
        left join (select artist_id, count(*) n from artworks group by artist_id) aw
          on aw.artist_id = a.id
        left join (
          select w.artist_id, count(*) n
          from museum_holdings mh
          join artworks w on w.id = mh.artwork_id
          group by w.artist_id
        ) mh
          on mh.artist_id = a.id
        """
    )
    rows = cur.fetchall()
    print(f"[resplit] 전체 artists {len(rows)}건 로드 완료")

    by_first_word: dict[str, list[tuple]] = defaultdict(list)
    for aid, name, nationality, birth_year, artwork_n, holding_n in rows:
        norm = normalize(name)
        core, has_attr = extract_core(norm)
        if has_attr:
            continue
        if not core or is_placeholder(core):
            continue
        if all(len(w) <= 2 for w in core.split(" ")):
            continue  # 모노그램류 제외 — 서로 다른 미상 작가가 우연히 편집거리로 묶이는 사고 방지
        if "#" in core or re.search(r"\d{3,}", core):
            continue  # 시스템 생성 placeholder ID(예: "#PredmetAutorFoto:322314")는 사람 이름이 아님
        richness = artwork_n + holding_n
        first_word = core.split(" ", 1)[0]
        by_first_word[first_word].append((core, str(aid), name, richness, nationality, birth_year))

    skipped_blocks = 0
    clusters = []
    still_oversized = []
    for first_word, items in by_first_word.items():
        if len(items) < 2:
            continue
        if len(items) > MAX_BLOCK:
            skipped_blocks += 1
            continue
        remaining = list(items)
        remaining.sort(key=lambda it: -it[3])
        while remaining:
            keep = remaining.pop(0)
            matched = []
            still_remaining = []
            for cand in remaining:
                if metadata_conflicts((keep[4], keep[5]), (cand[4], cand[5])):
                    still_remaining.append(cand)
                    continue
                dist = word_align(keep[0], cand[0])
                if dist is not None:
                    matched.append((cand, dist))
                else:
                    still_remaining.append(cand)
            remaining = still_remaining
            if matched:
                cluster = [(keep, 0)] + matched
                if len(matched) > MAX_CLUSTER_DUPES:
                    still_oversized.append(cluster)
                else:
                    clusters.append(cluster)

    print(f"[resplit] 메타데이터 재적용 후에도 여전히 대형(>{MAX_CLUSTER_DUPES}건)인 클러스터: {len(still_oversized)}개")
    print(f"[resplit] 메타데이터로 걸러져 새로 병합 가능해진 클러스터: {len(clusters)}개")

    log_entries = []
    review_entries = []
    for cluster in clusters:
        keep = cluster[0][0]
        east_asian = is_east_asian_surname_led(keep[0])
        auto_dupes = [
            c for c, d in cluster[1:]
            if d <= AUTO_MERGE_MAX_WORD_EDIT_DISTANCE and not east_asian
        ]
        review_dupes = [
            c for c, d in cluster[1:]
            if d > AUTO_MERGE_MAX_WORD_EDIT_DISTANCE or east_asian
        ]
        if auto_dupes:
            log_entries.append(
                {
                    "keep_id": keep[1], "keep_name": keep[2], "keep_richness": keep[3],
                    "dupes": [{"id": d[1], "name": d[2], "richness": d[3]} for d in auto_dupes],
                }
            )
        if review_dupes:
            review_entries.append(
                {
                    "keep_id": keep[1], "keep_name": keep[2], "keep_richness": keep[3],
                    "dupes": [{"id": d[1], "name": d[2], "richness": d[3]} for d in review_dupes],
                }
            )

    total_auto = sum(len(e["dupes"]) for e in log_entries)
    total_review = sum(len(e["dupes"]) for e in review_entries)
    print(f"[resplit] 자동 병합 대상(편집거리<=1): {total_auto}건 ({len(log_entries)}개 canonical)")
    print(f"[resplit] 검토용(편집거리==2): {total_review}건 ({len(review_entries)}개 그룹)")

    print("\n[resplit] 자동 병합 대상 미리보기:")
    for entry in log_entries[:30]:
        dupe_names = ", ".join(f"{d['name']!r}(r={d['richness']})" for d in entry["dupes"])
        print(f"  keep {entry['keep_name']!r}(r={entry['keep_richness']}) <- {dupe_names}")

    print("\n[resplit] 여전히 대형인 클러스터(수동 검토, 병합 안 함) 상위 10개:")
    for cluster in still_oversized[:10]:
        keep_name = cluster[0][0][2]
        names = [c[2] for c, _ in cluster[1:6]]
        print(f"  keep {keep_name!r} 후보 {len(cluster) - 1}건 (예: {names}...)")

    still_oversized_out = [
        {
            "keep_name": cluster[0][0][2],
            "keep_id": cluster[0][0][1],
            "candidates": [{"id": c[1], "name": c[2], "richness": c[3]} for c, _ in cluster[1:]],
        }
        for cluster in still_oversized
    ]
    oversized_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "docs", "철자변형_대형클러스터_잔여.json")
    )
    with open(oversized_path, "w", encoding="utf-8") as f:
        json.dump(still_oversized_out, f, ensure_ascii=False, indent=2)
    print(f"\n[resplit] 잔여 대형 클러스터 저장: {oversized_path}")

    review_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "docs", "철자변형_대형클러스터_재분류_검토.json")
    )
    with open(review_path, "w", encoding="utf-8") as f:
        json.dump(review_entries, f, ensure_ascii=False, indent=2)
    print(f"[resplit] 재분류 검토용(병합 안 함) 저장: {review_path}")

    if not args.apply:
        print("\n[resplit] dry-run — DB 변경 없음. --apply로 실행하면 실제 병합됩니다.")
        cur.close()
        conn.close()
        return

    merged = 0
    for entry in log_entries:
        keep_id = entry["keep_id"]
        dupe_ids = [d["id"] for d in entry["dupes"]]

        cur.execute("select id from artworks where artist_id = any(%s::uuid[])", (dupe_ids,))
        entry["moved_artwork_ids"] = [str(r[0]) for r in cur.fetchall()]
        cur.execute(
            "select id from gallery_representations where artist_id = any(%s::uuid[])", (dupe_ids,)
        )
        entry["moved_gallery_representation_ids"] = [str(r[0]) for r in cur.fetchall()]

        cur.execute(
            "update artworks set artist_id = %s where artist_id = any(%s::uuid[])", (keep_id, dupe_ids)
        )
        cur.execute(
            "update gallery_representations set artist_id = %s where artist_id = any(%s::uuid[])",
            (keep_id, dupe_ids),
        )
        cur.execute("delete from artists where id = any(%s::uuid[])", (dupe_ids,))
        merged += len(dupe_ids)

    conn.commit()
    print(f"\n[resplit] {merged}건 병합 완료 ({len(log_entries)}개 canonical)")

    log_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__), "..", "docs",
            f"철자변형_대형클러스터_병합로그_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json",
        )
    )
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_entries, f, ensure_ascii=False, indent=2)
    print(f"[resplit] 병합 로그 저장: {log_path}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
