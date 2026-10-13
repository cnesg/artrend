"""registry.EDITIONS의 원본 URL을 받아 그대로 저장한다 (파싱은 load.py 몫).

    python v2/collect.py                       # 전 회차 (이미 받은 페이지는 건너뜀)
    python v2/collect.py --only gwangju_2024 frieze_seoul_2023
    python v2/collect.py --series frieze_london
    python v2/collect.py --refetch             # 이미 받은 것도 다시 (현재 진행 중 회차 갱신용)

페이지 하나 = raw/<series>/<edition_id>__p<NN>.<ext>. 상세 페이지를 목록에서 찾아야 하는 소스는
registry에 `discover`(목록 원본 -> 상세 URL 리스트 함수)를 두고, 상세는 __d<NNN>으로 저장한다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import PoliteSession, already_fetched, raw_path_for, save_raw  # noqa: E402
from registry import EDITIONS, resolve  # noqa: E402

EXT = {"html": "html", "json": "json", "pdf": "pdf", "wikitext": "wiki.txt", "text": "txt"}


def fetch_edition(sess: PoliteSession, eid: str, refetch: bool) -> tuple[int, int]:
    ed = EDITIONS[eid]
    site = ed["series"]
    got = skipped = 0
    for i, src in enumerate(ed["sources"]):
        ext = EXT[src["fetch"]]
        rid = f"{eid}__p{i:02d}"
        if not refetch and already_fetched(site, rid, ext):
            skipped += 1
        else:
            r = sess.get(src["url"], delay=src.get("delay"), headers=src.get("headers"),
                         method=src.get("method", "GET"), json=src.get("json_body"))
            if src["fetch"] != "pdf" and (r.encoding or "").lower() == "iso-8859-1" and "charset" not in r.headers.get("content-type", "").lower():
                r.encoding = r.apparent_encoding  # 헤더에 charset 없으면 requests가 latin-1로 오인
            content = r.content if src["fetch"] == "pdf" else r.text
            save_raw(site, rid, content, url=src["url"], ext=ext, source_tier=src["tier"],
                     license_note=src.get("license", ""),
                     extra={"edition_id": eid, "role": "list",
                            **({"method": src["method"], "json_body": src.get("json_body")} if src.get("method") else {})})
            got += 1
        if src.get("discover"):
            listing = raw_path_for(site, rid, ext).read_text(encoding="utf-8")
            for j, durl in enumerate(resolve(src["discover"])(listing)):
                dext = EXT[src.get("detail_fetch", "html")]
                did = f"{eid}__p{i:02d}d{j:03d}"
                if not refetch and already_fetched(site, did, dext):
                    skipped += 1
                    continue
                r = sess.get(durl, delay=src.get("delay"), headers=src.get("headers"))
                if (r.encoding or "").lower() == "iso-8859-1" and "charset" not in r.headers.get("content-type", "").lower():
                    r.encoding = r.apparent_encoding
                save_raw(site, did, r.text, url=durl, ext=dext, source_tier=src["tier"],
                         license_note=src.get("license", ""), extra={"edition_id": eid, "role": "detail"})
                got += 1
    return got, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--series")
    ap.add_argument("--refetch", action="store_true")
    args = ap.parse_args()
    ids = [e for e in EDITIONS if (not args.only or e in args.only)
           and (not args.series or EDITIONS[e]["series"] == args.series)]
    sess = PoliteSession()
    for eid in ids:
        if not EDITIONS[eid]["sources"]:
            print(f"[none] {eid}: 확보 가능한 원본 없음 ({EDITIONS[eid].get('coverage_note', '')})", flush=True)
            continue
        try:
            got, skipped = fetch_edition(sess, eid, args.refetch)
            print(f"[ok] {eid}: 새로 {got}, 기존 {skipped}", flush=True)
        except Exception as exc:  # 회차 하나 실패가 전체를 멈추지 않게
            print(f"[fail] {eid}: {exc!r}", flush=True)


if __name__ == "__main__":
    main()
