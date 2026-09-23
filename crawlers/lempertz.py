"""Lempertz(쾰른, 1845년 설립 — 독일에서 가장 오래된 경매사 중 하나) 낙찰 로트 수집.

2026-09-22 경매 소스 확장 조사(B-3, `docs/경매소스확장_20260922.md`)에서 "가능(미착수)"
판정을 받은 소스를 이번 세션에서 실제 착수한다. 착수 전 직접 재확인한 근거
(`docs/logs/경매확장_lempertz_20260922.md`에 상세 기록):

  - robots.txt(직접 확인, 2026-09-22): `User-agent: *`에 `/typo3/` `/typo3_src/`만 차단.
    PetalBot(Huawei)은 전면 차단하지만 ClaudeBot/anthropic-ai 등 AI 봇에 대한 개별 차단은
    없다 — 중립. `Sitemap: https://www.lempertz.com/sitemapindex.xml` 제공.
  - Legal Notice(`/en/legal-notice.html`) — Impressum 정보만 있고 Hampel(뮌헨)에서 발견됐던
    "reproduction in databases" 금지, "personal/private use only" 조항이 **없다**(전문 확인).
  - Privacy Policy·Conditions of Sale·Conditions of Consignment 전문에도 crawl/scrape/robot/
    spider/data mining/harvest/database reuse 관련 키워드가 전혀 없다(grep 전수 확인).
  - 로트 상세 페이지(`/en/catalogues/lot/<경매번호>-<세션>/<로트번호>-<슬러그>.html`)가 완전
    SSR이고, 게다가 `<script type="application/ld+json">` Product 스키마에 작가(creator)·
    제목·추정가(offers.lowPrice/highPrice)·낙찰가(offers.price, 프리미엄 포함)·통화가 구조화된
    형태로 그대로 있다 — HTML 클래스 파싱보다 이 JSON-LD를 우선 신뢰한다.

sitemap 기반 수집: `sitemapindex.xml` -> `sitemap-en-lots-N.xml`(샤드당 최대 5,000건, 2026-09-22
기준 18개 샤드, 영문 기준 약 86,800건 로트 URL)를 전부 펼쳐 로트 페이지를 개별 GET한다.
로트를 한꺼번에 보여주는 목록/카탈로그 페이지를 찾지 못해(B-3에 이미 기록됨) 로트당 1회
요청이 불가피하다 — 규모가 커서 전량 수집은 여러 세션/배치로 나눠야 한다(`--limit`으로 이번
실행 분량을 제한).

**주의: sitemap에 죽은 URL이 섞여 있다.** 실측(2026-09-22)으로 카탈로그 번호가 30000번대인
로트(비공개/특수 세일로 추정, 샤드 0에서 약 94/5000건)가 실제로는 `/en/404.html`로 302
리다이렉트된다 — 응답 상태코드 자체는 200(리다이렉트 따라간 뒤 404 안내 페이지가 200으로
서빙됨)이라 상태코드만으로는 못 거른다. 최종 URL이 `/en/404.html`인지 확인해서 걸러내고
`_dead_urls.txt`에 기록해 재실행 시 재요청하지 않는다. 일반 카탈로그 번호(수백~1200번대)
샘플은 전부 200으로 정상 응답했다.

이미지 파일은 저장하지 않는다(사실 데이터만 수집).

사용법:
    python lempertz.py --limit 200      # 파일럿: 이번 실행에서 최대 200건만 새로 수집
    python lempertz.py                  # 계속 이어서 전량(약 8.7만 건, 매우 오래 걸림)
"""
from __future__ import annotations

import argparse
import sys
import time
import xml.etree.ElementTree as ET
import zlib

import requests

from common import RAW_ROOT, already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

SITE_NAME = "lempertz"
BASE = "https://www.lempertz.com"
SITEMAP_INDEX = f"{BASE}/sitemapindex.xml"
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}
# robots.txt에 Crawl-delay 지정 없음(전면 허용) — 예의상 최소 1.5~2초 간격을 스스로 지킨다.
CRAWL_DELAY = 1.8

LICENSE_NOTE = (
    "Lempertz(쾰른) 공개 로트 상세 페이지 SSR HTML — robots.txt: /typo3/만 차단(AI 봇 개별 차단 "
    "없음, PetalBot만 전면 차단), Legal Notice/Privacy Policy/Conditions of Sale/Conditions of "
    "Consignment 전문에 크롤링·스크래핑·데이터마이닝·DB 재이용·personal-use-only 조항 없음(TDM "
    "유보 없음) 확인, 2026-09-22"
)

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
DEAD_LOG = RAW_ROOT / SITE_NAME / "_dead_urls.txt"


class Blocked(Exception):
    """HTTP 403 — 봇 차단 신호. 재시도·우회하지 않고 크롤을 멈춘다."""


def _get(url: str, **kw) -> requests.Response:
    def _do():
        resp = requests.get(url, headers=HEADERS, timeout=60, **kw)
        if resp.status_code == 403:
            raise Blocked(url)
        resp.raise_for_status()
        return resp

    return with_retry(_do, attempts=4, base_delay=5.0)


def _get_lot(url: str) -> requests.Response | None:
    """로트 페이지 전용 GET — 진짜 HTTP 404는 즉시 죽은 링크로 판정하고 None을 반환한다.

    sitemap에 세션 번호가 중복 붙은 것 같은(예: '.../1311-1-1/8-joseph-beuys.html') 깨진
    경로가 섞여 있어 실제로 HTTP 404가 나는 경우가 있다(2026-09-22 파일럿에서 실측). 이걸
    `_get()`처럼 raise_for_status + with_retry에 그대로 태우면 진짜 존재하지 않는 페이지를
    4회(최대 35초) 재시도하며 시간을 낭비한다 — 404는 재시도 대상이 아니라 즉시 확정해야
    한다. 5xx/429(일시적 서버 오류)만 재시도하고, 그 외 오류는 `_get()`과 동일하게 던진다.
    """

    def _do():
        resp = requests.get(url, headers=HEADERS, timeout=60)
        if resp.status_code == 403:
            raise Blocked(url)
        if resp.status_code >= 500 or resp.status_code == 429:
            resp.raise_for_status()  # with_retry가 재시도하도록 예외로 승격
        return resp

    resp = with_retry(_do, attempts=4, base_delay=5.0)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp


def discover_lot_urls() -> list[str]:
    """sitemapindex.xml -> sitemap-en-lots-N.xml 전부 순회해 로트 URL 리스트를 만든다."""
    resp = _get(SITEMAP_INDEX)
    root = ET.fromstring(resp.content)
    shard_urls = [
        loc.text.strip()
        for loc in root.findall(".//sm:sitemap/sm:loc", NS)
        if loc.text and "-en-lots-" in loc.text
    ]
    print(f"[lempertz] lots sitemap 샤드 {len(shard_urls)}개 발견")

    lot_urls: list[str] = []
    for shard_url in shard_urls:
        resp = _get(shard_url)
        shard_root = ET.fromstring(resp.content)
        urls = [loc.text.strip() for loc in shard_root.findall(".//sm:url/sm:loc", NS) if loc.text]
        lot_urls.extend(urls)
        time.sleep(0.5)  # sitemap 자체는 가벼운 XML이라 짧게만 쉰다
    print(f"[lempertz] 로트 URL {len(lot_urls)}건 수집(sitemap 기준, 죽은 URL 포함될 수 있음)")
    return lot_urls


def _record_id_from_url(url: str) -> str:
    # https://www.lempertz.com/en/catalogues/lot/822-1/377-pablo-picasso.html
    #   -> 822-1_377-pablo-picasso
    path = url.split("/catalogues/lot/", 1)[1]
    if path.endswith(".html"):
        path = path[: -len(".html")]
    return path.replace("/", "_")


def _load_dead_set() -> set[str]:
    if not DEAD_LOG.exists():
        return set()
    return set(DEAD_LOG.read_text(encoding="utf-8").splitlines())


def _append_dead(url: str) -> None:
    DEAD_LOG.parent.mkdir(parents=True, exist_ok=True)
    with DEAD_LOG.open("a", encoding="utf-8") as f:
        f.write(url + "\n")


def crawl_lots(limit: int | None, skip_existing: bool, shard: tuple[int, int] | None = None) -> None:
    lot_urls = discover_lot_urls()
    if shard is not None:
        # URL 해시로 나눠 sitemap 순서가 바뀌어도 샤드 간 겹침·누락이 없다.
        k, n = shard
        lot_urls = [u for u in lot_urls if zlib.crc32(u.encode()) % n == k]
        print(f"[lempertz] 샤드 {k}/{n}: 로트 URL {len(lot_urls)}건")
    dead = _load_dead_set()

    saved = 0
    skipped_cached = 0
    skipped_dead = 0
    skipped_404 = 0

    for url in lot_urls:
        if limit is not None and saved >= limit:
            break
        if url in dead:
            skipped_dead += 1
            continue
        # lots sitemap에 로트가 아닌 URL이 섞여 있어 전체 크롤이 IndexError로 죽은 적이 있다.
        if "/catalogues/lot/" not in url:
            skipped_404 += 1
            continue
        record_id = _record_id_from_url(url)
        if skip_existing and already_fetched(SITE_NAME, record_id, ext="html"):
            skipped_cached += 1
            continue

        try:
            resp = _get_lot(url)
        except requests.RequestException as exc:
            print(f"[lempertz] {url} 요청 실패, 건너뜀: {exc}")
            time.sleep(CRAWL_DELAY)
            continue

        # 죽은 URL 케이스 1: 진짜 HTTP 404(세션 번호 중복 등 깨진 sitemap 경로).
        if resp is None:
            _append_dead(url)
            skipped_404 += 1
            time.sleep(CRAWL_DELAY)
            continue

        # 죽은 URL 케이스 2: 30000번대(비공개/특수 세일 추정) 카탈로그 — TYPO3가 302로
        # /en/404.html 로 돌리고 requests가 그대로 따라가므로 최종 응답 자체는 200이다 —
        # 상태코드가 아니라 최종 URL로 판별해야 한다.
        if resp.url.rstrip("/").endswith("/404.html"):
            _append_dead(url)
            skipped_404 += 1
            time.sleep(CRAWL_DELAY)
            continue

        save_raw(SITE_NAME, record_id, resp.text, url=url, license_note=LICENSE_NOTE, ext="html")
        saved += 1
        if saved % 20 == 0:
            print(
                f"[lempertz] {saved}건 저장 "
                f"(스킵: 캐시 {skipped_cached}, 기존dead {skipped_dead}, 신규404 {skipped_404})"
            )
        time.sleep(CRAWL_DELAY)

    print(
        f"[lempertz] 완료 — {saved}건 저장, 캐시 스킵 {skipped_cached}건, "
        f"기존 dead {skipped_dead}건, 신규 404 {skipped_404}건"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lempertz 낙찰 로트 크롤러")
    parser.add_argument(
        "--limit", type=int, default=None, help="이번 실행에서 새로 저장할 최대 로트 수(파일럿용)"
    )
    parser.add_argument(
        "--no-skip-existing", dest="skip_existing", action="store_false",
        help="이미 저장된 로트도 다시 수집",
    )
    parser.add_argument("--shard", default=None, help="K/N — 로트 URL 해시로 N분할 중 K번째만 수집")
    args = parser.parse_args()
    shard = tuple(int(x) for x in args.shard.split("/")) if args.shard else None
    try:
        crawl_lots(args.limit, args.skip_existing, shard)
    except Blocked as exc:
        print(f"[lempertz] HTTP 403(봇 차단 신호) — 우회하지 않고 중단: {exc}")
        sys.exit(3)
