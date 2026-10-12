"""귀속 수식어가 없는 '순수 철자변형' 중복 artists 병합.

audit_attribution_variants.py가 만든 스코프 리포트의 2번 섹션(순수 철자변형
후보)은 블로킹이 느슨해(첫 단어 일치 + 문자열 유사도) 동명이인 오탐이 많았음
(예: "Larsen Stevns, Niels" vs "Larsen Stevns, Anna" — 남매, "Eugene Atget"
vs "Eugene Savage" — 이름만 비슷한 다른 사람). 이 스크립트는 훨씬 엄격한
기준으로 재필터링해서 안전한 것만 병합한다:

1. core name에서 공백/하이픈/구두점을 전부 제거한 뒤 **절대 편집거리** 비교
   (비율이 아니라 절대값 — 진짜 철자 오타/표기변형은 이름 길이와 무관하게
   보통 1~3글자 차이지만, 동명이인은 이름이 길수록 비율상 비슷해 보여도
   절대 차이가 큼).
2. anonymous/unknown류 placeholder 이름(Ubekendt, Anonymous, Unbekannt 등)은
   애초에 개별 인물이 아니므로 제외.
3. nationality/birth_year 등 메타데이터가 둘 다 있는데 서로 명백히 다르면
   (국적 다름, 출생년도 30년 이상 차이) 동명이인 가능성으로 보고 제외.
4. attribution 수식어가 있는 행은 애초에 대상에서 제외(mixed 그룹은 이미
   병합하지 않기로 확정됨 — 별도 스코프).

--apply 없이 실행하면 dry-run(후보만 출력, DB 변경 없음). --apply를 줘야
실제 병합(artworks/gallery_representations의 artist_id 재배정 + 중복 행 삭제)
을 수행하고, 병합 내역을 로그 파일에 남긴다.
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

sys.stdout.reconfigure(encoding="utf-8")

PLACEHOLDER_WORDS = {
    "anonymous", "anonyme", "anonimo", "unbekannt", "onbekend", "ubekendt",
    "unknown", "inconnu", "desconocido", "sconosciuto", "okänd", "tuntematon",
    "neznamy", "nn", "n n",
}

MAX_EDIT_DISTANCE = 3
MAX_BIRTH_YEAR_GAP = 30


def concat_key(core: str) -> str:
    return re.sub(r"[\s\-.,']", "", core)


def is_placeholder(core: str) -> bool:
    tokens = set(core.split())
    return bool(tokens & PLACEHOLDER_WORDS)


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * lb
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[lb]


def metadata_conflicts(a, b) -> bool:
    nat_a, birth_a = a
    nat_b, birth_b = b
    if nat_a and nat_b and nat_a.strip().lower() != nat_b.strip().lower():
        return True
    if birth_a and birth_b and abs(birth_a - birth_b) > MAX_BIRTH_YEAR_GAP:
        return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 병합 수행 (기본은 dry-run)")
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
    print(f"[merge] 전체 artists {len(rows)}건 로드 완료")

    by_first_word: dict[str, list[tuple]] = defaultdict(list)
    for aid, name, nationality, birth_year, artwork_n, holding_n in rows:
        norm = normalize(name)
        core, has_attr = extract_core(norm)
        if has_attr:
            continue  # mixed 그룹은 종료 확정 — 대상 아님
        if not core or is_placeholder(core):
            continue
        richness = artwork_n + holding_n
        first_word = core.split(" ", 1)[0]
        # 모노그램류(예: "I.S.", "U.B.K.")는 애초에 후보 블록에 넣지 않음 —
        # 서로 다른 미상 작가를 우연한 편집거리로 묶어버리는 사고가 실제 발생함.
        if all(len(w) <= 2 for w in core.split(" ")):
            continue
        if "#" in core or re.search(r"\d{3,}", core):
            continue  # 시스템 생성 placeholder ID(예: "#PredmetAutorFoto:322314")는 사람 이름이 아님
        by_first_word[first_word].append(
            (core, str(aid), name, richness, nationality, birth_year)
        )

    MAX_BLOCK = 300
    MAX_CLUSTER_DUPES = 10  # 이보다 크면 알고리즘 오탐 가능성이 높아 자동 병합 대상에서 제외, 별도 리포트
    MAX_WORD_EDIT_DISTANCE = 2
    # 편집거리 <=1(대개 오타/OCR류)만 고신뢰로 보고 자동 병합, ==2는 검토용 리스트로만 남김.
    # 이유: "Alphonse Legros" vs "Alphonse Leroy", "Emile Bernard" vs "Emile Béchard"처럼
    # 편집거리 2인 서로 다른 실존 인물 쌍이 실제로 발견됨 — 2는 오탐 위험이 너무 큼.
    AUTO_MERGE_MAX_WORD_EDIT_DISTANCE = 1

    # "a"/"b"/"c" 등 단독 알파벳 한 글자는 로마숫자와 별개로, 동명이인 구분용
    # 접미사로 실제 쓰인다(예: MMCA "김원 a"/"김원 b" — 같은 이름의 서로 다른
    # 두 작가를 구분하려고 붙인 것. 2026-09-08 실제 오탐으로 확인 — 최소 30건
    # 이상의 서로 다른 한국 작가가 이 패턴으로 잘못 병합됐다가 롤백함).
    GENERATION_RE = re.compile(
        r"^\(?(i|ii|iii|iv|v|jr\.?|sr\.?|the elder|the younger|[a-z])\)?[,.]?$"
    )

    def generation_marker(word: str) -> str | None:
        return word if GENERATION_RE.match(word) else None

    def word_align(core_a: str, core_b: str) -> int | None:
        """단어 수가 같고, 같은 위치의 단어끼리 편집거리가 작을 때만 통과,
        통과 시 단어들 사이 최대 편집거리를 반환(그 값으로 신뢰도 등급을 나눔).
        전체 문자열을 이어붙여 비교하면(concat) 우연히 글자가 겹쳐 서로 다른
        사람이 걸리는 문제(Eugène Atget vs Eugène Béjot 등)가 있어, 반드시
        단어 단위로 정렬해서 비교한다 — 진짜 철자변형은 보통 이름은 그대로고
        성(surname) 한 단어만 살짝 다르다.
        세대 표기(I/II/III, Jr/Sr 등)가 단어 단위로 서로 다르면, 부자/삼촌-조카
        등 실제 다른 인물(예: Crispijn van de Passe I/II, Aegidius Sadeler I/II)일
        가능성이 높아 편집거리와 무관하게 항상 거부한다."""
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
        # 모든 단어가 완전히 다르면(즉 하나도 안 같으면) 실제로는 다른 이름일
        # 가능성이 높음 — 최소 한 단어는 정확히 일치해야 함(대개 이름 부분)
        if diff_words == len(words_a):
            return None
        return max_dist

    skipped_blocks = 0
    clusters = []
    oversized_clusters = []
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
            matched = []  # (cand, dist)
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
                    oversized_clusters.append(cluster)
                else:
                    clusters.append(cluster)

    if oversized_clusters:
        print(
            f"[merge] 자동 병합에서 제외한 대형 클러스터(중복 {MAX_CLUSTER_DUPES}건 초과, "
            f"오탐 위험 높아 수동 검토 필요): {len(oversized_clusters)}개"
        )
        for cluster in oversized_clusters[:5]:
            names = [c[2] for c, _ in cluster[1:4]]
            print(f"  - keep {cluster[0][0][2]!r} 후보 {len(cluster) - 1}건 (예: {names})")

    print(f"[merge] 엄격 재필터링 후 클러스터: {len(clusters)}개 (스킵된 대형 블록 {skipped_blocks}개)")

    clusters.sort(key=lambda c: -sum(it[3] for it, _ in c))

    log_entries = []      # tier A — 자동 병합 (편집거리 <=1)
    review_entries = []   # tier B — 검토용, 병합 안 함 (편집거리 ==2)
    for cluster in clusters:
        keep = cluster[0][0]
        auto_dupes = [c for c, d in cluster[1:] if d <= AUTO_MERGE_MAX_WORD_EDIT_DISTANCE]
        review_dupes = [c for c, d in cluster[1:] if d > AUTO_MERGE_MAX_WORD_EDIT_DISTANCE]
        if auto_dupes:
            log_entries.append(
                {
                    "keep_id": keep[1],
                    "keep_name": keep[2],
                    "keep_richness": keep[3],
                    "dupes": [
                        {"id": d[1], "name": d[2], "richness": d[3]} for d in auto_dupes
                    ],
                }
            )
        if review_dupes:
            review_entries.append(
                {
                    "keep_id": keep[1],
                    "keep_name": keep[2],
                    "keep_richness": keep[3],
                    "dupes": [
                        {"id": d[1], "name": d[2], "richness": d[3]} for d in review_dupes
                    ],
                }
            )

    total_dupes = sum(len(e["dupes"]) for e in log_entries)
    total_review = sum(len(e["dupes"]) for e in review_entries)
    print(f"[merge] 자동 병합 대상(편집거리<=1): {total_dupes}건 ({len(log_entries)}개 canonical로 수렴)")
    print(f"[merge] 검토용(편집거리==2, 병합 안 함): {total_review}건 ({len(review_entries)}개 그룹)")

    print("\n[merge] 자동 병합 대상 상위 30개 미리보기:")
    for entry in log_entries[:30]:
        dupe_names = ", ".join(f"{d['name']!r}(r={d['richness']})" for d in entry["dupes"])
        print(f"  keep {entry['keep_name']!r}(r={entry['keep_richness']}) <- {dupe_names}")

    print("\n[merge] 검토용(병합 안 함) 상위 20개 미리보기:")
    for entry in review_entries[:20]:
        dupe_names = ", ".join(f"{d['name']!r}(r={d['richness']})" for d in entry["dupes"])
        print(f"  keep {entry['keep_name']!r}(r={entry['keep_richness']}) <- {dupe_names}")

    review_path = os.path.join(
        os.path.dirname(__file__), "..", "docs", "철자변형_검토대상.json"
    )
    review_path = os.path.abspath(review_path)
    with open(review_path, "w", encoding="utf-8") as f:
        json.dump(review_entries, f, ensure_ascii=False, indent=2)
    print(f"\n[merge] 검토용 리스트 저장(병합 안 됨): {review_path}")

    if not args.apply:
        print("\n[merge] dry-run — DB 변경 없음. --apply로 실행하면 실제 병합됩니다.")
        cur.close()
        conn.close()
        return

    merged = 0
    for entry in log_entries:
        keep_id = entry["keep_id"]
        dupe_ids = [d["id"] for d in entry["dupes"]]

        # 되돌릴 수 있도록 병합 전에 영향받는 artwork/gallery_representation id를 로그에 남김
        cur.execute("select id from artworks where artist_id = any(%s::uuid[])", (dupe_ids,))
        entry["moved_artwork_ids"] = [str(r[0]) for r in cur.fetchall()]
        cur.execute(
            "select id from gallery_representations where artist_id = any(%s::uuid[])",
            (dupe_ids,),
        )
        entry["moved_gallery_representation_ids"] = [str(r[0]) for r in cur.fetchall()]

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

    conn.commit()
    print(f"\n[merge] {merged}건 병합 완료 ({len(log_entries)}개 canonical로 수렴)")

    log_path = os.path.join(
        os.path.dirname(__file__), "..", "docs",
        f"철자변형병합로그_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json",
    )
    log_path = os.path.abspath(log_path)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_entries, f, ensure_ascii=False, indent=2)
    print(f"[merge] 병합 로그 저장: {log_path}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
