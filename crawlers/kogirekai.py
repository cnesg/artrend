"""古裂會(Kogire-kai, kogire-kai.co.jp) 낙찰결과 PDF 수집.

2026-09-22 경매소스확장 조사(`docs/경매소스확장_20260922.md` B-5절)에서 "판단 보류"로 남아
있던 곳 — robots.txt가 지금까지 조사한 소스 중 가장 우호적이었지만 落札結果 페이지 구조·
약관이 미확인이었다. 이번에 실제 확인·착수한다(`docs/logs/경매확장_kogirekai_20260922.md`에
조사 경위 전체 기록).

판정 근거:
  - robots.txt(2026-09-22 직접 확인): `User-agent: *` / `Disallow:`(빈 값 — 사실상 전면 허용).
    유일한 제한은 워드프레스 플러그인 내부 JSON 파일 하나
    (`/wp-content/uploads/wpo-plugins-tables-list.json`)뿐, 落札結果·schedule 경로는 무제한.
  - 이용약관: 사이트에 **일반 이용약관(利用規約) 페이지 자체가 없다**. 대신 특정상거래법
    표시(`/law/`), 개인정보보호방침(`/privacy/`), 참가방법 안내(`/en/bid/`) 세 곳 전문을
    확인했는데 크롤링/스크래핑/데이터마이닝/자동수집/로봇/무단복제 금지, 제3자 정보 개시
    금지, 사전 서면승낙 요구 조항이 **전혀 없다** — SBI Art Auction·Est-Ouest·Shinwa 등
    다른 일본 경매사에서 반복적으로 걸렸던 패턴이 여기엔 없다. 푸터 저작권 표시는
    "© 2018 kogire-kai" 한 줄뿐이라 PDF 자체의 재배포는 하지 않는 것으로 대응한다(아래).
  - 구조: 落札結果(낙찰결과)가 PDF로 게시되고 파일명 패턴이 회차마다 제각각이라
    (`124result.pdf`, `142th528.pdf`, `f6166e787dcf8c8f65b14378b535015f.pdf` 등) URL을
    유추할 수 없다. 하지만 **PDF 링크 자체가 `/schedule/` 목록 페이지(SSR, 완전 정적
    HTML)에 이미 노출돼 있어** 상세페이지까지 들어갈 필요가 없다:
        <h4 class="title-double_mark mod-center">第142回入札オークション</h4>
        ...
        <dt class="mod-yellow">落札結果</dt>
        <dd><a href="https://.../142th528.pdf" target="_blank">落札結果（PDF）</a></dd>
    2026-09-22 기준 11페이지(`/schedule/`, `/schedule/page/2/`~`/page/11/`)에 걸쳐
    제102회(2018-09 하견)~제152회(2027-01 예정, 아직 결과 없음)가 나온다. 아직 안 끝난
    회차·오래된 회차 일부는 落札結果 링크가 없을 수 있다(정상 — 결과 미공개).
  - PDF는 스캔 이미지가 아니라 **텍스트 추출 가능**(pypdf로 실물 PDF 2개 직접 검증):
    `#번호 품명 ¥최저가 [¥낙찰가]` 형태의 표. 유찰이면 낙찰가 칸이 비어 있다(칸옥션과
    동일 관례). 최근 PDF(예: 142회)는 1페이지 상단에
    "第142回　古裂會　入札オークション落札結果一覧　2025/5/28" 형태로 정확한 날짜가
    박혀 있지만, 오래된 PDF(예: 124회)는 이 헤더가 없는 경우도 있어 **날짜는 best-effort**
    (pipeline 쪽에서 못 찾으면 지어내지 않고 None으로 둔다).
  - PDF 원문은 crawlers/raw/에 보관하되 **재배포하지 않는다** — pipeline 단계는 사실
    데이터(로트번호/품명/가격)만 추출해 DB에 적재한다(다른 소스와 동일 관례).
  - 대부분 품목은 무명 골동품(칠기·다도구·염직물·갑주 등)이고, 일부만 품명 안에
    "伝OOO"(전 OOO 작 — attributed to) 형태로 작가/유파가 붙는다. artist 파싱·매칭은
    pipeline/kogirekai.py 몫이며, 매칭 안 되는 대다수는 artist_id=None으로 둔다
    (LLM으로 채우지 않음, 이름 유사도 병합도 하지 않음).

2단계로 수집한다:
  1) schedule — `/schedule/`, `/schedule/page/N/` 목록 페이지(SSR) 원본 저장.
  2) pdf      — 저장된 목록에서 (회차번호, 落札結果 PDF URL) 쌍을 뽑아 PDF 원본 저장.

사용법:
    python kogirekai.py --phase schedule
    python kogirekai.py --phase pdf
    python kogirekai.py --phase all
"""
from __future__ import annotations

import argparse
import re
import sys
import time

import requests

from common import RAW_ROOT, already_fetched, save_raw, with_retry

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

SITE_NAME = "kogirekai"
BASE = "https://www.kogire-kai.co.jp"
SCHEDULE_URL_FIRST = f"{BASE}/schedule/"
SCHEDULE_URL_PAGE = f"{BASE}/schedule/page/{{page}}/"
HEADERS = {"User-Agent": "Mozilla/5.0 (artgraph-research-bot)"}
DELAY = 1.5

LICENSE_NOTE_SCHEDULE = (
    "古裂會(kogire-kai.co.jp) 開催日程 목록 페이지 SSR HTML — robots.txt `Disallow:`(전면 허용), "
    "일반 이용약관 없음(특정상거래법 표시·개인정보방침·참가안내 전문 확인, 크롤링/스크래핑/"
    "제3자 정보 개시 금지 조항 없음), 2026-09-22"
)
LICENSE_NOTE_PDF = (
    "古裂會(kogire-kai.co.jp) 落札結果(낙찰결과) PDF 원본 — 위 schedule 목록 페이지에 공개된 "
    "링크로 수집. 재배포하지 않고 사실 데이터(로트/가격)만 pipeline에서 추출해 DB에 적재함. "
    "2026-09-22"
)

ROUND_SPLIT = '<h4 class="title-double_mark mod-center">'
ROUND_RE = re.compile(r"^第(\d+)回")
PDF_RE = re.compile(r'落札結果</dt>\s*<dd>\s*<a href="([^"]+\.pdf)"')


def _get(url: str) -> requests.Response:
    def _do():
        resp = requests.get(url, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return resp

    return with_retry(_do, attempts=4, base_delay=5.0)


def crawl_schedule(start_page: int, max_pages: int | None, skip_existing: bool) -> None:
    saved = 0
    page = start_page
    while True:
        if max_pages is not None and saved >= max_pages:
            break
        record_id = f"schedule_p{page:04d}"

        if skip_existing and already_fetched(SITE_NAME, record_id, ext="html"):
            page += 1
            continue

        url = SCHEDULE_URL_FIRST if page == 1 else SCHEDULE_URL_PAGE.format(page=page)
        try:
            resp = _get(url)
        except requests.RequestException as exc:
            print(f"[kogirekai:schedule] page {page} 요청 실패 — 마지막 페이지로 보고 종료: {exc}")
            break

        if not ROUND_RE_ANY.search(resp.text):
            print(f"[kogirekai:schedule] page {page} 회차 0건 — 마지막 페이지로 판단하고 종료")
            break

        save_raw(
            SITE_NAME, record_id, resp.text,
            url=url, license_note=LICENSE_NOTE_SCHEDULE, ext="html",
        )
        saved += 1
        print(f"[kogirekai:schedule] page {page} 저장")
        page += 1
        time.sleep(DELAY)

    print(f"[kogirekai:schedule] 완료 — {saved}페이지 저장")


ROUND_RE_ANY = re.compile(r"第\d+回")


def _round_pdf_pairs() -> dict[int, str]:
    """저장된 schedule 목록 HTML에서 (회차번호 -> 落札結果 PDF URL)을 뽑는다."""
    pairs: dict[int, str] = {}
    site_dir = RAW_ROOT / SITE_NAME
    for path in sorted(site_dir.glob("schedule_p*.html")):
        html = path.read_text(encoding="utf-8")
        for chunk in html.split(ROUND_SPLIT)[1:]:
            round_match = ROUND_RE.match(chunk)
            if not round_match:
                continue
            round_no = int(round_match.group(1))
            pdf_match = PDF_RE.search(chunk)
            if pdf_match:
                pairs[round_no] = pdf_match.group(1)
    return pairs


def crawl_pdfs(skip_existing: bool) -> None:
    pairs = _round_pdf_pairs()
    print(f"[kogirekai:pdf] 목록에서 落札結果 PDF {len(pairs)}건 발견")

    saved = 0
    for round_no, pdf_url in sorted(pairs.items()):
        record_id = f"result_{round_no:03d}"
        if skip_existing and already_fetched(SITE_NAME, record_id, ext="pdf"):
            continue
        try:
            resp = _get(pdf_url)
        except requests.RequestException as exc:
            print(f"[kogirekai:pdf] 제{round_no}회 PDF 요청 실패, 건너뜀: {exc}")
            continue
        save_raw(
            SITE_NAME, record_id, resp.content,
            url=pdf_url, license_note=LICENSE_NOTE_PDF, ext="pdf",
        )
        saved += 1
        print(f"[kogirekai:pdf] 제{round_no}회 저장 ({pdf_url})")
        time.sleep(DELAY)

    print(f"[kogirekai:pdf] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="古裂會(Kogire-kai) 낙찰결과 크롤러")
    parser.add_argument("--phase", choices=["schedule", "pdf", "all"], default="all")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument(
        "--no-skip-existing", dest="skip_existing", action="store_false",
        help="이미 저장된 항목도 다시 수집",
    )
    args = parser.parse_args()

    if args.phase in ("schedule", "all"):
        crawl_schedule(args.start_page, args.max_pages, args.skip_existing)
    if args.phase in ("pdf", "all"):
        crawl_pdfs(args.skip_existing)
