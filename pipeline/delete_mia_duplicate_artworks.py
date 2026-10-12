"""mia 이중 적재 고아 artworks 삭제 — 2026-09-15 작업분담 §W1

원인: 2026-09-03 08시대에 같은 mia 벌크 로더가 두 번 돌아 artworks에
196,079건(museum_holdings 100,249건의 약 2배)이 적재됐다. 그중
museum_holdings/auction_lots 어디에도 연결되지 않은 95,830건이 고아
(소장/경매 없는) 행이며, 대부분 같은 title+year+dimensions를 가진
"다른 mia 행"이 실제 museum_holdings 연결을 갖고 있다 — 그 짝이 진짜 소장품이고
이 orphan은 중복 적재의 잔재.

판정: artworks 중 sources.site_name='mia'이고 museum_holdings/auction_lots
어디에도 연결되지 않은 행 전부.

동반 삭제: 해당 artwork_id를 참조하는 provenance_records,
vault_embeddings(doc_path에 id 앞 8자리 포함, artworks/ 폴더 export 규칙 —
cleanup_vault_orphans.py의 slugify 관례 재사용).

**기본은 dry-run(리포트만)이며, --apply 없이는 절대 DELETE하지 않는다.**
--apply 실행 후에도 idempotent — 재실행 시 대상 0건이 되어야 정상.

사용법:
    python pipeline/delete_mia_duplicate_artworks.py              # dry-run, 리포트 JSON 저장
    python pipeline/delete_mia_duplicate_artworks.py --apply       # 실제 삭제 (주의)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path(__file__).parent / ".env")

from db import get_connection  # noqa: E402

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "logs"

ID8_RE = re.compile(r"\(([0-9a-fA-F]{8})\)\.md$")

ORPHAN_QUERY = """
select w.id
from artworks w
join sources s on s.id = w.source_id
left join museum_holdings mh on mh.artwork_id = w.id
left join auction_lots al on al.artwork_id = w.id
where s.site_name = 'mia' and mh.id is null and al.id is null
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 삭제한다 (주의)")
    ap.add_argument("--batch-size", type=int, default=2000, help="삭제 배치 크기 (재개 가능성/커밋 단위)")
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("select count(*) from artworks w join sources s on s.id=w.source_id where s.site_name='mia'")
    total_mia = cur.fetchone()[0]

    cur.execute(ORPHAN_QUERY)
    orphan_ids = [str(r[0]) for r in cur.fetchall()]
    orphan_count = len(orphan_ids)

    print(f"[delete_mia] mia artworks 전체 {total_mia}건 / 고아(소장·경매 미연결) {orphan_count}건")

    in_range = 95000 <= orphan_count <= 96500
    print(f"[delete_mia] 자체진행 조건(a) 건수범위 95,000~96,500: {'충족' if in_range else '미충족'}")

    # 표본 50건 전수 검증: (a) 소장/경매 연결 없음 [정의상 항상 참]
    # (b) 같은 title+year+dimensions의 다른 mia 행이 museum_holdings 연결을 가짐
    #     (artist_id까지 엄격히 일치하는지는 별도로 표시만 하고 최종 판정에는 title/year/dimensions만 사용
    #      — 중복 로더 실행 사이에 artist 파싱이 달라진 사례(예: "Paul Caponigro" vs
    #      "Photographer: Paul Caponigro")가 있어 artist_id 일치를 조건에서 제외함.
    #      이 판단은 자체진행 여부에 영향을 주므로 --apply 전 반드시 메인 세션에 보고.)
    sample_ids = orphan_ids[:50]
    sample_detail = []
    strict_match = 0  # title+year+dimensions+artist_id/name 전부 일치
    loose_match = 0  # title+year+dimensions만 일치 (artist 무시)
    if sample_ids:
        cur.execute(
            """
            select w.id, w.artist_id, a0.name, w.title, w.year_created, w.dimensions
            from artworks w
            left join artists a0 on a0.id = w.artist_id
            where w.id = any(%s::uuid[])
            """,
            (sample_ids,),
        )
        rows = {str(r[0]): r for r in cur.fetchall()}

        for wid in sample_ids:
            _id, artist_id, artist_name, title, year, dims = rows[wid]
            cur.execute(
                """
                select w2.id, a1.name
                from artworks w2
                join sources s2 on s2.id = w2.source_id
                join museum_holdings mh2 on mh2.artwork_id = w2.id
                left join artists a1 on a1.id = w2.artist_id
                where s2.site_name = 'mia'
                  and w2.title = %s
                  and coalesce(w2.year_created, '') = coalesce(%s, '')
                  and coalesce(w2.dimensions, '') = coalesce(%s, '')
                """,
                (title, year, dims),
            )
            counterparts = cur.fetchall()
            has_loose = len(counterparts) > 0
            has_strict = any((cp_name or "") == (artist_name or "") for _cp_id, cp_name in counterparts)
            if has_loose:
                loose_match += 1
            if has_strict:
                strict_match += 1
            sample_detail.append(
                {
                    "orphan_id": wid,
                    "title": title,
                    "artist_name": artist_name,
                    "loose_match_b": has_loose,
                    "strict_match_b_incl_artist": has_strict,
                    "counterpart_artist_names": [cp_name for _cp_id, cp_name in counterparts],
                }
            )

    print(
        f"[delete_mia] 표본 {len(sample_ids)}건 중 조건(b) title+year+dimensions 일치(artist 무시): "
        f"{loose_match}/{len(sample_ids)}"
    )
    print(
        f"[delete_mia] 표본 {len(sample_ids)}건 중 조건(b) artist까지 엄격 일치: "
        f"{strict_match}/{len(sample_ids)}"
    )

    auto_apply_ok = in_range and strict_match == len(sample_ids) and len(sample_ids) > 0
    print(f"[delete_mia] 문서상 자체진행(--apply 무승인) 조건 충족 여부: {'예' if auto_apply_ok else '아니오 — 메인 승인 필요'}")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_mia_artworks": total_mia,
        "orphan_count": orphan_count,
        "condition_a_count_in_range": in_range,
        "sample_size": len(sample_ids),
        "condition_b_loose_match": loose_match,
        "condition_b_strict_match": strict_match,
        "auto_apply_ok_per_doc": auto_apply_ok,
        "sample_detail": sample_detail,
        "orphan_ids": orphan_ids,
    }
    out_path = DOCS_DIR / f"mia_이중적재_리포트_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[delete_mia] 상세 리포트 저장: {out_path}")

    if not args.apply:
        print("\n[delete_mia] dry-run — 삭제 없음. --apply로 실행하면 실제 삭제됩니다.")
        cur.close()
        conn.close()
        return

    # vault_embeddings: doc_path 끝의 (id8자리).md를 Python 정규식으로 한 번만 뽑아
    # 전체 orphan id 앞 8자리 집합과 비교 (cleanup_vault_orphans.py와 동일 관례)
    orphan_id8_set = {oid.replace("-", "")[:8].lower() for oid in orphan_ids}
    cur.execute("select id, doc_path from vault_embeddings where doc_type = 'artwork'")
    emb_ids_to_delete = [
        emb_id
        for emb_id, doc_path in cur.fetchall()
        if (m := ID8_RE.search(doc_path)) and m.group(1).lower() in orphan_id8_set
    ]

    # provenance_records, vault_embeddings 동반 삭제 + artworks 삭제 (배치 커밋 — 재개 가능)
    deleted_provenance = 0
    deleted_embeddings = 0
    deleted_artworks = 0
    batch_size = args.batch_size

    if emb_ids_to_delete:
        for i in range(0, len(emb_ids_to_delete), batch_size):
            eb = emb_ids_to_delete[i : i + batch_size]
            cur.execute("delete from vault_embeddings where id = any(%s::uuid[])", (eb,))
            deleted_embeddings += cur.rowcount
        conn.commit()
        print(f"[delete_mia] vault_embeddings {deleted_embeddings}건 삭제 완료")

    for i in range(0, len(orphan_ids), batch_size):
        batch = orphan_ids[i : i + batch_size]
        cur.execute("delete from provenance_records where artwork_id = any(%s::uuid[])", (batch,))
        deleted_provenance += cur.rowcount

        cur.execute("delete from artworks where id = any(%s::uuid[])", (batch,))
        deleted_artworks += cur.rowcount

        conn.commit()
        print(f"[delete_mia] 배치 {i // batch_size + 1}: artworks {cur.rowcount}건 삭제, 누적 {deleted_artworks}/{len(orphan_ids)}")

    print(
        f"\n[delete_mia] 완료 — artworks {deleted_artworks}건, "
        f"provenance_records {deleted_provenance}건, vault_embeddings {deleted_embeddings}건 삭제"
    )

    cur.execute("select count(*) from artworks w join sources s on s.id=w.source_id where s.site_name='mia'")
    remaining = cur.fetchone()[0]
    print(f"[delete_mia] 삭제 후 mia artworks 잔여: {remaining}건 (기대값 ~100,249)")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
