"""오늘(2026-09-08) 적용한 철자변형 병합 3개 로그에서 확인된 오탐(모노그램류,
한국어 동명이인 구분 접미사 "a"/"b"/"c")을 되돌린다.

판정 기준: keep_name과 dupe_name에서 알파벳만 남기고(악센트 제거, 소문자화)
비교했을 때 값이 다르면 "실제로 다른 사람"으로 간주 — 이 검사로 걸러지는
사례는 전부 수동으로 육안 검토했고(모노그램 다중 오분류, "이름 a"/"이름 b"
접미사) 전부 확인된 오탐이었다.

복구 방법:
  - MMCA 출처 artwork는 accession_number(wrkMngNo)로 원본 raw json을 재조회해
    정확한 원래 artistnm을 얻어 정밀 재배정 가능.
  - 그 외 출처(met/getty_provenance_sales/rijksmuseum/aic/cleveland/europeana/
    wikidata_*)는 병합 로그에 artwork별 원래 dupe 매핑이 남아있지 않아(entry
    단위로만 집계됨) 정밀 재배정이 불가능 — 삭제됐던 작가 정체성(이름)만
    복원하고, 해당 작품들은 일단 keep_id 아래 남겨둔 채 잔여 이슈로 보고한다.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
import uuid

import psycopg2

sys.stdout.reconfigure(encoding="utf-8")

LOG_PATHS = [
    "철자변형병합로그_20260908_004836.json",
    "철자변형_저위험병합로그_20260908_005832.json",
    "철자변형_리서치판정_병합로그_20260908_021246.json",
]


def letters_only(n: str) -> str:
    nf = unicodedata.normalize("NFKD", n)
    nf = "".join(c for c in nf if not unicodedata.combining(c))
    return re.sub(r"[^a-zA-Z]", "", nf).lower()


def load_mmca_lookup() -> dict[str, str]:
    from raw_iter import RAW_ROOT

    lookup: dict[str, str] = {}
    mmca_dir = RAW_ROOT / "mmca"
    for path in mmca_dir.glob("*.json"):
        if path.name.endswith(".meta.json"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        wrk_no = data.get("wrkMngNo")
        artistnm = (data.get("artistnm") or "").strip()
        if wrk_no and artistnm:
            lookup[wrk_no] = artistnm
    return lookup


def main() -> None:
    docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")

    bad_entries = []
    for fname in LOG_PATHS:
        path = os.path.join(docs_dir, fname)
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
        for e in entries:
            kl = letters_only(e["keep_name"])
            if len(kl) > 4:
                continue
            bad_dupes = [d for d in e["dupes"] if letters_only(d["name"]) != kl]
            if bad_dupes:
                bad_entries.append({**e, "bad_dupes": bad_dupes, "source_log": fname})

    print(f"[rollback] 확인된 오탐 그룹: {len(bad_entries)}개")

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    print("[rollback] MMCA raw lookup 구성 중...")
    mmca_lookup = load_mmca_lookup()
    print(f"[rollback] MMCA 원본 레코드 {len(mmca_lookup)}건 인덱싱 완료")

    recreated_names: dict[str, str] = {}  # letters_only(name) + keep_id 조합 -> new artist id (동일 오탐 그룹 내 중복 방지용)
    precise_recovered = 0
    identity_only_restored = 0
    unresolved_artwork_ids: list[str] = []

    for entry in bad_entries:
        keep_id = entry["keep_id"]
        bad_dupe_names = {d["name"] for d in entry["bad_dupes"]}
        moved_artwork_ids = entry.get("moved_artwork_ids", [])

        if not moved_artwork_ids:
            # 이번 그룹은 이동된 artwork가 없음(gallery_representation만 있었거나 0건) — 정체성만 복원
            for name in bad_dupe_names:
                cur.execute(
                    "insert into artists (id, name) values (%s, %s) returning id",
                    (str(uuid.uuid4()), name),
                )
                identity_only_restored += 1
            continue

        # 이 그룹에서 이동된 artwork들의 출처 확인
        cur.execute(
            """
            select a.id, s.site_name, mh.accession_number
            from artworks a
            join sources s on s.id = a.source_id
            left join museum_holdings mh on mh.artwork_id = a.id
            where a.id = any(%s::uuid[])
            """,
            (moved_artwork_ids,),
        )
        artwork_info = cur.fetchall()

        # dupe 이름별로 새 artist row를 만들어둘 준비(그룹 내에서 실제 필요할 때만 생성)
        name_to_new_id: dict[str, str] = {}

        def get_new_artist_id(name: str) -> str:
            if name not in name_to_new_id:
                new_id = str(uuid.uuid4())
                cur.execute("insert into artists (id, name) values (%s, %s)", (new_id, name))
                name_to_new_id[name] = new_id
            return name_to_new_id[name]

        for artwork_id, site_name, accession_number in artwork_info:
            if site_name == "mmca" and accession_number and accession_number in mmca_lookup:
                original_name = mmca_lookup[accession_number]
                new_id = get_new_artist_id(original_name)
                cur.execute("update artworks set artist_id = %s where id = %s", (new_id, str(artwork_id)))
                precise_recovered += 1
            else:
                unresolved_artwork_ids.append(str(artwork_id))

        # 정밀 복구가 안 된 나머지 이름들도 최소한 정체성은 복원(작품 재배정은 안 함)
        for name in bad_dupe_names:
            if name not in name_to_new_id:
                get_new_artist_id(name)
                identity_only_restored += 1

    conn.commit()
    print(f"[rollback] 정밀 복구(MMCA, artwork까지 정확히 재배정): {precise_recovered}건")
    print(f"[rollback] 정체성만 복원(작품 재배정 안 됨, keep_id 아래 잔류): 관련 이름 {identity_only_restored}개")
    print(f"[rollback] 정밀 복구 못한 채 keep_id 아래 남은 artwork: {len(unresolved_artwork_ids)}건")

    out_path = os.path.abspath(os.path.join(docs_dir, "철자변형_오탐롤백_잔여이슈.json"))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "unresolved_artwork_ids": unresolved_artwork_ids,
                "note": "이 artwork들은 오탐 병합으로 삭제됐던 원래 작가에게 정밀 재배정하지 못했다 "
                        "(병합 로그가 entry 단위로만 artwork를 집계해 어떤 dupe에서 왔는지 구분 불가). "
                        "현재 keep_id(병합 당시의 canonical) 아래 남아있다.",
            },
            f, ensure_ascii=False, indent=2,
        )
    print(f"[rollback] 잔여 이슈 로그 저장: {out_path}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
