"""gallery_representations의 artist_id가 실제로 올바른 artists 행에 매칭됐는지 감사.

get_or_create_artist()는 name.lower() 완전일치로만 매칭한다(pipeline/store.py).
갤러리 사이트의 표기(중간이름 생략, 철자 변형, 마침표 유무 등)가 미술관 소장품
표기와 달라 실제로는 동일 인물인데 별개 artists 행으로 중복 생성됐을 가능성이
있다 — 이 스크립트는 DB를 변경하지 않고, 이름을 정규화(악센트 제거·구두점 제거·
공백 정리)했을 때 서로 다른 artists.id인데 정규화된 이름이 같은 그룹을 찾아
리포트만 한다. gallery_representations로 연결된 작가만 우선 보고한다(원래
감사 대상).

사용법:
    python pipeline/audit_gallery_artist_matches.py
    python pipeline/audit_gallery_artist_matches.py --sample 20
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from db import get_connection


def normalize(name: str) -> str:
    # 악센트 제거 (Möller -> Moller, Jusidman -> Jusidman)
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    # 구두점/마침표 제거, 공백 정리, 소문자화
    cleaned = re.sub(r"[.\-'’,]", "", stripped)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


def main() -> None:
    parser = argparse.ArgumentParser(description="gallery_representations 작가명 매칭 감사")
    parser.add_argument("--sample", type=int, default=30, help="출력할 그룹 수")
    parser.add_argument(
        "--all-groups",
        action="store_true",
        help="갤러리 연결과 무관하게 미술관 소스 간 중복까지 전부 대상으로 샘플 출력",
    )
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    print("[audit] artists 전체 로드 중...")
    cur.execute("select id, name from artists")
    all_artists = cur.fetchall()
    print(f"[audit] artists {len(all_artists)}건")

    print("[audit] gallery_representations로 연결된 artist_id 로드 중...")
    cur.execute("select distinct artist_id from gallery_representations")
    gallery_artist_ids = {str(row[0]) for row in cur.fetchall()}
    print(f"[audit] 갤러리로 연결된 고유 artist_id {len(gallery_artist_ids)}건")

    # 정규화된 이름 -> [(id, 원래이름), ...]
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for aid, name in all_artists:
        groups[normalize(name)].append((str(aid), name))

    # 정규화 이름은 같은데 실제 id가 여러 개인 그룹만 후보로 추림
    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"[audit] 정규화 후 이름이 같은데 id가 다른 그룹 {len(dup_groups)}건 (전체)")

    # 그 중 최소 하나는 갤러리로 연결된 것만 우선순위로 필터
    gallery_related = {
        k: v for k, v in dup_groups.items() if any(aid in gallery_artist_ids for aid, _ in v)
    }
    print(f"[audit] 그중 갤러리 작가가 하나라도 포함된 그룹 {len(gallery_related)}건\n")

    target_groups = dup_groups if args.all_groups else gallery_related
    label = "전체(갤러리+미술관 소스 간)" if args.all_groups else "갤러리 포함"

    shown = 0
    for norm_name, members in sorted(target_groups.items(), key=lambda kv: -len(kv[1])):
        if shown >= args.sample:
            break
        tag = f"[{label}]"
        print(f"  {tag} 정규화명='{norm_name}' — {len(members)}개 서로 다른 id:")
        for aid, name in members:
            marker = " <- gallery_representations 연결" if aid in gallery_artist_ids else ""
            print(f"      {name!r} (id={aid}){marker}")
        shown += 1

    if len(target_groups) > args.sample:
        print(f"\n  ... 외 {len(target_groups) - args.sample}건 더 있음 (--sample로 더 보기)")

    print(
        "\n[audit] 이 스크립트는 리포트 전용이며 DB를 변경하지 않는다. "
        "실제 병합은 별도 dedup 스크립트(merge_case_dup_artists.py/merge_cross_lang_artists.py 사례)를 "
        "참고해 케이스별로 검토 후 진행할 것 — 동명이인 가능성도 있어 자동 병합은 위험."
    )


if __name__ == "__main__":
    main()
