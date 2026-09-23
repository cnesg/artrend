"""Auktionshaus im Kinsky(빈, Palais Kinsky — 오스트리아 최대 미술 경매사 중 하나) 낙찰 로트 수집.

오스트리아 축은 직전에 Dorotheum(빈)이 ToS에서 AI 학습/TDM/임베딩을 명시적으로 금지해
완전 제외되면서 공백이 생겼다. 그 대체 후보로 조사된 곳이 여기다.

착수 전 **직접 재확인한 근거**(2026-09-23, `docs/logs/경매확장_imkinsky_20260923.md`에 상세):

  - **도메인은 `imkinsky.com`이다.** `kinsky.at`은 DNS는 해석되지만(81.19.145.30) 443 연결
    자체가 거부된다 — 경매사 사이트가 아니다. 예비조사 단계에서 kinsky.at으로 잘못 기록돼
    있었던 것을 이번에 바로잡았다.
  - **robots.txt**(직접 확인): 표준 Drupal 9 기본값(`/core/` `/profiles/` `/admin/`
    `/user/login` 등 시스템 경로만 차단)에 커스텀 항목이 딱 두 줄 —
    `Disallow: /ergebnisse/139/723/2/94833` 와 그 영문판
    `Disallow: /en/auction-results/139/723/2/94833`. **이 로트 하나만 크롤링 금지**이며
    (실제로는 HTTP 200으로 살아 있다 — 예비조사의 "이미 404"는 틀렸다) 이 크롤러는
    `ROBOTS_DISALLOWED_PATHS`로 명시 제외한다. 나머지 `/en/auction-results/**`는 전면 허용.
    AI 봇(ClaudeBot/GPTBot/CCBot 등) 개별 차단 없음, `Content-Signal` 없음, `Crawl-delay` 없음.
  - **응답 헤더에 `X-Robots-Tag` 없음, 페이지에 `<meta name="robots">` 없음.**
  - **법적 페이지 전문 확인**: 사이트가 노출하는 법적 문서는 Imprint(`/en/impressum`),
    Privacy notice(`/en/privacy-notice`), Fees and Conditions(`/en/fees-and-conditions`),
    Withdrawal right(`/en/withdrawal-right`) 넷뿐이고 별도 이용약관/AGB 페이지는 존재하지
    않는다(`/agb`, `/nutzungsbedingungen`, `/de/impressum` 전부 404). 네 문서 + 독문판
    (`/impressum`, `/datenschutz`) 전문에 text-and-data-mining / TDM / Nutzungsvorbehalt /
    §42h(오스트리아 저작권법 TDM 유보 조항) / sui generis · Datenbankhersteller(DB제작자권) /
    AI · machine learning · Trainingsdaten / scraping · crawling · robot / 복제 금지 조항이
    **한 건도 없다**(정규식 전수 검색, 히트 0). Impressum은 회사 등기·감독관청·Google
    Analytics 고지뿐이고, Fees and Conditions는 수수료율 표뿐이다.
  - WAF/봇차단 없음, 완전 SSR(Drupal 9) — JS 렌더링 불필요.
  - **최신성**: 아카이브가 1996년부터 **2026년 경매까지** 이어진다(살아있는 소스).
    마지막 auction_id + 1부터 증분하는 패턴이라 주간 자동갱신에 붙이기 좋다.

수집 구조(3단계):

    /en/archive                        -> 경매(auction) id 목록
    /en/auction-results/<a>            -> 그 경매의 세일(부문별 세션) 목록 <a>/<s>/<n>
    /en/auction-results/<a>/<s>/<n>    -> 로트 목록(40건/페이지, ?page=N 페이징)
    /en/auction-results/<a>/<s>/<n>/<lot_id>  -> 로트 상세(여기만 원본 저장)

로트 상세 페이지 하나에 작가명 + 생몰 표기, 제목/제작연도/재질/규격/서명, **Provenance /
Exhibition / Literature 원문**, 추정가, Realized price(수수료·VAT 포함), **Hammer Price**
(수수료 제외 순수 낙찰가)가 전부 평문으로 들어 있다.

1~3단계 결과(로트 URL 목록)는 `raw/im_kinsky/_index.json`에 캐시해 재실행 시 다시 훑지
않는다(`--refresh-index`로 갱신, `--index-only`로 목록만). 4단계 로트 상세만
`already_fetched()` 기준으로 증분 수집한다. 이미지 파일은 저장하지 않는다.

사용법:
    python im_kinsky.py --index-only                 # 목록만 만들고 규모 확인
    python im_kinsky.py --limit 300                  # 파일럿: 300건만 상세 수집
    python im_kinsky.py --newest-first               # 최신 경매부터 역순으로 전량
    python im_kinsky.py --since-auction 150          # auction_id 150 이상만(주간 증분용)
    python im_kinsky.py --newest-first --shard 0/3 --delay 3.0   # 병렬 백필 샤드 1/3

로트 상세 한 건에 실측 약 2.3초(서버 응답) + 대기가 든다. 전량이 수만 건대라 단일
프로세스로는 수십 시간이 걸리므로 `--shard i/N`으로 나눠 병렬로 돌린다. 이때 **각 샤드의
`--delay`를 샤드 수만큼 늘려** 사이트에 가는 전체 요청률이 초당 1건 안팎을 넘지 않게 할 것.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

from common import RAW_ROOT, already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

SITE_NAME = "im_kinsky"
BASE = "https://imkinsky.com"
ARCHIVE_URL = f"{BASE}/en/archive"
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}
# robots.txt에 Crawl-delay 지정 없음 — 예의상 스스로 1.2초 간격을 지킨다.
CRAWL_DELAY = 1.2

# robots.txt가 유일하게 차단한 경로(그리고 그 독문판). 절대 요청하지 않는다.
ROBOTS_DISALLOWED_PATHS = {
    "/en/auction-results/139/723/2/94833",
    "/ergebnisse/139/723/2/94833",
}

LICENSE_NOTE = (
    "Auktionshaus im Kinsky(빈) 공개 낙찰결과 로트 상세 페이지 SSR HTML — robots.txt는 Drupal "
    "기본 시스템 경로 + 특정 로트 1건(/en/auction-results/139/723/2/94833)만 차단하고 "
    "/en/auction-results/** 전면 허용(AI 봇 개별 차단·Content-Signal 없음), Imprint/Privacy "
    "notice/Fees and Conditions/Withdrawal right 전문에 TDM 유보(§42h)·sui generis DB권·"
    "AI 학습 금지·스크래핑 금지 조항 없음(별도 이용약관 페이지 자체가 존재하지 않음) 확인, "
    "2026-09-23"
)

INDEX_PATH = RAW_ROOT / SITE_NAME / "_index.json"

SALE_PATH_RE = re.compile(r'href="(/en/auction-results/\d+/\d+/\d+)"')
LOT_PATH_RE = re.compile(r'href="(/en/auction-results/\d+/\d+/\d+/\d+)"')


def _get(url: str, *, allow_404: bool = False) -> requests.Response | None:
    """GET + 지수 백오프 재시도. 5xx/429만 재시도하고 404는 즉시 확정한다."""

    def _do():
        resp = requests.get(url, headers=HEADERS, timeout=60)
        if resp.status_code >= 500 or resp.status_code == 429:
            resp.raise_for_status()
        return resp

    resp = with_retry(_do, attempts=4, base_delay=5.0)
    if resp.status_code == 404:
        if allow_404:
            return None
        resp.raise_for_status()
    resp.raise_for_status()
    return resp


def _plain(fragment: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", fragment)
    text = re.sub(r"(?s)<[^>]+>", "\n", text)
    text = text.replace("&nbsp;", " ").replace("&#160;", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def discover_auction_ids() -> list[int]:
    """/en/archive -> 경매 id 목록(오름차순)."""
    resp = _get(ARCHIVE_URL)
    ids = sorted({int(m) for m in re.findall(r"/en/auction-results/(\d+)", resp.text)})
    print(f"[im_kinsky] 아카이브에서 경매 {len(ids)}개 발견 (id {min(ids)}~{max(ids)})")
    return ids


def discover_sales(auction_id: int) -> list[dict]:
    """경매 페이지 -> 세일(부문별 세션) 목록. 각 항목: path/title/date_text."""
    resp = _get(f"{BASE}/en/auction-results/{auction_id}", allow_404=True)
    if resp is None:
        return []
    html_text = resp.text
    auction_title = None
    m = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", html_text)
    if m:
        auction_title = _plain(m.group(1)).replace("Results ", "", 1).strip() or None

    sales: list[dict] = []
    seen: set[str] = set()
    # 세일 카드: <a href="/en/auction-results/139/723/2">Contemporary Art</a> 다음에
    # 날짜 텍스트가 이어진다. 카드 단위로 잘라서 제목/날짜를 같이 잡는다.
    for card in re.findall(r'(?is)<a href="/en/auction-results/\d+/\d+/\d+".*?(?=<a href="/en/auction-results/\d+/\d+/\d+"|\Z)', html_text):
        pm = SALE_PATH_RE.search(card)
        if not pm:
            continue
        path = pm.group(1)
        if path in seen:
            continue
        seen.add(path)
        lines = _plain(card).splitlines()
        title = lines[0] if lines else None
        date_text = None
        for line in lines[1:4]:
            if re.match(r"^\d{1,2}\.\s+\w+\s+\d{4}", line):
                date_text = line
                break
        sales.append(
            {
                "auction_id": auction_id,
                "auction_title": auction_title,
                "path": path,
                "title": title,
                "date_text": date_text,
            }
        )
    return sales


def discover_lots(sale: dict) -> list[dict]:
    """세일 목록 페이지(?page=N)를 끝까지 넘기며 로트 상세 경로를 모은다."""
    lots: list[dict] = []
    seen: set[str] = set()
    page = 0
    while True:
        url = f"{BASE}{sale['path']}" + (f"?page={page}" if page else "")
        resp = _get(url, allow_404=True)
        if resp is None:
            break
        paths = LOT_PATH_RE.findall(resp.text)
        new = [p for p in paths if p not in seen]
        if not new:
            break
        for p in new:
            seen.add(p)
            lots.append({"path": p, "sale_path": sale["path"], "auction_id": sale["auction_id"]})
        page += 1
        time.sleep(CRAWL_DELAY)
        if page > 200:  # 안전장치 — 정상적으로는 세일당 수십 페이지를 넘지 않는다
            print(f"[im_kinsky] {sale['path']} 페이지 200 초과 — 중단")
            break
    return lots


def build_index() -> dict:
    auction_ids = discover_auction_ids()
    sales: list[dict] = []
    lots: list[dict] = []
    for i, aid in enumerate(auction_ids, 1):
        found = discover_sales(aid)
        sales.extend(found)
        time.sleep(CRAWL_DELAY)
        for sale in found:
            lots.extend(discover_lots(sale))
        print(f"[im_kinsky] 경매 {aid} ({i}/{len(auction_ids)}) — 세일 {len(found)}개, 누적 로트 {len(lots)}건")
    index = {"auction_ids": auction_ids, "sales": sales, "lots": lots}
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    print(f"[im_kinsky] 인덱스 저장 — 경매 {len(auction_ids)}개 / 세일 {len(sales)}개 / 로트 {len(lots)}건")
    return index


def load_index(refresh: bool) -> dict:
    if refresh or not INDEX_PATH.exists():
        return build_index()
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def record_id_for(path: str) -> str:
    # /en/auction-results/139/723/2/94833 -> 139_723_2_94833
    return path.rsplit("/en/auction-results/", 1)[-1].replace("/", "_")


def crawl_lots(
    index: dict,
    *,
    limit: int | None,
    newest_first: bool,
    since_auction: int | None,
    shard: tuple[int, int] | None = None,
    delay: float = CRAWL_DELAY,
) -> None:
    lots = index["lots"]
    if since_auction is not None:
        lots = [l for l in lots if l["auction_id"] >= since_auction]
    if shard is not None:
        # 로트 id로 샤딩한다(경매 단위로 나누면 회차별 로트 수 편차가 커서 샤드 간
        # 작업량이 크게 어긋난다). 파이썬 `hash()`는 프로세스마다 시드가 달라져
        # 샤드가 어긋나므로 쓰지 않고, URL 끝의 로트 id 정수를 그대로 쓴다.
        # 여러 프로세스를 병렬로 띄워도 already_fetched() 덕분에 겹쳐도 안전하지만,
        # 샤딩하면 중복 요청 자체가 없다.
        idx, total = shard
        lots = [l for l in lots if int(l["path"].rsplit("/", 1)[-1]) % total == idx % total]
        print(f"[im_kinsky] 샤드 {idx}/{total} — 담당 로트 {len(lots)}건")
    lots = sorted(lots, key=lambda l: (-l["auction_id"] if newest_first else l["auction_id"], l["path"]))

    saved = skipped_cached = skipped_robots = skipped_404 = failed = 0
    for lot in lots:
        if limit is not None and saved >= limit:
            break
        path = lot["path"]
        if path in ROBOTS_DISALLOWED_PATHS:
            skipped_robots += 1
            continue
        rid = record_id_for(path)
        if already_fetched(SITE_NAME, rid, ext="html"):
            skipped_cached += 1
            continue
        url = f"{BASE}{path}"
        try:
            resp = _get(url, allow_404=True)
        except requests.RequestException as exc:
            failed += 1
            print(f"[im_kinsky] {url} 요청 실패, 건너뜀: {exc}")
            time.sleep(CRAWL_DELAY)
            continue
        if resp is None:
            skipped_404 += 1
            time.sleep(CRAWL_DELAY)
            continue
        save_raw(SITE_NAME, rid, resp.text, url=url, license_note=LICENSE_NOTE, ext="html")
        saved += 1
        if saved % 50 == 0:
            print(f"[im_kinsky] {saved}건 저장 (캐시스킵 {skipped_cached}, 404 {skipped_404}, 실패 {failed})")
        time.sleep(delay)

    print(
        f"[im_kinsky] 완료 — {saved}건 저장, 캐시 스킵 {skipped_cached}건, "
        f"robots 제외 {skipped_robots}건, 404 {skipped_404}건, 실패 {failed}건"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auktionshaus im Kinsky 낙찰 로트 크롤러")
    parser.add_argument("--index-only", action="store_true", help="로트 목록(인덱스)만 만들고 종료")
    parser.add_argument("--refresh-index", action="store_true", help="인덱스를 다시 만든다")
    parser.add_argument("--limit", type=int, default=None, help="이번 실행에서 새로 저장할 최대 로트 수")
    parser.add_argument("--newest-first", action="store_true", help="최신 경매부터 역순 수집")
    parser.add_argument("--since-auction", type=int, default=None, help="이 auction_id 이상만 수집")
    parser.add_argument(
        "--shard", default=None,
        help="'i/N' — 로트를 N등분해 i번째만 수집(병렬 백필용, 예: --shard 0/3)",
    )
    parser.add_argument(
        "--delay", type=float, default=CRAWL_DELAY,
        help=f"요청 간 대기(초). 기본 {CRAWL_DELAY}. 병렬 샤드를 띄울 땐 샤드 수만큼 늘려 "
             "전체 요청률을 1초당 1건 안팎으로 유지할 것",
    )
    args = parser.parse_args()

    shard = None
    if args.shard:
        i, n = args.shard.split("/")
        shard = (int(i), int(n))

    idx = load_index(refresh=args.refresh_index or args.index_only)
    if args.index_only:
        sys.exit(0)
    crawl_lots(
        idx,
        limit=args.limit,
        newest_first=args.newest_first,
        since_auction=args.since_auction,
        shard=shard,
        delay=args.delay,
    )
