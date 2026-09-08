"""gallery_representations 완전 중복 (gallery_id, artist_id) 행 정리.

원인: 일부 갤러리 사이트 자체가 같은 작가에 대해 두 개의 서로 다른 URL을
서빙한다(예: paulacoopergallery.com의 /artists/chuck-close 와
/artists/chuck-close2 가 완전히 동일한 내용을 반환, ocimuseum.org도
artist/155·artist/156처럼 같은 작가에 다른 숫자 id가 붙은 페이지가 존재).
크롤러의 중복 방지는 href 단위라 이런 사이트 자체의 중복 URL은 서로 다른
raw 파일로 저장되고, pipeline/galleries.py의 load()도 raw_path 단위로만
already-loaded를 확인해 (gallery_id, artist_id) 쌍이 두 번 들어간다.

동명이인 위험이 없는 완전 중복(같은 gallery_id + 같은 artist_id)만 대상 —
이름 표기 차이로 인한 잠재적 중복이 아니라 문자 그대로 같은 행이 두 번
들어간 경우라 자동 정리 안전.

사용법:
    python pipeline/dedup_gallery_representations.py          # 리포트만
    python pipeline/dedup_gallery_representations.py --apply  # 실제 삭제
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from db import get_connection


def main() -> None:
    parser = argparse.ArgumentParser(description="gallery_representations 완전 중복 행 정리")
    parser.add_argument("--apply", action="store_true", help="실제 삭제 실행")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        select id, gallery_id, artist_id, created_at
        from gallery_representations
        order by gallery_id, artist_id, created_at
        """
    )
    rows = cur.fetchall()
    print(f"[dedup_gallery_representations] gallery_representations 전체 {len(rows)}건")

    groups: dict[tuple, list] = defaultdict(list)
    for row_id, gallery_id, artist_id, created_at in rows:
        groups[(gallery_id, artist_id)].append(row_id)

    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    to_delete = [rid for ids in dup_groups.values() for rid in ids[1:]]
    print(f"[dedup_gallery_representations] 중복 (gallery_id, artist_id) 쌍 {len(dup_groups)}개, 삭제 대상 {len(to_delete)}건")

    for (gallery_id, artist_id), ids in dup_groups.items():
        print(f"  gallery={gallery_id} artist={artist_id} -> {len(ids)}건 중 {len(ids) - 1}건 삭제 예정")

    if not args.apply:
        print("\n[dedup_gallery_representations] --apply 없이 리포트만 실행함 (DB 변경 없음)")
        return

    cur.execute("delete from gallery_representations where id = any(%s::uuid[])", (to_delete,))
    conn.commit()
    print(f"\n[dedup_gallery_representations] 완료 — {len(to_delete)}건 삭제")


if __name__ == "__main__":
    main()
