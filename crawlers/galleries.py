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
import html as html_entities
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
    "shugoarts": {
        "base": "",
        "list_path": "https://shugoarts.com/en/artists/",
        "pattern": r'href="(https://shugoarts\.com/en/artists/[a-zA-Z0-9\-]+)"[^>]*>(.*?)</a>',
    },
    "tomiokoyama": {
        "base": "",
        "list_path": "https://www.tomiokoyamagallery.com/en/artists",
        "pattern": r'href="(https://www\.tomiokoyamagallery\.com/en/artists/[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "estherschipper": {
        "base": "https://www.estherschipper.com",
        "list_path": "/artists",
        "pattern": ARTLOGIC_PATTERN,
    },
    "maxhetzler": {
        "base": "https://www.maxhetzler.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/[a-zA-Z0-9\-_]+)"[^>]*>(.*?)</a>',
    },
    "otafinearts": {
        "base": "https://otafinearts.com",
        "list_path": "/artists",
        "pattern": ARTLOGIC_PATTERN,
        "exclude_slugs": {"list", "grid"},
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
    "313artproject": {
        "base": "https://313artproject.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+-[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "gallery2": {
        "base": "https://gallery2.co.kr",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+-[a-zA-Z0-9\-]+/overview/)"[^>]*>(.*?)</a>',
    },
    "seankelly": {
        "base": "https://www.skny.com",
        "list_path": "/artists",
        "pattern": r"href='(/artists/[a-zA-Z0-9\-]+)'[^>]*>(.*?)</a>",
    },
    "303gallery": {
        "base": "https://www.303gallery.com",
        "list_path": "/artists",
        "pattern": r"href='(/artists/[a-zA-Z0-9\-]+)'[^>]*>(.*?)</a>",
    },
    "regenprojects": {
        "base": "https://www.regenprojects.com",
        "list_path": "/artists",
        "pattern": r"href='(/artists/[a-zA-Z0-9\-]+)'[^>]*>(.*?)</a>",
    },
    "taronasu": {
        "base": "https://www.taronasugallery.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "scaithebathhouse": {
        "base": "https://www.scaithebathhouse.com/en/artists",
        "list_path": "",
        "pattern": r'href="\.(/[a-zA-Z0-9_]+/)"[^>]*>(.*?)</a>',
    },
    "mizuma": {
        "base": "",
        "list_path": "https://www.mizuma-art.co.jp/artists/",
        "pattern": r'href="(https://mizuma-art\.co\.jp/artists/[a-zA-Z0-9_\-]+/)"[^>]*>(.*?)</a>',
    },
    "alminerech": {
        "base": "",
        "list_path": "https://www.alminerech.com/artists",
        "pattern": r'href="(https://www\.alminerech\.com/artists/\d+-[a-zA-Z0-9\-]+)"[^>]*>(.*?)</a>',
    },
    "mennour": {
        "base": "https://www.mennour.com",
        "list_path": "/artists",
        "pattern": r'href="(/artist/[a-zA-Z0-9\-]+)"[^>]*>(.*?)</a>',
    },
    "skarstedt": {
        "base": "https://www.skarstedt.com",
        "list_path": "/artists",
        "pattern": r"href='(/artists/[a-zA-Z0-9\-]+)'[^>]*>(.*?)</a>",
    },
    "galleriacontinua": {
        "base": "https://www.galleriacontinua.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/[a-zA-Z0-9\-]+-\d+)"[^>]*>(.*?)</a>',
    },
    "massimodecarlo": {
        "base": "https://www.massimodecarlo.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/[a-zA-Z0-9\-]+)"[^>]*>(.*?)</a>',
    },
    "leeahn": {
        # HTTPS 인증서가 깨져 있음(SSLCertVerificationError, CN 불일치) — 사이트
        # 자체는 정상 운영 중이고 HTTP는 정상 응답해서 http로 접속. robots.txt는
        # 특정 SEO봇만 차단, AI봇 차단 없음.
        "base": "http://www.leeahngallery.com/artists",
        "list_path": "/list",
        "pattern": r'href="\.(/view\?wm_id=\d+)"[^>]*>(.*?)</a>',
    },
    "gallerychosun": {
        # robots.txt 확인(2026-09-03): catch-all 규칙이 /admin//embed//api/ 등
        # 특정 경로만 막고 /artists는 허용 범위. 이름은 <a> 태그 안이 아니라
        # 썸네일 <img alt="이름">로 표시돼 있어 별도 패턴 필요.
        "base": "https://gallerychosun.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+/)"[^>]*>\s*<img[^>]*alt="([^"]+)"',
    },
    "matthewmarks": {
        "base": "https://www.matthewmarks.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/[a-zA-Z0-9\-_/]+)"[^>]*>(.*?)</a>',
    },
    "paulacooper": {
        # Artlogic 플랫폼이지만 작가명이 <a> 안이 아니라 뒤따르는
        # <div class="title">이름</div>에 있어 arario 등과 다른 패턴 필요.
        "base": "https://www.paulacoopergallery.com",
        "list_path": "/artists",
        "pattern": r"href='(/artists/[a-zA-Z0-9\-_/]+)'.*?<div class=\"title\">([^<]+)</div>",
    },
    "caseykaplan": {
        "base": "",
        "list_path": "https://caseykaplangallery.com/artists",
        "pattern": r'href="(https://caseykaplangallery\.com/artists/[a-zA-Z0-9\-_/]+/)"[^>]*>(.*?)</a>',
    },
    "luhringaugustine": {
        "base": "https://www.luhringaugustine.com",
        "list_path": "/artists",
        "pattern": r"href='(/artists/[a-zA-Z0-9\-_/]+)'[^>]*>(.*?)</a>",
    },
    "petzel": {
        "base": "https://www.petzel.com",
        "list_path": "/artists",
        "pattern": r"href='(/artists/[a-zA-Z0-9\-_/]+)'[^>]*>(.*?)</a>",
    },
    "takeninagawa": {
        "base": "",
        "list_path": "https://www.takeninagawa.com/artists",
        "pattern": r'href="(https://www\.takeninagawa\.com/artists/\d+/)"[^>]*>(.*?)</a>',
    },
    "anomalytokyo": {
        "base": "",
        "list_path": "https://anomalytokyo.com/artists",
        "pattern": r'href="(https://anomalytokyo\.com/artist/[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "carliergebauer": {
        "base": "",
        "list_path": "https://www.carliergebauer.com/artist",
        "pattern": r'href="(https://www\.carliergebauer\.com/artist/[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "kurimanzutto": {
        # Artlogic 플랫폼(paulacooper와 동일 구조) — 멕시코시티, 유럽은
        # 아니지만 EU 우선순위 소진 후 확보한 추가 국제 갤러리.
        "base": "https://www.kurimanzutto.com",
        "list_path": "/artists",
        "pattern": r"href='(/artists/[a-zA-Z0-9\-_/]+)'.*?<div class=\"title\">([^<]+)</div>",
    },
    "krinzinger": {
        # 2026-09-03: 페이지네이션 지원 추가로 보류 해제. WordPress
        # Elementor 테마 — /artists/page/N/ 형태로 계속 이어지며 실제
        # 종료 지점을 미리 알 수 없어(설립 1973년, 작고 작가/에스테이트
        # 포함 로스터가 큼) crawl_gallery의 paginate_template 루프가
        # 새 작가가 0명인 페이지를 만나면 자동으로 멈추도록 처리.
        "base": "",
        "list_path": "https://galerie-krinzinger.at/artists",
        "pattern": r"href='(https://galerie-krinzinger\.at/artists/[a-zA-Z0-9\-]+/)'><span class='elementor-icon-list-text[^']*'>(.*?)</span>",
        "paginate_template": "https://galerie-krinzinger.at/artists/page/{page}/",
        "max_pages": 20,
    },
    "sungallery": {
        # robots.txt는 Wix 자동생성 SQLi 페이로드 차단 목록뿐(gallerychosun과
        # 동일 패턴) — /artists는 허용 범위. 작가명이 <a> 안이 아니라
        # <span class="content"><h2>이름</h2>에 있어 별도 패턴 필요.
        "base": "https://www.sungallery.co.kr",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+-[a-zA-Z0-9\-]+/overview/)"[^>]*>\s*<span class="content">\s*<h2>(.*?)</h2>',
    },
    "ocimuseum": {
        # OCI미술관(OCI재단) — 엄밀히는 미술관/재단이지만 소장품이 아니라
        # 지원 작가 인명록(관계 데이터)만 있어 다른 갤러리와 같은 구조로 수집.
        # robots.txt는 `Disallow:` 빈 값(전체 허용).
        "base": "",
        "list_path": "https://www.ocimuseum.org/artist",
        "pattern": r'href="(https://www\.ocimuseum\.org/artist/\d+)">.*?<p>([^<]+)</p>',
    },
    "tanyabonakdar": {
        "base": "https://www.tanyabonakdargallery.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+-[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "jamescohan": {
        "base": "https://www.jamescohan.com",
        "list_path": "/artists",
        "pattern": r"href='(/artists/[a-zA-Z0-9\-_/]+)'.*?<div class=\"title\">([^<]+)</div>",
    },
    "cheimread": {
        # 목록에 스팸성 장난 항목("cumwizard69420")이 섞여 있어 명시적으로 제외.
        "base": "https://www.cheimread.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+-[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
        "exclude_slugs": {"8-cumwizard69420"},
    },
    "nararoesler": {
        "base": "https://www.nararoesler.art",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+-[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "kasmin": {
        "base": "https://www.kasmingallery.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+-[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "milesmcenery": {
        # /artists/c/artists, /artists/c/estates는 작가 개별 페이지가 아니라
        # 카테고리 필터 링크라 제외.
        "base": "https://www.milesmcenery.com",
        "list_path": "/artists",
        "pattern": r"href='(/artists/[a-zA-Z0-9\-_/]+)'[^>]*>(.*?)</a>",
        "exclude_slugs": {"artists", "estates"},
    },
    "jackshainman": {
        "base": "https://www.jackshainman.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/[a-zA-Z0-9_\-]+)"[^>]*>(.*?)</a>',
    },
    "antonkern": {
        "base": "https://www.antonkerngallery.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+-[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "miandn": {
        # Mitchell-Innes & Nash. Artlogic — 이름이 img alt 속성에 있음
        # (luhringaugustine/kurimanzutto와 동일 구조).
        "base": "https://www.miandn.com",
        "list_path": "/artists",
        "pattern": r"href='(/artists/[a-zA-Z0-9\-_/]+)'.*?alt='([^']+)'",
    },
    "nonakahill": {
        "base": "https://www.nonaka-hill.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+-[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "waitingroom": {
        # feed 링크가 다음 작가의 <div class="artist-name-en"> 앞에 와서
        # 오탐되므로 명시적으로 제외.
        "base": "",
        "list_path": "https://waitingroom.jp/artists/",
        "pattern": r'href="(https://waitingroom\.jp/artists/[a-zA-Z0-9\-]+/)".*?<div class="artist-name-en">([^<]+)</div>',
        "exclude_slugs": {"feed"},
    },
    "meyerriegger": {
        "base": "",
        "list_path": "https://meyer-riegger.com/en/artists",
        "pattern": r'href="(https://meyer-riegger\.com/en/artists/[a-zA-Z0-9\-]+)"[^>]*>(.*?)</a>',
    },
    "wentrup": {
        "base": "https://www.wentrupgallery.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+-[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "mai36": {
        "base": "",
        "list_path": "https://mai36.com/artists",
        "pattern": r'href="(https://mai36\.com/artists/[a-zA-Z0-9\-]+)"[^>]*>(.*?)</a>',
    },
    "capitainpetzel": {
        "base": "https://www.capitainpetzel.de",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+-[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "annetgelink": {
        "base": "https://www.annetgelink.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+-[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "vielmetter": {
        "base": "",
        "list_path": "https://vielmetter.com/artists/",
        "pattern": r'href="(https://vielmetter\.com/artists/[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "zenox": {
        "base": "",
        "list_path": "https://zeno-x.com/artists",
        "pattern": r'href="(https://zeno-x\.com/artists/[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "xavierhufkens": {
        "base": "",
        "list_path": "https://www.xavierhufkens.com/artists",
        "pattern": r'href="(https://www\.xavierhufkens\.com/artists/[a-zA-Z0-9\-]+)"[^>]*>(.*?)</a>',
    },
    "dvirgallery": {
        "base": "https://www.dvirgallery.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+-[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "cardigallery": {
        # /artists/feed/ 링크가 매치돼 뒤따르는 거대한 인라인 CSS/JS 블록까지
        # "이름"으로 잡히는 문제가 있어 feed 슬러그를 명시적으로 제외.
        "base": "",
        "list_path": "https://cardigallery.com/artists",
        "pattern": r'href="(https://cardigallery\.com/artists/[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
        "exclude_slugs": {"feed"},
    },
    "meminc": {
        "base": "",
        "list_path": "https://mem-inc.jp/artists",
        "pattern": r'href="(https://mem-inc\.jp/artists/[a-zA-Z0-9_\-]+/)"[^>]*>(.*?)</a>',
    },
    "proyectosmonclova": {
        "base": "https://proyectosmonclova.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/[a-zA-Z0-9\-]+)"[^>]*>(.*?)</a>',
    },
    "gallerykiche": {
        "base": "https://www.gallerykiche.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+)" class="link"><span class="title">([^<]+)</span>',
    },
    "cristinaguerra": {
        "base": "https://www.cristinaguerra.com",
        "list_path": "/en/artists/",
        "pattern": r'href="(/en/artist/[a-zA-Z0-9\-]+/)"[^>]*>\s*<div[^>]*data-bl-name="Artist Name"[^>]*>([^<]+)</div>',
    },
    "vsf": {
        "base": "https://vsf.la",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+-[a-zA-Z0-9\-]+)"[^>]*>(.*?)</a>',
    },
    "nightgallery": {
        "base": "https://www.nightgallery.ca",
        "list_path": "/artists",
        "pattern": r"href='(/artists/[a-zA-Z0-9\-_/]+)'[^>]*>(.*?)</a>",
    },
    "barakatcontemporary": {
        # gallerychosun과 동일 구조 — 이름이 <a> 태그 바로 앞 HTML 주석에
        # 들어있음(예: `<!-- Wael Shawky --><a href="/artists/25/">`).
        "base": "https://barakatcontemporary.com",
        "list_path": "/artists",
        "pattern": r'<!-- ([^>]+) -->\s*<a href="(/artists/\d+[a-zA-Z0-9\-]*/)"',
        "swap_groups": True,
    },
    "tinakimgallery": {
        "base": "https://tinakimgallery.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+-[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "andrewkreps": {
        "base": "https://www.andrewkreps.com",
        "list_path": "/artists",
        "pattern": r"href='(/artists/[a-zA-Z0-9\-_/]+)'[^>]*>(.*?)</a>",
    },
    "thomasschulte": {
        "base": "https://www.galeriethomasschulte.de",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+-[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "kaynegriffin": {
        "base": "https://www.kaynegriffin.com",
        "list_path": "/artists",
        "pattern": r"href='(/artists/[a-zA-Z0-9\-_/]+)'[^>]*>(.*?)</a>",
    },
    "ghebaly": {
        "base": "https://www.ghebaly.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/[a-zA-Z0-9\-_/]+/)"[^>]*>\s*<span class="content">\s*<h2>(.*?)</h2>',
    },
    "omr": {
        "base": "https://omr.art",
        "list_path": "/artists",
        "pattern": r'href="(/artists/[a-zA-Z0-9\-]+)" class="link-block w-inline-block"></a></div><div class="artist-name-ingrid"><div>([^<]+)</div>',
    },
    "stpi": {
        "base": "https://www.stpi.com.sg",
        "list_path": "/artists",
        "pattern": r'href="(/artists/[a-zA-Z0-9\-]+)"[^>]*>(.*?)</a>',
    },
    "whitespace": {
        "base": "",
        "list_path": "https://whitespace.cn/artists/",
        "pattern": r'href="(https://whitespace\.cn/artists/[a-zA-Z0-9\-]+/)"[^>]*>(.*?)</a>',
    },
    "thethirdline": {
        "base": "https://www.thethirdline.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+-[a-zA-Z0-9\-.]+/)"[^>]*>(.*?)</a>',
    },
    "athrart": {
        "base": "https://athrart.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/\d+-/biography/)"[^>]*>\s*<span class="content">\s*<h2>(.*?)</h2>',
    },
    "goodmangallery": {
        "base": "https://goodman-gallery.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/[a-zA-Z0-9\-]+)"[^>]*>(.*?)</a>',
    },
    "roslynoxley9": {
        "base": "https://www.roslynoxley9.com.au",
        "list_path": "/artists",
        "pattern": r'href="(/artist/[a-zA-Z0-9\-]+)"[^>]*>(.*?)</a>',
    },
    "sadiecoles": {
        # 2026-09-03: 보류 해제. 작가 목록이 <a> 태그가 아니라 Alpine.js
        # x-data 속성 안에 HTML 엔티티로 이중 인코딩된 JSON 배열로 들어있음
        # (예: &quot;title&quot;:&quot;Agnes Scherer&quot;,&quot;url&quot;:
        # &quot;https:\/\/www.sadiecoles.com\/artists\/agnes-scherer&quot;).
        # html.unescape()로 엔티티를 풀고 JSON 이스케이프 슬래시(\/)를
        # 되돌린 뒤 title/url 쌍을 정규식으로 추출 — 그룹 순서가
        # (name, href)라 swap_groups로 뒤집는다.
        "base": "",
        "list_path": "https://www.sadiecoles.com/artists",
        "pattern": r'"title":"([^"]+)","url":"(https://www\.sadiecoles\.com/artists/[a-zA-Z0-9\-]+)"',
        "unescape": True,
        "swap_groups": True,
    },
    # --- 2026-09-22 신규 추가 (국내 갤러리 축 확대) ---
    "rhogallery": {
        # 노화랑(Gallery Rho). WordPress 기본 테마 — 개별 작가 글이 최상위
        # 경로(/작가슬러그/)에 있고 entry-title 안 <a title="이름" rel="bookmark">
        # 형태로 이름이 들어있음.
        "base": "",
        "list_path": "https://rhogallery.com/artists/",
        "pattern": r'href="(https://rhogallery\.com/[a-z0-9\-]+/)" title="[^"]*" rel="bookmark">(.*?)</a>',
    },
    "artside": {
        # 아트사이드갤러리. artside.org(자체 개발, Bulma CSS) — 작가 목록은
        # 복수형 /artists가 아니라 단수형 /artist 경로. 링크 자체가
        # 해시형 ID(href="/artist/<hash>")라 record_id도 자동으로 그 해시를 씀.
        "base": "https://artside.org",
        "list_path": "/artist",
        "pattern": r'href="(/artist/[a-z0-9]+)" class="ml-5">(.*?)</a>',
    },
    # --- 2026-09-22 신규 추가 (해외 갤러리 축 확대) ---
    "pilarcorrias": {
        # Pilar Corrias(런던). Artlogic — 이름이 <a> 안이 아니라 뒤따르는
        # <div class="artist_name">이름</div>에 있어 paulacooper와 같은 계열
        # 패턴 필요.
        "base": "https://www.pilarcorrias.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/[a-zA-Z0-9\-]+/)">.*?<div class="artist_name">(.*?)</div>',
    },
    "nordenhake": {
        "base": "https://nordenhake.com",
        "list_path": "/artists",
        "pattern": r'<a class="ndh-artistList__link" href="(https://nordenhake\.com/artists/[a-z0-9\-]+)">(.*?)</a>',
    },
    "companygallery": {
        "base": "https://companygallery.us",
        "list_path": "/artists",
        "pattern": r'href="(/artists/[a-zA-Z0-9\-]+)" class="artist_link heart_hover">(.*?)</a>',
    },
    "greenenaftaligallery": {
        "base": "https://greenenaftaligallery.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/[a-zA-Z0-9\-]+)"><header class="thumb_header"><h2 class="caps b">(.*?)</h2>',
    },
    "bortolamigallery": {
        "base": "https://www.bortolamigallery.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/[a-zA-Z0-9\-]+)">(.*?)</a>',
    },
    "konradfischergalerie": {
        # gallerychosun/barakatcontemporary와 동일 패턴 — 이름이 <a> 태그
        # 바로 앞 HTML 주석에 들어있음(예: `<!-- Carl Andre --><a href="/artists/43/">`).
        "base": "https://konradfischergalerie.de",
        "list_path": "/artists/",
        "pattern": r'<!-- ([^>]+) -->\s*<a href="(/artists/\d+/)"',
        "swap_groups": True,
    },
    "maureenpaley": {
        "base": "https://www.maureenpaley.com",
        "list_path": "/artists",
        "pattern": r'href="(/artists/[a-zA-Z0-9\-]+)"[^>]*>(.*?)</a>',
    },
    "corbettvsdempsey": {
        # 슬러그에 움라우트 등 비-ASCII 문자가 URL 인코딩되어 들어있는 경우가
        # 있어(예: peter-br%C3%B6tzmann) 슬러그 패턴에 %를 포함시켰다.
        "base": "https://corbettvsdempsey.com",
        "list_path": "/artists/",
        "pattern": r'href="(/artists/[a-zA-Z0-9%_\-]+/)">(.*?)</a>',
    },
}

# 확인했지만 크롤링하지 않기로 한 곳:
# - Lehmann Maupin, Perrotin: 클라이언트 렌더링(SPA)이라 requests만으로는
#   작가 목록을 못 긁음 — 헤드리스 브라우저로 별도 수집(정규 크롤러 경로 아님).
# - Lisson Gallery: robots.txt가 `User-agent: GPTBot / Disallow: /`로 AI 봇을
#   명시 차단 — 명확한 거부 시그널이라 제외.
# - Gladstone Gallery: robots.txt 자체가 404(부재)였으나 MMCA/일본 국립미술관과
#   같은 기준(명시적 차단 신호 없으면 진행)으로 수집 완료 — Gatsby SSG의
#   page-data.json 엔드포인트를 직접 호출해 75명 확보(이 파일의 정규 크롤러
#   경로 아님, pipeline/galleries.py GALLERY_INFO에 "gladstone"으로 등록됨).
# - Taka Ishii Gallery, neugerriemschneider: robots.txt는 문제없으나 작가
#   목록 페이지가 클라이언트 렌더링이라 requests로는 개별 작가 링크를 못 얻음
#   (홈페이지/카테고리 페이지에 정적 링크가 아예 없음) — SPA로 판단, 제외.
# - Blum(구 Blum & Poe): robots.txt가 Googlebot/Bingbot만 Allow하고 나머지
#   User-agent는 전부 Disallow: / — 명시적 차단, 제외.
# - Pyo Gallery(표갤러리), Gallery Simon: robots.txt는 문제없으나 Wix 사이트라
#   작가 목록이 JS 렌더링(Pyo) 또는 이름이 이미지 파일명에만 있어 신뢰 가능한
#   텍스트 소스가 없음(Simon) — requests 기반으로는 해결 불가 확인, 계속 보류.
# - Galerie Krinzinger, Sadie Coles HQ: 2026-09-03 페이지네이션/이스케이프
#   해제 처리 추가 후 GALLERIES에 등록 완료(각각 "krinzinger"/"sadiecoles").
# 2026-09-22 신규 발굴 라운드에서 확인했지만 보류한 곳:
# - P21: 도메인 자체가 Angular SPA(ng-app)라 robots.txt조차 index.html로
#   폴백 — 정적 작가 링크 없음.
# - 두산갤러리(Doosan Gallery): doosanartcenter.com 서브도메인
#   doosangallery.com은 있으나 /artists, /artist, /en(ko)/artists 전부 404 —
#   React 기반 클라이언트 라우팅으로 추정. 개념적으로도 상시 전속작가
#   로스터보다는 공모/기획전 중심이라 "작가 로스터" 구조 자체가 불명확.
# - 이화익갤러리(Leehwaik Gallery): robots.txt는 문제없으나 /artistList가
#   wookmark.js 그리드로 JS 렌더링 — 정적 HTML에 작가 링크 없음.
# - PIBI Gallery(피비갤러리): robots.txt 문제없으나 /pages/artists/artists.php
#   응답에 swiper/AOS만 있고 개별 작가 링크가 없음 — JS/AJAX 렌더링으로 판단.
# - 원앤제이갤러리: 이미 제외 확정(위 목록 참고, HTTP 410) — 재확인 없이 스킵.
# - David Kordansky Gallery: /artists가 /exception/info로 리다이렉트 —
#   봇 감지/WAF 차단 페이지로 판단.
# - Peres Projects: /artists가 도메인 파킹 페이지 스타일의 /lander로
#   리다이렉트(요청 도메인이 실제로는 파킹/프록시 상태로 추정) — 정적 컨텐츠 없음.
# - Galerie Chantal Crousel: /artists, /en/artists/ 전부 404 또는 빈 페이지 —
#   실제 작가 목록은 /artistes/, /en/artistes/ 등 프랑스어 경로인데도
#   정적 HTML에 개별 링크가 없어(JS 렌더링) 보류.
# - Corvi-Mora: /artists가 401 Unauthorized — 접근 자체가 차단됨.
# - Herald St: robots.txt는 AI봇 다수를 이름으로 나열하지만 실제 Disallow는
#   `/config` 하나뿐이라 명시적 차단은 아님. 다만 /artists 페이지가
#   Squarespace 동적 렌더링이라 정적 HTML에서 개별 작가 링크를 못 찾음 — 보류.
# - Galerie Eva Presenhuber: robots.txt 문제없으나 /artists 응답(114KB)에
#   개별 작가 슬러그 링크가 전혀 없음 — 클라이언트 렌더링으로 판단.
# - Galerie Buchholz: 커스텀 JS 프레임워크("chewing the sun") 기반이라
#   /artists 정적 HTML에 네비게이션 링크 하나만 있고 실제 목록은 JS 로드.
# - Galerie Thomas: galerie-thomas.de 연결 자체가 타임아웃(접속 실패) — 스킵.
# - Contemporary Fine Arts(CFA Berlin): 실제 도메인은 cfa-gallery.com(WordPress,
#   robots.txt 문제없음)이나 /artists/ 페이지가 Elementor 위젯으로 렌더링돼
#   정적 HTML에는 "Other Artists" 같은 메뉴 텍스트만 있고 개별 링크가 없음.
# - Foksal Gallery Foundation: foksalgalleryfoundation.com(Drupal, robots.txt
#   문제없음)에 /artists 경로 자체가 없고 홈페이지 내비게이션에도 작가 로스터
#   섹션이 보이지 않음 — 공개된 정적 작가 목록 페이지를 찾지 못함.
# - Chapter II(챕터투): 사이트 자체는 Artlogic 브랜딩이지만 /artists,
#   /artists/list 응답 모두 카테고리 필터 내비게이션뿐이고 실제 작가 카드는
#   JS/AJAX로 채워짐(정적 HTML에 artist_name/title류 마크업 전무) — 보류.
# - Timothy Taylor: Artlogic, robots.txt 문제없고 /artists도 정적 링크가
#   있으나 작가 이름이 <a> 텍스트가 아니라 썸네일 img의 alt 속성에
#   "이름 - 작품명, 연도" 형태로 작품명과 섞여 있어 안정적으로 이름만
#   뽑아내는 패턴을 찾지 못함 — 데이터 품질 우려로 보류.


def _extract(html_text: str, pattern: str, cfg: dict, exclude_slugs: set, seen: dict) -> int:
    """html_text에서 pattern으로 (href, name) 쌍을 뽑아 seen에 채워넣고 신규 건수를 반환."""
    if cfg.get("unescape"):
        html_text = html_entities.unescape(html_text).replace("\\/", "/")

    new_count = 0
    for m in re.finditer(pattern, html_text, re.S):
        href, inner = (m.group(2), m.group(1)) if cfg.get("swap_groups") else (m.group(1), m.group(2))
        name = _clean(inner)
        if cfg.get("truncate_at_comma"):
            name = name.split(",")[0].strip()
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        if name and href not in seen and slug not in exclude_slugs:
            seen[href] = name
            new_count += 1
    return new_count


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
    _extract(html, pattern, cfg, exclude_slugs, seen)

    paginate_template = cfg.get("paginate_template")
    if paginate_template:
        max_pages = cfg.get("max_pages", 20)
        for page_num in range(2, max_pages + 1):
            page_url = paginate_template.format(page=page_num)
            try:
                page_html = _fetch(page_url)
            except requests.RequestException as exc:
                print(f"[galleries:{key}] 페이지 {page_num} 조회 실패, 페이지네이션 중단: {exc}")
                break
            new_count = _extract(page_html, pattern, cfg, exclude_slugs, seen)
            if new_count == 0:
                break
            time.sleep(delay)

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
