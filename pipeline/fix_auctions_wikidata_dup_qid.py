"""auctions_wikidata 중복 로트 정리 — 2026-09-16 워커 큐.

원인: `crawlers/auctions.py`가 같은 미술 유형 범주 여러 개(painting/self_portrait/
pastel_artwork/drawing 등)를 각각 SPARQL로 질의하는데, 한 작품(Wikidata QID)이
두 범주의 instance-of(P31)를 동시에 만족하면 **완전히 같은 P793 경매 statement**가
두 범주 질의 모두에 잡힌다. `record_id`가 `"<type_key>_" + stmt_guid`라서
같은 statement가 `painting_Q136892338-<GUID>.json` / `self_portrait_Q136892338-
<GUID>.json`처럼 서로 다른 파일명으로 두 번 저장되고, `already_fetched()`가
type_key까지 포함한 이름으로 비교하다 보니 이미 저장된 걸 못 알아채 pipeline
적재 시 auctions/auction_lots/artworks가 각각 2벌 생긴다.

**중요: QID만으로 그룹핑하면 안 됨.** 같은 작품이 실제로 여러 번 경매에 나온
정상 케이스(예: Q111263529 — 2008년 로트10, 2018년 로트11, 가격·날짜·로트번호
전부 다름)도 같은 QID를 공유해서, QID 단위로 "가장 이른 것만 남기고 삭제"하면
진짜 재경매 이력을 지워버린다(raw_path 803개 중 QID만으로 묶으면 239그룹인데,
그중 상당수가 이런 정상 재경매 사례로 확인됨, 2026-09-16). 진짜 중복은
**(QID, statement GUID)가 완전히 같은 경우**(=raw_path의 type_key 접두사만
다르고 나머지는 동일한 파일 쌍)뿐이며, 실제로 이 쌍들은 lot_number·가격·
날짜·제목까지 전부 동일한 것으로 확인했다(true positive 209그룹). 이 스크립트는
(QID, GUID) 기준으로만 중복 판정한다 — 메인 지시의 "QID로" 표현은 이 분석을
거쳐 (QID, GUID)로 좁혀 적용함(리포트에 근거 남김).

정리 순서(W5 fix_auction_lot_anomalies.py와 동일 패턴):
1. (QID, GUID) 그룹에서 created_at 가장 이른 auction_lots 1건만 남기고 나머지 삭제.
2. 삭제되는 lot의 artwork_id가 다른 auction_lots/museum_holdings에서도 전혀
   안 쓰이면 그 artwork(+ provenance_records)도 삭제.
3. 삭제 후 auction_lots가 0건이 된 auctions 행도 삭제(다른 걸 참조 안 하는지
   FK 확인 후).

**기본은 dry-run(리포트만)이며, --apply 없이는 DELETE하지 않는다.** idempotent.

사용법:
    python pipeline/fix_auctions_wikidata_dup_qid.py            # 리포트만
    python pipeline/fix_auctions_wikidata_dup_qid.py --apply     # 실제 반영
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from db import get_connection  # noqa: E402

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "logs"
KEY_RE = re.compile(r"_(Q\d+-[0-9a-fA-F-]+)\.json$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        select al.id, al.auction_id, al.artwork_id, al.created_at, s.raw_path,
               al.lot_number, al.hammer_price, au.auction_date, a.title
        from auction_lots al
        join sources s on s.id = al.source_id
        join auctions au on au.id = al.auction_id
        join artworks a on a.id = al.artwork_id
        where s.site_name = 'auctions_wikidata'
        """
    )
    rows = cur.fetchall()

    groups: dict[str, list[tuple]] = defaultdict(list)
    for lot_id, auction_id, artwork_id, created_at, raw_path, lot_number, price, adate, title in rows:
        m = KEY_RE.search(raw_path or "")
        if not m:
            continue
        groups[m.group(1)].append(
            (lot_id, auction_id, artwork_id, created_at, raw_path, lot_number, price, adate, title)
        )

    dupes = []
    for key, items in groups.items():
        if len(items) <= 1:
            continue
        items.sort(key=lambda r: r[3])  # created_at 오름차순 — 가장 이른 것 유지
        keep = items[0]
        drop = items[1:]
        dupes.append(
            {
                "qid_guid": key,
                "keep_lot_id": str(keep[0]),
                "keep_raw_path": keep[4],
                "drop_lot_ids": [str(r[0]) for r in drop],
                "drop_auction_ids": [str(r[1]) for r in drop],
                "drop_artwork_ids": [str(r[2]) for r in drop],
                "drop_raw_paths": [r[4] for r in drop],
                "title": keep[8],
                "lot_number": keep[5],
                "hammer_price": str(keep[6]) if keep[6] is not None else None,
                "auction_date": str(keep[7]) if keep[7] else None,
            }
        )

    drop_lot_ids = [lid for d in dupes for lid in d["drop_lot_ids"]]
    drop_artwork_candidates = {aid for d in dupes for aid in d["drop_artwork_ids"]}
    touched_auction_ids = {aid for d in dupes for aid in d["drop_auction_ids"]}

    print(f"[fix_auctions_wikidata_dup] raw_path 매칭 {sum(len(v) for v in groups.values())}건, "
          f"(QID,GUID) 그룹 {len(groups)}개, 중복 그룹 {len(dupes)}개, 삭제 대상 lot {len(drop_lot_ids)}건")

    final_drop_artworks: list[str] = []
    if drop_artwork_candidates:
        cur.execute(
            "select artwork_id::text, count(*) from auction_lots where artwork_id = any(%s::uuid[]) group by artwork_id",
            (list(drop_artwork_candidates),),
        )
        lot_ref_count = dict(cur.fetchall())
        cur.execute(
            "select artwork_id::text, count(*) from museum_holdings where artwork_id = any(%s::uuid[]) group by artwork_id",
            (list(drop_artwork_candidates),),
        )
        holding_ref_count = dict(cur.fetchall())
        for aid in drop_artwork_candidates:
            drop_lots_for_this_artwork = sum(
                1 for d in dupes for lid, a in zip(d["drop_lot_ids"], d["drop_artwork_ids"]) if a == aid
            )
            remaining_lot_refs = lot_ref_count.get(aid, 0) - drop_lots_for_this_artwork
            remaining_holding_refs = holding_ref_count.get(aid, 0)
            if remaining_lot_refs <= 0 and remaining_holding_refs <= 0:
                final_drop_artworks.append(aid)

    print(f"[fix_auctions_wikidata_dup] 참조 없어 artwork까지 삭제될 것: {len(final_drop_artworks)}건")

    # 삭제 후 lot이 0건이 될 auctions (다른 site 경매에서 같은 auction_id를 공유할 수도 있으니 재확인)
    empty_auction_ids: list[str] = []
    if touched_auction_ids:
        cur.execute(
            "select auction_id::text, count(*) from auction_lots where auction_id = any(%s::uuid[]) group by auction_id",
            (list(touched_auction_ids),),
        )
        auction_lot_count = dict(cur.fetchall())
        drop_lots_per_auction: dict[str, int] = defaultdict(int)
        for d in dupes:
            for aid in d["drop_auction_ids"]:
                drop_lots_per_auction[aid] += 1
        for aid in touched_auction_ids:
            remaining = auction_lot_count.get(aid, 0) - drop_lots_per_auction.get(aid, 0)
            if remaining <= 0:
                empty_auction_ids.append(aid)

    print(f"[fix_auctions_wikidata_dup] 삭제 후 로트 0건 되는 auctions: {len(empty_auction_ids)}건")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "QID만으로 묶지 않고 (QID,statement GUID)로만 중복 판정 — 근거는 파일 상단 docstring 참고",
        "raw_path_total": sum(len(v) for v in groups.values()),
        "qid_guid_groups": len(groups),
        "duplicate_groups": len(dupes),
        "duplicate_lots_to_drop": len(drop_lot_ids),
        "artworks_to_drop": len(final_drop_artworks),
        "empty_auctions_to_drop": len(empty_auction_ids),
        "samples": dupes[:30],
        "drop_lot_ids": drop_lot_ids,
        "final_drop_artwork_ids": final_drop_artworks,
        "empty_auction_ids": empty_auction_ids,
    }
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DOCS_DIR / f"auctions_wikidata_중복QID_리포트_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[fix_auctions_wikidata_dup] 리포트: {report_path}")

    if not args.apply:
        print("[fix_auctions_wikidata_dup] dry-run — --apply로 실제 반영")
        return

    if drop_lot_ids:
        cur.execute("delete from auction_lots where id = any(%s::uuid[])", (drop_lot_ids,))
        conn.commit()
        print(f"[fix_auctions_wikidata_dup] 중복 auction_lots {len(drop_lot_ids)}건 삭제 완료")

    if final_drop_artworks:
        cur.execute("delete from provenance_records where artwork_id = any(%s::uuid[])", (final_drop_artworks,))
        cur.execute("delete from artworks where id = any(%s::uuid[])", (final_drop_artworks,))
        conn.commit()
        print(f"[fix_auctions_wikidata_dup] 참조 없는 artworks {len(final_drop_artworks)}건 (+provenance_records) 삭제 완료")

    if empty_auction_ids:
        cur.execute("delete from auctions where id = any(%s::uuid[]) and not exists (select 1 from auction_lots al where al.auction_id = auctions.id)", (empty_auction_ids,))
        conn.commit()
        print(f"[fix_auctions_wikidata_dup] 빈 auctions {len(empty_auction_ids)}건 삭제 완료")


if __name__ == "__main__":
    main()
