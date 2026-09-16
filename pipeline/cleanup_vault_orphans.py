"""vault/{artists,museums,galleries,artworks}에 쌓인 고아 .md 파일 정리.

export_vault.py의 slugify()가 파일명에 `(uid앞8자리)` 형태로 DB id를 박아두는데,
merge/dedup/재분류 스크립트들이 병합 loser 행을 실제 DELETE하면서(예:
merge_dup_museums.py, fix_foundation_museum_misclass.py, 여러 merge_*_artists.py)
그 id로 만들어진 옛 vault 파일은 지워지지 않고 그대로 남는다 — 2026-09-08
artrend-3a가 발견(museums 47%/934건, artists 31%/88,604건 고아).

판정 방법: 파일명 끝의 `(xxxxxxxx).md`에서 id 앞 8자리를 뽑아, 현재 DB에 있는
해당 테이블 id들의 앞 8자리 집합과 비교 — 집합에 없으면 고아로 판정.
(앞 8자리만 쓰는 건 slugify()와 동일한 관례를 따른 것 — 각 테이블 규모에서
8자리 hex 충돌 확률은 무시 가능한 수준이다.)

**기본은 dry-run이며, --apply 없이는 실제 파일 삭제를 절대 하지 않는다.**
--apply는 고아 .md 파일 삭제와 함께, 같은 경로(doc_path)로 연결된
vault_embeddings 행도 같이 삭제한다 — 사용자 승인 완료(artrend-3a 경유,
2026-09-08) 후 활성화.

사용법:
    python pipeline/cleanup_vault_orphans.py              # dry-run, 리포트만
    python pipeline/cleanup_vault_orphans.py --apply       # 실제 파일+임베딩 삭제(주의)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

sys.stdout.reconfigure(encoding="utf-8")

VAULT_ROOT = Path(__file__).resolve().parent.parent / "vault"
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

# vault 폴더명 -> DB 테이블명
FOLDER_TABLE = {
    "artists": "artists",
    "museums": "museums",
    "galleries": "galleries",
    "artworks": "artworks",
}

ID8_RE = re.compile(r"\(([0-9a-fA-F]{8})\)\.md$")


def load_valid_id8(cur, table: str) -> set[str]:
    cur.execute(f"select id from {table}")
    return {str(row[0]).replace("-", "")[:8].lower() for row in cur.fetchall()}


def scan_folder(folder: Path, valid_id8: set[str]) -> tuple[list[Path], list[Path]]:
    """(orphan 파일 목록, id8 파싱 실패 파일 목록) 반환."""
    orphans: list[Path] = []
    unparseable: list[Path] = []
    if not folder.exists():
        return orphans, unparseable
    for path in folder.glob("*.md"):
        m = ID8_RE.search(path.name)
        if not m:
            unparseable.append(path)
            continue
        id8 = m.group(1).lower()
        if id8 not in valid_id8:
            orphans.append(path)
    return orphans, unparseable


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 고아 파일을 삭제한다 (주의: 임베딩 작업 중엔 절대 사용 금지)")
    args = ap.parse_args()

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    report: dict[str, dict] = {}
    total_orphans = 0

    for folder_name, table in FOLDER_TABLE.items():
        valid_id8 = load_valid_id8(cur, table)
        folder = VAULT_ROOT / folder_name
        orphans, unparseable = scan_folder(folder, valid_id8)
        total_files = sum(1 for _ in folder.glob("*.md")) if folder.exists() else 0

        print(
            f"[cleanup_vault] {folder_name}: 전체 {total_files}건 / "
            f"DB {table} {len(valid_id8)}건 / 고아 {len(orphans)}건"
            + (f" / id8 파싱실패 {len(unparseable)}건" if unparseable else "")
        )

        report[folder_name] = {
            "total_files": total_files,
            "db_count": len(valid_id8),
            "orphan_count": len(orphans),
            "orphan_paths": [str(p) for p in orphans],
            "unparseable_paths": [str(p) for p in unparseable],
        }
        total_orphans += len(orphans)

    print(f"\n[cleanup_vault] 전체 고아 파일: {total_orphans}건")

    out_path = DOCS_DIR / f"vault_고아파일_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[cleanup_vault] 상세 리포트 저장: {out_path}")

    if not args.apply:
        print("\n[cleanup_vault] dry-run — 파일 삭제 없음. --apply로 실행하면 실제 삭제됩니다.")
        cur.close()
        conn.close()
        return

    deleted = 0
    doc_paths: list[str] = []
    for folder_name, info in report.items():
        for p in info["orphan_paths"]:
            os.remove(p)
            deleted += 1
            doc_paths.append(f"{folder_name}/{Path(p).name}")
    print(f"[cleanup_vault] {deleted}건 파일 삭제 완료")

    embeddings_deleted = 0
    batch_size = 1000
    for i in range(0, len(doc_paths), batch_size):
        batch = doc_paths[i : i + batch_size]
        cur.execute("delete from vault_embeddings where doc_path = any(%s)", (batch,))
        embeddings_deleted += cur.rowcount
    conn.commit()
    print(f"[cleanup_vault] vault_embeddings {embeddings_deleted}건 삭제 완료")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
