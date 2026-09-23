"""Poly Auction(raw/polypm/) -> auction_houses/auctions/auction_lots 적재.

`crawlers/polypm.py`가 저장한 3단 JSON(notices_all / sessions_<noticeId> /
items_<sessionId>)을 합쳐 로트를 적재한다. 실제 로트 데이터는 items_*.json 하나에
다 있다(제목·로트번호·추정가·낙찰가). sessions_*.json은 세션 이름/날짜를 얻기 위한
조인용 인덱스일 뿐이라 — 칸옥션의 year_*.html과 같은 성격 — 자체 `sources` 행으로
적재하지 않는다.

작가 파싱: Poly의 항목 JSON에는 구조화된 작가 필드(authorCh)가 있지만 실제로는 거의
항상 비어 있다(표본 조사, 2026-09-22). 대신 서화(書畵) 카테고리는 제목 필드
(`itemNamePpch`)가 "<작가명> [<연도>年作] <작품명> <표구형식>" 패턴을 강하게 따른다
(예: "程十发 1972年作 驯鹿图 立轴"). 이 패턴은 표구형식(镜心/立轴/手卷/册页/镜片/成扇/
扇面/횡피/대련/…屏)으로 끝나는 항목에서만 신뢰할 수 있고, 도자기·옥기 등 다른 카테고리는
"清乾隆 ..." 처럼 연호가 앞에 오는 등 전혀 다른 패턴이라 오탐 위험이 크다 — 그래서
**표구형식으로 끝나는 항목에서만** 선행 순한자 2~5자를 작가명으로 인정하고, 나머지는
제목 전체를 그대로 저장하고 artist_id를 비워 둔다(칸옥션의 "생몰년 안 붙으면 작가로
인정 안 함"과 같은 보수적 원칙).

낙찰 판정: `dealStatus`가 "2"(成交)이고 `dealPrice`가 있는 것만 적재한다(1=유찰,
3=취소, 4=매수인위약, 5/6=철회 — 전부 스킵, 칸옥션과 동일하게 유찰은 세지 않는다).
"""
from __future__ import annotations

import html
import json
import re

from raw_iter import RAW_ROOT, iter_records

SITE_NAME = "polypm"
HOUSE_NAME = "北京保利（Poly Auction）"

FORM_SUFFIXES = ("镜心", "立轴", "手卷", "册页", "镜片", "成扇", "扇面", "横披", "对联")
# 병풍류(条屏/通屏/N屏)는 서화에도, 가구(砚屏/座屏/挂屏 등 문진/장식용 병풍)에도 쓰여서
# 무조건 "屏"으로 끝나면 인정하면 안 된다(2026-09-22 파일럿에서 "黄花梨嵌云石砚屏" 같은
# 가구 로트의 "清早期"가 작가명으로 오탐된 사례 발견 — 숫자/条/通 + 屏으로 한정해 재조정).
PAINTING_SCREEN_RE = re.compile(r"(?:[一二三四五六七八九十百]+屏|条屏|通屏|屏轴)$")
LEADING_NAME_RE = re.compile(r"^([一-鿿]{2,5})\s+(.+)$", re.S)
# 왕조/시대 구분어 — 사람 이름이 아닌데 표구형식(镜心/对联/条屏 등)이 자수·도자기 서화류에도
# 똑같이 쓰여서 선행 토큰으로 오인되는 사례가 실제 전체 수집에서 나왔다(2026-09-23,
# "清晚期 粤绣花鸟纹四条屏" 8건, "当代 彭文清书青花釉里红书法对联" 1건 등). 후자는 진짜
# 작가명(彭文清)이 두 번째 토큰이라 이 휴리스틱으로는 못 살리지만, 최소한 오탐은 막는다.
ERA_PREFIXES = {"当代", "现代", "古代", "近代", "民国", "清代", "明代", "宋代", "元代", "唐代"}
YEAR_RE = re.compile(r"(\d{4})")
TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", text))).strip()
    return cleaned or None


def _is_painting_form(title: str) -> bool:
    return title.endswith(FORM_SUFFIXES) or bool(PAINTING_SCREEN_RE.search(title))


def _parse_title(item_name: str | None) -> tuple[str | None, str | None]:
    """(artist_name, title) — 표구형식으로 끝날 때만 선행 순한자 토큰을 작가로 인정."""
    if not item_name:
        return None, None
    item_name = item_name.strip()
    if not item_name:
        return None, None
    if not _is_painting_form(item_name):
        return None, item_name
    m = LEADING_NAME_RE.match(item_name)
    if not m:
        return None, item_name
    name, rest = m.group(1), m.group(2).strip()
    if not name:
        return None, rest or item_name
    if name.endswith("期") or name in ERA_PREFIXES:
        # 시대구분(清早期/清中期/清晚期/清中晚期 등, "N期"로 끝나는 왕조 시대어, 또는
        # 当代/现代 같은 광의 시대어)이 표구형식과 맞물리면 작가명으로 오인된다(전체
        # 수집 audit에서 발견, 전부 자수/직물/도자기 서화류 — 2026-09-23). 실제 인명이
        # "期"로 끝나거나 ERA_PREFIXES와 완전히 같은 경우는 없다고 판단해 거른다.
        return None, item_name
    return name, rest or item_name


def _parse_year(prop2: str | None) -> str | None:
    if not prop2:
        return None
    m = YEAR_RE.search(prop2)
    return m.group(1) if m else None


_SENTINELS = {"0.00", "-1.00", "0", "-1"}


def _parse_price(value) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in _SENTINELS:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _session_index() -> dict[str, dict]:
    """sessions_<noticeId>.json 전부를 읽어 session_id -> {sessionName, startTime} 색인."""
    index: dict[str, dict] = {}
    for path in sorted((RAW_ROOT / SITE_NAME).glob("sessions_*.json")):
        try:
            wrapped = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for session in wrapped.get("data", {}).get("rows", []):
            sid = session.get("infoId")
            if not sid:
                continue
            index[sid] = {
                "sessionName": session.get("sessionName"),
                "startTime": session.get("startTime"),
            }
    return index


def load(store) -> int:
    session_meta = _session_index()
    house_id = store.get_or_create_auction_house(HOUSE_NAME, country="CN")

    loaded = 0
    skipped_not_sold = 0
    auction_ids: dict[str, str] = {}

    for record_id, data, meta in iter_records(SITE_NAME, ext="json"):
        if not record_id.startswith("items_"):
            continue  # notices_all / sessions_* — 조인용, 자체 적재 안 함
        if store.source_already_loaded(meta["raw_path"]):
            continue

        session_id = record_id[len("items_"):]
        rows = data.get("data", {}).get("rows", [])
        if not rows:
            continue
        source_id = store.insert_source(meta)

        meta_for_session = session_meta.get(session_id, {})
        sale_name = meta_for_session.get("sessionName") or f"session_{session_id}"
        start_time = meta_for_session.get("startTime")
        sale_date = start_time[:10] if start_time else None

        auction_id = auction_ids.get(session_id)
        if auction_id is None:
            auction_id = store.get_or_create_auction(
                house_id, sale_date, source_id=source_id, sale_key=sale_name
            )
            auction_ids[session_id] = auction_id

        for item in rows:
            deal_status = item.get("dealStatus")
            hammer = _parse_price(item.get("dealPrice"))
            if deal_status != "2" or hammer is None:
                skipped_not_sold += 1
                continue

            artist_name, title = _parse_title(item.get("itemNamePpch"))
            artist_id = (
                store.get_or_create_artist_safe(artist_name, source_id=source_id)
                if artist_name
                else None
            )

            artwork_id = store.insert_artwork(
                artist_id=artist_id,
                title=title or item.get("itemNamePpch") or "(제목 미상)",
                year_created=_parse_year(item.get("porcelainPropertie2")),
                medium=item.get("porcelainPropertie3") or None,
                dimensions=item.get("porcelainPropertie1") or None,
                description=_strip_html(item.get("itemRemark")),
                source_id=source_id,
            )
            store.insert_auction_lot_batch(
                auction_id=auction_id,
                artwork_id=artwork_id,
                lot_number=str(item["lotNo"]) if item.get("lotNo") is not None else None,
                estimate_low=_parse_price(item.get("valLow")),
                estimate_high=_parse_price(item.get("valHigh")),
                currency="CNY",
                hammer_price=hammer,
                sold=True,
                source_id=source_id,
            )
            loaded += 1

    store.commit()
    print(
        f"[pipeline:polypm] {loaded}건 적재, 미성사(유찰/취소/위약/철회) 스킵 {skipped_not_sold}건, "
        f"세일 {len(auction_ids)}개"
    )
    return loaded
