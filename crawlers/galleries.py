"""국내/국내진출 사유 갤러리 작가 로스터 크롤러.

갤러리는 공식 API가 없고 소장품 규모도 미술관과 달리 작가 로스터·전시 이력
수준(관계 데이터)이라, 작품 하나하나가 아니라 **작가 목록 페이지**를 긁는다.
사이트마다 robots.txt를 개별 확인했고(2026-09-02), 여기 등록된 곳은 전부
일반 콘텐츠 경로가 허용 범위임을 확인한 것만 넣었다.

Artlogic 플랫폼(artlogic.net)을 쓰는 갤러리들은 HTML 구조가 동일해서
파서를 공유한다 — 아라리오/타데우스로팍/우손/갤러리바톤/조현화랑.

사용법:
    python crawlers/galleries.py --gallery kukje
    python crawlers/galleries.py --gallery all
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time

import requests

from common import already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}
LICENSE_NOTE = "갤러리 공식 웹사이트 — robots.txt 확인 후 작가 로스터 페이지만 수집(2026-09-02)"


def _fetch(url: str) -> str:
    def _do():
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.text

    return with_retry(_do)


def _clean(html_fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html_fragment)
    return re.sub(r"\s+", " ", text).strip()


# 사이트별 (작가 목록 페이지 URL, 상세 링크 정규식) — 정규식 캡처 그룹1이 href
KUKJE = ("https://www.kukjegallery.com/artists", r'href="(/artists/view\?seq=\d+)"[^>]*>(.*?)</a>')
ARTLOGIC_PATTERN = r'href="(/artists/[a-zA-Z0-9\-_/]+/)"[^>]*>(.*?)</a>'

GALLERIES: dict[str, dict] = {
    "kukje": {
        "base": "https://www.kukjegallery.com",
        "list_path": "/artists",
        "pattern": KUKJE[1],
    },
    "gallery_hyundai": {
        "base": "https://www.galleryhyundai.com",
        "list_path": "/artist/list",
        "pattern": r'href="(/artist/view/[a-zA-Z0-9\-_/]+)"[^>]*>(.*?)</a>',
    },
    "pkm": {
        "base": "https://www.pkmgallery.com",
        "list_path": "/artists",
        "pattern": r"href='(/artists/[a-zA-Z0-9\-_/]+)'[^>]*>(.*?)</a>",
    },
    "arario": {"base": "https://www.arariogallery.com", "list_path": "/artists/", "pattern": ARTLOGIC_PATTERN},
    "ropac": {"base": "https://www.ropac.net", "list_path": "/artists/", "pattern": ARTLOGIC_PATTERN},
    "wooson": {"base": "https://www.woosongallery.com", "list_path": "/artists/", "pattern": ARTLOGIC_PATTERN},
    "gallery_baton": {"base": "https://www.gallerybaton.com", "list_path": "/artists/", "pattern": ARTLOGIC_PATTERN},
    "johyun": {"base": "https://www.johyungallery.com", "list_path": "/artists/", "pattern": ARTLOGIC_PATTERN},
    "pace": {
        "base": "https://www.pacegallery.com",
        "list_path": "/artists/",
        "pattern": r'href="(/artists/[a-zA-Z0-9\-_/]+/)"[^>]*>(.*?)</a>',
    },
    "davidzwirner": {
        "base": "https://www.davidzwirner.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/[a-zA-Z0-9\-_/]+)"[^>]*>(.*?)</a>',
    },
    "whitecube": {
        "base": "",
        "list_path": "https://www.whitecube.com/artists",
        "pattern": r'href="(https://www\.whitecube\.com/artists/[a-zA-Z0-9\-_]+)"[^>]*>(.*?)</a>',
    },
    "mariangoodman": {
        "base": "https://www.mariangoodman.com",
        "list_path": "/artists",
        "pattern": ARTLOGIC_PATTERN,
    },
    "spruethmagers": {
        "base": "",
        "list_path": "https://www.spruethmagers.com/artists",
        "pattern": r'href="(https://spruethmagers\.com/artists/[a-zA-Z0-9\-_]+/)"[^>]*>(.*?)</a>',
    },
    "victoriamiro": {
        "base": "https://www.victoria-miro.com",
        "list_path": "/artists",
        "pattern": ARTLOGIC_PATTERN,
    },
    "koeniggalerie": {
        "base": "https://www.koeniggalerie.com",
        "list_path": "/pages/artist-overview",
        "pattern": r'href="(/collections/[a-z0-9\-]+)"[^>]*>(.*?)</a>',
        # 작가 아닌 일반 컬렉션 링크(작품/에디션/매거진 등)는 제외
        "exclude_slugs": {
            "artworks", "editions", "koenig-magazine", "store-artworks",
            "publications", "souvenirs", "events",
        },
    },
}

# 확인했지만 크롤링하지 않기로 한 곳:
# - Lehmann Maupin, Perrotin: 클라이언트 렌더링(SPA)이라 requests만으로는
#   작가 목록을 못 긁음 — 헤드리스 브라우저로 별도 수집(정규 크롤러 경로 아님).
# - Lisson Gallery: robots.txt가 `User-agent: GPTBot / Disallow: /`로 AI 봇을
#   명시 차단 — 명확한 거부 시그널이라 제외.
# - Gladstone Gallery: robots.txt 자체가 404(부재) — MMCA/일본 국립미술관과
#   같은 애매한 상황이라 정책 판단 없이 크롤링하지 않고 후보로만 남겨둠.


def crawl_gallery(key: str, delay: float, skip_existing: bool) -> int:
    cfg = GALLERIES[key]
    base, list_path, pattern = cfg["base"], cfg["list_path"], cfg["pattern"]
    exclude_slugs = cfg.get("exclude_slugs") or set()
    site_name = f"gallery_{key}"

    list_url = list_path if list_path.startswith("http") else base + list_path
    try:
        html = _fetch(list_url)
    except requests.RequestException as exc:
        print(f"[galleries:{key}] 목록 페이지 조회 실패: {exc}")
        return 0

    seen: dict[str, str] = {}
    for m in re.finditer(pattern, html, re.S):
        href, inner = m.group(1), m.group(2)
        name = _clean(inner)
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        if name and href not in seen and slug not in exclude_slugs:
            seen[href] = name

    print(f"[galleries:{key}] 작가 {len(seen)}명 발견")

    saved = 0
    for href, name in seen.items():
        record_id = re.sub(r"[^a-zA-Z0-9]+", "-", href).strip("-")
        if skip_existing and already_fetched(site_name, record_id):
            continue

        url = base + href if href.startswith("/") else href
        try:
            detail_html = _fetch(url)
        except requests.RequestException as exc:
            print(f"[galleries:{key}] {url} 조회 실패: {exc}")
            continue

        save_raw(
            site_name,
            record_id,
            json.dumps({"name": name, "url": url, "raw_html": detail_html}, ensure_ascii=False),
            url=url,
            license_note=LICENSE_NOTE,
        )
        saved += 1
        time.sleep(delay)

    print(f"[galleries:{key}] 완료 — {saved}명 저장")
    return saved


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="사유 갤러리 작가 로스터 크롤러")
    parser.add_argument("--gallery", type=str, default="all", help="갤러리 키 (all 또는 쉼표 구분)")
    parser.add_argument("--delay", type=float, default=0.3, help="요청 간 대기(초)")
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="이미 저장된 작가도 다시 수집",
    )
    args = parser.parse_args()
    keys = list(GALLERIES.keys()) if args.gallery == "all" else args.gallery.split(",")
    for key in keys:
        if key not in GALLERIES:
            print(f"[galleries] 알 수 없는 갤러리 키: {key} (사용 가능: {list(GALLERIES.keys())})")
            continue
        crawl_gallery(key, args.delay, args.skip_existing)
