"""古裂會(raw/kogirekai/) -> auction_houses/auctions/auction_lots 적재.

`crawlers/kogirekai.py`가 저장한 落札結果(낙찰결과) PDF(`result_NNN.pdf`)를 파싱한다.
PDF는 스캔 이미지가 아니라 텍스트 추출 가능(pypdf)한 표 형태다:

    番号 品名 最低価格 落札価格 番号 品名 最低価格 落札価格 番号 品名 最低価格 落札価格
    #001 石造佛頭 ¥500,000 #002 石造地蔵 ¥350,000 ¥350,000 #078 木彫女面 ¥50,000 ...

3열이 한 행에 나란히 붙어 텍스트로 풀리지만, 각 품목이 `#숫자`로 시작해 자기 자신을
구분하므로 열 구조를 신경 쓸 필요 없이 `#(\\d+)...` 패턴으로 순서대로 스캔하면 된다.
최저가만 있으면 유찰, 낙찰가까지 있으면 낙찰(`sold=True`)이다(칸옥션과 동일 관례).

**작가 추출은 하지 않는다(의도적 설계 선택).** 품명에 "伝OOO"(전 OOO 작 — attributed to)
형태로 작가/유파가 붙는 경우가 있어 처음엔 접두어 매칭을 시도했으나, "伝来"(대대로 전해
내려온, 상속·유래를 뜻하는 흔한 복합어 — 예: "武田家伝来色漆角高杯" = "타케다 가문 전래
색칠 칠기")처럼 작가 귀속과 무관한 "伝"으로 시작하는 표현이 섞여 있어 접두어만으로는
오탐을 피할 수 없었다(칸옥션 로더가 "span 뒤에 생몰년이 와야만 작가로 인정"하는 안전장치를
둔 것과 달리, 이 PDF 표에는 그런 명확한 2차 신호가 없다). 오탐 하나가 존재하지 않는
작가를 artists 테이블에 만드는 것보다 **전부 artist_id=None으로 두는 쪽이 안전**하다고
판단했다(이 프로젝트의 "결손 메타를 LLM/추측으로 채우지 않는다" 원칙과 같은 방향).
작가 귀속이 필요해지면 후속 과제로 별도 검토할 것 — 이번 범위 밖.

경매 날짜: 최근 PDF(예: 142회) 1페이지 상단에
"第142回　古裂會　入札オークション落札結果一覧　2025/5/28" 형태로 정확한 날짜가 박혀
있지만, 오래된 PDF(예: 124회)는 이 헤더가 없다. 날짜를 찾으면 쓰고, 못 찾으면 **지어내지
않고 None**으로 둔다(연도조차 모르면 auctions.auction_date가 NULL — 스키마가 허용).

가격 단위는 円(JPY)이며, 표에 있는 값은 "최저가"(최저 응찰가) 하나뿐이라
`estimate_low`에만 채우고 `estimate_high`는 None으로 둔다(칸옥션처럼 추정가 구간이
아니라 단일 최저가 관례이기 때문).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pypdf import PdfReader

from raw_iter import RAW_ROOT

SITE_NAME = "kogirekai"
HOUSE_NAME = "古裂會（Kogire-kai）"

# 로트 번호 접두어가 회차마다 다르다 — "#001"(일반), "CN-001"(중국미술 특집),
# "A-001"/"B-040"(공가공예 등 특집 카테고리별 알파벳 구분) 전부 관찰됨. 접두어 뒤에
# 공백 없이 바로 품명이 붙는 경우도 있어(예: "A-001後伏見天皇 千載和歌集切幅") `\s*`로 둔다.
# 낙찰가 자리에 금액 대신 "SOLD"/"sold"만 적힌 경우도 있다(낙찰됐으나 가격 비공개 요청 등으로
# 추정 — hammer_price는 None으로 두고 sold=True만 기록한다).
#
# **페이지 넘김 표시("1 / 11 ページ")를 먼저 제거해야 한다** — 안 그러면 이 표시가 다음
# 품목 id 앞에 끼어들어 lookahead가 실패하고, 정규식이 역추적하며 다음 품목 전체를 직전
# 품목의 title로 통째로 삼켜버린다(실측: 2026-09-22, HEADER_NOISE_RE에 페이지 표시를
# 추가하기 전에는 32,532건 중 365건이 이렇게 오염됐었다).
# 접두어 대소문자·전각/반각이 섞여 있다 — "CN-"/"i-"(소문자 특집 카테고리),
# "Ｂ-085"(전각 B, 폰트 치환으로 추정되는 드문 케이스) 전부 실물 PDF에서 확인됨.
ID_RE_STR = r"(?:#|[A-Za-zＡ-Ｚａ-ｚ]{1,3}-)\d{2,6}"
ITEM_RE = re.compile(
    rf"(?:#|[A-Za-zＡ-Ｚａ-ｚ]{{1,3}}-)(\d{{2,6}})\s*(.+?)\s*¥([\d,]+)(?:\s*(¥[\d,]+|SOLD|sold))?"
    rf"(?=\s*(?:{ID_RE_STR})|\s*\Z)",
    re.S,
)
TITLE_LINE_RE = re.compile(
    r"第(\d+)回.*?(\d{4})/(\d{1,2})/(\d{1,2})"
)
HEADER_NOISE_RE = re.compile(
    r"番号\s*品名\s*最低価格\s*落札価格\s*|ホームページでは.*?kogire-kai\.co\.jp"
    r"|\d+\s*/\s*\d+\s*ページ"
    # 기념호(예: 150회 「清華譜」)는 페이지 표시 대신 이 꼴의 반복 각주를 쓴다
    # (2026-09-22 실물 확인, result_150.pdf) — 같은 PDF 안에 아래 두 번째 각주 형태도
    # 섞여 나온다("第N回" 없이 "오ークション落札結果一覧 N/M 날짜"만).
    r"|古裂會\s*第\d+回入札[・･]記念号「[^」]*」"
    r"|オークション落札結果一覧\s*\d+\s*/\s*\d+\s*\d{4}/\d{1,2}/\d{1,2}",
    re.S,
)


def _extract_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _parse_date(full_text: str) -> str | None:
    m = TITLE_LINE_RE.search(full_text)
    if not m:
        return None
    _round, year, month, day = m.groups()
    try:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    except ValueError:
        return None


def parse_items(full_text: str) -> list[dict]:
    cleaned = HEADER_NOISE_RE.sub(" ", full_text)
    cleaned = TITLE_LINE_RE.sub(" ", cleaned)
    items: list[dict] = []
    for lot_number, name, min_price, hammer_field in ITEM_RE.findall(cleaned):
        name = re.sub(r"\s+", " ", name).strip()
        if not name:
            continue
        if hammer_field in ("SOLD", "sold"):
            # 낙찰됐으나 금액이 비공개("SOLD"/"sold"만 표기) — 가격은 지어내지 않고 None,
            # 낙찰 여부만 True로 남긴다.
            sold, hammer_price = True, None
        elif hammer_field:
            sold, hammer_price = True, float(hammer_field.lstrip("¥").replace(",", ""))
        else:
            sold, hammer_price = False, None
        items.append(
            {
                "lot_number": lot_number,
                "title": name,
                "estimate_low": float(min_price.replace(",", "")),
                "hammer_price": hammer_price,
                "sold": sold,
            }
        )
    return items


def _iter_pdf_records():
    """raw/kogirekai/result_*.pdf + <id>.meta.json 쌍을 순회한다.

    iter_records()는 텍스트 파일을 가정해 PDF(바이너리)에는 못 쓴다 — 직접 순회한다.
    """
    site_dir = RAW_ROOT / SITE_NAME
    for meta_path in sorted(site_dir.glob("result_*.meta.json")):
        record_id = meta_path.name[: -len(".meta.json")]
        pdf_path = meta_path.with_name(f"{record_id}.pdf")
        if not pdf_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        yield record_id, pdf_path, meta


def load(store) -> int:
    house_id = store.get_or_create_auction_house(HOUSE_NAME, country="JP")

    loaded = 0
    skipped_not_sold = 0
    round_count = 0

    for record_id, pdf_path, meta in _iter_pdf_records():
        if store.source_already_loaded(meta["raw_path"]):
            continue

        round_no = int(record_id.split("_")[1])
        full_text = _extract_text(pdf_path)
        auction_date = _parse_date(full_text)
        items = parse_items(full_text)
        if not items:
            print(f"[pipeline:kogirekai] 제{round_no}회 — 파싱된 품목 0건, 건너뜀 ({pdf_path.name})")
            continue

        source_id = store.insert_source(meta)
        round_count += 1
        auction_id = store.get_or_create_auction(
            house_id, auction_date, source_id=source_id, sale_key=f"제{round_no}회"
        )

        for item in items:
            if not item["sold"]:
                skipped_not_sold += 1
                continue

            artwork_id = store.insert_artwork(
                artist_id=None,  # 의도적으로 작가 추출 안 함 — 모듈 docstring 참고
                title=item["title"],
                source_id=source_id,
            )
            store.insert_auction_lot_batch(
                auction_id=auction_id,
                artwork_id=artwork_id,
                lot_number=item["lot_number"],
                estimate_low=item["estimate_low"],
                estimate_high=None,
                currency="JPY",
                hammer_price=item["hammer_price"],  # SOLD인데 금액 비공개면 None일 수 있음
                sold=True,
                source_id=source_id,
            )
            loaded += 1

    store.commit()
    print(
        f"[pipeline:kogirekai] {loaded}건 적재, 유찰(낙찰가 없음) 스킵 {skipped_not_sold}건, "
        f"세일 {round_count}개"
    )
    return loaded
