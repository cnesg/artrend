"""갤러리 5곳 전시 페이지 수집 — Gladstone/Lehmann Maupin/Taka Ishii/Pyo/Simon.

2026-09-17 SPA갤러리_엔드포인트_20260917.md 조사 결과에 따라 사이트별로 다른
방식으로 원본을 보존한다(전부 JS 렌더링 없이 순수 HTTP GET, robots.txt 위반 없음
확인됨 — Perrotin은 진짜 SPA라 이번 스코프 제외):

- gladstone: Gatsby 빌드타임 JSON `/page-data/exhibitions/page-data.json` 1회 GET.
  Contentful 데이터(title/artists/startDate/endDate)가 이미 구조화돼 있어 그대로 보존.
- lehmannmaupin: `/exhibitions` 목록 페이지 1회 GET. 페이지에 SSR로 박힌
  schema.org JSON-LD(ItemList)에서 전시명+URL만 나옴(날짜는 개별 페이지에도 구조화
  텍스트로 없어 이번엔 미수집 — venue만 확정, start_date는 비워 둠).
- takaishii: `/en/exhibition/` 목록 페이지를 페이지네이션 따라 순회(순수 워드프레스
  SSR, 전시명/기간(Dates:)/장소(Location:) 텍스트 그대로 있음).
- pyo, simon: Wix 다이나믹 사이트맵(`dynamic-exhibit*-sitemap.xml`)으로 개별 전시
  URL 전량 확보 후, 각 페이지를 GET해 `<title>`(전시명+작가)과
  `<meta name="description">`(기간)만 저장 — 본문 상세는 JS 필요라 이번 스코프 밖.

원본만 저장(save_raw/already_fetched), 요청 간 1초 이상. 정규화는
pipeline/gallery_exhibitions_pages_load.py.

사용법:
    python crawlers/gallery_exhibitions_pages.py --site gladstone
    python crawlers/gallery_exhibitions_pages.py --site all
"""
from __future__ import annotations

import argparse
import hashlib
import html
import re
import sys
import time

import requests

from common import already_fetched, save_raw, with_retry

sys.stdout.reconfigure(encoding="utf-8")

HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot/1.0; +https://github.com/cnesg/artrend)"}
LICENSE_NOTE_BASE = "공개 전시 페이지, robots.txt 확인(2026-09-17, docs/SPA갤러리_엔드포인트_20260917.md)"


def _get(url: str, timeout: int = 25) -> requests.Response:
    def _do():
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r
    return with_retry(_do)


def crawl_gladstone() -> None:
    site = "gladstone_exhibitions"
    record_id = "page-data"
    if already_fetched(site, record_id):
        print(f"[{site}] 이미 수집됨 — 스킵")
        return
    url = "https://www.gladstonegallery.com/page-data/exhibitions/page-data.json"
    r = _get(url)
    save_raw(site, record_id, r.text, url=url, license_note=LICENSE_NOTE_BASE + " — Gatsby page-data.json(Contentful 빌드타임 데이터)")
    print(f"[{site}] 저장 완료")


def crawl_lehmannmaupin() -> None:
    site = "lehmannmaupin_exhibitions"
    record_id = "exhibitions-list"
    if already_fetched(site, record_id, ext="html"):
        print(f"[{site}] 이미 수집됨 — 스킵")
        return
    url = "https://www.lehmannmaupin.com/exhibitions"
    r = _get(url)
    save_raw(site, record_id, r.text, url=url, license_note=LICENSE_NOTE_BASE + " — SSR HTML(JSON-LD ItemList 포함)", ext="html")
    print(f"[{site}] 저장 완료")


def crawl_takaishii(max_pages: int = 10) -> None:
    # 주의: /en/exhibition/(단수)는 현재 진행 전시 1건짜리 페이지라 ?paged=로 다른 값을
    # 줘도 서버가 무시하고 항상 같은 콘텐츠를 돌려준다(2026-09-17 확인, 중복수집 실수로
    # 한 번 걸렸다가 정정) — 진짜 연도별 전체 목록은 /en/exhibitions/(복수), 진짜
    # 페이지네이션 경로는 /en/exhibitions/tokyo/page/N/ ("Next" 링크로 확인).
    site = "takaishii_exhibitions"
    base = "https://www.takaishiigallery.com/en/exhibitions/"
    page = 1
    saved = skipped = 0
    while page <= max_pages:
        url = base if page == 1 else f"https://www.takaishiigallery.com/en/exhibitions/tokyo/page/{page}/"
        record_id = f"page-{page:02d}"
        if already_fetched(site, record_id, ext="html"):
            skipped += 1
        else:
            try:
                r = _get(url)
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    break
                raise
            save_raw(site, record_id, r.text, url=url, license_note=LICENSE_NOTE_BASE + " — 워드프레스 SSR HTML(연도별 목록, 페이지네이션)", ext="html")
            saved += 1
            has_next = f"/page/{page + 1}/" in r.text
            time.sleep(1.2)
            if not has_next:
                break
        page += 1
    print(f"[{site}] 완료 — 신규 {saved}, 스킵 {skipped}")


WIX_SITEMAP = {
    "pyo": "https://www.pyogallery.com/dynamic-exhibitions_p_db925c17_053b_4c52_b6ca_fa2be0ba9d10_0_5000-sitemap.xml",
    "simon": "https://www.gallerysimon.com/dynamic-exhibition_p_7f79cb71_2b7a_48fd_91ab_bae74404c395_0_5000-sitemap.xml",
}


def crawl_wix(key: str) -> None:
    site = f"{key}_exhibitions"
    sitemap_url = WIX_SITEMAP[key]
    r = _get(sitemap_url)
    urls = [html.unescape(u) for u in re.findall(r"<loc>(.*?)</loc>", r.text)]
    print(f"[{site}] sitemap {len(urls)}건")
    saved = skipped = failed = 0
    for url in urls:
        slug = url.rstrip("/").rsplit("/", 1)[-1] or url
        record_id = slug if len(slug) <= 80 else hashlib.md5(url.encode()).hexdigest()
        if already_fetched(site, record_id):
            skipped += 1
            continue
        try:
            page = _get(url)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                failed += 1
                time.sleep(1.2)
                continue
            raise
        title_m = re.search(r"<title>(.*?)</title>", page.text)
        desc_m = re.search(r'<meta name="description" content="(.*?)"', page.text)
        payload = {
            "url": url,
            "title": title_m.group(1) if title_m else None,
            "description": desc_m.group(1) if desc_m else None,
        }
        import json as _json
        save_raw(site, record_id, _json.dumps(payload, ensure_ascii=False), url=url,
                 license_note=LICENSE_NOTE_BASE + " — Wix SSR title/meta만(본문은 JS 렌더링 필요, 이번 스코프 밖)")
        saved += 1
        time.sleep(1.2)
    print(f"[{site}] 완료 — 신규 {saved}, 스킵 {skipped}, 404 {failed}")


CRAWLERS = {
    "gladstone": crawl_gladstone,
    "lehmannmaupin": crawl_lehmannmaupin,
    "takaishii": crawl_takaishii,
    "pyo": lambda: crawl_wix("pyo"),
    "simon": lambda: crawl_wix("simon"),
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="갤러리 5곳 전시 페이지 크롤러")
    parser.add_argument("--site", choices=["all", *CRAWLERS.keys()], default="all")
    args = parser.parse_args()
    sites = list(CRAWLERS.keys()) if args.site == "all" else [args.site]
    for s in sites:
        CRAWLERS[s]()
