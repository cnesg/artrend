"""Durán Arte y Subastas(마드리드, 1969년 설립 — 스페인 최대 미술 경매사 중 하나) 낙찰 로트 수집.

2026-09-23 경매 소스 확장(이베리아 권역) 조사에서 착수 판정. 조사 경위와 다른 후보
(Setdart·Balclis = ToS 불가)의 판정 근거는 `docs/logs/경매확장_setdart_20260923.md`.

착수 전 직접 확인한 근거:
  - robots.txt(2026-09-23 직접 확인): `User-agent: *` / `Disallow:` — **전면 허용**.
    AI 봇(ClaudeBot/GPTBot/CCBot/anthropic-ai 등)에 대한 개별 차단 문구 없음.
  - Aviso legal(`/es/pagina/aviso-legal`) 전문 확인. 두 조항이 핵심이다:
      * "queda prohibida su reproducción, distribución, comunicación pública y
         transformación, **salvo para uso personal y privado**" — 개인적·사적 이용은 예외.
      * "**Expresamente se autoriza** la impresión, edición en cualquier soporte y
         distribución de cuantos documentos aparezcan en la página ... la documentación
         será utilizada **con fines informativos**, en ningún caso se podrá utilizar con
         fines comerciales salvo autorización expresa, y **deberá incluir siempre una
         referencia sobre el origen o titular del derecho**, esto es Durán Sala de Arte,
         S.L.U." — 비상업·정보목적·출처표시 조건부 **명시적 허용**.
    artrend은 비상업 개인 프로젝트이고 모든 레코드가 `sources` 행으로 출처를 인용하므로
    이 조건을 그대로 충족한다. **단 이 허용은 조건부다** — 상업적 이용으로 전환되면
    재검토 필요(로그 문서에 조건 명시).
    Setdart/Balclis가 쓰는 스페인 LSSI 보일러플레이트("Independientemente de la finalidad
    ... requiere en todo caso de la autorización escrita previa")와 **정반대 조항**이라는
    점이 판정의 갈림길이었다.
  - 로트 상세 페이지가 완전 SSR이고 구조화 필드(Autor/Título/Procedencia/Medidas/
    Técnica/Observaciones/Categorias)를 라벨-값 쌍으로 그대로 노출한다.

수집 경로(3단계):
  1. `/es/subastas-historicas/` 1회 GET — 경매 목록(codSub, refSession, 제목, 개최일
     `div.fechas > p`의 dd-mm-yyyy). 이 페이지 자체도 raw로 저장해 경매일자 출처를 남긴다.
  2. 경매별 로트 목록: 무한스크롤이 `POST /es/GetAjaxLots`(Laravel CSRF `_token` 필요)로
     48건씩 HTML 조각을 준다. `award=1`을 주면 **낙찰된 로트만** 나온다. 응답이 빈 문자열이면
     마지막 페이지.
  3. 로트 상세 페이지 개별 GET 후 저장. 목록 조각에도 낙찰가는 있지만 작가가 제목 문자열에
     뭉쳐 있어(`"Joan Miró. Joan Miró Litógrafo II"`) 쓸 수 없다 — 상세 페이지의 `Autor`
     필드가 `MIRÓ FERRÁ, JOAN (1893 - 1983)`처럼 생몰년까지 구조화돼 있어 이쪽만 신뢰한다.
     (제목에서 작가를 문자열로 떼어내는 추측성 분리는 하지 않는다.)

**저장 시 입찰자 정보 삭제**: 상세 페이지엔 `var auction_info = $.parseJSON('...')`로 실시간
입찰 상태가 박혀 있고 그 안에 입찰자 고객번호(`cli_licit`)와 입찰 시각이 들어 있다. 이 프로젝트가
쓰지 않는 제3자 개인정보라 **저장 전에 해당 블롭만 `{}`로 치환**한다. 우리가 쓰는 필드는 전부
가시 HTML(라벨-값 쌍, Precio salida, VENDIDO POR)에 있어 영향이 없다.

이미지 파일은 저장하지 않는다(사실 데이터만 수집).

사용법:
    python duran.py --auctions 3 --limit 120   # 파일럿: 최근 경매 3개에서 최대 120로트
    python duran.py --auctions 12              # 최근 1년치
    python duran.py --all                      # 전량(504~659, 154개 경매 — 매우 오래 걸림)
"""
from __future__ import annotations

import argparse
import re
import sys
import time

import requests

from common import already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

SITE_NAME = "duran"
BASE = "https://www.duran-subastas.com"
HIST_URL = f"{BASE}/es/subastas-historicas/"
AJAX_URL = f"{BASE}/es/GetAjaxLots"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (artgraph-research-bot)",
    "Accept-Language": "es-ES,es;q=0.9",
}
# robots.txt에 Crawl-delay 지정 없음(전면 허용) — 예의상 최소 1.5초 간격을 스스로 지킨다.
CRAWL_DELAY = 1.5

LICENSE_NOTE = (
    "Durán Arte y Subastas(마드리드) 공개 로트 상세 페이지 SSR HTML — robots.txt 전면 허용"
    "(AI 봇 개별 차단 없음), Aviso legal이 '비상업·정보목적·출처표시' 조건으로 복제·배포를 "
    "명시적으로 허용(Expresamente se autoriza ... con fines informativos ... deberá incluir "
    "siempre una referencia sobre el origen), 개인적·사적 이용도 별도 예외. 출처 표시 의무: "
    "Durán Sala de Arte, S.L.U. 확인 2026-09-23. 입찰자 고객번호 블롭은 저장 전 제거함."
)

# 경매 카드: 썸네일 파일명이 AUCTION_<refSession>_<codSub>.jpg, 그 뒤 div.fechas > p 에 개최일.
AUCTION_CARD_RE = re.compile(
    r'AUCTION_(\d+)_(\d+)\.jpg.*?class="[^"]*\bfechas\b[^"]*">\s*<p>\s*(\d{2})-(\d{2})-(\d{4})',
    re.S,
)
AUCTION_TITLE_RE = re.compile(r'alt="([^"]*)"')
TOKEN_RE = re.compile(r'name="_token" value="([^"]+)"')
# 목록 조각의 로트 상세 링크: .../es/subasta-lote/<슬러그>/<codSub>-<로트번호>
LOT_HREF_RE = re.compile(r"href='(" + re.escape(BASE) + r"/es/subasta-lote/[^']+/(\d+)-(\d+))'")
# 저장 전 제거할 실시간 입찰 상태 블롭(입찰자 고객번호 포함).
AUCTION_INFO_RE = re.compile(
    r"var\s+auction_info\s*=\s*\$\.parseJSON\(\s*'.*?'\s*\)\s*;", re.S
)


def _get(session: requests.Session, url: str, **kw) -> requests.Response:
    def _do():
        resp = session.get(url, headers=HEADERS, timeout=60, **kw)
        resp.raise_for_status()
        return resp

    return with_retry(_do, attempts=5, base_delay=4.0)


def _redact(page_html: str) -> str:
    """입찰자 고객번호가 담긴 실시간 입찰 블롭을 제거한다(모듈 독스트링 참고)."""
    return AUCTION_INFO_RE.sub("var auction_info = {}; /* redacted: bidder data */", page_html)


def discover_auctions(session: requests.Session) -> list[dict]:
    """과거 경매 목록 -> [{cod_sub, ref_session, title, date}] (최신순)."""
    resp = _get(session, HIST_URL)
    save_raw(
        SITE_NAME, "_index", resp.text, url=HIST_URL, license_note=LICENSE_NOTE, ext="html"
    )
    out: dict[str, dict] = {}
    for m in AUCTION_CARD_RE.finditer(resp.text):
        ref_session, cod_sub, dd, mm, yyyy = m.groups()
        tm = AUCTION_TITLE_RE.search(resp.text, m.start(), m.start() + 600)
        out.setdefault(
            cod_sub,
            {
                "cod_sub": cod_sub,
                "ref_session": ref_session,
                "title": tm.group(1).strip() if tm else None,
                "date": f"{yyyy}-{mm}-{dd}",
            },
        )
    auctions = sorted(out.values(), key=lambda a: a["date"], reverse=True)
    print(f"[duran] 과거 경매 {len(auctions)}개 발견 "
          f"({auctions[-1]['date']} ~ {auctions[0]['date']})" if auctions else "[duran] 경매 0개")
    return auctions


def collect_lot_urls(session: requests.Session, auction: dict) -> list[tuple[str, str]]:
    """경매 1개의 낙찰 로트 상세 URL 목록 -> [(url, record_id)]."""
    cod, ref = auction["cod_sub"], auction["ref_session"]
    slug = f"subasta-{cod}"
    page_url = f"{BASE}/es/subasta/{slug}_{cod}-{ref}"
    try:
        resp = _get(session, page_url)
    except requests.RequestException as exc:
        print(f"[duran] 경매 {cod} 페이지 실패, 건너뜀: {exc}")
        return []
    tm = TOKEN_RE.search(resp.text)
    if not tm:
        print(f"[duran] 경매 {cod}: CSRF 토큰 미검출, 건너뜀")
        return []
    token = tm.group(1)

    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for page in range(1, 400):  # 안전 상한
        body = {
            "_token": token, "order": "ref", "description": "", "category": "",
            "section": "", "subsection": "", "typeSub": "W", "reference": "",
            "award": "1", "noAward": "0", "liveLots": "0", "purchasable": "0",
            "myLotsProperty": "0", "myLotsClient": "0", "total": "48",
            "page": str(page), "filter_session": "", "actualPage": str(page),
            "historic": "", "codSub": cod, "refSession": ref,
        }

        def _post():
            r = session.post(
                AJAX_URL, data=body, timeout=60,
                headers={**HEADERS, "X-Requested-With": "XMLHttpRequest", "Referer": page_url},
            )
            r.raise_for_status()
            return r

        try:
            ar = with_retry(_post, attempts=5, base_delay=4.0)
        except requests.RequestException as exc:
            print(f"[duran] 경매 {cod} p{page} AJAX 실패, 중단: {exc}")
            break

        if not ar.text.strip():
            break
        new = 0
        for m in LOT_HREF_RE.finditer(ar.text):
            url, c, lot = m.group(1), m.group(2), m.group(3)
            rid = f"{c}-{lot}"
            if rid in seen:
                continue
            seen.add(rid)
            found.append((url, rid))
            new += 1
        if new == 0:
            break
        time.sleep(CRAWL_DELAY)
    return found


def crawl(
    auction_count: int | None,
    limit: int | None,
    skip_existing: bool,
    per_auction: int | None = None,
) -> None:
    session = requests.Session()
    auctions = discover_auctions(session)
    if auction_count is not None:
        auctions = auctions[:auction_count]

    saved = 0
    skipped_cached = 0
    for auction in auctions:
        if limit is not None and saved >= limit:
            break
        lots = collect_lot_urls(session, auction)
        print(f"[duran] 경매 {auction['cod_sub']} ({auction['date']}, "
              f"{auction['title']}) 낙찰 로트 {len(lots)}건")
        saved_here = 0
        for url, rid in lots:
            if limit is not None and saved >= limit:
                break
            if per_auction is not None and saved_here >= per_auction:
                break
            if skip_existing and already_fetched(SITE_NAME, rid, ext="html"):
                skipped_cached += 1
                continue
            try:
                resp = _get(session, url)
            except requests.RequestException as exc:
                print(f"[duran] {url} 실패, 건너뜀: {exc}")
                time.sleep(CRAWL_DELAY)
                continue
            save_raw(
                SITE_NAME, rid, _redact(resp.text),
                url=url, license_note=LICENSE_NOTE, ext="html",
            )
            saved += 1
            saved_here += 1
            if saved % 20 == 0:
                print(f"[duran] {saved}건 저장 (캐시 스킵 {skipped_cached})")
            time.sleep(CRAWL_DELAY)

    print(f"[duran] 완료 — {saved}건 저장, 캐시 스킵 {skipped_cached}건")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Durán Arte y Subastas 낙찰 로트 크롤러")
    parser.add_argument("--auctions", type=int, default=3,
                        help="최신순으로 이번 실행에서 훑을 경매 수(기본 3)")
    parser.add_argument("--all", action="store_true", help="전체 경매(154개) 대상")
    parser.add_argument("--limit", type=int, default=None,
                        help="이번 실행에서 새로 저장할 최대 로트 수(파일럿용)")
    parser.add_argument("--per-auction", type=int, default=None,
                        help="경매 1개당 최대 로트 수(여러 경매에 고르게 퍼뜨릴 때)")
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false",
                        help="이미 저장된 로트도 다시 수집")
    args = parser.parse_args()
    crawl(None if args.all else args.auctions, args.limit, args.skip_existing,
          per_auction=args.per_auction)
