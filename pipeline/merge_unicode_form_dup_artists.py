"""작가 이름 유니코드 정규화 형태(NFC/NFD) 차이 중복 병합.

merge_case_dup_artists.py는 SQL lower()로 그룹화해 순수 대소문자 차이만
잡는다. 그런데 "ANDRÉ BUTZER"와 "André Butzer"처럼 화면에는 똑같이 보여도
내부적으로 조합형(NFC, é = U+00E9 한 글자)과 완성형 분해(NFD, e + ́ 두 글자)
가 섞여 들어간 경우는 SQL lower()로도 서로 다른 문자열로 남아 안 잡힌다
(audit_gallery_artist_matches.py 감사 중 발견 — 예: André Butzer, Günther
Förg 등). 이건 사람이 봐도 완전히 동일한 표기라 동명이인 위험이 없는
케이스라서, unicodedata.normalize("NFC", ...) 후 lower()로 그룹화해 병합한다.

canonical 선택 기준은 merge_case_dup_artists.py와 동일(전체 대문자가
아닌 쪽 우선, 메타데이터 채워진 쪽 우선).
"""
from __future__ import annotations

import unicodedata

from db import get_connection


def nfc_lower(name: str) -> str:
    return unicodedata.normalize("NFC", name).lower()


def is_all_caps(name: str) -> bool:
    letters = [c for c in name if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def main() -> None:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("select id, name, nationality, birth_year, death_year from artists")
    rows = cur.fetchall()

    groups: dict[str, list[tuple]] = {}
    for row in rows:
        key = nfc_lower(row[1])
        groups.setdefault(key, []).append(row)

    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"[merge_unicode_form] 대상 그룹 {len(dup_groups)}개")

    total_merged = 0
    total_repointed = 0
    for key, members in dup_groups.items():
        # SQL lower() 기준으로 이미 동일하면(순수 대소문자 차이) merge_case_dup_artists.py 몫이니 스킵
        if len({m[1].lower() for m in members}) == 1:
            continue

        def score(r):
            _, name, nat, by, dy = r
            meta = sum(1 for v in (nat, by, dy) if v)
            return (0 if is_all_caps(name) else 1, meta)

        members.sort(key=score, reverse=True)
        canonical_id = members[0][0]
        loser_ids = [m[0] for m in members[1:]]

        cur.execute("update artworks set artist_id = %s where artist_id = any(%s::uuid[])", (canonical_id, loser_ids))
        n1 = cur.rowcount
        cur.execute(
            "update gallery_representations set artist_id = %s where artist_id = any(%s::uuid[])",
            (canonical_id, loser_ids),
        )
        n2 = cur.rowcount
        cur.execute("delete from artists where id = any(%s::uuid[])", (loser_ids,))

        print(f"  병합: {[m[1] for m in members]} -> canonical={members[0][1]!r}")
        total_merged += len(loser_ids)
        total_repointed += n1 + n2

    conn.commit()
    print(f"[merge_unicode_form] 병합된 행 {total_merged}개, 재연결 {total_repointed}건")


if __name__ == "__main__":
    main()
