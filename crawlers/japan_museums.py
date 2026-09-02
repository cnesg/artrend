"""일본 독립행정법인 국립미술관 소장품 통합검색 크롤러.

https://search.artmuseums.go.jp/ — 도쿄/교토 국립근대미술관, 국립서양미술관,
국립국제미술관, 국립공예관 5개관 통합 소장품 목록(총 48,690건, 2026.03.30
기준 掲載状況). robots.txt 없음(404) — MMCA 초기와 동일 상황으로 판단해 진행.
저작권: 사이트 footer에 일반적 저작권 고지가 있으나(이미지·해설문 등 콘텐츠에
대한 것), MMCA의 copyrightAllowYn 필드처럼 작품별 Rights Statement(예:
NoC-CR)가 개별 표시되므로 메타데이터만 수집하고 이미지 저작권은 레코드별로
별도 확인해야 한다는 동일한 원칙 적용. 원본 HTML(raw_html)만 저장하며 이미지
파일 자체는 다운로드하지 않는다.

레거시 구식 사이트라 검색어 없이 전체 목록을 못 얻는다 — 작가명 요미(50음)
색인(yomi.php)으로 작가를 전부 순회하고, 각 작가의 작품 목록
(sakuhin_list.php?sakka=<id>)에서 작품 ID를 모아 개별 작품
(records.php?sakuhin=<id>)을 저장하는 2단계 구조.

사용법:
    python crawlers/japan_museums.py --limit 200   # 테스트
    python crawlers/japan_museums.py                # 전체
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

BASE = "https://search.artmuseums.go.jp"
SITE_NAME = "japan_museums"
LICENSE_NOTE = (
    "독립행정법인국립미술관 소장품 통합검색 — 메타데이터만 수집, "
    "이미지 저작권은 작품별 Rights Statement(NoC-CR 등) 개별 확인 필요 "
    "(https://search.artmuseums.go.jp/terms.html)"
)
MUSEUM_FLAGS = {"momat": "on", "momak": "on", "nmwa": "on", "nmao": "on", "ncm": "on"}

# yomi-index.php의 search_sw('yomi', <kana>) 호출에서 추출한 50음 전체 목록
KANA_LIST = [
    "ア", "カ", "サ", "タ", "ナ", "ハ", "マ", "ヤ", "ラ", "ワ",
    "イ", "キ", "シ", "チ", "ニ", "ヒ", "ミ", "リ", "ヰ",
    "ウ", "ク", "ス", "ツ", "ヌ", "フ", "ム", "ユ", "ル",
    "エ", "ケ", "セ", "テ", "ネ", "ヘ", "メ", "レ", "ヱ",
    "オ", "コ", "ソ", "ト", "ノ", "ホ", "モ", "ヨ", "ロ", "ヲ",
]

SAKKA_LINK_RE = re.compile(r"url_link\('sakuhin_list\.php\?sakka=(\d+)'\)")
SAKUHIN_LINK_RE = re.compile(r"url_link\('records\.php\?sakuhin=(\d+)'\)")
SAKUHIN_ID_RE = re.compile(r"records\.php\?sakuhin=(\d+)")


def fetch_yomi_page(kana: str) -> str:
    def _do():
        resp = requests.post(f"{BASE}/yomi.php", data={**MUSEUM_FLAGS, "yomi": kana, "yomi_col": "yomi"}, timeout=30)
        resp.raise_for_status()
        return resp.text

    return with_retry(_do)


def fetch_sakka_works(sakka_id: str) -> list[str]:
    def _do():
        resp = requests.post(f"{BASE}/sakuhin_list.php?sakka={sakka_id}", data=MUSEUM_FLAGS, timeout=30)
        resp.raise_for_status()
        return resp.text

    html = with_retry(_do)
    return sorted(set(SAKUHIN_ID_RE.findall(html)))


def fetch_record(sakuhin_id: str) -> str:
    def _do():
        resp = requests.get(f"{BASE}/records.php", params={"sakuhin": sakuhin_id}, timeout=30)
        resp.raise_for_status()
        return resp.text

    return with_retry(_do)


def collect_sakuhin_ids(delay: float) -> list[str]:
    """작가 요미 색인을 순회해 전체 작품 ID를 모은다(작가 단위 중복 방지)."""
    sakuhin_ids: set[str] = set()
    seen_sakka: set[str] = set()

    for kana in KANA_LIST:
        html = fetch_yomi_page(kana)
        direct_ids = SAKUHIN_LINK_RE.findall(html)
        sakuhin_ids.update(direct_ids)

        sakka_ids = set(SAKKA_LINK_RE.findall(html))
        for sakka_id in sakka_ids - seen_sakka:
            seen_sakka.add(sakka_id)
            try:
                ids = fetch_sakka_works(sakka_id)
            except requests.RequestException as exc:
                print(f"[japan_museums] 작가 {sakka_id} 작품목록 조회 실패: {exc}")
                continue
            sakuhin_ids.update(ids)
            time.sleep(delay)

        print(f"[japan_museums] 요미 '{kana}' 처리 완료 — 누적 작품 {len(sakuhin_ids)}건, 작가 {len(seen_sakka)}명")
        time.sleep(delay)

    return sorted(sakuhin_ids, key=int)


def crawl(limit: int, delay: float, skip_existing: bool) -> None:
    sakuhin_ids = collect_sakuhin_ids(delay)
    print(f"[japan_museums] 작품 ID 총 {len(sakuhin_ids)}건 확인, 저장 시작")

    saved = 0
    for sakuhin_id in sakuhin_ids:
        if saved >= limit:
            break
        if skip_existing and already_fetched(SITE_NAME, sakuhin_id):
            continue
        try:
            html = fetch_record(sakuhin_id)
        except requests.RequestException as exc:
            print(f"[japan_museums] {sakuhin_id} 요청 실패: {exc}")
            continue

        save_raw(
            SITE_NAME,
            sakuhin_id,
            html,
            url=f"{BASE}/records.php?sakuhin={sakuhin_id}",
            license_note=LICENSE_NOTE,
        )
        saved += 1
        if saved % 1000 == 0:
            print(f"[japan_museums] {saved}건 진행 중...")
        time.sleep(delay)

    print(f"[japan_museums] 완료 — {saved}건 저장")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="일본 국립미술관 통합검색 크롤러")
    parser.add_argument("--limit", type=int, default=60000, help="이번 실행에서 수집할 최대 작품 수")
    parser.add_argument("--delay", type=float, default=0.3, help="요청 간 대기(초)")
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    args = parser.parse_args()
    crawl(args.limit, args.delay, args.skip_existing)
