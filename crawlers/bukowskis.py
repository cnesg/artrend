"""Bukowskis(스웨덴, bukowskis.com) 낙찰 결과 크롤러 — 북유럽(스칸디나비아) 첫 착수.

2026-09-22 경매 소스 확장(북유럽 축) 조사에서 확인한 근거:

  - robots.txt(2026-09-22 직접 확인): `Disallow: /admin/` `/cms/` `/*/pdf$` 뿐,
    경매/로트 경로에는 아무 제한이 없다. AI 봇을 이름으로 차단/허용하는 문구도 없음
    (중립 — Grisebach처럼 명시 허용은 아니지만 Van Ham처럼 명시 차단도 아니다).
  - 약관 전문(en/tos, en/help/buyer_terms/hammer, en/help/seller_terms/online,
    en/privacy) 4개를 직접 GET해 crawl/scrape/spider/harvest/data mining/robot/
    "database right"/sui generis 키워드로 전수 검색 — **전혀 검출되지 않음**.
    스웨덴/EU 사이트라 특히 주의해서 본 sui generis database right(EU Directive
    96/9/EC) 관련 조항도 없다. "IMAGE REPRODUCTION" 조항(구매약관 17조/판매약관 12조)은
    Bukowskis 자신이 촬영한 사진의 저작권을 스스로에게 유보하는 조항일 뿐 — 칸옥션
    제7조③과 동일 성격이라 **이미지는 수집하지 않는 것으로 지킨다**.
  - 구조: `/en/auctions/<auction_id>/lots/page/<N>` 로트 그리드가 완전 SSR이고,
    로트 하나당 (로트번호, 작가/설명, 제목, **Hammer price**, Estimate)가 전부 그
    페이지 안에 평문으로 들어 있다 — 로트 상세 페이지를 개별 요청할 필요가 없다
    (Grisebach 패턴과 동일, 로트 하나하나를 따로 받아야 했던 Lempertz와 다름).
    `auction_id`는 숫자(라이브 세일, 예 654/673)와 `F` 접두(온라인/피처드 세일, 예
    F533) 두 형식이 섞여 있는데 그리드 엔드포인트는 둘 다 동일하게 동작한다.
  - 규모: `sitemaps/sitemap.xml.gz` → `sitemaps/archived_lots*.xml.gz` (0~88, 89개
    샤드)가 sv/en/fi 3개 언어 URL을 합쳐 약 190만 개 loc을 준다 — 언어당 약 63만
    로트. 이 크롤러는 그리드 페이지 단위로 받으므로 실제 요청 수는 훨씬 적다
    (auction_id 개수 × 세일당 페이지 수, 100로트/페이지).

크롤 절차 2단계:
  1) auction-ids — sitemap.xml.gz의 archived_lots*.xml.gz 샤드를 받아
     `/en/auctions/<id>/` 패턴에서 고유 auction_id를 뽑아 텍스트 파일로 저장.
     (자체 발견용 메타데이터라 raw/로는 저장하지 않는다 — 아래 grid 저장물만 원본.)
  2) grid — auction_id마다 `/en/auctions/<id>/lots/page/<N>`을 0건이 나올 때까지
     순차 저장.

이미지 파일은 저장하지 않는다(사실 데이터만 수집).

사용법:
    python bukowskis.py --phase auction-ids
    python bukowskis.py --phase grid                                  # 발견된 모든 auction_id(_auction_ids.txt)
    python bukowskis.py --phase grid --auction-id 654                 # 특정 세일만(파일럿/재시도용)
    python bukowskis.py --phase grid --ids-file raw/bukowskis/_auction_ids_fineart.txt
        # 2026-09-22 1차 착수는 auction_id 2,121개 중 숫자형(라이브, 122개)+F접두(온라인/
        # 피처드, 682개)=804개만 이 필터 파일로 돌렸다 — 표본 확인 결과 H/S/G/V 접두는
        # 가구·명품가방·은제품·패션 전문이라 스코프 밖으로 판단해 제외(docs/logs/
        # 경매확장_bukowskis_20260922.md 참고). E접두(1,257개, 온라인 상시경매)는 표본이
        # 유리공예 등 혼재라 전수 확인 없이 우선순위만 낮췄다 — 전량 배제는 아니다.
"""
from __future__ import annotations

import argparse
import gzip
import re
import sys
import time
from pathlib import Path

import requests

from common import RAW_ROOT, already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

SITE_NAME = "bukowskis"
BASE = "https://www.bukowskis.com"
SITEMAP_INDEX_URL = f"{BASE}/sitemaps/sitemap.xml.gz"
GRID_URL_TMPL = BASE + "/en/auctions/{auction_id}/lots/page/{page}"
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}
# 2026-09-23: 대량 재개 크롤 중 /lots/page/N 경로에서 간헐적 403(같은 URL을 재요청하면
# 성공하기도 하는 비일관적 패턴 — robots.txt·다른 로트 페이지는 계속 200)을 관측했다.
# 명시적 차단이 아니라 지속 크롤링에 따른 완만한 레이트리밋으로 판단해 딜레이를
# 1.5초 -> 3.0초로 늘렸다(docs/logs/경매확장_bukowskis_20260922.md 참고).
DELAY = 3.0

LICENSE_NOTE = (
    "Bukowskis 공개 로트 그리드(/en/auctions/<id>/lots/page/<N>) SSR HTML — "
    "robots.txt Disallow는 /admin/ /cms/ /*/pdf$ 뿐(경매 경로 제한 없음), "
    "en/tos·en/help/buyer_terms/hammer·en/help/seller_terms/online·en/privacy 전문에 "
    "크롤링/스크래핑/데이터마이닝/sui generis database right 금지 조항 없음 확인, "
    "2026-09-22"
)

AUCTION_ID_DIR = RAW_ROOT / SITE_NAME
AUCTION_IDS_FILE = AUCTION_ID_DIR / "_auction_ids.txt"

# sitemap loc 안의 auction_id: /en/auctions/<id>/... 또는 /sv/auctions/<id>/... 등
AUCTION_ID_RE = re.compile(r"/[a-z]{2}/auctions/([A-Za-z0-9]+)/")
LOT_ITEM_SPLIT = 'data-lot-id="'


def _get(url: str, params: dict | None = None, *, attempts: int = 4, base_delay: float = 5.0) -> requests.Response:
    def _do():
        resp = requests.get(url, params=params, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return resp

    return with_retry(_do, attempts=attempts, base_delay=base_delay)


# 2026-09-23 재개 크롤 중 간헐적 403(레이트리밋 추정 — robots.txt·다른 페이지는 계속
# 200이고 같은 URL을 시간을 두고 재요청하면 성공하기도 함)을 관측했다. 두 가지를
# 시도해 본 뒤 지금 방식으로 정착했다:
#   1) "403이면 그 페이지에서 세일 끝"으로 보고 즉시 끊기 — F165/page 4~5가 이렇게
#      끊길 뻔했는데, 잠시 후 처음부터 재수집하니 **실제로는 7페이지까지 전부 정상
#      존재**했다. 데이터를 조용히 빠뜨릴 위험이 있어 폐기.
#   2) 모든 페이지를 5회(누적 최대 155초)까지 재시도 — 정확하지만 F162처럼 특정
#      구간에서 여러 세일이 연달아 걸리면 세일 하나당 최악 13분(5회 연속 페이지 실패
#      × 155초)까지 걸려 804개 세일 전체를 도는 데 비현실적으로 오래 걸렸다.
# 지금은 절충: 그리드 페이지는 `attempts=3, base_delay=5.0`(5+10+20=35초)로 적당히만
# 재시도하고, **세일 하나를 포기하는 연속 실패 기준도 5 -> 2로 낮춰** 막힌 세일에
# 매달리는 시간을 최악 약 70초로 줄였다. 트레이드오프: 일부 세일의 꼬리 페이지를
# 놓칠 수 있다(그리자바흐가 약 2%를 이런 이유로 후속 과제로 남긴 것과 같은 성격의
# 손실 — `docs/logs/경매확장_bukowskis_20260922.md`에 기록). `already_fetched` 기반이라
# 특정 세일을 나중에 다시 지정해 재시도하는 것은 언제든 가능하다
# (`--auction-id <id> --no-skip-existing`).


def discover_auction_ids() -> list[str]:
    """sitemap.xml.gz -> archived_lots*.xml.gz 샤드들에서 고유 auction_id를 모은다."""
    print("[bukowskis:auction-ids] sitemap 인덱스 요청")
    idx_resp = _get(SITEMAP_INDEX_URL)
    shard_urls = re.findall(r"<loc>([^<]*archived_lots[^<]*)</loc>", idx_resp.text)
    print(f"[bukowskis:auction-ids] archived_lots 샤드 {len(shard_urls)}개")

    auction_ids: set[str] = set()
    for i, shard_url in enumerate(sorted(shard_urls), start=1):
        try:
            resp = _get(shard_url)
        except requests.RequestException as exc:
            print(f"[bukowskis:auction-ids] 샤드 요청 실패, 건너뜀: {shard_url} ({exc})")
            continue
        try:
            xml_text = gzip.decompress(resp.content).decode("utf-8", errors="replace")
        except OSError:
            xml_text = resp.text  # 이미 풀린 응답일 경우 대비
        found = AUCTION_ID_RE.findall(xml_text)
        auction_ids.update(found)
        if i % 10 == 0:
            print(f"[bukowskis:auction-ids] 샤드 {i}/{len(shard_urls)} 처리, 누적 auction_id {len(auction_ids)}개")
        time.sleep(0.3)  # sitemap XML은 검색엔진도 자유롭게 받는 자원이라 로트 그리드보다 짧게

    AUCTION_ID_DIR.mkdir(parents=True, exist_ok=True)
    AUCTION_IDS_FILE.write_text("\n".join(sorted(auction_ids)), encoding="utf-8")
    print(f"[bukowskis:auction-ids] 완료 — auction_id {len(auction_ids)}개, {AUCTION_IDS_FILE} 저장")
    return sorted(auction_ids)


def _load_auction_ids(ids_file: Path | None = None) -> list[str]:
    path = ids_file or AUCTION_IDS_FILE
    if not path.exists():
        raise SystemExit(
            f"{path} 없음 — 먼저 `python bukowskis.py --phase auction-ids` 실행 필요"
        )
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def crawl_auction_grid(auction_id: str, skip_existing: bool) -> int:
    saved = 0
    page = 1
    consecutive_failures = 0
    while True:
        if consecutive_failures >= 2:
            print(f"[bukowskis:grid] auction {auction_id} 연속 실패 {consecutive_failures}회 — 중단(page={page})")
            break
        record_id = f"grid_{auction_id}_p{page:04d}"

        if skip_existing and already_fetched(SITE_NAME, record_id, ext="html"):
            page += 1
            continue

        url = GRID_URL_TMPL.format(auction_id=auction_id, page=page)
        try:
            resp = _get(url, attempts=3, base_delay=5.0)
        except requests.RequestException as exc:
            print(f"[bukowskis:grid] auction {auction_id} page {page} 요청 실패: {exc}")
            consecutive_failures += 1
            page += 1
            time.sleep(DELAY)
            continue
        consecutive_failures = 0

        if LOT_ITEM_SPLIT not in resp.text:
            if page == 1:
                print(f"[bukowskis:grid] auction {auction_id} 로트 0건(page 1) — 존재하지 않거나 빈 세일로 판단")
            break

        save_raw(
            SITE_NAME,
            record_id,
            resp.text,
            url=url,
            license_note=LICENSE_NOTE,
            ext="html",
        )
        saved += 1
        page += 1
        time.sleep(DELAY)

    return saved


def crawl_grid(auction_ids: list[str], skip_existing: bool) -> None:
    total_pages = 0
    for i, auction_id in enumerate(auction_ids, start=1):
        n = crawl_auction_grid(auction_id, skip_existing)
        total_pages += n
        if n:
            print(f"[bukowskis:grid] auction {auction_id}: {n}페이지 저장 ({i}/{len(auction_ids)})")
    print(f"[bukowskis:grid] 전체 완료 — 세일 {len(auction_ids)}개, 총 {total_pages}페이지 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bukowskis 낙찰 결과 크롤러")
    parser.add_argument("--phase", choices=["auction-ids", "grid", "all"], default="all")
    parser.add_argument("--auction-id", action="append", default=None, help="특정 auction_id만(여러 번 지정 가능)")
    parser.add_argument(
        "--ids-file", type=Path, default=None,
        help="auction_id 목록 파일(기본 _auction_ids.txt 대신 필터링된 목록을 쓸 때)",
    )
    parser.add_argument(
        "--no-skip-existing", dest="skip_existing", action="store_false",
        help="이미 저장된 페이지도 다시 수집",
    )
    args = parser.parse_args()

    if args.phase in ("auction-ids", "all"):
        discover_auction_ids()
    if args.phase in ("grid", "all"):
        ids = args.auction_id if args.auction_id else _load_auction_ids(args.ids_file)
        crawl_grid(ids, args.skip_existing)
