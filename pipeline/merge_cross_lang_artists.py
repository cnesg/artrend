"""작가 이름 교차언어(한글/로마자) 중복 병합 — 1차 확정 리스트.

confirmed_clusters에 적힌 id 그룹을 하나의 canonical artist로 합친다.
canonical 선택 기준: nationality/birth_year 등 메타데이터가 채워진 행 우선,
없으면 그룹 내 첫 번째 id.
"""
from __future__ import annotations

import os

import psycopg2

# 각 그룹: (사람 이름 설명, [artist id, ...])
confirmed_clusters: list[tuple[str, list[str]]] = [
    ("이우환/Lee Ufan", ["2309a292-8a47-45d3-86fc-c4c7733bd4f4", "a1609fe4-9ef7-439e-ad13-147c9e26a7ea"]),
    ("백남준/Nam June Paik", [
        "e6f075f3-11b1-4f20-9617-3c8cdb92321c",
        "d86620b2-41b9-4022-8626-eb06f4f9a6bb",
        "ef30e45b-4874-4750-93d3-cc4e17fe85e8",
    ]),
    ("박서보/Park Seo-bo", ["507ef4eb-4110-41b0-8a18-b5f2a7d72ff6", "1e9b9ba6-7b81-441e-83a7-41794f96fa0a"]),
    ("서도호/Do Ho Suh", ["a2b07197-cf81-442a-93ec-a16f2fcb0fec", "3411978a-dede-4ab4-8c33-f8775f842e33"]),
    ("양혜규/Haegue Yang", ["1a246cc7-e066-4f55-8de3-8b798668709f", "3ccd6b7c-a29b-4bfd-877b-aff9585fe6e9"]),
    ("윤형근/Yun Hyong-keun", [
        "75b54721-12d1-498e-9927-c3ac55fef574",
        "371ee733-b27d-424f-b33c-56d1aa51a01f",
        "d3276a43-4139-43f6-a569-80482c20c49d",
    ]),
    ("강익중/Ik-Joong Kang", ["fc5930e7-d155-46af-951e-d48767bcc930", "3e86663a-eb8d-46ff-9a34-02328872924c"]),
    ("이승택/Lee Seung-taek", [
        "b98e5a67-42fd-4f33-9c9c-1ce8704887e7",
        "ec33631d-2821-4b2d-a981-33766cfc03ce",
        "17216a17-23f1-4273-aab3-510e93a958e5",
    ]),
]


def main() -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    total_repointed = 0
    for label, ids in confirmed_clusters:
        cur.execute(
            "select id, name, nationality, birth_year, death_year from artists where id = any(%s::uuid[])",
            (ids,),
        )
        rows = cur.fetchall()
        if len(rows) != len(ids):
            print(f"[skip] {label}: 예상 id 중 일부가 이미 없음 ({len(rows)}/{len(ids)})")
            continue

        # canonical: 메타데이터(국적/생몰년)가 가장 많이 채워진 행 우선
        def score(r):
            _, _, nat,by, dy = r
            return sum(1 for v in (nat, by, dy) if v)

        rows.sort(key=score, reverse=True)
        canonical_id = rows[0][0]
        loser_ids = [r[0] for r in rows[1:]]

        cur.execute("update artworks set artist_id = %s where artist_id = any(%s::uuid[])", (canonical_id, loser_ids))
        n1 = cur.rowcount
        cur.execute(
            "update gallery_representations set artist_id = %s where artist_id = any(%s::uuid[])",
            (canonical_id, loser_ids),
        )
        n2 = cur.rowcount
        cur.execute("delete from artists where id = any(%s::uuid[])", (loser_ids,))

        total_repointed += n1 + n2
        print(f"[merge] {label}: canonical={rows[0][1]!r}, 병합된 행={len(loser_ids)}, "
              f"artworks 재연결={n1}, gallery_representations 재연결={n2}")

    conn.commit()
    print(f"완료 — 총 재연결 {total_repointed}건")


if __name__ == "__main__":
    main()
