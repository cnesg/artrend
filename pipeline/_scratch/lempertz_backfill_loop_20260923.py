"""Lempertz 전량 백필 — DB 적재 루프 (2026-09-23, 코디네이터 승인 후 착수).

`crawlers/lempertz.py`(--limit 없이 전량, already_fetched 기반 재개 안전, 약 44시간 추산)와
독립된 프로세스로 돈다. 크롤이 raw/lempertz/*.html을 계속 만들어내는 동안 주기적으로
`lempertz.load()`를 재호출해 증분 적재한다 — 로더 자체가 `source_already_loaded`로 중복을
막으므로 몇 번을 더 불러도 안전(idempotent).

pgportable이 오늘 이미 두 번 죽었다 살아난 이력이 있어(코디네이터 지시), DB 연결 실패에
짧게 포기하지 않는다 — 연결 자체를 6분(`CONNECT_MAX_WAIT`) 동안 15초 간격으로 재시도하고,
그래도 안 되면 이번 주기만 건너뛰고 다음 주기(15분 뒤)에 다시 시도한다. pgportable을
재기동하는 것 자체는 이 스크립트의 책임이 아니다(다른 세션/사용자 영역) — 여기서는 "짧게
포기하지 않는다"까지만 보장한다.

진행 로그는 `docs/logs/경매확장_lempertz_20260922.md`에 이어서 append한다(이 파일은 이번
Lempertz 조사용으로 이번 세션이 새로 만든 전용 로그라 다른 에이전트와 충돌 위험 없음 — 공유
문서인 `docs/경매소스확장_20260922.md`/`docs/작업분담_20260915.md`/`docs/크롤러현황.md`는
건드리지 않는다).

기동:
    DATABASE_URL=... python3 lempertz_backfill_loop_20260923.py
(백그라운드 detached 프로세스로 띄우는 건 호출부 책임 — 이 스크립트 자체는 포그라운드로 돌아도
되는 평범한 장기 루프다.)
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

from db import get_connection  # noqa: E402
from store import PgStore  # noqa: E402
import lempertz  # noqa: E402

LOG_MD = Path(__file__).resolve().parent.parent.parent / "docs" / "logs" / "경매확장_lempertz_20260922.md"
CONNECT_MAX_WAIT = 360  # 초 — "5분+" 지시 반영(여유를 둬서 6분)
CONNECT_POLL = 15
CYCLE_SLEEP = 900  # 15분마다 재적재 시도
MAX_CYCLES = 300  # 대략 75시간 커버(크롤 전체 추산 44h + 넉넉한 여유)


def _log(line: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    msg = f"- {ts}Z {line}"
    print(msg)
    try:
        with LOG_MD.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception as exc:  # 로그 파일 쓰기 실패는 적재 자체를 막을 이유가 아니다
        print(f"[lempertz-backfill] 로그 append 실패(무시): {exc}")


def _connect_with_retry():
    start = time.time()
    last_exc: Exception | None = None
    attempt = 0
    while time.time() - start < CONNECT_MAX_WAIT:
        attempt += 1
        try:
            return get_connection()
        except Exception as exc:  # psycopg2.OperationalError 등 — pgportable 죽었을 때
            last_exc = exc
            elapsed = time.time() - start
            print(
                f"[lempertz-backfill] DB 연결 실패(시도 {attempt}, 경과 {elapsed:.0f}s): {exc} "
                f"— {CONNECT_POLL}초 후 재시도",
                flush=True,
            )
            time.sleep(CONNECT_POLL)
    raise RuntimeError(f"DB 연결 {CONNECT_MAX_WAIT}초 넘게 실패: {last_exc}")


def main() -> None:
    _log("## 전량 백필 적재 루프 시작 — pgportable 연결 실패 시 최대 6분 재시도, 15분마다 재적재")
    total_loaded = 0
    for cycle in range(1, MAX_CYCLES + 1):
        try:
            conn = _connect_with_retry()
        except Exception as exc:
            _log(f"cycle {cycle}: DB 연결 포기(6분 초과) — 다음 주기(15분 뒤)에 재시도. {exc}")
            time.sleep(CYCLE_SLEEP)
            continue

        try:
            store = PgStore(conn)
            n = lempertz.load(store)
            total_loaded += n
            if n > 0:
                _log(f"cycle {cycle}: 신규 적재 {n}건 (누적 {total_loaded}건)")
            else:
                print(f"[lempertz-backfill] cycle {cycle}: 신규 0건 (크롤이 아직 새 raw를 못 만들었거나 이미 다 적재됨)")
        except Exception as exc:
            _log(f"cycle {cycle}: 적재 중 오류(다음 주기에 재시도) — {exc}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

        time.sleep(CYCLE_SLEEP)

    _log(f"## 전량 백필 적재 루프 종료(최대 주기 {MAX_CYCLES}회 도달, 누적 {total_loaded}건) — 크롤이 더 남았으면 루프 재실행 필요")


if __name__ == "__main__":
    main()
