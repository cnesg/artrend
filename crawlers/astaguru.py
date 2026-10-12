"""AstaGuru(인도 뭄바이, astaguru.com) 낙찰 결과 크롤러 — 인도 축 두 번째 경매사.

2026-09-23 경매 소스 확장(인도 축) 조사에서 확인한 근거:

  - robots.txt(2026-09-23 직접 확인): `User-Agent: *` / `Allow: /*` 로 시작하고
    Disallow는 `/Past/` `/flip/` `/blogdetailpage/` `/Home/` `/pdf/` `/lp/`
    `/default.aspx` `/auction-calendar` `/Upcoming/UpcomingPreview*` `/mediadetail/`
    그리고 일부 `/department/*`(희귀서적·만년필·인도골동·자연사)·`/services/*` 뿐이다.
    **이 크롤러가 쓰는 `/api/auctions/*`와 `/auctions/results/*` 경로에는 제한이 없다.**
    ClaudeBot/GPTBot/CCBot 등 AI 봇을 이름으로 차단하는 문구도 전혀 없다
    (Gagosian이 `Content-Signal: ai-train=no`로 명시 차단한 것과 대조적 — 중립).
    `Disallow: /Past/`는 대문자 경로의 구(舊) ASP.NET 사이트 잔재이고, 현행
    과거 낙찰 결과는 `/auctions/results/<year>/<slug>-<id>` 로 서비스된다.
    robots.txt는 경로 대소문자를 구분하므로 `/Past/`가 `/auctions/results/`를
    덮지 않는다. 확실히 하기 위해 `/Past/` 경로는 아예 요청하지 않는다.
  - 약관 전문 4개(terms-and-conditions, privacy-policy, cookie-policy, faqs)를 직접
    GET해 crawl/scrape/spider/harvest/data mining/robot/"database right"/sui generis/
    automated/aggregate/third party 키워드로 전수 검색 — **크롤링·스크래핑·데이터마이닝·
    DB권리 관련 조항이 전혀 없다**. terms-and-conditions는 제목 그대로 "Terms and
    Conditions of **Sale**"로, 응찰자/낙찰자의 등록·입찰·결제·반출 의무만 다루는
    매매 약관이고 **웹사이트 이용(acceptable use) 조항 자체가 없다**(UK/싱가포르 탭도
    같은 매매 약관의 관할별 변형). privacy-policy도 응찰자 개인정보 처리 고지일 뿐
    공개 카탈로그 데이터 이용을 제한하지 않는다.
  - 구조: 화면은 Next.js CSR이라 `/auctions/results/...` HTML에는 로트가 없고,
    페이지가 내부 JSON API 두 개를 호출한다(2026-09-23 네트워크 관찰로 확인).
      * `/api/auctions/get-auctions-by-status?auctionType=PAST&sortOrder=desc&limit=300`
        → 과거 세일 133건(2008-02 ~ 2026-09)의 id·이름·시작/종료 ISO 일시·낙찰총액.
      * `/api/auctions/filter-lots?auctionId=<id>&limit=<n>&page=<n>`
        → 그 세일의 로트. 인증·쿠키·토큰 전부 불필요.
    **과거 세일의 filter-lots는 낙찰된 로트만 돌려준다** — 2026-08 Iconic Masters(50건)
    hammer 합계 974,130,119 x 1.21(프리미엄 21%) = 1,178,697,444 로 사이트가 공시한
    Total Sale과 정확히 일치했고, 2026-09 Imperial Treasures(23건)도 동일하게 검증됐다.
    따라서 유찰 로트는 애초에 응답에 없다(로더가 sold=True로 적재하는 근거).
  - 최신성: 133개 세일이 2008-02-20 ~ 2026-09-11 에 걸쳐 있고 거의 매달 새 세일이
    열린다. 주간 갱신 잡(refresh_weekly.ps1)에 붙이면 get-auctions-by-status를 한 번만
    다시 받아 신규 id만 증분 수집하면 된다.

**개인정보 제거** — filter-lots 응답에는 낙찰자/최고응찰자의 Firebase UID
(`winnerClientID`/`leadingClientID`/`outbidClientID`)와 위탁자 필드
(`consignerID`/`consignerName`/`crID`/`crName`/`sourcingCrID`/`sourcingCrName`)가 섞여
있다. 이 프로젝트가 필요로 하는 건 로트 사실 데이터(작가·작품·추정가·낙찰가)뿐이고
개인 식별자는 수집할 이유가 없어 **저장 전에 해당 키만 제거**한다(그 외 필드는 원본
그대로). 원본 보존 원칙의 예외이며 그 사실을 여기와 meta의 license_note에 남긴다.
카탈로그 원문인 `provenance`("Property from a Parsi collection based in Mumbai" 같은
익명화된 공개 문구)는 그대로 둔다.

이미지 파일은 저장하지 않는다(사실 데이터만 수집 — mediaCollection의 URL 문자열만 남음).

사용법:
    python astaguru.py --phase auctions          # 과거 세일 목록
    python astaguru.py --phase lots              # 목록의 모든 세일 로트
    python astaguru.py --phase lots --auction-id 222   # 특정 세일만(파일럿/증분)
    python astaguru.py --phase lots --since-id 210     # id가 이 값 이상인 세일만(증분)
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

SITE_NAME = "astaguru"
BASE = "https://www.astaguru.com"
AUCTIONS_URL = BASE + "/api/auctions/get-auctions-by-status"
LOTS_URL = BASE + "/api/auctions/filter-lots"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (artgraph-research-bot)",
    "Accept": "application/json",
}
DELAY = 1.5
PAGE_LIMIT = 200

AUCTIONS_RECORD_ID = "auctions_past"

LICENSE_NOTE = (
    "AstaGuru 공개 과거 낙찰결과 JSON API(/api/auctions/get-auctions-by-status, "
    "/api/auctions/filter-lots) — 인증 불필요. robots.txt는 `Allow: /*`이고 "
    "Disallow 목록(/Past/ /flip/ /Home/ /pdf/ /lp/ /auction-calendar 등)에 "
    "/api/ 및 /auctions/results/ 경로 없음, AI 봇 명시 차단 문구 없음. "
    "terms-and-conditions(매매약관)·privacy-policy·cookie-policy·faqs 전문에 "
    "크롤링/스크래핑/데이터마이닝/database right 금지 조항 없음 확인, 2026-09-23. "
    "낙찰자·위탁자 개인식별 필드는 저장 전 제거함."
)

# 저장 전에 제거하는 개인 식별 필드(모듈 독스트링 '개인정보 제거' 참고).
LOT_PII_KEYS = (
    "consignerID", "consignerName", "crID", "crName", "sourcingCrID", "sourcingCrName",
)
STATE_PII_KEYS = ("winnerClientID", "leadingClientID", "outbidClientID")


def _get(url: str, params: dict | None = None, *, attempts: int = 5, base_delay: float = 5.0):
    def _do():
        resp = requests.get(url, params=params, headers=HEADERS, timeout=90)
        resp.raise_for_status()
        return resp.json()

    return with_retry(_do, attempts=attempts, base_delay=base_delay)


def _strip_pii(lot: dict) -> dict:
    for key in LOT_PII_KEYS:
        lot.pop(key, None)
    state = lot.get("auctionState")
    if isinstance(state, dict):
        for key in STATE_PII_KEYS:
            state.pop(key, None)
    return lot


def crawl_auctions() -> list[dict]:
    """과거 세일 목록을 받아 저장한다."""
    data = _get(AUCTIONS_URL, {"auctionType": "PAST", "sortOrder": "desc", "limit": 300})
    auctions = data.get("auctions") or []
    save_raw(
        SITE_NAME,
        AUCTIONS_RECORD_ID,
        json.dumps(data, ensure_ascii=False),
        url=f"{AUCTIONS_URL}?auctionType=PAST&sortOrder=desc&limit=300",
        license_note=LICENSE_NOTE,
    )
    print(f"[astaguru:auctions] 과거 세일 {len(auctions)}개 저장 (totalCount={data.get('totalCount')})")
    return auctions


def _load_auction_ids() -> list[str]:
    path = RAW_ROOT / SITE_NAME / f"{AUCTIONS_RECORD_ID}.json"
    if not path.exists():
        raise SystemExit(
            f"{path} 없음 — 먼저 `python astaguru.py --phase auctions` 실행 필요"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    ids = [str(a.get("id")) for a in (data.get("auctions") or []) if a.get("id") is not None]
    # id는 숫자 문자열이라 수치 정렬(오래된 세일부터)
    return sorted(ids, key=lambda s: int(s) if s.isdigit() else 0)


def crawl_auction_lots(auction_id: str, skip_existing: bool) -> int:
    saved = 0
    page = 1
    while True:
        record_id = f"lots_{auction_id}_p{page:03d}"
        if skip_existing and already_fetched(SITE_NAME, record_id):
            page += 1
            continue

        params = {"auctionId": auction_id, "limit": PAGE_LIMIT, "page": page}
        url = f"{LOTS_URL}?auctionId={auction_id}&limit={PAGE_LIMIT}&page={page}"
        try:
            data = _get(LOTS_URL, params)
        except requests.RequestException as exc:
            print(f"[astaguru:lots] auction {auction_id} page {page} 요청 실패: {exc}")
            break

        lots = data.get("lots") or []
        if not lots:
            if page == 1:
                print(f"[astaguru:lots] auction {auction_id} 로트 0건 — 빈 세일로 판단")
            break

        data["lots"] = [_strip_pii(lot) for lot in lots]
        save_raw(
            SITE_NAME,
            record_id,
            json.dumps(data, ensure_ascii=False),
            url=url,
            license_note=LICENSE_NOTE,
        )
        saved += 1

        total_pages = (data.get("pagination") or {}).get("totalPages")
        if isinstance(total_pages, int) and page >= total_pages:
            break
        if len(lots) < PAGE_LIMIT:
            break
        page += 1
        time.sleep(DELAY)

    return saved


def crawl_lots(auction_ids: list[str], skip_existing: bool) -> None:
    total = 0
    for i, auction_id in enumerate(auction_ids, start=1):
        n = crawl_auction_lots(auction_id, skip_existing)
        total += n
        if n:
            print(f"[astaguru:lots] auction {auction_id}: {n}페이지 저장 ({i}/{len(auction_ids)})")
        time.sleep(DELAY)
    print(f"[astaguru:lots] 전체 완료 — 세일 {len(auction_ids)}개, 총 {total}페이지 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AstaGuru 낙찰 결과 크롤러")
    parser.add_argument("--phase", choices=["auctions", "lots", "all"], default="all")
    parser.add_argument("--auction-id", action="append", default=None, help="특정 auction id만(여러 번 지정 가능)")
    parser.add_argument("--since-id", type=int, default=None, help="이 id 이상인 세일만(증분 수집용)")
    parser.add_argument(
        "--no-skip-existing", dest="skip_existing", action="store_false",
        help="이미 저장된 페이지도 다시 수집",
    )
    args = parser.parse_args()

    if args.phase in ("auctions", "all"):
        crawl_auctions()
    if args.phase in ("lots", "all"):
        ids = args.auction_id if args.auction_id else _load_auction_ids()
        if args.since_id is not None:
            ids = [i for i in ids if i.isdigit() and int(i) >= args.since_id]
        crawl_lots(ids, args.skip_existing)
