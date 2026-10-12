"""Auctionet(auctionet.com) 종료 경매(낙찰/유찰) 미술 로트 수집.

Auctionet은 **단일 경매사가 아니라 애그리게이터**다 — Auction Network Sweden AB가 운영하는
온라인 마켓플레이스에 북유럽(스웨덴·덴마크·핀란드)·독일·스페인·영국의 개별 경매사 약 83곳이
입점해, 각 경매사가 자기 실물 경매를 온라인으로 함께 연다(2026-09-23 `/en/auction_houses` 확인).
ToS 서두가 이 구조를 명시한다: "Auctionet is only a provider of the Service ... Customer who
purchases an Auction Item ... will purchase the Auction Item from the Auction House which has
held the auction."

  => 따라서 **Auctionet 자체를 auction_houses 한 행으로 넣지 않는다.** 로트마다 실제 개최
     경매사(상세 페이지 `House` 필드)를 auction_houses로 쓰고, Auctionet은 sources(수집 출처)
     로만 남긴다. `pipeline/auctionet.py` 상단 주석에 이 결정의 근거를 더 적어 뒀다.

착수 전 직접 확인한 근거(2026-09-23):
  - robots.txt: `User-Agent: *` / `Disallow: /admin/`, `/*/my$`, `/*/my/*` 뿐. 검색·로트·경매사
    페이지는 전부 허용이고 **ClaudeBot/GPTBot/CCBot 등 AI 봇 개별 차단 문구 없음**.
    Content-Signal(ai-train=no) 류 헤더도 없음. Gagosian 사례와 정반대.
  - Terms of Use 영문 전문(`/en/terms_of_use`, 2026-06-23 발효)과 스웨덴어 전문
    (`/sv/terms_of_use`, 구조·조항 동일) 을 직접 통독하고 crawl/scrape/spider/robot/
    data mining/text and data mining/databas(e) right/96/9/EC/2019/790/personal use/
    non-commercial/third party 키워드를 전수 검색 — **해당 금지 조항이 하나도 없다.**
    ToU는 계정 등록·로그인 관리·AML/제재·책임제한·준거법만 다루고, 콘텐츠 이용이나
    자동수집에 대한 제한 조항 자체가 존재하지 않는다. Terms of Purchase / Hammer auction
    terms / Privacy policy도 같은 키워드로 훑었고 마찬가지.
    (오늘 같은 축에서 막힌 Setdart·Balclis의 스페인 LSSI 보일러플레이트 "목적 불문 사전
     서면 동의 필요"나 Dorotheum의 명시적 TDM 옵트아웃 같은 조항이 여기엔 **없다**.
     Balclis는 자사 사이트 ToS로는 막혔지만 실제 입찰은 Auctionet에서 돌고, Auctionet의
     ToS에는 그 제한이 없어 Auctionet 경로로는 수집 가능하다.)
  - 로트 상세/검색 결과가 전부 SSR이고, 데이터가 React 프리하이드레이션 JSON
    (`data-react-props`)으로 페이지 안에 그대로 박혀 있다. 비공개 API를 때리는 게 아니라
    공개 HTML이 이미 들고 있는 값을 읽는다.

**입찰자 정보 제거(필수)**: 상세 페이지의 `VipBidFormOrResult` 프리하이드레이션 JSON에는
`bids[]` 배열이 통째로 들어 있고 각 원소에 입찰자 식별번호(`bidder`, 경매별 익명 번호),
입찰 색상, **초 단위 입찰 시각**(`time_string_long`, `max_bid_time_string`)이 담긴다.
이 프로젝트가 쓰지 않는 제3자 정보라 **저장 전에 `bids[]`를 통째로 버리고** 집계값
(`bid_count`, `top_bid_amount`)만 남긴다. 낙찰가는 `top_bid_amount`로 충분하다.

**통화**: 로트의 원 통화는 SEK/DKK/EUR/GBP 4종뿐이다(10페이지 480건 표본, 2026-09-23).
페이지 금액은 **세션 표시통화로 환산돼** 나오는데, 과거 낙찰가에 현재 환율을 먹인 값이라
그대로 쓰면 안 된다. 다행히 `?currency=XXX` 쿼리 파라미터로 표시통화를 지정할 수 있어서,
**통화별로 한 번씩 훑고 그 통화가 원 통화인 로트만 취한다** — 환산이 전혀 개입하지 않는다.
(원 통화는 목록 JSON의 `currency`, 상세의 `original_currency`로 확인 가능.)

수집 경로(2단계):
  1. 목록: `/en/search/25-art?is=ended&order=end_desc&currency=<CUR>&page=N`
     — 48건/페이지 SSR. 25-art가 상위 카테고리로 회화·드로잉·판화·사진·조각·기타를 포함.
     `order=end_desc`라 **최근 종료순** — 주간 증분(로드맵 7)에 그대로 붙일 수 있다.
     **딥 페이지네이션은 209페이지(약 10,032건)에서 막히고 그 뒤로는 1페이지로 되돌아온다**
     (실측). 전량 백필을 하려면 company_id/카테고리/기간으로 슬라이스해야 한다.
  2. 상세: `/en/<item_id>?currency=<CUR>` — 개최 경매사명/주소, 판매상태(state), 원 통화,
     **작가 엔티티 링크**(`/en/artists/<id>-<slug>`, 이름+생년 텍스트 포함), 설명/컨디션.
     목록 JSON에는 작가 필드가 없고 제목 문자열에 뭉쳐 있어서, 제목을 문자열로 쪼개 작가를
     추측하지 않고 상세 페이지의 작가 링크만 신뢰한다(duran.py와 같은 원칙).

**금액은 목록(thumb) 쪽이 정본이다** — 레코드에 `thumb`과 `vip_item`을 둘 다 남기지만,
현장 슬래그옥션(`hammer_auction: true`) 로트는 (1) 상세 페이지가 `?currency=` 지정을 무시하고
(2) `bids[]`에 사전입찰만 담겨 실제 낙찰가와 크게 어긋난다(실측: 사전입찰 798 SEK vs
낙찰 9,000 SEK). 그래서 `pipeline/auctionet.py`는 통화·추정가·낙찰가·로트번호를 전부 thumb에서
읽는다. 자세한 근거는 그쪽 모듈 주석.

**종료 직후 로트는 낙찰 상태가 아직 확정되지 않는다**(종료 당일 낙찰률 약 40% → 2일 뒤 약 83%).
수집은 해도 되지만 적재는 로더가 `min_age_days`(기본 3일)로 걸러낸다.

이미지 파일은 저장하지 않는다(URL만 원본 JSON에 남음).

사용법:
    python auctionet.py --limit 300                      # 파일럿: 최근 종료 300건
    python auctionet.py --limit 2000 --pages 40          # 주간 증분 규모
    python auctionet.py --company-id 238 --pages 209     # 경매사 1곳 전량(백필 슬라이스)
    python auctionet.py --start-page 195 --pages 15      # 오래 전 종료분(상태 확정된 코호트)
    python auctionet.py --houses                         # 입점 경매사 목록만 갱신
"""
from __future__ import annotations

import argparse
import html as H
import json
import re
import sys
import time

import requests

from common import already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

SITE_NAME = "auctionet"
BASE = "https://auctionet.com"
ART_CATEGORY = "25-art"
# 25-art 하위 카테고리(2026-09-23 실측 raw 캐시에서 확인) — 209페이지 상한을 넘는 대형
# 경매사를 슬라이스할 때 하나씩 돈다. 합치면 25-art 전체와 같아야 한다(중복/누락 없음).
ART_SUBCATEGORIES = (
    "28-paintings", "119-drawings", "26-photography",
    "27-engravings-prints", "29-sculptures-bronzes", "30-other",
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; artgraph-research-bot)",
    "Accept-Language": "en",
}
# robots.txt에 Crawl-delay 지정이 없다 — 예의상 1.2초 간격을 스스로 지킨다.
CRAWL_DELAY = 1.2
# 실측 상한: 209페이지(48*209=10,032건) 이후로는 1페이지 내용이 반복된다.
MAX_PAGE = 209
# 로트 원 통화 전체 집합(표본 확인). 표시통화로도 전부 선택 가능해서 환산 없이 읽을 수 있다.
CURRENCIES = ("SEK", "EUR", "GBP", "DKK")

LICENSE_NOTE = (
    "Auctionet.com(Auction Network Sweden AB) 공개 로트 페이지의 SSR 프리하이드레이션 JSON — "
    "robots.txt 전면 허용(/admin/·/*/my 만 차단, AI 봇 개별 차단 없음), Terms of Use 영문·"
    "스웨덴어 전문(2026-06-23 발효)에 crawl/scrape/data mining/database right/개인용도한정/"
    "제3자제공금지 등 자동수집·재이용 제한 조항이 전무함을 2026-09-23 직접 통독 확인. "
    "Auctionet은 마켓플레이스 운영자이고 실제 판매자는 입점 경매사(ToU 서두) — 로트의 "
    "auction_house는 상세 페이지 House 필드의 개별 경매사를 쓴다. "
    "입찰자 식별번호·입찰시각이 담긴 bids[] 배열은 저장 전 제거하고 집계값만 남김."
)

_PROPS_RE = re.compile(r'data-react-props="(.*?)"(?=\s|>)', re.S)
_ARTIST_RE = re.compile(r'href="(/en/artists/(\d+)-[^"]*)"[^>]*>([^<]*)</a>')
_DL_RE = re.compile(r"<dt>(.*?)</dt><dd>(.*?)</dd>", re.S)
_SECTION_RE = re.compile(
    r'<h2 class="small-header[^"]*">([^<]{1,40})</h2>(.*?)(?=<h2 class="small-header|<div class="box )',
    re.S,
)
_CANONICAL_RE = re.compile(r'<link href="([^"]+)" rel="canonical"')
_CATEGORY_RE = re.compile(r'href="(/en/search/\d+-[a-z0-9\-]+)[^"]*"')
_HOUSE_ROW_RE = re.compile(
    r'<h2 class="subheader">([^<]+)</h2>\s*<dl[^>]*>(.*?)</dl>', re.S
)
_HOUSE_LINK_RE = re.compile(
    r'<dt>([^<]*?):\s*</dt><dd><a[^>]+href="/en/([a-z0-9][a-z0-9\-_]*)"[^>]*>([^<]+)</a>'
)
_COMPANY_ID_RE = re.compile(r"company_id=(\d+)")


def _text(fragment: str) -> str:
    """HTML 조각 -> 공백 정리된 평문."""
    t = re.sub(r"(?is)<(script|style|button|svg).*?</\1>", " ", fragment)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", H.unescape(t)).strip()


def _get(session: requests.Session, url: str) -> requests.Response:
    def _do():
        resp = session.get(url, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return resp

    return with_retry(_do, attempts=5, base_delay=4.0)


def _react_props(page_html: str, component: str) -> dict | None:
    """`data-react-props`로 박힌 프리하이드레이션 JSON 중 지정 컴포넌트의 것을 파싱."""
    for m in _PROPS_RE.finditer(page_html):
        raw = H.unescape(m.group(1))
        if component not in raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        payload.pop("translations", None)  # UI 문자열 — 데이터가 아니라 용량만 차지
        return payload
    return None


def list_page(session: requests.Session, currency: str, page: int,
              company_id: int | None = None, category: str = ART_CATEGORY) -> list[dict]:
    """종료 경매 목록 한 페이지 -> 썸네일 JSON 리스트(원본 그대로)."""
    url = (f"{BASE}/en/search/{category}?is=ended&order=end_desc"
           f"&currency={currency}&page={page}")
    if company_id is not None:
        url += f"&company_id={company_id}"
    props = _react_props(_get(session, url).text, "ItemThumbList")
    return (props or {}).get("items", [])


def fetch_detail(session: requests.Session, item_id: int, currency: str) -> dict | None:
    """로트 상세 -> 저장용 raw 레코드(입찰자 정보 제거 완료)."""
    url = f"{BASE}/en/{item_id}?currency={currency}"
    page = _get(session, url).text

    vip = _react_props(page, "VipBidFormOrResult") or {}
    item = dict(vip.get("initialItem") or {})
    # ── 입찰자 정보 제거: bids[]에 입찰자 식별번호와 초 단위 입찰시각이 들어 있다.
    bids = item.pop("bids", []) or []
    bid_amounts = [b.get("amount") for b in bids if isinstance(b.get("amount"), (int, float))]
    item["bid_count"] = len(bids)
    item["top_bid_amount"] = max(bid_amounts) if bid_amounts else None
    item["_bids_redacted"] = True

    follow = _react_props(page, "FollowButtonWrapper") or {}

    details = {
        _text(m.group(1)): _text(m.group(2))
        for m in _DL_RE.finditer(page)
    }

    sections: dict[str, str] = {}
    section_html: dict[str, str] = {}
    for m in _SECTION_RE.finditer(page):
        label = _text(m.group(1))
        if label and label not in sections:
            sections[label] = _text(m.group(2))
            section_html[label] = m.group(2)

    # 작가는 "Artist/designer" 섹션 안의 링크만 신뢰한다 — 페이지 전체를 훑으면 추천 로트나
    # 내비게이션에 섞인 다른 작가 링크까지 딸려 들어올 수 있다.
    artists = []
    seen_ids: set[str] = set()
    for m in _ARTIST_RE.finditer(section_html.get("Artist/designer", "")):
        if m.group(2) in seen_ids:
            continue
        seen_ids.add(m.group(2))
        artists.append({
            "auctionet_artist_id": int(m.group(2)),
            "path": m.group(1),
            "label": H.unescape(m.group(3)).strip(),
        })

    canonical = _CANONICAL_RE.search(page)
    categories = sorted({m.group(1) for m in _CATEGORY_RE.finditer(page)})

    return {
        "item_id": item_id,
        "url": url,
        "canonical": canonical.group(1) if canonical else None,
        "display_currency": currency,
        # 원 통화 기준 추정가 — FollowButton 프롭이 환산 전 값을 준다.
        "original_estimate": follow.get("estimate"),
        "original_currency": follow.get("currency") or item.get("original_currency"),
        "vip_item": item,
        "artists": artists,
        "details": details,
        "sections": sections,
        "categories": categories,
    }


def discover_houses(session: requests.Session) -> list[dict]:
    """입점 경매사 목록(/en/auction_houses) -> [{slug, name, city, country, company_id}]."""
    url = f"{BASE}/en/auction_houses"
    resp = _get(session, url)
    houses: list[dict] = []
    for block in _HOUSE_ROW_RE.finditer(resp.text):
        country = _text(block.group(1))
        if not country or len(country) > 40:
            continue
        for lm in _HOUSE_LINK_RE.finditer(block.group(2)):
            city, slug, name = _text(lm.group(1)), lm.group(2), _text(lm.group(3))
            if slug in ("about", "app", "help", "sell", "contact", "artists"):
                continue
            houses.append({"country": country, "city": city, "slug": slug, "name": name})

    for house in houses:
        try:
            hp = _get(session, f"{BASE}/en/{house['slug']}")
        except requests.RequestException as exc:
            print(f"[auctionet] 경매사 {house['slug']} 페이지 실패: {exc}")
            continue
        cm = _COMPANY_ID_RE.search(hp.text)
        house["company_id"] = int(cm.group(1)) if cm else None
        print(f"[auctionet] 경매사 {house['name']} ({house['country']}/{house['city']}) "
              f"company_id={house['company_id']}")
        time.sleep(CRAWL_DELAY)

    save_raw(SITE_NAME + "_houses", "_houses", json.dumps(houses, ensure_ascii=False, indent=2),
             url=url, license_note=LICENSE_NOTE)
    print(f"[auctionet] 입점 경매사 {len(houses)}곳 저장")
    return houses


def crawl(limit: int | None, pages: int, skip_existing: bool,
          currencies: tuple[str, ...] = CURRENCIES,
          company_id: int | None = None, start_page: int = 1,
          category: str = ART_CATEGORY) -> None:
    session = requests.Session()
    saved = 0
    skipped_cached = 0
    skipped_other_currency = 0

    for currency in currencies:
        if limit is not None and saved >= limit:
            break
        for page in range(start_page, min(start_page + pages - 1, MAX_PAGE) + 1):
            if limit is not None and saved >= limit:
                break
            try:
                thumbs = list_page(session, currency, page, company_id=company_id, category=category)
            except requests.RequestException as exc:
                print(f"[auctionet] {currency} p{page} 목록 실패, 중단: {exc}")
                break
            if not thumbs:
                print(f"[auctionet] {currency} p{page} 결과 없음 — 통화 {currency} 종료")
                break

            for thumb in thumbs:
                if limit is not None and saved >= limit:
                    break
                # 원 통화가 이번 표시통화와 다르면 금액이 환산값이라 취하지 않는다
                # (해당 통화 차례에 다시 만난다).
                if thumb.get("currency") != currency:
                    skipped_other_currency += 1
                    continue
                item_id = thumb.get("id")
                if item_id is None:
                    continue
                if skip_existing and already_fetched(SITE_NAME, str(item_id)):
                    skipped_cached += 1
                    continue
                try:
                    record = fetch_detail(session, item_id, currency)
                except requests.RequestException as exc:
                    print(f"[auctionet] 로트 {item_id} 상세 실패, 건너뜀: {exc}")
                    time.sleep(CRAWL_DELAY)
                    continue
                record["thumb"] = thumb
                save_raw(SITE_NAME, str(item_id), json.dumps(record, ensure_ascii=False, indent=2),
                         url=record["url"], license_note=LICENSE_NOTE)
                saved += 1
                if saved % 25 == 0:
                    print(f"[auctionet] {saved}건 저장 (캐시 스킵 {skipped_cached}, "
                          f"타통화 보류 {skipped_other_currency})")
                time.sleep(CRAWL_DELAY)
            time.sleep(CRAWL_DELAY)

    print(f"[auctionet] 완료 — {saved}건 저장, 캐시 스킵 {skipped_cached}건, "
          f"타통화 보류 {skipped_other_currency}건")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auctionet 종료 경매 미술 로트 크롤러")
    parser.add_argument("--limit", type=int, default=300,
                        help="이번 실행에서 새로 저장할 최대 로트 수(기본 300)")
    parser.add_argument("--pages", type=int, default=MAX_PAGE,
                        help=f"통화별로 훑을 최대 목록 페이지 수(상한 {MAX_PAGE})")
    parser.add_argument("--currencies", default=",".join(CURRENCIES),
                        help="훑을 표시통화 목록(쉼표 구분). 원 통화가 같은 로트만 취한다")
    parser.add_argument("--start-page", type=int, default=1,
                        help="목록 시작 페이지(기본 1). end_desc 기준으로 뒤 페이지일수록 "
                             "오래 전에 끝난 로트 — 낙찰 상태가 확정된 코호트를 뽑을 때 쓴다")
    parser.add_argument("--company-id", type=int, default=None,
                        help="특정 입점 경매사로 한정(crawlers/raw/auctionet_houses/_houses.json 참고). "
                             "209페이지 상한 때문에 전량 백필은 이 슬라이스가 필수")
    parser.add_argument("--category", default=ART_CATEGORY,
                        help=f"검색 카테고리 슬러그(기본 {ART_CATEGORY}=미술 전체). "
                             f"209페이지 상한을 넘는 경매사는 하위 카테고리로 한 번 더 슬라이스: "
                             + ",".join(ART_SUBCATEGORIES))
    parser.add_argument("--houses", action="store_true",
                        help="입점 경매사 목록만 갱신하고 종료")
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false",
                        help="이미 저장된 로트도 다시 수집")
    args = parser.parse_args()

    if args.houses:
        discover_houses(requests.Session())
    else:
        crawl(args.limit, args.pages, args.skip_existing,
              tuple(c.strip().upper() for c in args.currencies.split(",") if c.strip()),
              company_id=args.company_id, start_page=args.start_page, category=args.category)
