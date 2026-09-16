"""vault/ 마크다운 프론트매터에 건수·하이라이트 필드 추가 (DB 미사용).

export_vault.py가 이미 써 놓은 본문의 "## 소장 작품 (N건)" 같은 헤딩에서
건수를 정규식으로 뽑아 프론트매터에 숫자/불린으로 얹는다. 옵시디언 Bases에서
정렬·필터가 되려면 값이 quoted string이 아니라 진짜 number/boolean이어야 함.

DB를 다시 쿼리하지 않는 이유: pgportable이 불안정했던 전례가 있고, 이미
내보낸 파일에 필요한 정보가 전부 들어있어 DB 없이 끝낼 수 있음.

사용법:
    python pipeline/enrich_vault_frontmatter.py --what artists,collectors,auctions
    python pipeline/enrich_vault_frontmatter.py --what artists --limit 200   # 테스트용

재실행해도 안전(idempotent) — 이미 필드가 있는 파일은 본문 재파싱 없이 건너뜀.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

VAULT_ROOT = Path(__file__).resolve().parent.parent / "vault"

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)

ARTIST_ARTWORK_RE = re.compile(r"## 소장 작품 \((\d+)건\)")
ARTIST_AUCTION_RE = re.compile(r"## 경매 기록 \((\d+)건\)")
ARTIST_GALLERY_SECTION = "## 전속/취급 갤러리"
COLLECTOR_PROVENANCE_RE = re.compile(r"## 소장/거쳐간 작품 \((\d+)건\)")
AUCTION_LOT_RE = re.compile(r"## 낙찰 기록 \((\d+)건\)")

NATIONALITY_QUOTA = 30   # 국적당 하이라이트 상한
HIGHLIGHT_TOTAL = 1500   # 전역 하이라이트 총 상한(artists)
COLLECTOR_HIGHLIGHT_TOTAL = 500


def parse_frontmatter(text: str):
    """(순서 보존 dict, match객체|None) 반환. 값은 원본 그대로(따옴표 포함)."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, None
    fields: dict[str, str] = {}
    for line in m.group(1).split("\n"):
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fields[k.strip()] = v.strip()
    return fields, m


def write_fields(path: Path, text: str, m, fields: dict, new_fields: dict) -> None:
    lines = [f"{k}: {v}" for k, v in fields.items()]
    for k, v in new_fields.items():
        if k in fields:
            continue
        if isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        else:
            lines.append(f"{k}: {v}")
    new_text = "---\n" + "\n".join(lines) + "\n---\n" + text[m.end():]
    path.write_text(new_text, encoding="utf-8")


def process_artists(limit: int | None):
    folder = VAULT_ROOT / "artists"
    files = sorted(folder.glob("*.md"))
    if limit:
        files = files[:limit]
    total = len(files)
    print(f"[enrich:artists] 대상 {total}건")

    records = []  # (path, nationality, artwork_count, auction_count, has_gallery, is_merged)
    previously_highlighted: set[Path] = set()
    for i, path in enumerate(files, 1):
        text = path.read_text(encoding="utf-8")
        fields, m = parse_frontmatter(text)
        if m is None:
            continue
        if fields.get("highlight") == "true":
            previously_highlighted.add(path)
        if "artwork_count" in fields:
            artwork_count = int(fields["artwork_count"])
            auction_count = int(fields.get("auction_count", "0"))
            has_gallery = fields.get("has_gallery", "false") == "true"
        else:
            am = ARTIST_ARTWORK_RE.search(text)
            artwork_count = int(am.group(1)) if am else 0
            um = ARTIST_AUCTION_RE.search(text)
            auction_count = int(um.group(1)) if um else 0
            has_gallery = ARTIST_GALLERY_SECTION in text
            write_fields(path, text, m, fields, {
                "artwork_count": artwork_count,
                "auction_count": auction_count,
                "has_gallery": has_gallery,
            })
        raw_name = fields.get("name", '""').strip('"')
        raw_nat = fields.get("nationality", '""').strip('"')
        # 원본 데이터에 "저자|삽화가|출판사|인쇄소" 식으로 여러 창작자가 한 레코드로
        # 합쳐진 경우가 있음(예: Met 복수 크레딧) — name에 "|"가 있으면 진짜 단일
        # 작가가 아니므로 하이라이트 후보에서 제외. nationality도 같은 이유로
        # "British|British|British|British" 처럼 중복 반복되므로 정규화한다.
        is_merged = "|" in raw_name
        nat_tokens = [t.strip() for t in raw_nat.split("|") if t.strip()]
        nationality = "/".join(dict.fromkeys(nat_tokens))  # 순서 보존 dedup
        records.append((path, nationality, artwork_count, auction_count, has_gallery, is_merged))
        if i % 5000 == 0:
            print(f"[enrich:artists] {i}/{total} 진행 중...")

    print(f"[enrich:artists] 1차 패스 완료 ({len(records)}건)")

    def score(r):
        _, _, aw, au, gal, is_merged = r
        if is_merged:
            return -1  # 하이라이트 후보에서 제외
        return aw + 3 * au + 5 * (1 if gal else 0)

    by_nat: dict[str, list] = defaultdict(list)
    for r in records:
        by_nat[r[1]].append(r)

    selected: dict[Path, tuple] = {}
    for nat, recs in by_nat.items():
        recs.sort(key=score, reverse=True)
        for r in recs[:NATIONALITY_QUOTA]:
            if score(r) > 0:
                selected[r[0]] = r

    global_sorted = sorted(records, key=score, reverse=True)
    for r in global_sorted:
        if len(selected) >= HIGHLIGHT_TOTAL:
            break
        if score(r) <= 0:
            break
        selected[r[0]] = r

    print(f"[enrich:artists] 하이라이트 {len(selected)}건 선정 — 국적 분포 상위 10:")
    nat_counts = defaultdict(int)
    for r in selected.values():
        nat_counts[r[1] or "(미상)"] += 1
    for nat, cnt in sorted(nat_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"    {nat}: {cnt}")

    stale = previously_highlighted - set(selected.keys())
    if stale:
        print(f"[enrich:artists] 이전 선정에서 빠진 {len(stale)}건 highlight 제거 중...")
        for path in stale:
            text = path.read_text(encoding="utf-8")
            fields, m = parse_frontmatter(text)
            if m is None or fields.get("highlight") != "true":
                continue
            del fields["highlight"]
            new_text = "---\n" + "\n".join(f"{k}: {v}" for k, v in fields.items()) + "\n---\n" + text[m.end():]
            path.write_text(new_text, encoding="utf-8")

    for path, *_ in selected.values():
        text = path.read_text(encoding="utf-8")
        fields, m = parse_frontmatter(text)
        if m is None:
            continue
        if fields.get("highlight") == "true":
            continue
        write_fields(path, text, m, fields, {"highlight": True})

    print(f"[enrich:artists] 완료")


def process_collectors(limit: int | None):
    folder = VAULT_ROOT / "collectors"
    files = sorted(folder.glob("*.md"))
    if limit:
        files = files[:limit]
    total = len(files)
    print(f"[enrich:collectors] 대상 {total}건")

    records = []  # (path, provenance_count)
    for i, path in enumerate(files, 1):
        text = path.read_text(encoding="utf-8")
        fields, m = parse_frontmatter(text)
        if m is None:
            continue
        if "provenance_count" in fields:
            provenance_count = int(fields["provenance_count"])
        else:
            pm = COLLECTOR_PROVENANCE_RE.search(text)
            provenance_count = int(pm.group(1)) if pm else 0
            write_fields(path, text, m, fields, {"provenance_count": provenance_count})
        records.append((path, provenance_count))
        if i % 5000 == 0:
            print(f"[enrich:collectors] {i}/{total} 진행 중...")

    print(f"[enrich:collectors] 1차 패스 완료 ({len(records)}건)")

    top = sorted(records, key=lambda r: r[1], reverse=True)[:COLLECTOR_HIGHLIGHT_TOTAL]
    top = [r for r in top if r[1] > 0]
    print(f"[enrich:collectors] 하이라이트 {len(top)}건 선정")

    for path, _ in top:
        text = path.read_text(encoding="utf-8")
        fields, m = parse_frontmatter(text)
        if m is None:
            continue
        if fields.get("highlight") == "true":
            continue
        write_fields(path, text, m, fields, {"highlight": True})

    print(f"[enrich:collectors] 완료")


def process_auctions(limit: int | None):
    folder = VAULT_ROOT / "auctions"
    files = sorted(folder.glob("*.md"))
    if limit:
        files = files[:limit]
    total = len(files)
    print(f"[enrich:auctions] 대상 {total}건")

    count = 0
    for i, path in enumerate(files, 1):
        text = path.read_text(encoding="utf-8")
        fields, m = parse_frontmatter(text)
        if m is None:
            continue
        if "lot_count" in fields:
            continue
        lm = AUCTION_LOT_RE.search(text)
        lot_count = int(lm.group(1)) if lm else 0
        write_fields(path, text, m, fields, {"lot_count": lot_count})
        count += 1
        if i % 500 == 0:
            print(f"[enrich:auctions] {i}/{total} 진행 중...")

    print(f"[enrich:auctions] 완료 ({count}건 갱신)")


def main() -> None:
    parser = argparse.ArgumentParser(description="vault/ 프론트매터 건수·하이라이트 보강 (DB 미사용)")
    parser.add_argument("--what", default="artists,collectors,auctions")
    parser.add_argument("--limit", type=int, default=None, help="테스트용 — 카테고리별 상한")
    args = parser.parse_args()

    targets = set(args.what.split(","))
    if "artists" in targets:
        process_artists(args.limit)
    if "collectors" in targets:
        process_collectors(args.limit)
    if "auctions" in targets:
        process_auctions(args.limit)


if __name__ == "__main__":
    main()
