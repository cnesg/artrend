"""Poly Auction(北京保利, polypm.com.cn) 낙찰 결과 크롤러.

2026-09-22 중국 경매사 2곳(China Guardian·Poly Auction) 재조사 대상 중 한 곳 —
`docs/logs/경매확장_중국경매_20260922.md`에 조사 경위 전문이 있다. 요약:

  - robots.txt: www/en/csen 세 서브도메인 모두 **404**(파일 자체가 없음) — 제한 없음으로
    해석.
  - 이용약관: 사이트에 전용 "이용약관/개인정보처리방침" 페이지가 없고, `/laws/`
    한 페이지에 경매 참가 규칙(拍卖规则)·중화인민공화국 拍卖法·文物保护法 전문만 있다.
    전문 확인 결과 크롤링/스크래핑/데이터마이닝/제3자 정보제공 금지 조항 **없음**.
    저작권 조항(拍卖规则 제59조)은 "회사가 직접 촬영한 사진/도록"에 대한 것뿐이라
    이미지는 수집하지 않는 것으로 지킨다(칸옥션과 동일한 논리).
  - 대응 사이트인 China Guardian(cguardian.com)은 robots.txt가 `User-agent: *` →
    `Disallow: /`(파비콘 제외 전면 차단)이고 Googlebot조차 `/auction*`을 막아 **불가
    확정**했다 — 이 프로젝트에서는 건드리지 않는다.

구조: 홈페이지 "拍卖结果"(Auction Results) 섹션이 SPA라 눈으로 보는 페이지 자체는 비어
있지만, 그 SPA가 호출하는 내부 JSON API 3단이 인증 없이 그대로 열려 있다(mmca.py의
AjaxCollectionsList.do와 같은 성격):

    /notice/list                          — 拍卖会(경매 이벤트) 목록. noticeId(infoId) 포함
    /session/getSessionList?noticeId=..   — 그 경매의 专场(세션) 목록. sessionId(infoId) 포함
    /item/list?sessionId=..               — 그 세션의 로트 목록. dealPrice(낙찰가) 포함,
                                             2005년 경매까지 남아있음

`oldData` 파라미터(true/false)는 2005~2026년 아카이브를 구시스템(ZkEpai)/신시스템으로
나누는 스위치로 보인다 — 과거 데이터는 `oldData=true`가 아니면 빈 결과가 온다. 크롤러가
notice/session 단위로 먼저 `oldData=true`를 시도하고 비어 있으면 `false`로 재시도한다.

사용법:
    python polypm.py --phase notices
    python polypm.py --phase sessions --cutoff-days 60 --max-notices 20
    python polypm.py --phase items --max-notices 20
    python polypm.py --phase all --max-notices 20
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import requests

from common import RAW_ROOT, already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

SITE_NAME = "polypm"
BASE = "https://www.polypm.com.cn"
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}
DELAY = 2.5  # 해외 사이트라 여유 있게

LICENSE_NOTE = (
    "Poly Auction(polypm.com.cn) 拍卖结果 내부 JSON API(/notice/list, "
    "/session/getSessionList, /item/list) — robots.txt 없음(www/en/csen 전부 404, "
    "2026-09-22 확인), /laws/ 페이지(拍卖规则·拍卖法·文物保护法) 전문에 크롤링/스크래핑/"
    "제3자 정보제공 금지 조항 없음 확인(제59조는 회사 자체 촬영물 저작권 조항뿐이라 "
    "이미지는 수집 안 함), 2026-09-22"
)


def _get(path: str, params: dict) -> dict:
    def _do():
        resp = requests.get(f"{BASE}{path}", params=params, headers=HEADERS, timeout=90)
        resp.raise_for_status()
        return resp.json()

    return with_retry(_do, attempts=5, base_delay=6.0)


def crawl_notices(refetch: bool) -> None:
    record_id = "notices_all"
    if not refetch and already_fetched(SITE_NAME, record_id, ext="json"):
        print("[polypm] notices_all 이미 있음 — --refetch-notices로 강제 갱신")
        return
    data = _get("/notice/list", {"startTime": "", "noticeName": "", "pageSize": 2000, "isShow": "T", "pageNum": 1})
    total = data.get("total", 0)
    rows = data.get("rows", [])
    print(f"[polypm] notices 목록 total={total} rows={len(rows)}건 수신")
    save_raw(
        SITE_NAME, record_id, json.dumps(data, ensure_ascii=False),
        url=f"{BASE}/notice/list?startTime=&noticeName=&pageSize=2000&isShow=T&pageNum=1",
        license_note=LICENSE_NOTE, ext="json",
    )


def _load_notices() -> list[dict]:
    path = RAW_ROOT / SITE_NAME / "notices_all.json"
    if not path.exists():
        print("[polypm] notices_all.json이 없다 — 먼저 --phase notices 실행")
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("rows", [])


def _fetch_with_old_data_fallback(path: str, params: dict) -> tuple[dict, bool]:
    """oldData=true로 먼저 시도하고 total==0이면 false로 재시도."""
    data = _get(path, {**params, "oldData": "true"})
    if data.get("total", 0) > 0:
        return data, True
    data2 = _get(path, {**params, "oldData": "false"})
    return data2, False


def crawl_sessions(cutoff_days: int, max_notices: int | None, skip_existing: bool) -> None:
    import datetime

    cutoff = (datetime.datetime.now() - datetime.timedelta(days=cutoff_days)).strftime("%Y-%m-%d")
    notices = _load_notices()
    processed = 0
    for notice in notices:
        info_id = notice.get("infoId")
        start_time = notice.get("startTime") or ""
        if not info_id:
            continue
        if start_time > cutoff:
            continue  # 아직 정산 안 됐을 가능성 — 건너뛴다
        if max_notices is not None and processed >= max_notices:
            break

        record_id = f"sessions_{info_id}"
        if skip_existing and already_fetched(SITE_NAME, record_id, ext="json"):
            processed += 1
            continue

        data, old_data = _fetch_with_old_data_fallback(
            "/session/getSessionList", {"noticeId": info_id}
        )
        wrapped = {"oldData": old_data, "noticeId": info_id, "data": data}
        save_raw(
            SITE_NAME, record_id, json.dumps(wrapped, ensure_ascii=False),
            url=f"{BASE}/session/getSessionList?noticeId={info_id}&oldData={str(old_data).lower()}",
            license_note=LICENSE_NOTE, ext="json",
        )
        processed += 1
        if processed % 10 == 0:
            print(f"[polypm] sessions {processed}건 처리 (notice={info_id})")
        time.sleep(DELAY)

    print(f"[polypm] sessions 완료 — notice {processed}건 처리")


def crawl_items(max_notices: int | None, skip_existing: bool) -> None:
    site_dir = RAW_ROOT / SITE_NAME
    session_files = sorted(site_dir.glob("sessions_*.json"))
    if max_notices is not None:
        session_files = session_files[:max_notices]

    processed = 0
    total_sessions_seen = 0
    for path in session_files:
        wrapped = json.loads(path.read_text(encoding="utf-8"))
        old_data = wrapped.get("oldData", True)
        rows = wrapped.get("data", {}).get("rows", [])
        for session in rows:
            session_id = session.get("infoId")
            if not session_id:
                continue
            total_sessions_seen += 1
            record_id = f"items_{session_id}"
            if skip_existing and already_fetched(SITE_NAME, record_id, ext="json"):
                continue

            data, resolved_old_data = _fetch_with_old_data_fallback(
                "/item/list", {"pageNum": 1, "pageSize": 2000, "itemNamePpch": "", "sessionId": session_id}
            )
            wrapped_item = {"oldData": resolved_old_data, "sessionId": session_id, "data": data}
            save_raw(
                SITE_NAME, record_id, json.dumps(wrapped_item, ensure_ascii=False),
                url=f"{BASE}/item/list?oldData={str(resolved_old_data).lower()}&pageNum=1&pageSize=2000&sessionId={session_id}",
                license_note=LICENSE_NOTE, ext="json",
            )
            processed += 1
            if processed % 10 == 0:
                print(f"[polypm] items {processed}개 세션 처리 (session={session_id})")
            time.sleep(DELAY)

    print(f"[polypm] items 완료 — 세션 {total_sessions_seen}개 중 {processed}개 신규 수집")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Poly Auction(polypm.com.cn) 낙찰 결과 크롤러")
    parser.add_argument("--phase", choices=["notices", "sessions", "items", "all"], default="all")
    parser.add_argument("--refetch-notices", action="store_true")
    parser.add_argument("--cutoff-days", type=int, default=60, help="이 일수보다 최근 시작한 경매는 건너뜀(정산 미확정)")
    parser.add_argument("--max-notices", type=int, default=None, help="pilot용 — 처리할 notice(경매) 수 제한")
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    args = parser.parse_args()

    if args.phase in ("notices", "all"):
        crawl_notices(args.refetch_notices)
    if args.phase in ("sessions", "all"):
        crawl_sessions(args.cutoff_days, args.max_notices, args.skip_existing)
    if args.phase in ("items", "all"):
        crawl_items(args.max_notices, args.skip_existing)
