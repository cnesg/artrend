"""1회성 런처 — im Kinsky 전량 백필을 인덱스 빌드가 끝나는 즉시 4샤드 병렬로 띄운다. 2026-09-23.

`crawlers/im_kinsky.py --index-only`(백그라운드)가 `crawlers/raw/im_kinsky/_index.json`을
**전부 훑은 뒤 한 번에** 기록하기 때문에, 그 전에는 전량 백필을 시작할 수 없다. 이 스크립트가
인덱스가 완성될 때까지 기다렸다가(부분 인덱스 `_partial` 플래그가 사라질 때까지) 샤드를
띄운다 — 사람이 두 시간 지켜보고 있지 않아도 되도록.

로트 상세 1건당 실측 약 2.3초(서버 응답)이라 단일 프로세스로는 수만 건이 수십 시간 걸린다.
**4샤드 x `--delay 1.5`** 로 나누면 사이트에 가는 전체 요청률은 초당 1건 안팎으로 유지되면서
처리량은 약 4배가 된다. 샤딩 키는 로트 id 정수라 프로세스 간 중복 요청이 없고, 겹치더라도
`already_fetched()`가 막는다.

    python pipeline/_scratch/launch_im_kinsky_backfill_20260923.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO / "crawlers" / "raw" / "im_kinsky" / "_index.json"
LOG_DIR = REPO / "docs" / "logs"
SHARDS = 4
DELAY = "1.5"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)


def index_ready() -> dict | None:
    if not INDEX_PATH.exists():
        return None
    try:
        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None  # 쓰는 중일 수 있다 — 다음 회차에 다시 본다
    if index.get("_partial"):
        return None  # 파일럿용 부분 인덱스
    return index


def main() -> None:
    waited = 0
    while True:
        index = index_ready()
        if index is not None:
            break
        time.sleep(60)
        waited += 60
        if waited % 600 == 0:
            print(f"[launcher] 인덱스 대기 중… {waited // 60}분 경과")
    print(
        f"[launcher] 인덱스 완성 — 경매 {len(index.get('auction_ids', []))}개 / "
        f"세일 {len(index.get('sales', []))}개 / 로트 {len(index.get('lots', []))}건"
    )

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for i in range(SHARDS):
        out = (LOG_DIR / f"imkinsky_backfill_20260923_shard{i}_stdout.log").open("a", encoding="utf-8")
        err = (LOG_DIR / f"imkinsky_backfill_20260923_shard{i}_stderr.log").open("a", encoding="utf-8")
        subprocess.Popen(
            [sys.executable, "-u", "crawlers/im_kinsky.py",
             "--newest-first", "--shard", f"{i}/{SHARDS}", "--delay", DELAY],
            cwd=str(REPO), stdout=out, stderr=err,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        print(f"[launcher] 샤드 {i}/{SHARDS} 기동")
        time.sleep(2)
    print("[launcher] 4샤드 기동 완료 — 최신 경매부터 역순으로 수집한다")


if __name__ == "__main__":
    main()
